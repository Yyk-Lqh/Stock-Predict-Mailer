import tempfile
import unittest
from pathlib import Path

from stock_predict_mailer.core import Config
from stock_predict_mailer.data import demo_csv, import_csv, load_snapshot
from stock_predict_mailer.research import experiment, feature_rows, label_rows, purged_before


class ResearchTests(unittest.TestCase):
    def test_purge_label_overlap(self):
        rows = [{"date": "2020-01-01", "label_end": "2020-01-07"},
                {"date": "2020-01-02", "label_end": "2020-01-08"}]
        self.assertEqual(purged_before(rows, "2020-01-08"), rows[:1])

    def test_future_bar_does_not_change_past_feature(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Config(Path(folder))
            manifest = import_csv(cfg, demo_csv(Path(folder) / "a.csv", 160, 6), synthetic=True)
            _, rows = load_snapshot(cfg, manifest["snapshot_id"])
            first = feature_rows(rows, cfg)
            rows[-1]["close"] *= 2
            second = feature_rows(rows, cfg)
            self.assertEqual(first[:-6], second[:-6])
            rows[20 * 6]["available_at"] = "2099-01-01T00:00:00+08:00"
            self.assertNotEqual(feature_rows(rows, cfg), second)

    def test_full_experiment_time_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Config(Path(folder))
            manifest = import_csv(cfg, demo_csv(Path(folder) / "a.csv", 180, 6), synthetic=True)
            result = experiment(cfg, manifest["snapshot_id"], "2021-01-01T20:00:00+08:00")
            split = result["split"]
            self.assertLess(split["train_max_label_end"], split["validation_start"])
            self.assertLess(split["development_max_label_end"], split["test_start"])
            self.assertEqual(len(result["predictions"]), 6)
            self.assertTrue(result["synthetic"])
            self.assertEqual(len(result["cost_diagnostics"]), 3)
            self.assertEqual(result["experiment_id"], experiment(cfg, manifest["snapshot_id"], "2021-01-01T20:00:00+08:00")["experiment_id"])
            real = import_csv(cfg, Path(folder) / "a.csv", synthetic=False)
            with self.assertRaises(ValueError):
                experiment(cfg, real["snapshot_id"], "2021-01-01T20:00:00+08:00")
            exploratory = experiment(cfg, real["snapshot_id"], "2021-01-01T20:00:00+08:00", allow_unverified_real=True)
            self.assertFalse(exploratory["synthetic"])
            self.assertTrue(exploratory["unverified_real"])


if __name__ == "__main__":
    unittest.main()
