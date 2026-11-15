"""Endpoint cutover uses synthetic messages and injected transports exclusively."""
import asyncio
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import asynccontextmanager, redirect_stdout
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cryptography.fernet import Fernet

import test_mail_core as core_fixtures
from stock_predict_mailer.agent_service.adapters import MockPredictionAdapter
from stock_predict_mailer.agent_service.analysis import AnalysisAgent, identity
from stock_predict_mailer.agent_service.contracts import ServiceError, utcnow
from stock_predict_mailer.cli import main
from stock_predict_mailer.control.mcp_layer import MCPLayer
from stock_predict_mailer.control.models import Budget
from stock_predict_mailer.control.orchestrator import Orchestrator
from stock_predict_mailer.control.store import Store
from stock_predict_mailer.core import Config, digest
from stock_predict_mailer.delivery import process_lock
from stock_predict_mailer.mail_core import MailCore, bindings, history, legacy, migration
from stock_predict_mailer.mail_core.transports import MCPTransport
from test_mail_core import database


class FakeSMTP:
    def __init__(self, *args, **kwargs): pass
    def ehlo(self): pass
    def starttls(self, **kwargs): pass
    def login(self, *args): pass
    def close(self): pass
    def sendmail(self, *args): return {}


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.analysis = AnalysisAgent().analyze(MockPredictionAdapter().fetch())
        self.settings = {"transport": "smtp", "sender": "sender@example.com", "host": "smtp.example.com", "allow_synthetic": True}
        self.core = MailCore(self.root, self.settings)

    def queue(self):
        return self.core.enqueue(self.analysis, "recipient@example.com")["id"]

    def code(self, expected, fn, *args, **kwargs):
        with self.assertRaises(ServiceError) as caught:
            fn(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected)

    def files(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}


class BindingTests(Fixture):
    def test_endpoint_drift_stops_before_attempt_or_smtp(self):
        mid = self.queue()
        for field, value in (("host", "other.example.com"), ("port", 2465), ("tls", "ssl"), ("user_env", "OTHER_USER"), ("password_env", "OTHER_PASSWORD")):
            with self.subTest(field=field), patch.dict(self.settings, {field: value}), patch("smtplib.SMTP") as smtp:
                self.code("MAIL_ENDPOINT_CHANGED", self.core.deliver, mid)
                self.assertEqual(self.core.get(mid)["attempts"], 0)
                smtp.assert_not_called()

    def test_credential_values_rotate_without_entering_binding(self):
        mid = self.queue()
        with patch.dict(os.environ, {"SMTP_USER": "private-rotated-user", "SMTP_PASSWORD": "private-rotated-password"}):
            self.core.smtp_factory = FakeSMTP
            result = self.core.deliver(mid)
        self.assertEqual(result["status"], "submitted")
        self.assertNotIn(b"private-rotated", (self.root / "agent-mail.sqlite3").read_bytes())

    def test_plan_is_readonly_and_binding_preserves_uncertain_attempts(self):
        mid = self.queue()
        self.core.update(mid, "uncertain", 2)
        self.settings["host"] = "replacement.example.com"
        before = self.files()
        plan = self.core.binding_plan(mid)
        self.assertFalse(plan["sends_mail"])
        self.assertEqual(self.files(), before)
        result = self.core.bind(mid, plan["plan_id"])
        self.assertEqual((result["status"], result["attempts"]), ("uncertain", 2))
        self.assertEqual(self.core.binding(mid)["profile"]["host"], "replacement.example.com")
        with self.core.db() as con:
            self.assertEqual(con.execute("SELECT action FROM mail_audit ORDER BY rowid DESC").fetchone()[0], "reviewed_endpoint_binding")

    def test_plan_change_and_completed_binding_are_rejected(self):
        mid = self.queue()
        plan = self.core.binding_plan(mid)
        self.settings["host"] = "changed.example.com"
        self.code("MAIL_PLAN_CHANGED", self.core.bind, mid, plan["plan_id"])
        self.core.update(mid, "submitted", 1)
        plan = self.core.binding_plan(mid)
        self.code("MAIL_FINAL", self.core.bind, mid, plan["plan_id"])

    def test_sending_binding_recovers_without_retry(self):
        mid = self.queue()
        self.core.update(mid, "sending", 1)
        result = self.core.bind(mid, self.core.binding_plan(mid)["plan_id"])
        self.assertEqual((result["status"], result["attempts"]), ("uncertain", 1))

    def test_unbound_attempted_history_needs_review(self):
        mid = self.queue()
        with self.core.db() as con:
            con.execute("DELETE FROM mail_binding WHERE message_id=?", (mid,))
            con.execute("UPDATE mail SET attempts=1 WHERE id=?", (mid,))
        self.code("MAIL_BINDING_REQUIRED", self.core.deliver, mid)
        self.core.bind(mid, self.core.binding_plan(mid)["plan_id"])
        self.assertEqual(self.core.get(mid)["attempts"], 1)
        self.assertIsNotNone(self.core.binding(mid)["profile"])

    def test_missing_initial_host_can_bind_on_explicit_first_delivery(self):
        self.settings.pop("host")
        mid = self.queue()
        self.assertIsNone(self.core.binding(mid)["profile"])
        self.settings["host"] = "smtp.example.com"
        with patch.dict(os.environ, {"SMTP_USER": "u", "SMTP_PASSWORD": "p"}):
            self.core.smtp_factory = FakeSMTP
            self.assertEqual(self.core.deliver(mid)["status"], "submitted")

    def test_paired_envelope_and_payload_tamper_still_fails_binding(self):
        mid = self.queue()
        path = self.root / "agent-outbox" / (mid + ".eml")
        path.write_bytes(path.read_bytes().replace(b"recipient@example.com", b"intruder@example.com"))
        with self.core.db() as con:
            con.execute("UPDATE mail SET recipient=?,payload_hash=? WHERE id=?", ("intruder@example.com", digest(path.read_bytes()), mid))
        self.code("MAIL_INTEGRITY", self.core.deliver, mid)

    def test_binding_profile_tamper_cannot_be_approved(self):
        mid = self.queue()
        with self.core.db() as con:
            con.execute("UPDATE mail_binding SET profile='{}' WHERE message_id=?", (mid,))
        self.code("MAIL_INTEGRITY", self.core.binding_plan, mid)

    def test_allowlist_revocation_and_process_lock(self):
        mid = self.queue()
        self.settings["recipient_allowlist"] = ["someoneelse@example.com"]
        self.code("PERMISSION_DENIED", self.core.deliver, mid)
        with process_lock(self.core.cfg), self.assertRaises(RuntimeError):
            self.core.bind(mid, self.core.binding_plan(mid)["plan_id"])

    def test_cli_plan_bind_and_history_commands_do_not_send(self):
        mid = self.queue()
        cfg = self.root / "agent.toml"
        cfg.write_text('workspace = "' + self.root.as_posix() + '"\n[mail]\ntransport = "smtp"\nsender = "sender@example.com"\nhost = "smtp.example.com"\n', encoding="utf-8")
        def invoke(*arguments):
            output = io.StringIO()
            with redirect_stdout(output), patch("smtplib.SMTP", side_effect=AssertionError("must not send")):
                result = main(["--config", str(cfg), *arguments])
            self.assertEqual(result, 0, output.getvalue())
            return json.loads(output.getvalue())
        before = self.files()
        plan = invoke("mail-binding-plan", mid)
        self.assertEqual(before, self.files())
        self.assertEqual(invoke("mail-bind", mid, "--expected-plan", plan["plan_id"])["attempts"], 0)
        reviewed = invoke("mail-history-plan")
        self.assertFalse(invoke("mail-history-ack", "--expected-plan", reviewed["plan_id"], "--not-before", utcnow().isoformat())["sends_mail"])


class LegacyCutoverTests(Fixture):
    def build(self):
        if importlib.util.find_spec("sklearn") is None:
            self.skipTest("legacy report API requires the research extra")
        cfg = Config(self.root)
        report_id = digest(b"synthetic cutover report")
        folder = self.root / "reports" / report_id
        folder.mkdir(parents=True)
        payload = b"<html>Synthetic report</html>"
        (folder / "report.html").write_bytes(payload)
        (folder / "report.json").write_text(json.dumps({"principal": "owner", "evidence": [], "cutoff": "2026-10-24T20:00:00+08:00",
            "synthetic": True, "latest_data_date": "2026-10-23", "html_sha256": digest(payload)}), encoding="utf-8")
        legacy.enqueue(cfg, report_id, "preview@example.invalid")
        queued = legacy.enqueue(cfg, report_id, "recipient@example.com", "sender@example.com")
        return cfg, queued

    def old_fixture(self, status="retry"):
        # Reuse only the fixture helper, without inheriting/rerunning B1 tests.
        fixture = core_fixtures.MigrationTests()
        fixture.source = self.root
        return fixture.legacy(status=status)

    def test_new_legacy_rows_live_only_in_core_and_keep_original_eml(self):
        cfg, row = self.build()
        with database(self.root / "state.sqlite3") as con:
            self.assertIsNone(con.execute("SELECT name FROM sqlite_master WHERE name='outbox'").fetchone())
        original = (self.root / "outbox" / (row["id"] + ".eml")).read_bytes()
        self.assertEqual(original, (self.root / "agent-outbox" / (row["core_id"] + ".eml")).read_bytes())
        self.assertIn(("<" + row["id"] + "@").encode(), original)
        self.assertEqual(legacy.enqueue(cfg, row["report_id"], row["recipient"], row["sender"])["core_id"], row["core_id"])
        self.assertEqual(legacy.listing(Config(self.root, principal="other")), [])
        other = MailCore(self.root, {})
        other.cfg = Config(self.root, principal="other")
        self.code("PERMISSION_DENIED", other.get, row["core_id"])
        self.code("PERMISSION_DENIED", other.binding_plan, row["core_id"])
        self.assertEqual(other.listing(), [])

    def test_legacy_generic_send_and_drain_cannot_bypass_report_checks(self):
        _, row = self.build()
        self.code("MAIL_CONFIG", self.core.deliver, row["core_id"])
        self.assertEqual(self.core.drain()["due"], 0)
        self.code("PERMISSION_DENIED", legacy.deliver, Config(self.root), row["id"])

    def test_completed_and_uncertain_old_rows_are_readonly(self):
        mid, _ = self.old_fixture("sending")
        before = (self.root / "state.sqlite3").read_bytes()
        self.assertEqual(legacy.deliver(Config(self.root), mid), "uncertain")
        self.assertEqual((self.root / "state.sqlite3").read_bytes(), before)
        self.assertFalse((self.root / "agent-mail.sqlite3").exists())

    def test_old_pending_requires_explicit_plan_binding_without_source_writes(self):
        mid, payload = self.old_fixture()
        cfg = Config(self.root)
        source = (self.root / "state.sqlite3").read_bytes()
        self.code("MAIL_BINDING_REQUIRED", legacy.deliver, cfg, mid)
        with patch.dict(os.environ, {"SMTP_HOST": "smtp.example.com"}):
            plan = legacy.binding_plan(cfg, mid)
            self.assertFalse((self.root / "agent-mail.sqlite3").exists())
            config = self.root / "agent.toml"
            config.write_text('workspace = "' + self.root.as_posix() + '"\n[mail]\ntransport="file"\nsender="research@example.invalid"\n', encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--config", str(config), "legacy-binding-plan", mid, "--principal", "owner"]), 0)
            self.assertEqual(json.loads(output.getvalue())["plan_id"], plan["plan_id"])
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--config", str(config), "legacy-bind", mid, "--principal", "owner", "--expected-plan", plan["plan_id"]]), 0)
            bound = json.loads(output.getvalue())
            self.assertEqual(legacy.bind_old(cfg, mid, plan["plan_id"])["core_id"], bound["core_id"])
        self.assertEqual((self.root / "state.sqlite3").read_bytes(), source)
        self.assertEqual((bound["status"], bound["attempts"]), ("retry", 1))
        self.assertEqual((self.root / "agent-outbox" / (bound["core_id"] + ".eml")).read_bytes(), payload)

    def test_completed_old_records_cannot_be_activated(self):
        mid, _ = self.old_fixture("submitted")
        with patch.dict(os.environ, {"SMTP_HOST": "smtp.example.com"}):
            plan = legacy.binding_plan(Config(self.root), mid)
            self.code("MAIL_FINAL", legacy.bind_old, Config(self.root), mid, plan["plan_id"])

    def test_legacy_rebind_retains_principal_report_source_and_status(self):
        cfg, row = self.build()
        self.core.cfg = cfg
        self.core.update(row["core_id"], "uncertain", 2)
        with patch.dict(os.environ, {"SMTP_HOST": "new.example.com"}):
            plan = self.core.binding_plan(row["core_id"])
            self.core.bind(row["core_id"], plan["plan_id"])
        current = legacy.listing(cfg)
        bound = next(item for item in current if item["id"] == row["id"])
        self.assertEqual((bound["principal"], bound["report_id"], bound["status"], bound["attempts"]), ("owner", row["report_id"], "uncertain", 2))

    def test_migration_understands_legacy_core_and_principal_filter(self):
        _, row = self.build()
        plan = migration.plan_migration(self.root)
        self.assertTrue(plan["ready"], plan)
        entry = next(item for item in plan["entries"] if item["source_id"] == row["core_id"])
        self.assertEqual((entry["principal"], entry["report_id"], entry["kind"]), ("owner", row["report_id"], "message"))
        self.assertEqual(migration.plan_migration(self.root, principal="other")["counts"]["messages"], 0)
        target = self.root / "archive"
        self.assertEqual(migration.import_archive(self.root, target, plan["plan_id"])["imported"], 2)


class HistoryTests(Fixture):
    def marker(self, key=None, status="sending", development=False):
        key = key or identity(["synthetic historical marker"])
        filename = "control-development.sqlite3" if development else "control.sqlite3"
        with database(self.root / filename) as con:
            con.execute("CREATE TABLE IF NOT EXISTS mcp_mail(id TEXT PRIMARY KEY,status TEXT)")
            con.execute("INSERT OR REPLACE INTO mcp_mail VALUES (?,?)", (key, status))
        return key

    def test_exact_legacy_marker_returns_uncertain_without_write(self):
        key = self.marker()
        before = self.files()
        self.assertEqual(history.historical_result(self.root, key), {"id": key, "status": "uncertain", "legacy_read_only": True})
        self.assertEqual(self.files(), before)

    def test_conflicting_markers_across_databases_are_uncertain(self):
        key = self.marker(status="submitted")
        self.marker(key, "simulated", development=True)
        self.assertEqual(history.historical_result(self.root, key)["status"], "uncertain")

    def test_unknown_history_needs_review_and_new_prediction_fence(self):
        self.marker()
        self.code("MAIL_HISTORY_REVIEW_REQUIRED", history.require_new_prediction, self.core, self.analysis)
        plan = history.review(self.root)
        history.acknowledge(self.core, plan["plan_id"], (utcnow() - timedelta(days=1)).isoformat())
        history.require_new_prediction(self.core, self.analysis)
        old = {"prediction": {"generated_at": "2020-01-01T00:00:00Z"}}
        self.code("MAIL_HISTORY_REVIEW_REQUIRED", history.require_new_prediction, self.core, old)
        self.marker(status="submitted")
        self.code("MAIL_HISTORY_REVIEW_REQUIRED", history.require_new_prediction, self.core, self.analysis)

    def test_changed_plan_and_future_fence_rejected_without_ack(self):
        self.marker()
        plan = history.review(self.root)
        self.marker(status="submitted")
        self.code("MAIL_PLAN_CHANGED", history.acknowledge, self.core, plan["plan_id"], utcnow().isoformat())
        self.code("INVALID_INPUT", history.acknowledge, self.core, history.review(self.root)["plan_id"], (utcnow() + timedelta(days=1)).isoformat())
        self.assertFalse((self.root / "agent-mail.sqlite3").exists())


class MCPCutoverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store(self.root, Fernet.generate_key())
        self.server = self.store.put("mcp", {"name": "Synthetic mail", "transport": "stdio", "command": "never-executed",
            "allowed_tools": ["send_email"], "effects": {"send_email": "email"}, "env": {"TOKEN": "private-mcp-secret"}})
        self.settings = self.store.settings()
        self.settings["mail"].update(transport="mcp", sender="sender@example.com", recipient_allowlist=["recipient@example.com"],
            allow_synthetic=True, mcp_server_id=self.server["id"], mcp_tool="send_email")
        self.store.save_settings(self.settings)
        self.analysis = AnalysisAgent().analyze(MockPredictionAdapter().fetch())
        self.selected = bindings.mcp_profile(self.store, self.settings["mail"])
        self.core = MailCore(self.root, self.settings["mail"])

    def queue(self):
        return self.core.enqueue(self.analysis, "recipient@example.com", mcp_profile=self.selected)["id"]

    async def test_new_mcp_uses_core_canonical_id_frozen_request_and_no_old_marker(self):
        mid = self.queue()
        expected = identity([self.analysis["analysis_id"], "recipient@example.com", "sender@example.com", "mcp"])
        self.assertEqual(mid, expected)
        call = AsyncMock(return_value={"status": "simulated"})
        transport = MCPTransport(call, self.server["id"], "send_email")
        result = await self.core.deliver_mcp(mid, self.selected, transport, lambda: None)
        self.assertEqual(result["status"], "simulated")
        self.assertEqual(call.await_args.args[2], self.core.binding(mid)["request"])
        self.assertEqual(call.await_args.args[2]["idempotency_key"], mid)
        await self.core.deliver_mcp(mid, self.selected, transport, lambda: None)
        self.assertEqual(call.await_count, 1)
        self.assertEqual(history.markers(self.root), [])
        self.assertNotIn(b"private-mcp-secret", (self.root / "agent-mail.sqlite3").read_bytes())
        self.assertEqual(self.core.drain()["due"], 0)

    async def test_cancellation_recovers_uncertain_and_never_resends(self):
        mid = self.queue()
        call = AsyncMock(side_effect=asyncio.CancelledError)
        transport = MCPTransport(call, self.server["id"], "send_email")
        with self.assertRaises(asyncio.CancelledError):
            await self.core.deliver_mcp(mid, self.selected, transport, lambda: None)
        self.assertEqual((self.core.get(mid)["status"], self.core.get(mid)["attempts"]), ("uncertain", 1))
        await self.core.deliver_mcp(mid, self.selected, transport, lambda: None)
        self.assertEqual(call.await_count, 1)

    async def test_revoked_authorization_stops_before_claim(self):
        mid = self.queue()
        call = AsyncMock()
        def denied():
            raise ServiceError("PERMISSION_DENIED", "revoked")
        with self.assertRaises(ServiceError):
            await self.core.deliver_mcp(mid, self.selected, MCPTransport(call, "s", "t"), denied)
        self.assertEqual(self.core.get(mid)["attempts"], 0)
        call.assert_not_called()

    async def test_unknown_transport_error_preserves_uncertain_and_redacts_details(self):
        mid = self.queue()
        call = AsyncMock(side_effect=TimeoutError("private-provider-response"))
        with self.assertRaises(ServiceError) as caught:
            await self.core.deliver_mcp(mid, self.selected, MCPTransport(call, "s", "t"), lambda: None)
        self.assertEqual(caught.exception.code, "MAIL_UNCERTAIN")
        self.assertEqual(self.core.get(mid)["status"], "uncertain")
        self.assertNotIn(b"private-provider-response", (self.root / "agent-mail.sqlite3").read_bytes())

    async def test_discovery_checks_synthetic_permission_again_before_call(self):
        engine = Orchestrator(self.store)
        layer = engine.mcp
        client = SimpleNamespace(call_tool=AsyncMock(), list_tools=AsyncMock())
        @asynccontextmanager
        async def session(*args):
            yield client, None, self.server
        async def pages(*args):
            current = self.store.settings()
            current["mail"]["allow_synthetic"] = False
            self.store.save_settings(current)
            return [{"name": "send_email", "inputSchema": {"type": "object"}}]
        progress = SimpleNamespace(tool_attempt=lambda: None, emit=lambda *a, **k: None)
        with patch.object(layer, "session", session), patch.object(layer, "pages", pages):
            result = await engine.notify(self.analysis, "recipient@example.com", Budget(self.settings["limits"]), progress)
        self.assertEqual((result["status"], result["attempts"]), ("uncertain", 1))
        self.assertEqual(result["id"], self.core.listing()[0]["id"])
        client.call_tool.assert_not_called()
        self.assertEqual(self.core.listing()[0]["status"], "uncertain")

    async def test_changed_route_requires_review_without_changing_id_or_attempts(self):
        mid = self.queue()
        self.store.put("mcp", {**self.server, "command": "another-never-executed"}, self.server["id"])
        changed = bindings.mcp_profile(self.store, self.settings["mail"])
        with self.assertRaises(ServiceError) as caught:
            self.core.enqueue(self.analysis, "recipient@example.com", mcp_profile=changed)
        self.assertEqual(caught.exception.code, "MAIL_ENDPOINT_CHANGED")
        plan = self.core.binding_plan(mid)
        self.assertEqual(plan["new_profile"], changed)
        self.core.bind(mid, plan["plan_id"])
        self.assertEqual(self.core.enqueue(self.analysis, "recipient@example.com", mcp_profile=changed)["id"], mid)
        self.assertEqual(self.core.get(mid)["attempts"], 0)

    async def test_frozen_request_tamper_stops_without_external_call(self):
        mid = self.queue()
        with self.core.db() as con:
            con.execute("UPDATE mail_binding SET request='{}' WHERE message_id=?", (mid,))
        call = AsyncMock()
        with self.assertRaises(ServiceError):
            await self.core.deliver_mcp(mid, self.selected, MCPTransport(call, "s", "t"), lambda: None)
        call.assert_not_called()

    async def test_concurrent_delivery_claim_only_calls_transport_once(self):
        mid = self.queue()
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_call(*args, **kwargs):
            started.set()
            await release.wait()
            return {"status": "simulated"}
        call = AsyncMock(side_effect=slow_call)
        transport = MCPTransport(call, self.server["id"], "send_email")
        task = asyncio.create_task(self.core.deliver_mcp(mid, self.selected, transport, lambda: None))
        await asyncio.wait_for(started.wait(), 3)
        try:
            with self.assertRaises(RuntimeError):
                await self.core.deliver_mcp(mid, self.selected, transport, lambda: None)
        finally:
            release.set()
            await task
        self.assertEqual(call.await_count, 1)

    async def test_session_endpoint_guard_precedes_transport_start(self):
        self.store.put("mcp", {**self.server, "command": "changed"}, self.server["id"])
        with patch("stock_predict_mailer.control.mcp_layer.stdio_client") as client:
            with self.assertRaises(ServiceError) as caught:
                async with MCPLayer(self.store).session(self.server["id"], self.selected["endpoint"]):
                    self.fail("should not open session")
            self.assertEqual(caught.exception.code, "MAIL_ENDPOINT_CHANGED")
            client.assert_not_called()

    async def test_discovery_rechecks_revocation_before_email_effect(self):
        layer = MCPLayer(self.store)
        client = SimpleNamespace(call_tool=AsyncMock(), list_tools=AsyncMock())
        @asynccontextmanager
        async def session(*args):
            yield client, None, self.server
        async def pages(*args):
            current = self.store.settings()
            current["mail"]["recipient_allowlist"] = []
            self.store.save_settings(current)
            return [{"name": "send_email", "inputSchema": {"type": "object"}}]
        with patch.object(layer, "session", session), patch.object(layer, "pages", pages):
            with self.assertRaises(ServiceError):
                await layer.call(self.server["id"], "send_email", {"recipient": "recipient@example.com"}, effect="email", expected_endpoint=self.selected["endpoint"])
        client.call_tool.assert_not_called()

    async def test_orchestrator_exact_old_marker_suppresses_resend_readonly(self):
        key = identity([self.analysis["analysis_id"], "recipient@example.com", "sender@example.com", self.server["id"], "send_email"])
        with self.store.db() as con:
            con.execute("CREATE TABLE mcp_mail(id TEXT PRIMARY KEY,status TEXT)")
            con.execute("INSERT INTO mcp_mail VALUES (?, 'sending')", (key,))
        engine = Orchestrator(self.store)
        before = (self.root / "control.sqlite3").read_bytes()
        engine.mcp.call = AsyncMock(side_effect=AssertionError("must not resend"))
        progress = SimpleNamespace(tool_attempt=lambda: None, emit=lambda *a, **k: None)
        result = await engine.notify(self.analysis, "recipient@example.com", Budget(self.settings["limits"]), progress)
        self.assertEqual((result["id"], result["status"]), (key, "uncertain"))
        self.assertEqual((self.root / "control.sqlite3").read_bytes(), before)
        self.assertFalse((self.root / "agent-mail.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
