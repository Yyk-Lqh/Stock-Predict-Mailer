import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from stock_predict_mailer.contracts import contract_id, prepare_rows, read_contract, validate_contract
from stock_predict_mailer.core import Config
from stock_predict_mailer.data import demo_csv, import_csv, load_snapshot
from stock_predict_mailer.model_registry import (
    evaluate_model,
    get_model,
    list_models,
    model_folder,
    predict_snapshot,
    publish_demo,
    select_model,
    train_platform,
)
from stock_predict_mailer.native_models import fit_native, native_predict


class ModelRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cfg = Config(Path(self.temp.name) / "state")
        self.contract = read_contract(Path("config/task-demo.json"))
        self.snapshot = import_csv(self.cfg, demo_csv(Path(self.temp.name) / "bars.csv", 200, 6), synthetic=True)["snapshot_id"]
        _, self.raw = load_snapshot(self.cfg, self.snapshot)
        self.dates = sorted({r["date"] for r in self.raw})
        self.train_cutoff = f"{self.dates[110]}T20:00:00+08:00"
        self.end_cutoff = f"{self.dates[-1]}T20:00:00+08:00"

    def train(self, algorithm="ridge"):
        return train_platform(self.cfg, self.snapshot, self.contract, self.train_cutoff, algorithm, confirm_platform_data=True)

    def release(self, algorithm="ridge"):
        model = self.train(algorithm)
        evaluation = evaluate_model(self.cfg, model["version"], self.snapshot, self.end_cutoff)
        publish_demo(self.cfg, model["version"], evaluation["evaluation_id"])
        return model

    def test_fixed_benchmark_labels_invariant_to_uploaded_universe(self):
        _, full = prepare_rows(self.raw, self.contract, self.end_cutoff)
        reduced = [r for r in self.raw if r["security_id"] in ("SYN000", "SYN001", "SYN002", "SYN003")]
        _, subset = prepare_rows(reduced, self.contract, self.end_cutoff)
        def key(r):
            return (r["date"], r["security_id"])
        targets = {key(r): r["y"] for r in full}
        self.assertTrue(all(r["y"] == targets[key(r)] for r in subset))
        sample = subset[0]
        lookup = {(r["date"], r["security_id"]): r for r in self.raw}
        actual = lookup[(sample["label_end"], "SYN001")]["open"] / lookup[(sample["entry_date"], "SYN001")]["open"] - 1
        reference = lookup[(sample["label_end"], "SYN000")]["open"] / lookup[(sample["entry_date"], "SYN000")]["open"] - 1
        self.assertAlmostEqual(sample["y"], actual - reference)

    def test_calendar_gaps_future_records_and_contract_order(self):
        first, _ = prepare_rows(self.raw, self.contract, self.train_cutoff)
        changed = copy.deepcopy(self.raw)
        changed[-1]["close"] *= 10
        self.assertEqual(first, prepare_rows(changed, self.contract, self.train_cutoff)[0])
        missing_day = self.dates[50]
        gapped = [r for r in self.raw if not (r["date"] == missing_day and r["security_id"] == "SYN001")]
        features, _ = prepare_rows(gapped, self.contract, self.end_cutoff)
        forbidden = set(self.dates[50:71])
        self.assertFalse(any(r["security_id"] == "SYN001" and r["date"] in forbidden for r in features))
        invalid = {**self.contract, "features": list(reversed(self.contract["features"]))}
        with self.assertRaises(ValueError):
            validate_contract(invalid)
        self.assertEqual(contract_id(self.contract), contract_id({**self.contract, "universe": list(reversed(self.contract["universe"]))}))

    def test_native_linear_reconstruction_matches_estimator(self):
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import StandardScaler
        _, rows = prepare_rows(self.raw, self.contract, self.train_cutoff)
        _, payload = fit_native("ridge", rows)
        x, y = np.array([r["x"] for r in rows]), np.array([r["y"] for r in rows])
        scaler = StandardScaler().fit(x)
        expected = Ridge(alpha=100).fit(scaler.transform(x), y).predict(scaler.transform(x))
        np.testing.assert_allclose(native_predict("ridge", payload, rows), expected, atol=1e-12)

    def test_draft_gate_forward_evaluation_and_no_fit_during_prediction(self):
        model = self.train()
        with self.assertRaises(ValueError):
            select_model(self.cfg, model["version"], allow_demo=True)
        with self.assertRaises(ValueError):
            evaluate_model(self.cfg, model["version"], self.snapshot, self.train_cutoff)
        evaluation = evaluate_model(self.cfg, model["version"], self.snapshot, self.end_cutoff)
        self.assertGreater(evaluation["feature_start"], model["train_label_end"])
        publish_demo(self.cfg, model["version"], evaluation["evaluation_id"])
        with self.assertRaises(ValueError):
            select_model(self.cfg, model["version"])
        select_model(self.cfg, model["version"], allow_demo=True)
        with patch("stock_predict_mailer.native_models.fit_native", side_effect=AssertionError("must not train")), patch("sklearn.linear_model.Ridge.fit", side_effect=AssertionError("must not fit")):
            result = predict_snapshot(self.cfg, self.snapshot, self.end_cutoff, allow_demo=True)
        self.assertFalse(result["training_performed"])
        self.assertEqual(result["model_version"], model["version"])
        self.assertEqual(result["data_date"], self.dates[-1])

    def test_authorization_selection_isolation_and_tampering(self):
        with self.assertRaises(ValueError):
            train_platform(self.cfg, self.snapshot, self.contract, self.train_cutoff)
        first = self.release("ridge")
        other = Config(self.cfg.workspace, principal="another-local-user")
        second = self.release("momentum")
        select_model(self.cfg, first["version"], allow_demo=True)
        select_model(other, second["version"], allow_demo=True)
        self.assertEqual(predict_snapshot(self.cfg, self.snapshot, self.end_cutoff, allow_demo=True)["model_version"], first["version"])
        self.assertEqual(predict_snapshot(other, self.snapshot, self.end_cutoff, allow_demo=True)["model_version"], second["version"])
        draft = self.train()
        with self.assertRaises(ValueError):
            get_model(other, draft["version"])
        path = model_folder(self.cfg, first["version"]) / "model.json"
        path.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            predict_snapshot(self.cfg, self.snapshot, self.end_cutoff, allow_demo=True)
        self.assertEqual(len(list_models(other)), 2)

    def test_lightgbm_native_and_publication_immutable(self):
        if importlib.util.find_spec("lightgbm") is None:
            self.skipTest("install optional trees dependency")
        model = self.release("lightgbm")
        selected = select_model(self.cfg, model["version"], allow_demo=True)
        result = predict_snapshot(self.cfg, self.snapshot, self.end_cutoff, allow_demo=True)
        self.assertEqual(len(result["predictions"]), 5)
        self.assertEqual(selected["channel"], "demo")
        new_eval = evaluate_model(self.cfg, model["version"], self.snapshot, self.end_cutoff)
        with self.assertRaises(ValueError):
            publish_demo(self.cfg, model["version"], new_eval["evaluation_id"])


if __name__ == "__main__":
    unittest.main()
