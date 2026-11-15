"""Synthetic history and transport fixtures; migration never sends mail."""
import asyncio
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from datetime import timedelta
from email import policy
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from stock_predict_mailer.agent_service.adapters import MockPredictionAdapter
from stock_predict_mailer.agent_service.analysis import AnalysisAgent
from stock_predict_mailer.agent_service.contracts import ServiceError, instant, utcnow
from stock_predict_mailer.agent_service.mail import MailService
from stock_predict_mailer.cli import main
from stock_predict_mailer.core import digest
from stock_predict_mailer.delivery import outbox_schema
from stock_predict_mailer.mail_core import MailCore, migration
from stock_predict_mailer.mail_core.transports import MCPTransport


@contextmanager
def database(path):
    con = sqlite3.connect(path)
    try:
        with con:
            yield con
    finally:
        con.close()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.target = self.root / "target"

    def legacy(self, principal="owner", status="pending", tag="first"):
        report_id = digest((principal + tag).encode())
        recipient, sender = principal + "@example.invalid", "research@example.invalid"
        source_id = digest(f"{report_id}\n{recipient}\n{sender}".encode())
        message_id = f"<{source_id}@original.example>"
        message = EmailMessage(policy=policy.SMTP)
        message["From"], message["To"], message["Message-ID"] = sender, recipient, message_id
        message["Subject"] = "SYNTHETIC MIGRATION FIXTURE"
        message.set_content("Synthetic original bytes. Never send this archive.")
        payload = message.as_bytes()
        folder = self.source / "outbox"
        folder.mkdir(exist_ok=True)
        (folder / (source_id + ".eml")).write_bytes(payload)
        with database(self.source / "state.sqlite3") as con:
            outbox_schema(con)
            stamp = "2020-01-01T00:00:00+00:00"
            con.execute("INSERT INTO outbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                source_id, report_id, principal, recipient, sender, status, 1, stamp, stamp, message_id, digest(payload), None))
        return source_id, payload

    def marker(self, source_id=None, status="sending", development=False):
        source_id = source_id or digest(b"synthetic mcp history")
        filename = "control-development.sqlite3" if development else "control.sqlite3"
        with database(self.source / filename) as con:
            con.execute("CREATE TABLE IF NOT EXISTS mcp_mail (id TEXT PRIMARY KEY,status TEXT)")
            con.execute("INSERT INTO mcp_mail VALUES (?,?)", (source_id, status))
            con.execute("CREATE TABLE IF NOT EXISTS profiles (secrets BLOB)")
            con.execute("INSERT INTO profiles VALUES (?)", (b"private-ciphertext-must-not-be-exported",))
        return source_id

    def agent(self, expired=False):
        predicted = MockPredictionAdapter().fetch()
        if expired:
            predicted["generated_at"] = "2020-01-01T00:00:00+00:00"
            predicted["valid_until"] = "2020-01-02T00:00:00+00:00"
        clock = instant(predicted["generated_at"]) + timedelta(minutes=1) if expired else utcnow()
        with patch("stock_predict_mailer.agent_service.contracts.utcnow", return_value=clock):
            analysis = AnalysisAgent().analyze(predicted)
            mail = MailService(self.source, {"transport": "file", "sender": "research@example.invalid"})
            source_id = mail.enqueue(analysis, "preview@example.invalid")["id"]
        return source_id

    def files(self):
        return {path.relative_to(self.source).as_posix(): path.read_bytes() for path in self.source.rglob("*") if path.is_file()}

    def plan(self, **kwargs):
        return migration.plan_migration(self.source, **kwargs)

    def apply(self, plan=None, **kwargs):
        plan = plan or self.plan()
        return migration.import_archive(self.source, self.target, plan["plan_id"], **kwargs)

    def test_empty_preview_and_archive_listing_create_nothing(self):
        before = self.files()
        self.assertTrue(self.plan()["ready"])
        self.assertEqual(migration.list_archive(self.target), [])
        self.assertEqual(self.files(), before)
        self.assertFalse(self.target.exists())

    def test_preview_is_deterministic_readonly_and_does_not_open_vault(self):
        self.agent()
        self.legacy()
        self.marker()
        before = self.files()
        with patch.object(MailCore, "__init__", side_effect=AssertionError("preview must not construct core")):
            first, second = self.plan(), self.plan()
        self.assertEqual(first["plan_id"], second["plan_id"])
        self.assertEqual(self.files(), before)
        self.assertFalse(self.target.exists())
        self.assertNotIn("private-ciphertext", json.dumps(first))
        self.assertFalse((self.source / "control-development.key").exists())

    def test_principal_scope_does_not_include_other_legacy_recipients(self):
        selected, _ = self.legacy("alice")
        self.legacy("bob")
        plan = self.plan(principal="alice")
        self.assertEqual([entry["source_id"] for entry in plan["entries"]], [selected])
        self.assertNotIn("bob@example.invalid", json.dumps(plan))
        self.apply(plan, principal="alice")
        self.assertEqual(len(migration.list_archive(self.target, "alice")), 1)
        self.assertEqual(migration.list_archive(self.target, "bob"), [])

    def test_sending_maps_to_uncertain_without_changing_source(self):
        self.legacy(status="sending")
        self.marker()
        before = self.files()
        plan = self.plan()
        self.assertTrue(all(entry["planned_status"] == "uncertain" for entry in plan["entries"]))
        self.apply(plan)
        self.assertEqual(self.files(), before)
        self.assertTrue(all(row["status"] == "uncertain" for row in migration.list_archive(self.target)))

    def test_receipts_preserve_missing_fields_without_fabrication(self):
        self.marker(status="submitted")
        plan = self.plan()
        entry = plan["entries"][0]
        self.assertIsNone(entry["recipient"])
        self.assertIsNone(entry["analysis_id"])
        self.assertIn("payload", entry["missing_fields"])
        self.apply(plan)
        with database(self.target / "agent-mail.sqlite3") as con:
            row = con.execute("SELECT kind,recipient,sender,analysis_id,payload,status FROM mail_archive").fetchone()
        self.assertEqual(row, ("receipt", None, None, None, None, "submitted"))

    def test_original_eml_and_message_id_survive_exactly(self):
        source_id, payload = self.legacy()
        self.apply()
        with database(self.target / "agent-mail.sqlite3") as con:
            row = con.execute("SELECT source_id,payload,message_id,analysis_id,delivery_disabled FROM mail_archive").fetchone()
        self.assertEqual(row, (source_id, payload, f"<{source_id}@original.example>", None, 1))

    def test_idempotent_reimport_uses_same_mapping(self):
        self.legacy()
        self.marker()
        plan = self.plan()
        first, second = self.apply(plan), self.apply(plan)
        self.assertEqual(first["imported"], 2)
        self.assertEqual(second["imported"], 0)
        self.assertEqual(second["existing"], 2)
        self.assertEqual(len(migration.list_archive(self.target)), 2)

    def test_same_source_id_in_different_namespaces_is_not_merged(self):
        source_id, _ = self.legacy()
        self.marker(source_id)
        self.marker(source_id, development=True)
        result = self.apply()
        self.assertEqual(result["imported"], 3)
        self.assertEqual(len({row["id"] for row in migration.list_archive(self.target)}), 3)

    def test_missing_or_tampered_payload_blocks_import(self):
        source_id, _ = self.legacy()
        path = self.source / "outbox" / (source_id + ".eml")
        path.write_bytes(b"tampered")
        plan = self.plan()
        self.assertFalse(plan["ready"])
        self.assertIn("PAYLOAD_HASH_MISMATCH", plan["entries"][0]["blockers"])
        with self.assertRaises(ServiceError):
            self.apply(plan)
        self.assertFalse(self.target.exists())
        path.unlink()
        self.assertIn("PAYLOAD_MISSING", self.plan()["entries"][0]["blockers"])

    def test_unknown_status_and_invalid_id_are_blocked(self):
        self.marker(status="delivered-for-sure")
        self.assertFalse(self.plan()["ready"])
        with database(self.source / "control.sqlite3") as con:
            con.execute("UPDATE mcp_mail SET id='../escape',status='pending'")
        self.assertIn("INVALID_SOURCE_ID", self.plan()["entries"][0]["blockers"])

    def test_changed_source_plan_is_rejected_before_target_creation(self):
        self.legacy()
        plan = self.plan()
        with database(self.source / "state.sqlite3") as con:
            con.execute("UPDATE outbox SET status='retry'")
        with self.assertRaises(ServiceError) as caught:
            self.apply(plan)
        self.assertEqual(caught.exception.code, "MIGRATION_PLAN_CHANGED")
        self.assertFalse(self.target.exists())

    def test_changed_already_imported_source_is_not_overwritten(self):
        self.legacy()
        self.apply()
        with database(self.source / "state.sqlite3") as con:
            con.execute("UPDATE outbox SET status='retry'")
        with self.assertRaises(ServiceError) as caught:
            self.apply()
        self.assertEqual(caught.exception.code, "MIGRATION_CONFLICT")
        self.assertEqual(migration.list_archive(self.target)[0]["status"], "pending")

    def test_import_transaction_rolls_back_records_and_ledger(self):
        self.legacy()
        self.marker()
        insert = migration._insert_archive
        count = 0
        def interrupted(*args):
            nonlocal count
            count += 1
            if count == 2:
                raise KeyboardInterrupt()
            return insert(*args)
        with patch.object(migration, "_insert_archive", side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            self.apply()
        with database(self.target / "agent-mail.sqlite3") as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM mail_archive").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM mail_migration_ledger").fetchone()[0], 0)

    def test_paired_target_payload_and_hash_tampering_is_detected(self):
        self.legacy()
        self.apply()
        with database(self.target / "agent-mail.sqlite3") as con:
            con.execute("UPDATE mail_archive SET payload=?,payload_hash=?", (b"forged", digest(b"forged")))
        with self.assertRaises(ServiceError) as caught:
            self.apply()
        self.assertEqual(caught.exception.code, "MIGRATION_CONFLICT")

    def test_target_status_tampering_is_detected(self):
        self.legacy(status="sending")
        self.apply()
        with database(self.target / "agent-mail.sqlite3") as con:
            con.execute("UPDATE mail_archive SET status='submitted'")
        with self.assertRaises(ServiceError):
            self.apply()

    def test_archives_do_not_enter_delivery_queue_or_contact_smtp(self):
        self.legacy()
        self.agent()
        self.marker()
        with patch("smtplib.SMTP", side_effect=AssertionError("must not send")):
            self.apply()
            core = MailCore(self.target, {"transport": "smtp"})
            self.assertEqual(core.listing(), [])
            self.assertEqual(core.drain(), {"due": 0, "results": []})

    def test_expired_analysis_can_be_archived_without_new_inference(self):
        self.agent(expired=True)
        plan = self.plan()
        self.assertTrue(plan["ready"])
        self.assertEqual(self.apply(plan)["imported"], 1)

    def test_bad_analysis_binding_is_blocked(self):
        self.agent()
        with database(self.source / "agent-mail.sqlite3") as con:
            con.execute("UPDATE mail SET analysis='{}'")
        self.assertIn("INVALID_ANALYSIS_BINDING", self.plan()["entries"][0]["blockers"])

    def test_source_and_target_must_be_separate(self):
        self.legacy()
        before = self.files()
        with self.assertRaises(ServiceError) as caught:
            migration.import_archive(self.source, self.source, self.plan()["plan_id"])
        self.assertEqual(caught.exception.code, "MIGRATION_TARGET")
        self.assertEqual(self.files(), before)

    def test_corrupt_schema_and_batch_limit_fail_safely(self):
        self.legacy()
        self.marker()
        with self.assertRaises(ServiceError):
            self.plan(limit=1)
        with database(self.source / "control.sqlite3") as con:
            con.execute("DROP TABLE mcp_mail")
            con.execute("CREATE TABLE mcp_mail (id TEXT)")
        with self.assertRaises(ServiceError) as caught:
            self.plan()
        self.assertEqual(caught.exception.code, "MIGRATION_SCHEMA")
        self.assertFalse(self.target.exists())

    def test_oversized_payload_and_aggregate_limits_do_not_create_target(self):
        _, payload = self.legacy()
        with patch.object(migration, "MAX_EML", 1):
            self.assertFalse(self.plan()["ready"])
        with patch.object(migration, "MAX_BATCH_BYTES", len(payload) - 1), self.assertRaises(ServiceError):
            self.plan()
        with patch.object(migration, "MAX_METADATA_BYTES", 1), self.assertRaises(ServiceError):
            self.plan()
        self.assertFalse(self.target.exists())

    def test_cli_dry_run_apply_and_readonly_listing(self):
        self.legacy()
        cfg = self.root / "config.toml"
        cfg.write_text('workspace="source"\n', encoding="utf-8")
        base = ["--config", str(cfg)]
        before = self.files()
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(base + ["mail-migrate"]), 0)
        plan = json.loads(output.getvalue())["plan"]
        self.assertEqual(self.files(), before)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(base + ["mail-migrate", "--apply"]), 2)
        self.assertFalse(self.target.exists())
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(base + ["mail-migrate", "--apply", "--target-workspace", str(self.target), "--expected-plan", plan["plan_id"]]), 0)
        self.assertEqual(json.loads(output.getvalue())["result"]["imported"], 1)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(base + ["mail-archive", "--target-workspace", str(self.target)]), 0)
        self.assertEqual(len(json.loads(output.getvalue())), 1)


class CoreCompatibilityTests(unittest.TestCase):
    def test_legacy_class_is_compatible_core_facade(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = MailService(Path(temporary), {"transport": "file", "sender": "research@example.invalid"})
            self.assertIsInstance(service, MailCore)
            analysis = AnalysisAgent().analyze(MockPredictionAdapter().fetch())
            message = service.enqueue(analysis, "preview@example.invalid")
            self.assertEqual(service.deliver(message["id"])["status"], "simulated")
            self.assertEqual(MailCore(Path(temporary), {}).get(message["id"])["status"], "simulated")

    def test_unknown_transport_cannot_fall_through_to_smtp(self):
        with tempfile.TemporaryDirectory() as temporary:
            core = MailCore(Path(temporary), {"transport": "unknown", "sender": "research@example.invalid"})
            analysis = AnalysisAgent().analyze(MockPredictionAdapter().fetch())
            with self.assertRaises(ServiceError):
                core.enqueue(analysis, "preview@example.invalid")
            self.assertEqual(core.listing(), [])


class MCPTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_declared_acceptance_is_submitted(self):
        for reply, expected in (({"status": "submitted"}, "submitted"), ({"status": "sent"}, "submitted"),
                                ({"status": "simulated"}, "simulated"), ({"status": "unknown"}, "uncertain"), (None, "uncertain")):
            async def call(*args, value=reply, **kwargs):
                self.assertEqual(kwargs["effect"], "email")
                return value
            self.assertEqual((await MCPTransport(call, "server", "send").send({})).status, expected)

    async def test_cancellation_and_permission_errors_reach_marker_owner(self):
        for error in (asyncio.CancelledError(), ServiceError("PERMISSION_DENIED", "revoked")):
            async def call(*args, failure=error, **kwargs):
                raise failure
            with self.assertRaises(type(error)):
                await MCPTransport(call, "server", "send").send({})
