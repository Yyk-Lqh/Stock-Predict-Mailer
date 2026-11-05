import copy
import io
import json
import os
import smtplib
import socketserver
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from stock_predict_mailer.agent_service.adapters import FileAdapter, HttpAdapter, MockContextAdapter, MockPredictionAdapter
from stock_predict_mailer.agent_service.analysis import AnalysisAgent, identity, validate_analysis
from stock_predict_mailer.agent_service.config import load
from stock_predict_mailer.agent_service.contracts import ServiceError, context, decode, prediction, utcnow
from stock_predict_mailer.agent_service.mail import MailService
from stock_predict_mailer.agent_service.reporting import render, save_report
from stock_predict_mailer.cli import main


class FakeSMTP:
    sent = 0
    failure = None

    def __init__(self, *args, **kwargs):
        pass

    def ehlo(self):
        pass

    def starttls(self, **kwargs):
        pass

    def login(self, *args):
        pass

    def close(self):
        pass

    def sendmail(self, *args):
        type(self).sent += 1
        if self.failure:
            raise self.failure
        return {}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.p = MockPredictionAdapter().fetch()
        self.c = MockContextAdapter().fetch()

    def test_normalizes_time_and_preserves_missing_confidence(self):
        p = prediction(self.p)
        self.assertTrue(p["generated_at"].endswith("+00:00"))
        a = AnalysisAgent().analyze(p, self.c)
        self.assertIsNone(a["prediction"]["confidence"])
        self.assertEqual(a["mode"], "deterministic_no_llm")
        self.assertEqual(a, validate_analysis(a))
        self.assertEqual(a["analysis_id"], AnalysisAgent().analyze(p, self.c)["analysis_id"])

    def test_missing_context_explicit_limit(self):
        a = AnalysisAgent().analyze(self.p)
        self.assertFalse(a["facts"])
        self.assertTrue(any("未提供客观上下文" in s for s in a["limitations"]))

    def test_invalid_predictions(self):
        cases = [{"confidence": 1.1}, {"confidence": True}, {"confidence": float("nan")}, {"value": 10**1000, "value_unit": "score"},
                 {"generated_at": "2026-01-01T00:00:00"}, {"direction": "buy"},
                 {"horizon": {"value": True, "unit": "hours"}}, {"synthetic": "false"},
                 {"value": 10}, {"unexpected": "secret"}, {"generated_at": (utcnow() + timedelta(days=2)).isoformat()}]
        for changes in cases:
            with self.subTest(changes=list(changes)), self.assertRaises(ServiceError):
                prediction({**self.p, **changes})
        p = {k: v for k, v in self.p.items() if k != "direction"}
        with self.assertRaises(ServiceError):
            prediction(p)

    def test_value_only_and_confidence_not_probability(self):
        self.p.pop("direction")
        self.p.update(value=0.3, value_unit="score", confidence=0.9)
        a = AnalysisAgent().analyze(self.p)
        self.assertEqual(a["inferences"][0]["code"], "INSUFFICIENT")
        self.assertTrue(any("不能直接理解" in s for s in a["limitations"]))

    def test_expiry_and_max_age(self):
        old = utcnow() - timedelta(days=2)
        for expiry in (utcnow() - timedelta(days=1), utcnow() + timedelta(days=1)):
            with self.assertRaises(ServiceError) as cm:
                prediction({**self.p, "generated_at": old.isoformat(), "valid_until": expiry.isoformat()})
            self.assertEqual(cm.exception.code, "STALE_RESULT")

    def test_context_errors(self):
        for field, value in (("subject", "OTHER"), ("facts", [self.c["facts"][0]] * 2)):
            with self.assertRaises(ServiceError):
                context({**self.c, field: value}, self.p["subject"])
        for changes in ({"observed_at": (utcnow() - timedelta(days=2)).isoformat()},
                        {"available_at": (utcnow() + timedelta(hours=1)).isoformat()}, {"value": float("inf")}):
            c = copy.deepcopy(self.c)
            c["facts"][0].update(changes)
            with self.assertRaises(ServiceError):
                context(c, self.p["subject"])

    def test_agent_failure_is_visible(self):
        with patch("stock_predict_mailer.agent_service.analysis.http_json", side_effect=ServiceError("UPSTREAM_UNAVAILABLE", "secret")):
            a = AnalysisAgent({"provider": "http", "url": "http://localhost"}).analyze(self.p)
        self.assertEqual(a["status"], "degraded")
        self.assertIn("AGENT_UNAVAILABLE", str(a["limitations"]))
        self.assertNotIn("secret", json.dumps(a))

    def test_agent_cannot_invent_direction_or_evidence(self):
        good = {"evidence_ids": ["f1"], "inference_codes": ["MODEL_UP"], "recommendation_codes": ["VERIFY"]}
        for changes in ({}, {"evidence_ids": ["invented"]}, {"inference_codes": ["MODEL_DOWN"]}, {"text": "guaranteed profit"}):
            with patch("stock_predict_mailer.agent_service.analysis.http_json", return_value={**good, **changes}):
                a = AnalysisAgent({"provider": "http", "url": "http://localhost"}).analyze(self.p, self.c)
            self.assertEqual(a["status"], "ok" if not changes else "degraded")

    def test_html_escapes_upstream_text(self):
        self.c["facts"][0]["name"] = "<script>alert(1)</script>"
        a = AnalysisAgent().analyze(self.p, self.c)
        _, html = render(a)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        with tempfile.TemporaryDirectory() as tmp:
            folder = save_report(Path(tmp), a)
            self.assertEqual(json.loads((folder / "analysis.json").read_text(encoding="utf-8")), a)

    def test_output_validation(self):
        a = AnalysisAgent().analyze(self.p)
        a["inferences"][0]["code"] = "MODEL_DOWN"
        a["analysis_id"] = identity({k: v for k, v in a.items() if k != "analysis_id"})
        with self.assertRaises(ServiceError):
            validate_analysis(a)

    def test_file_and_json_guards(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'[]oops', b'x' * (1024 * 1024 + 1)):
            with self.assertRaises(ServiceError):
                decode(raw)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prediction.json"
            path.write_text(json.dumps(self.p), encoding="utf-8")
            self.assertEqual(FileAdapter(path).fetch(), self.p)

    def test_config_validation_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.toml"
            path.write_text('workspace="work"\n[context]\nadapter="mock"\n', encoding="utf-8")
            self.assertEqual(load(path)["workspace"], Path(tmp) / "work")
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(["--config", str(path), "run", "--send"]), 0)
                self.assertEqual(main(["--config", str(path), "run", "--send"]), 0)
            self.assertIn('"simulated"', out.getvalue())
            path.write_text('workspace="work"\n[mail]\npassword="forbidden"', encoding="utf-8")
            with self.assertRaises(ServiceError):
                load(path)


class MailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.analysis = AnalysisAgent().analyze(MockPredictionAdapter().fetch(), MockContextAdapter().fetch())
        self.settings = {"transport": "smtp", "sender": "sender@example.com", "host": "localhost", "allow_synthetic": True}
        self.mail = MailService(self.root, self.settings, smtp_factory=FakeSMTP)
        self.env = patch.dict(os.environ, {"SMTP_USER": "test", "SMTP_PASSWORD": "test-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)
        FakeSMTP.sent, FakeSMTP.failure = 0, None

    def enqueue(self):
        return self.mail.enqueue(self.analysis, "recipient@example.com")["id"]

    def test_success_and_duplicate(self):
        mid = self.enqueue()
        self.assertEqual(self.mail.deliver(mid)["status"], "submitted")
        self.assertEqual(self.enqueue(), mid)
        self.assertEqual(self.mail.deliver(mid)["status"], "submitted")
        self.assertEqual(FakeSMTP.sent, 1)

    def test_file_transport(self):
        self.settings["transport"] = "file"
        mid = self.enqueue()
        self.assertEqual(self.mail.deliver(mid)["status"], "simulated")
        self.assertTrue((self.root / "sent" / f"{mid}.eml").exists())

    def test_uncertain_stops_retry(self):
        FakeSMTP.failure = TimeoutError("secret")
        mid = self.enqueue()
        self.assertEqual(self.mail.deliver(mid)["status"], "uncertain")
        self.mail.deliver(mid)
        self.assertEqual(FakeSMTP.sent, 1)
        self.assertNotIn("secret", str(self.mail.public(self.mail.get(mid))))

    def test_retry_schedule_and_limit(self):
        def unavailable(*args, **kwargs):
            raise ConnectionRefusedError("secret")
        self.mail.smtp_factory = unavailable
        mid = self.enqueue()
        for expected in ("retry", "retry", "failed"):
            with self.mail.db() as con:
                con.execute("UPDATE mail SET next_attempt='2000-01-01T00:00:00Z' WHERE id=?", (mid,))
            self.assertEqual(self.mail.deliver(mid)["status"], expected)
            if expected == "retry":
                self.assertEqual(self.mail.deliver(mid)["status"], "not_due")

    def test_definite_smtp_rejection(self):
        for code, expected in ((451, "retry"), (550, "failed")):
            with self.subTest(code=code):
                FakeSMTP.failure = smtplib.SMTPDataError(code, b"secret")
                mid = self.enqueue()
                self.assertEqual(self.mail.deliver(mid)["status"], expected)
                self.analysis = AnalysisAgent().analyze({**MockPredictionAdapter().fetch(), "prediction_id": str(code)})

    def test_interrupted_delivery(self):
        mid = self.enqueue()
        self.mail.update(mid, "sending", 1)
        self.assertEqual(self.mail.deliver(mid)["status"], "uncertain")
        self.assertEqual(FakeSMTP.sent, 0)

    def test_mail_guards(self):
        with self.assertRaises(ServiceError):
            self.mail.enqueue(self.analysis, "x@example.com\r\nBcc: bad@example.com")
        mid = self.enqueue()
        payload = self.root / "agent-outbox" / f"{mid}.eml"
        payload.write_bytes(b"tampered")
        with self.assertRaises(ServiceError):
            self.mail.deliver(mid)
        with self.assertRaises(ServiceError):
            self.mail.get("../escape")

    def test_synthetic_guard_and_no_credentials(self):
        self.settings["allow_synthetic"] = False
        mid = self.enqueue()
        with self.assertRaises(ServiceError):
            self.mail.deliver(mid)
        self.assertEqual(self.mail.get(mid)["attempts"], 0)
        self.settings["allow_synthetic"] = True
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ServiceError):
            self.mail.deliver(mid)


class LocalSMTPHandler(socketserver.StreamRequestHandler):
    messages = []

    def handle(self):
        self.wfile.write(b"220 localhost test\r\n")
        while True:
            line = self.rfile.readline()
            if not line:
                break
            if line.upper().startswith(b"DATA"):
                self.wfile.write(b"354 send data\r\n")
                data = b""
                while True:
                    line = self.rfile.readline()
                    if line in (b".\r\n", b""):
                        break
                    data += line
                self.messages.append(data)
                self.wfile.write(b"250 accepted\r\n")
            elif line.upper().startswith(b"EHLO"):
                self.wfile.write(b"250 localhost\r\n")
            else:
                self.wfile.write(b"250 ok\r\n")


class LocalSMTP(smtplib.SMTP):
    # Test server has no TLS/auth; production MailService always requires both.
    def starttls(self, **kwargs):
        pass

    def login(self, *args):
        pass


class SocketIntegrationTests(unittest.TestCase):
    def test_mock_to_report_to_smtp_wire(self):
        with socketserver.TCPServer(("127.0.0.1", 0), LocalSMTPHandler) as server, tempfile.TemporaryDirectory() as tmp:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            settings = {"transport": "smtp", "sender": "sender@example.com", "host": "127.0.0.1",
                        "port": server.server_address[1], "allow_synthetic": True}
            a = AnalysisAgent().analyze(MockPredictionAdapter().fetch(), MockContextAdapter().fetch())
            save_report(Path(tmp), a)
            mail = MailService(Path(tmp), settings, smtp_factory=LocalSMTP)
            try:
                with patch.dict(os.environ, {"SMTP_USER": "test", "SMTP_PASSWORD": "test"}):
                    queued = mail.enqueue(a, "recipient@example.com")
                    self.assertEqual(mail.deliver(queued["id"])["status"], "submitted")
                self.assertIn(b"multipart/alternative", LocalSMTPHandler.messages[-1])
                self.assertIn(b"Message-ID:", LocalSMTPHandler.messages[-1])
            finally:
                server.shutdown()
                thread.join(timeout=2)

    def test_http_adapter_and_failure(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == "/ok" else 503)
                self.end_headers()
                self.wfile.write(json.dumps(MockPredictionAdapter().fetch()).encode())

            def log_message(self, *args):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                self.assertEqual(prediction(HttpAdapter(url + "/ok").fetch())["subject"], "DEMO.SZ")
                with self.assertRaises(ServiceError) as cm:
                    HttpAdapter(url + "/fail").fetch()
                self.assertTrue(cm.exception.retryable)
            finally:
                server.shutdown()


if __name__ == "__main__":
    unittest.main()
