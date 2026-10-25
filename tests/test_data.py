import tempfile
import unittest
from pathlib import Path

from stock_predict_mailer.core import Config
from stock_predict_mailer.data import asof_rows, demo_csv, import_csv, load_snapshot, snapshot_summary, validate_rows


class DataTests(unittest.TestCase):
    def setUp(self):
        self.row = {"date": "2026-10-23", "security_id": "DEMO", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "available_at": "2026-10-23T18:00:00+08:00", "source": "test"}

    def test_duplicates_and_invalid_prices_rejected(self):
        with self.assertRaises(ValueError):
            validate_rows([self.row, self.row])
        invalid = {**self.row, "high": 8}
        with self.assertRaises(ValueError):
            validate_rows([invalid])
        with self.assertRaises(ValueError):
            validate_rows([{**self.row, "close": float("nan")}])

    def test_asof_uses_available_time(self):
        rows = validate_rows([self.row])
        self.assertEqual(asof_rows(rows, "2026-10-23T17:59:59+08:00"), [])
        self.assertEqual(len(asof_rows(rows, "2026-10-23T10:00:00+00:00")), 1)

    def test_snapshot_idempotency_and_integrity(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Config(Path(folder))
            path = demo_csv(Path(folder) / "bars.csv", days=80, stocks=6)
            first = import_csv(cfg, path, synthetic=True)
            self.assertEqual(first, import_csv(cfg, path, synthetic=True))
            summary = snapshot_summary(cfg, first["snapshot_id"])
            self.assertEqual(summary["duckdb_count"], 480)
            self.assertTrue(summary["synthetic"])
            manifest, rows = load_snapshot(cfg, first["snapshot_id"])
            self.assertEqual(len(rows), 480)
            parquet = cfg.workspace / "snapshots" / first["snapshot_id"] / "bars.parquet"
            parquet.write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                load_snapshot(cfg, first["snapshot_id"])


if __name__ == "__main__":
    unittest.main()
