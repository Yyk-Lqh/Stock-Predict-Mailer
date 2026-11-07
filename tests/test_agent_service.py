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
            self.assertEqual(load(path)["workspace"], (Path(tmp) / "work").resolve())
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(["--config", str(path), "run", "--send"]), 0)
                self.assertEqual(main(["--config", str(path), "run", "--send"]), 0)
            self.assertIn('"simulated"', out.getvalue())
            path.write_text('workspace="work"\n[mail]\npassword="forbidden"', encoding="utf-8")
            with self.assertRaises(ServiceError):
                load(path)

    def test_mail_config_allowlist_and_chart_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.toml"
            path.write_text('workspace="work"\n[mail]\nchart_delivery="attachment"\nrecipient_allowlist=["a@example.com"]\n',
                            encoding="utf-8")
            cfg = load(path)
            self.assertEqual(cfg["mail"]["chart_delivery"], "attachment")
            self.assertEqual(cfg["mail"]["recipient_allowlist"], ["a@example.com"])
            for broken in ('recipient_allowlist=["a@example.com\\nBcc: x@example.com"]',
                           'recipient_allowlist="a@example.com"',
                           'chart_delivery="inline;evil"'):
                with self.subTest(broken=broken):
                    path.write_text('workspace="work"\n[mail]\n' + broken + "\n", encoding="utf-8")
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

    def test_png_determinism_and_mail_parts(self):
        import struct
        import zlib
        from email import policy
        from email.parser import BytesParser

        from stock_predict_mailer.agent_service.png import chart_png

        chart = {"title": "测试", "unit": "CNY", "caption": "区间", "series": {
            "observed": {"source": "历史", "points": [
                {"at": "2026-01-01T00:00:00Z", "value": 1},
                {"at": "2026-01-02T00:00:00Z", "value": 2}]},
            "forecast": {"source": "模型", "points": [
                {"at": "2026-01-03T00:00:00Z", "value": 3, "lower": 2, "upper": 4}]}}}
        png = chart_png(chart)
        self.assertEqual(png, chart_png(chart))
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        offset, compressed = 8, b""
        while offset < len(png):
            size = struct.unpack(">I", png[offset:offset + 4])[0]
            kind, data = png[offset + 4:offset + 8], png[offset + 8:offset + 8 + size]
            self.assertEqual(zlib.crc32(kind + data), struct.unpack(">I", png[offset + 8 + size:offset + 12 + size])[0])
            if kind == b"IDAT":
                compressed += data
            offset += size + 12
        self.assertEqual(len(zlib.decompress(compressed)), 350 * (720 * 3 + 1))
        from stock_predict_mailer.agent_service.contracts import instant
        issued = instant(self.analysis["prediction"]["generated_at"])
        chart["series"]["observed"]["points"][0]["at"] = (issued - timedelta(days=2)).isoformat()
        chart["series"]["observed"]["points"][1]["at"] = (issued - timedelta(days=1)).isoformat()
        forecast = chart["series"]["forecast"]["points"][0]
        forecast["at"] = (issued + timedelta(days=1)).isoformat()
        self.analysis["prediction"].pop("value", None)
        self.analysis["charts"] = [chart]
        self.analysis["analysis_id"] = identity({k: v for k, v in self.analysis.items() if k != "analysis_id"})
        png = chart_png(chart)
        for mode in ("inline", "attachment"):
            self.settings["chart_delivery"] = mode
            mid = self.mail.enqueue(self.analysis, mode + "@example.com")["id"]
            msg = BytesParser(policy=policy.default).parsebytes(
                (self.root / "agent-outbox" / f"{mid}.eml").read_bytes())
            part = next(p for p in msg.walk() if p.get_content_type() == "image/png")
            self.assertEqual(part.get_payload(decode=True), png)
            self.assertEqual(part.get_content_disposition(), mode)
            if mode == "inline":
                self.assertEqual(part["Content-ID"], "<chart-0@stock-predict-mailer.local>")

    def test_listing_filters_limits_and_cli(self):
        self.assertEqual(self.mail.listing(), [])
        first = self.enqueue()
        second = self.mail.enqueue(self.analysis, "second@example.com")["id"]
        self.mail.update(first, "failed", 2, "Rejected")
        self.assertEqual([r["id"] for r in self.mail.listing(1)], [second])
        row = self.mail.listing(status="failed")[0]
        self.assertEqual(set(row), {"id", "recipient", "sender", "transport", "status", "attempts", "next_attempt", "error"})
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["sender"], "sender@example.com")
        self.assertEqual(self.mail.listing(status="submitted"), [])
        for kwargs in ({"limit": 0}, {"limit": True}, {"limit": 1001}, {"status": "bad"}):
            with self.assertRaises(ServiceError):
                self.mail.listing(**kwargs)
        config = self.root / "list.toml"
        config.write_text('workspace="."\n', encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--config", str(config), "mail-list", "--limit", "1", "--status", "failed"]), 0)
        self.assertEqual(json.loads(output.getvalue())[0]["id"], first)

    def test_sender_name_keeps_identity_and_envelope(self):
        from email import policy
        from email.parser import BytesParser

        self.settings["sender_name"] = "研究报告, 每日"
        mid = self.enqueue()
        payload = (self.root / "agent-outbox" / f"{mid}.eml").read_bytes()
        msg = BytesParser(policy=policy.default).parsebytes(payload)
        self.assertEqual(msg["From"].addresses[0].display_name, "研究报告, 每日")
        self.assertEqual(msg["From"].addresses[0].addr_spec, self.settings["sender"])
        self.assertEqual(self.mail.get(mid)["sender"], self.settings["sender"])
        self.settings["sender_name"] = "Changed"
        self.assertEqual(self.enqueue(), mid)
        self.assertEqual((self.root / "agent-outbox" / f"{mid}.eml").read_bytes(), payload)
        self.assertEqual(mid, identity([self.analysis["analysis_id"], "recipient@example.com", self.settings["sender"], "smtp"]))
        for name in ("bad\rname", "bad\nname", 123):
            self.settings["sender_name"] = name
            with self.assertRaises(ServiceError):
                self.enqueue()
        config = self.root / "names.toml"
        config.write_text('workspace="."\n[mail]\nsender_name="研究报告"\n', encoding="utf-8")
        self.assertEqual(load(config)["mail"]["sender_name"], "研究报告")
        for name in ('bad\\rname', 'bad\\nname'):
            config.write_text('workspace="."\n[mail]\nsender_name="' + name + '"\n', encoding="utf-8")
            with self.assertRaises(ServiceError):
                load(config)

    def test_mock_context_carries_charts_into_mail(self):
        from email import policy
        from email.parser import BytesParser

        analysis = AnalysisAgent().analyze(MockPredictionAdapter().fetch(), MockContextAdapter().fetch())
        validate_analysis(analysis)
        self.assertEqual([c["title"] for c in analysis["charts"]], ["历史观测与预测", "实际值与历史预测"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.toml"
            path.write_text('workspace="work"\n[context]\nadapter="mock"\n', encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--config", str(path), "run", "--send"]), 0)
            mid = json.loads(output.getvalue())["mail"]["id"]
            msg = BytesParser(policy=policy.default).parsebytes(
                (Path(tmp) / "work" / "agent-outbox" / f"{mid}.eml").read_bytes())
            parts = [p for p in msg.walk() if p.get_content_type() == "image/png"]
            self.assertEqual([p["Content-ID"] for p in parts],
                             ["<chart-0@stock-predict-mailer.local>", "<chart-1@stock-predict-mailer.local>"])
            self.assertTrue(all(p.get_payload(decode=True)[:8] == b"\x89PNG\r\n\x1a\n" for p in parts))

    def test_chart_data_rides_outside_the_context_contract(self):
        raw = MockContextAdapter().fetch()
        p = MockPredictionAdapter().fetch()
        series = raw.pop("chart_data")
        analysis = AnalysisAgent().analyze(p, raw)
        self.assertNotIn("charts", analysis)
        analysis = AnalysisAgent().analyze(p, {**raw, "chart_data": series})
        self.assertEqual(len(analysis["charts"]), 2)
        broken = {**raw, "chart_data": {"unit": "CNY", "series": {"forecast": {"source": "x", "points": [
            {"at": p["generated_at"], "value": 1}]}}}}
        with self.assertRaises(ServiceError):
            AnalysisAgent().analyze(p, broken)

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

    def test_allowlist_blocks_unlisted_recipient(self):
        self.settings["recipient_allowlist"] = ["allowed@example.com"]
        with self.assertRaises(ServiceError) as caught:
            self.mail.enqueue(self.analysis, "other@example.com")
        self.assertEqual(caught.exception.code, "PERMISSION_DENIED")
        self.assertEqual(self.mail.enqueue(self.analysis, "allowed@example.com")["status"], "pending")

    def test_drain_delivers_due_only_and_isolates_failures(self):
        first = self.enqueue()
        second = self.mail.enqueue(self.analysis, "second@example.com")["id"]
        with self.mail.db() as con:
            con.execute("UPDATE mail SET next_attempt='2099-01-01T00:00:00+00:00' WHERE id=?", (second,))
        summary = self.mail.drain()
        self.assertEqual(summary["due"], 1)
        self.assertEqual([item["id"] for item in summary["results"]], [first])
        self.assertEqual(summary["results"][0]["status"], "submitted")
        self.assertEqual(FakeSMTP.sent, 1)
        with self.mail.db() as con:
            con.execute("UPDATE mail SET next_attempt='2000-01-01T00:00:00+00:00' WHERE id=?", (second,))
        with patch.dict(os.environ, {}, clear=True):
            blocked = self.mail.drain()
        self.assertEqual(blocked["results"][0]["status"], "pending")
        self.assertEqual(blocked["results"][0]["error"], "MAIL_CONFIG")
        with self.assertRaises(ServiceError):
            self.mail.drain(0)

    def test_resolve_is_the_only_way_out_of_uncertain(self):
        FakeSMTP.failure = TimeoutError("secret")
        mid = self.enqueue()
        self.assertEqual(self.mail.deliver(mid)["status"], "uncertain")
        with self.assertRaises(ServiceError):
            self.mail.resolve(mid, delivered="yes")
        self.assertEqual(self.mail.resolve(mid, delivered=False)["status"], "retry")
        FakeSMTP.failure = None
        self.assertEqual(self.mail.deliver(mid)["status"], "submitted")
        self.assertEqual(self.mail.get(mid)["attempts"], 2)
        with self.assertRaises(ServiceError):
            self.mail.resolve(mid, delivered=True)
        with self.mail.db() as con:
            actions = [row[0] for row in con.execute("SELECT action FROM mail_audit WHERE message_id=?", (mid,))]
        self.assertEqual(actions, ["confirmed_not_delivered"])

    def test_resolve_can_accept_delivery_without_resending(self):
        FakeSMTP.failure = TimeoutError("secret")
        mid = self.enqueue()
        self.assertEqual(self.mail.deliver(mid)["status"], "uncertain")
        self.assertEqual(self.mail.resolve(mid, delivered=True)["status"], "submitted")
        self.assertEqual(self.mail.deliver(mid)["status"], "submitted")
        self.assertEqual(FakeSMTP.sent, 1)


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
