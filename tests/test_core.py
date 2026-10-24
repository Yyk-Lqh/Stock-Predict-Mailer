import tempfile
import unittest
from pathlib import Path

from stock_predict_mailer.core import Config, atomic_write, connect, load_config, timestamp, tracked_run


class CoreTests(unittest.TestCase):
    def test_config_relative_paths_and_reject_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            path.write_text('workspace="state"\nhorizon=5\n', encoding="utf-8")
            self.assertEqual(load_config(path).workspace, Path(folder) / "state")
            path.write_text('workspace="state"\nhorizno=5\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_failed_run_records_type_without_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Config(Path(folder))
            with self.assertRaises(RuntimeError):
                with tracked_run(cfg, "test"):
                    raise RuntimeError("secret-token")
            with connect(cfg) as con:
                row = con.execute("SELECT status,error FROM runs").fetchone()
            self.assertEqual(tuple(row), ("failed", "RuntimeError"))

    def test_atomic_replace_and_timezone(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "a"
            atomic_write(path, b"first")
            atomic_write(path, b"second")
            self.assertEqual(path.read_bytes(), b"second")
        with self.assertRaises(ValueError):
            timestamp("2026-10-24T20:00:00")


if __name__ == "__main__":
    unittest.main()
