import tempfile
import unittest
from pathlib import Path

import numpy as np

from stock_predict_mailer import dataset_auth
from stock_predict_mailer.contracts import read_contract
from stock_predict_mailer.core import Config, connect, now
from stock_predict_mailer.data import demo_csv, import_csv, load_snapshot
from stock_predict_mailer.drift import drift_history, feature_drift, population_stability
from stock_predict_mailer.model_registry import train_platform


class DriftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.cfg = Config(root / "state")
        self.contract = read_contract(Path("config/task-demo.json"))
        self.snapshot = import_csv(self.cfg, demo_csv(root / "bars.csv", 200, 6), synthetic=True)["snapshot_id"]
        _, self.raw = load_snapshot(self.cfg, self.snapshot)
        self.dates = sorted({row["date"] for row in self.raw})
        self.model = train_platform(self.cfg, self.snapshot, self.contract,
                                    f"{self.dates[110]}T20:00:00+08:00", "ridge", confirm_platform_data=True)
        self.cutoff = f"{self.dates[-1]}T20:00:00+08:00"

    def test_drift_is_reproducible_and_cached(self):
        first = feature_drift(self.cfg, self.model["version"], self.snapshot, self.cutoff, 30)
        second = feature_drift(self.cfg, self.model["version"], self.snapshot, self.cutoff, 30)
        self.assertEqual(first, second)
        self.assertEqual(first["drift_id"], second["drift_id"])
        self.assertEqual(set(first["features"]), {"return_1", "return_5", "return_20", "volatility_20", "relative_volume"})
        self.assertIn(first["verdict"], ("stable", "moderate_shift", "major_shift"))
        self.assertEqual(len(drift_history(self.cfg)), 1)

    def test_replay_grant_gates_the_report_and_revocation_stops_it(self):
        dataset_auth.set_authorization(self.cfg, self.snapshot, replay=True, note="drift diagnostics approved")
        report = feature_drift(self.cfg, self.model["version"], self.snapshot, self.cutoff, 30)
        self.assertIn("features", report)
        dataset_auth.set_authorization(self.cfg, self.snapshot, replay=False, note="replay withdrawn")
        with self.assertRaises(ValueError) as caught:
            feature_drift(self.cfg, self.model["version"], self.snapshot, self.cutoff, 30)
        self.assertIn("replay", str(caught.exception))
        dataset_auth.set_authorization(self.cfg, self.snapshot, replay=True, note="replay restored")
        self.assertEqual(feature_drift(self.cfg, self.model["version"], self.snapshot, self.cutoff, 30)["drift_id"],
                         report["drift_id"])

    def test_psi_is_zero_for_identical_and_large_for_shifted_samples(self):
        rng = np.random.default_rng(20261026)
        reference = rng.normal(0.0, 1.0, 4000)
        self.assertLess(population_stability(reference, reference.copy()), 1e-9)
        shifted = reference + 2.0
        self.assertGreater(population_stability(reference, shifted), 0.25)

    def test_old_authorization_table_gains_replay_without_losing_platform_grants(self):
        with connect(self.cfg) as con:
            con.executescript("""
              DROP TABLE IF EXISTS dataset_authorizations;
              CREATE TABLE dataset_authorizations (
                snapshot_id TEXT NOT NULL, owner TEXT NOT NULL,
                personal_training INTEGER NOT NULL, platform_training INTEGER NOT NULL,
                note TEXT NOT NULL DEFAULT '', recorded_at TEXT NOT NULL,
                PRIMARY KEY (snapshot_id, owner));
            """)
            con.execute("INSERT INTO dataset_authorizations VALUES (?, ?, 1, 1, 'legacy grant', ?)",
                        ("f" * 64, self.cfg.principal, now()))
        migrated = dataset_auth.record(self.cfg, "f" * 64)
        self.assertEqual(migrated["platform_training"], 1)
        self.assertEqual(migrated["replay_enabled"], 1, "an existing platform grant implies replay was already in use")
        with connect(self.cfg) as con:
            columns = {row[1] for row in con.execute("PRAGMA table_info(dataset_authorizations)")}
        self.assertIn("replay_enabled", columns)


if __name__ == "__main__":
    unittest.main()
