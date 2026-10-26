import json
import tempfile
import unittest
from pathlib import Path

from stock_predict_mailer.contracts import read_contract
from stock_predict_mailer.core import Config
from stock_predict_mailer.data import demo_csv, import_csv, load_snapshot
from stock_predict_mailer.model_registry import (
    evaluate_model,
    get_model,
    personal_model_folder,
    predict_snapshot,
    publish_demo,
    train_platform,
)
from stock_predict_mailer.model_training import compare_models
from stock_predict_mailer.residual import fit_residual_adapter


class ResidualAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.cfg = Config(root / "state")
        self.contract = read_contract(Path("config/task-demo.json"))
        self.snapshot = import_csv(self.cfg, demo_csv(root / "bars.csv", 220, 6), synthetic=True)["snapshot_id"]
        _, self.raw = load_snapshot(self.cfg, self.snapshot)
        self.dates = sorted({row["date"] for row in self.raw})
        self.parent = train_platform(self.cfg, self.snapshot, self.contract,
                                     f"{self.dates[110]}T20:00:00+08:00", "ridge", confirm_platform_data=True)
        self.cutoff = f"{self.dates[-1]}T20:00:00+08:00"
        evaluation = evaluate_model(self.cfg, self.parent["version"], self.snapshot, self.cutoff)
        publish_demo(self.cfg, self.parent["version"], evaluation["evaluation_id"])

    def fit(self, **kwargs):
        return fit_residual_adapter(self.cfg, self.parent["version"], self.snapshot, self.cutoff, **kwargs)

    def test_adapter_only_uses_dates_the_parent_never_saw(self):
        result = self.fit()
        manifest, payload, state = get_model(self.cfg, result["model_version"])
        self.assertEqual(manifest["algorithm"], "residual")
        self.assertEqual(manifest["residual_of"], self.parent["version"])
        self.assertEqual(manifest["method"], "residual_adapter")
        self.assertEqual(manifest["scope"], "personal")
        self.assertEqual(state["status"], "ready")
        self.assertGreater(result["fit_start"], self.parent["train_label_end"])
        adapter = json.loads(payload)
        self.assertEqual(adapter["parent_train_label_end"], self.parent["train_label_end"])
        self.assertGreaterEqual(result["cross_fit"]["oos_dates"], 20)
        self.assertIn("rank_ic_before", result["cross_fit"])
        self.assertIn("rank_ic_after", result["cross_fit"])
        self.assertEqual(result["auto_switched"], False)

    def test_cross_fitting_skips_blocks_without_purged_history(self):
        result = self.fit(folds=4)
        folds = result["cross_fit"]["folds_detail"]
        self.assertEqual(len(folds), 4)
        self.assertTrue(any(item["status"] == "fitted" for item in folds))
        # Later blocks are the ones with enough purged history behind them.
        self.assertEqual(folds[-1]["status"], "fitted")

    def test_adapter_can_be_scored_and_compared_against_a_retrain(self):
        # The adapter is fitted at an earlier cutoff, then compared on the newer
        # arrivals: a forward comparison window only exists after both label ends.
        fit_cutoff = f"{self.dates[170]}T20:00:00+08:00"
        adapter = fit_residual_adapter(self.cfg, self.parent["version"], self.snapshot, fit_cutoff)
        prediction = predict_snapshot(self.cfg, self.snapshot, self.cutoff, adapter["model_version"], allow_personal=True)
        self.assertEqual(prediction["model_scope"], "personal")
        self.assertEqual(len(prediction["predictions"]), self.cfg.top_k)
        self.assertFalse(prediction["training_performed"])
        retrain = train_platform(self.cfg, self.snapshot, self.contract, fit_cutoff, "ridge", confirm_platform_data=True)
        comparison = compare_models(self.cfg, adapter["model_version"], retrain["version"], self.snapshot, self.cutoff)
        self.assertIn(comparison["verdict"], ("candidate_improved", "candidate_degraded", "inconclusive"))
        self.assertFalse(comparison["auto_switched"])
        self.assertGreaterEqual(comparison["test_days"], 30)
        self.assertGreater(comparison["label_end_boundary"], adapter["fit_end"])

    def test_insufficient_forward_window_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            fit_residual_adapter(self.cfg, self.parent["version"], self.snapshot,
                                 f"{self.dates[115]}T20:00:00+08:00")
        self.assertIn("adapter needs at least", str(caught.exception))

    def test_adapter_on_adapter_is_rejected(self):
        first = self.fit()
        with self.assertRaises(ValueError) as caught:
            fit_residual_adapter(self.cfg, first["model_version"], self.snapshot, self.cutoff)
        self.assertIn("stacking", str(caught.exception))

    def test_tampered_adapter_is_rejected(self):
        result = self.fit()
        folder = personal_model_folder(self.cfg, self.cfg.principal, result["model_version"])
        (folder / "adapter.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            get_model(self.cfg, result["model_version"])
        self.assertIn("integrity", str(caught.exception))

    def test_shrink_and_alpha_bounds(self):
        for kwargs in ({"shrink": 0.0}, {"shrink": 1.5}, {"alpha": 0.0}, {"folds": 2}, {"folds": 9}):
            with self.assertRaises(ValueError):
                self.fit(**kwargs)


if __name__ == "__main__":
    unittest.main()
