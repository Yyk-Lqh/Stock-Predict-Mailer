import tempfile
import threading
import time
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from stock_predict_mailer.contracts import prepare_rows, read_contract
from stock_predict_mailer.core import atomic_write, digest, load_config, timestamp


class PlatformBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_atomic_write_completes_while_a_reader_holds_the_file(self):
        """Windows refuses to replace a file another handle is reading."""
        target = self.root / "state.json"
        atomic_write(target, b'{"value": 1}')
        stop = threading.Event()
        seen = []

        def reader():
            while not stop.is_set():
                try:
                    seen.append(target.read_bytes())
                except OSError:
                    # A replace window can make a read fail on Windows; that is the
                    # behaviour under test, not a test failure.
                    seen.append(b"")
                time.sleep(0.001)

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        try:
            for value in range(2, 12):
                atomic_write(target, f'{{"value": {value}}}'.encode())
        finally:
            stop.set()
            thread.join(5)
        self.assertEqual(target.read_bytes(), b'{"value": 11}')
        self.assertTrue(seen)
        leftovers = [path.name for path in self.root.iterdir() if path.name.startswith(".pending-")]
        self.assertEqual(leftovers, [], "a failed replace must not leave staging files behind")

    def test_atomic_write_handles_unicode_and_space_in_paths(self):
        target = self.root / "中文 目录" / "状态 文件.json"
        atomic_write(target, "内容".encode())
        self.assertEqual(target.read_text(encoding="utf-8"), "内容")
        atomic_write(target, "更新".encode())
        self.assertEqual(target.read_text(encoding="utf-8"), "更新")

    def test_cutoff_in_another_timezone_still_uses_the_contract_zone(self):
        """A UTC cutoff must select the same Shanghai session, not the UTC date."""
        contract = read_contract(Path("config/task-demo.json"))
        rows = []
        for day in ("2026-10-19", "2026-10-20", "2026-10-21"):
            for security in ("SYN000", "SYN001", "SYN002", "SYN003"):
                rows.append({"date": day, "security_id": security, "open": 10.0, "high": 10.5, "low": 9.5,
                             "close": 10.0, "volume": 1000, "available_at": f"{day}T18:00:00+08:00",
                             "source": "synthetic"})
        # 2026-10-20T13:00Z is 21:00 in Shanghai on the same day.
        shanghai = timestamp("2026-10-20T21:00:00+08:00")
        utc = timestamp("2026-10-20T13:00:00+00:00")
        self.assertEqual(shanghai, utc)
        self.assertEqual(shanghai.astimezone(ZoneInfo(contract["timezone"])).date().isoformat(), "2026-10-20")
        features_shanghai, _ = prepare_rows(rows, contract, "2026-10-20T21:00:00+08:00")
        features_utc, _ = prepare_rows(rows, contract, "2026-10-20T13:00:00+00:00")
        self.assertEqual([row["date"] for row in features_shanghai], [row["date"] for row in features_utc])

    def test_naive_timestamps_are_rejected(self):
        for value in ("2026-10-20T21:00:00", "2026-10-20"):
            with self.assertRaises(ValueError):
                timestamp(value)

    def test_config_rejects_unknown_timezone_and_relative_workspace_resolves(self):
        config = self.root / "config" / "example.toml"
        config.parent.mkdir(parents=True)
        config.write_text('workspace = "../state"\ntimezone = "Asia/Shanghai"\nhorizon = 5\ntop_k = 5\n'
                          'cost_bps = 30\nprincipal = "owner"\n', encoding="utf-8")
        loaded = load_config(config)
        self.assertEqual(loaded.workspace, (self.root / "state").resolve())
        config.write_text('workspace = "../state"\ntimezone = "Mars/Olympus"\nhorizon = 5\ntop_k = 5\n'
                          'cost_bps = 30\nprincipal = "owner"\n', encoding="utf-8")
        with self.assertRaises(ZoneInfoNotFoundError):
            load_config(config)

    def test_reader_between_writes_never_sees_a_partial_document(self):
        target = self.root / "manifest.json"
        atomic_write(target, b'{"a": 1}')
        stop = threading.Event()
        observed = []

        def reader():
            while not stop.is_set():
                try:
                    payload = target.read_bytes()
                except OSError:
                    continue
                if payload:
                    observed.append(payload)

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        try:
            for index in range(2, 30):
                atomic_write(target, f'{{"a": {index}}}'.encode())
        finally:
            stop.set()
            thread.join(5)
        self.assertTrue(observed)
        self.assertTrue(all(payload.startswith(b'{"a": ') and payload.endswith(b"}") for payload in observed))
        self.assertEqual(digest(target.read_bytes()), digest(b'{"a": 29}'))


if __name__ == "__main__":
    unittest.main()
