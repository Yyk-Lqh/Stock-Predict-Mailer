import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_predict_mailer.core import Config, connect
from stock_predict_mailer.delivery import address, deliver, enqueue, outbox, process_lock
from stock_predict_mailer.pipeline import demo_run


class FakeSMTP:
    fail = False

    def __init__(self, *args, **kwargs): pass
    def ehlo(self): pass
    def starttls(self, **kwargs): pass
    def login(self, *args): pass
    def close(self): pass
    def sendmail(self, *args):
        if self.fail:
            raise TimeoutError("secret-must-not-be-recorded")
        return {}


class DeliveryTests(unittest.TestCase):
    def test_pre_send_failures_retry_then_stop_and_interruption_is_uncertain(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Config(Path(folder))
            built = demo_run(cfg, "2026-10-24T20:00:00+08:00")
            queued = enqueue(cfg, built["report_id"], "test@example.com", "sender@example.com")
            def unavailable(*args, **kwargs):
                raise ConnectionRefusedError("private-server-details")
            with patch.dict(os.environ, {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "u", "SMTP_PASSWORD": "p"}):
                for expected in ("retry", "retry", "failed"):
                    with connect(cfg) as con:
                        con.execute("UPDATE outbox SET next_attempt='2000-01-01T00:00:00Z' WHERE id=?", (queued["id"],))
                    self.assertEqual(deliver(cfg, queued["id"], allow_synthetic=True, allow_stale=True, factory=unavailable), expected)
            with connect(cfg) as con:
                con.execute("UPDATE outbox SET status='sending' WHERE id=?", (queued["id"],))
            self.assertEqual(deliver(cfg, queued["id"]), "uncertain")

    def test_pipeline_idempotent_preview_and_smtp_uncertainty(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Config(Path(folder))
            first = demo_run(cfg, "2026-10-24T20:00:00+08:00")
            second = demo_run(cfg, "2026-10-24T20:00:00+08:00")
            self.assertEqual(first["outbox_id"], second["outbox_id"])
            self.assertEqual(len(outbox(cfg)), 1)
            self.assertFalse(first["sent"])
            queued = enqueue(cfg, first["report_id"], "test@example.com", "sender@example.com")
            with self.assertRaises(ValueError):
                deliver(cfg, queued["id"])
            env = {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "user", "SMTP_PASSWORD": "private"}
            with patch.dict(os.environ, env), patch.object(FakeSMTP, "fail", True):
                self.assertEqual(deliver(cfg, queued["id"], allow_synthetic=True, allow_stale=True, factory=FakeSMTP), "uncertain")
            with connect(cfg) as con:
                row = con.execute("SELECT status,error,attempts FROM outbox WHERE id=?", (queued["id"],)).fetchone()
            self.assertEqual(tuple(row), ("uncertain", "TimeoutError", 1))
            self.assertEqual(deliver(cfg, queued["id"], allow_synthetic=True, allow_stale=True, factory=FakeSMTP), "uncertain")

    def test_success_and_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Config(Path(folder))
            built = demo_run(cfg, "2026-10-24T20:00:00+08:00")
            queued = enqueue(cfg, built["report_id"], "test@example.com", "sender@example.com")
            with patch.dict(os.environ, {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "u", "SMTP_PASSWORD": "p"}):
                self.assertEqual(deliver(cfg, queued["id"], allow_synthetic=True, allow_stale=True, factory=FakeSMTP), "submitted")
            with process_lock(cfg):
                with self.assertRaises(RuntimeError):
                    with process_lock(cfg):
                        pass
        with self.assertRaises(ValueError):
            address("safe@example.com\r\nBcc: other@example.com")


if __name__ == "__main__":
    unittest.main()
