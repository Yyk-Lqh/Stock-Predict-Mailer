"""Encrypted backup/restore uses only synthetic temporary data and keys."""
import io
import json
import os
import socket
import sqlite3
import stat
import tempfile
import unittest
import zipfile
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from mcp_server.jobs import JobStore
from stock_predict_mailer.agent_service.adapters import MockPredictionAdapter
from stock_predict_mailer.agent_service.analysis import AnalysisAgent
from stock_predict_mailer.agent_service.config import load
from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.cli import main
from stock_predict_mailer.control.memory import Memory
from stock_predict_mailer.control.store import Store
from stock_predict_mailer.core import Config, connect
from stock_predict_mailer.delivery import outbox_schema, process_lock
from stock_predict_mailer.mail_core import MailCore
from stock_predict_mailer.operations import backup
from stock_predict_mailer.operations import backup_inventory as inv
from stock_predict_mailer.operations.components import Component
from stock_predict_mailer.private_knowledge.service import Knowledge


@contextmanager
def database(path):
    con = sqlite3.connect(path)
    try:
        with con:
            yield con
    finally:
        con.close()


class BackupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.app, self.crawler = self.base / "app", self.base / "crawler"
        self.app.mkdir()
        self.crawler.mkdir()
        self.config = self.base / "agent.toml"
        self.config.write_text('workspace="app"\n[mail]\ntransport="file"\nsender="preview@example.invalid"\n', encoding="utf-8")
        self.cfg = load(self.config)
        self.archive, self.target = self.base / "snapshot.spmbak", self.base / "restored"
        self.key = Fernet.generate_key()
        environment = patch.dict(os.environ, {"TEST_BACKUP_KEY": self.key.decode(), "STOCK_PREDICT_MAILER_MASTER_KEY": "", "SPM_MASTER_KEY": ""})
        environment.start()
        self.addCleanup(environment.stop)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]

    def plan(self):
        return backup.plan(self.cfg, self.config, crawler_workspace=self.crawler, port=self.port)

    def create(self, plan=None):
        plan = plan or self.plan()
        self.assertTrue(plan["ready"], plan["blockers"])
        return backup.create(self.cfg, self.config, self.archive, plan["plan_id"], crawler_workspace=self.crawler, port=self.port, key_env="TEST_BACKUP_KEY")

    def restore(self, archive=None):
        return backup.restore(archive or self.archive, self.target, key_env="TEST_BACKUP_KEY")

    def code(self, expected, function, *args, **kwargs):
        with self.assertRaises(ServiceError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected)

    def files(self):
        return {str(path): path.read_bytes() for root in (self.app, self.crawler) for path in root.rglob("*") if path.is_file()}

    def populate(self):
        self.store = Store(self.app)
        self.store.put("models", {"name": "Synthetic backup profile", "api_key": "PRIVATE-PROVIDER-SECRET"})
        memory = Memory(self.store)
        self.owner = memory.create_owner()["owner"]
        self.kb = Knowledge(self.store)
        self.doc = self.kb.upload(self.owner, "private-document.txt", b"CONFIDENTIAL-SYNTHETIC-DOCUMENT", {"document_date": "2026-10-01", "available_date": "2026-10-01"})["id"]
        with self.store.db() as con:
            body = {"kind": "task", "id": "analysis-task", "status": {"state": "working"}, "metadata": {}, "artifacts": []}
            con.execute("INSERT INTO tasks VALUES (?,?)", ("analysis-task", json.dumps(body)))
            con.execute("CREATE TABLE mcp_mail(id TEXT PRIMARY KEY,status TEXT)")
            con.execute("INSERT INTO mcp_mail VALUES ('receipt','sending')")
        self.mail = MailCore(self.app, {"transport": "file", "sender": "research@example.invalid"})
        analysis = AnalysisAgent().analyze(MockPredictionAdapter().fetch())
        self.mid = self.mail.enqueue(analysis, "preview@example.invalid")["id"]
        self.done = self.mail.enqueue(analysis, "done@example.invalid")["id"]
        self.mail.update(self.done, "submitted", 1)
        self.jobs = JobStore(self.crawler)
        self.job = self.jobs.submit("catalog")["id"]
        with self.jobs.db(True) as con:
            con.execute("UPDATE jobs SET state='running',attempts=2,owner='synthetic-owner',checkpoint=? WHERE id=?", ('{"completed_codes":["600000.SH"]}', self.job))
        with connect(Config(self.app)) as con:
            outbox_schema(con)
            con.execute("INSERT INTO outbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("a" * 64, "b" * 64, "owner", "preview@example.invalid", "sender@example.invalid",
                "retry", 2, "2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z", "<original@example.invalid>", "hash", None))

    def rewrite(self, change):
        plain = Fernet(self.key).decrypt(self.archive.read_bytes())
        with zipfile.ZipFile(io.BytesIO(plain)) as source:
            data = {name: source.read(name) for name in source.namelist()}
        manifest = json.loads(data["manifest.json"])
        change(manifest, data)
        data["manifest.json"] = json.dumps(manifest).encode()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as output:
            for name, raw in data.items():
                output.writestr(name, raw)
        bad = self.base / "modified.spmbak"
        bad.write_bytes(Fernet(self.key).encrypt(buffer.getvalue()))
        return bad

    def test_plan_is_deterministic_readonly_and_never_constructs_services(self):
        self.populate()
        before = self.files()
        with patch.object(Store, "__init__", side_effect=AssertionError("no init")), patch.object(Knowledge, "__init__", side_effect=AssertionError("no init")), patch.object(MailCore, "__init__", side_effect=AssertionError("no mail")):
            first, second = self.plan(), self.plan()
        self.assertTrue(first["ready"], first["blockers"])
        self.assertEqual(first["plan_id"], second["plan_id"])
        self.assertEqual(self.files(), before)
        self.assertNotIn("PRIVATE-PROVIDER-SECRET", json.dumps(first))
        self.assertFalse(self.archive.exists())

    def test_encrypted_roundtrip_preserves_bytes_keys_and_pauses_all_queues(self):
        self.populate()
        self.kb.heartbeat("synthetic-host", 4242, state="busy", current=self.doc, processed=3)
        before = inv.inventory(self.app, self.crawler, self.config, self.port)["plan_id"]
        made = self.create()
        self.assertTrue(made["encrypted"])
        self.assertNotIn(b"PRIVATE-PROVIDER-SECRET", self.archive.read_bytes())
        self.assertNotIn(b"CONFIDENTIAL-SYNTHETIC-DOCUMENT", self.archive.read_bytes())
        verified = backup.verify(self.archive, key_env="TEST_BACKUP_KEY")
        self.assertEqual(verified["archive_sha256"], made["archive_sha256"])
        result = self.restore()
        self.assertEqual(result["services_started"], 0)
        self.assertEqual(self.mail.get(self.mid)["status"], "pending")
        self.assertEqual(inv.inventory(self.app, self.crawler, self.config, self.port)["plan_id"], before)
        with database(self.target / "app" / "agent-mail.sqlite3") as con:
            self.assertEqual(con.execute("SELECT status,attempts FROM mail WHERE id=?", (self.mid,)).fetchone(), ("uncertain", 0))
            self.assertEqual(con.execute("SELECT status FROM mail WHERE id=?", (self.done,)).fetchone()[0], "submitted")
            self.assertEqual(con.execute("SELECT action FROM mail_audit WHERE message_id=?", (self.mid,)).fetchone()[0], "restored_quarantine")
        with database(self.target / "crawler" / "jobs" / "crawler-jobs.sqlite3") as con:
            self.assertEqual(con.execute("SELECT state,attempts,owner,checkpoint FROM jobs").fetchone(), ("interrupted", 2, None, '{"completed_codes":["600000.SH"]}'))
        with database(self.target / "app" / "private-knowledge" / "knowledge.sqlite3") as con:
            self.assertEqual(con.execute("SELECT status,error FROM documents").fetchone(), ("failed", "RESTORED_REVIEW_REQUIRED"))
            self.assertEqual(con.execute("SELECT state,current,processed FROM workers").fetchone(), ("stopped", None, 3))
        self.assertEqual(result["quarantined"]["knowledge_workers"], 1)
        self.assertEqual(self.kb.worker_status()["state"], "busy")
        with database(self.target / "app" / "control-development.sqlite3") as con:
            body = json.loads(con.execute("SELECT body FROM tasks").fetchone()[0])
            self.assertEqual(body["status"]["state"], "failed")
            self.assertEqual(con.execute("SELECT status FROM mcp_mail").fetchone()[0], "uncertain")
        with database(self.target / "app" / "state.sqlite3") as con:
            self.assertEqual(con.execute("SELECT status,attempts FROM outbox").fetchone(), ("uncertain", 2))
        payload = self.target / "app" / "private-knowledge" / self.owner / (self.doc + ".bin")
        key = (self.target / "app" / "control-development.key").read_bytes()
        self.assertEqual(Fernet(key).decrypt(payload.read_bytes()), b"CONFIDENTIAL-SYNTHETIC-DOCUMENT")
        self.assertFalse((self.target / "app" / ".runtime").exists())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.target.stat().st_mode) & 0o077, 0)
        self.assertEqual(load(self.target / "restored-agent.toml")["workspace"], self.target / "app")
        self.assertEqual(load(self.target / "restored-agent.toml")["mail"]["transport"], "file")
        receipt = json.loads((self.target / "restore-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["archive_sha256"], made["archive_sha256"])
        self.assertEqual(receipt["vaults"], {"development": "paired_file"})

    def test_live_wal_commits_are_merged_without_source_coordination_changes(self):
        self.mail = MailCore(self.app, {"transport": "file", "sender": "research@example.invalid"})
        self.mail.enqueue(AnalysisAgent().analyze(MockPredictionAdapter().fetch()), "preview@example.invalid")
        with self.mail.db() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE committed_marker(value TEXT)")
            con.execute("INSERT INTO committed_marker VALUES ('WAL-ONLY-COMMIT')")
            con.commit()
            before = self.files()
            planned = self.plan()
            self.assertTrue(planned["ready"], planned["blockers"])
            self.assertEqual(self.files(), before)
            self.create(planned)
            self.assertEqual((self.app / "agent-mail.sqlite3-wal").read_bytes(), before[str(self.app / "agent-mail.sqlite3-wal")])
            self.restore()
        with database(self.target / "app" / "agent-mail.sqlite3") as con:
            self.assertEqual(con.execute("SELECT value FROM committed_marker").fetchone()[0], "WAL-ONLY-COMMIT")
        self.assertEqual((self.target / "app" / "agent-mail.sqlite3").read_bytes()[18:20], b"\x01\x01")
        self.assertFalse(list(self.target.rglob("*-wal")))

    def test_source_runtime_logs_locks_and_external_inputs_are_excluded(self):
        (self.app / ".runtime").mkdir()
        (self.app / ".runtime" / "notes.txt").write_text("ephemeral", encoding="utf-8")
        (self.app / "logs").mkdir()
        (self.app / "logs" / "sensitive.log").write_text("not archived", encoding="utf-8")
        (self.app / "pipeline.lock").write_bytes(b"0")
        (self.app / "input.txt").write_text("included", encoding="utf-8")
        (self.base / "external-model.bin").write_bytes(b"external")
        entries = self.plan()["files"]
        self.assertEqual({item["path"] for item in entries}, {"app/input.txt", "reference/original-agent.toml"})

    def test_source_nested_scopes_and_nonexistent_application_are_refused(self):
        self.code("BACKUP_SCOPE", inv.inventory, self.app, self.app / "crawler", self.config, self.port)
        self.code("BACKUP_SOURCE", inv.inventory, self.base / "missing", self.crawler, self.config, self.port)

    def test_optional_missing_crawler_can_be_backed_up_without_initializing_it(self):
        self.crawler.rmdir()
        self.assertTrue(self.plan()["ready"])
        self.create()
        self.assertFalse(self.crawler.exists())
        self.restore()
        self.assertTrue((self.target / "crawler").is_dir())

    def test_active_component_and_business_lock_block_capture(self):
        with Component(self.app, "console") as component:
            component.phase("running")
            self.assertIn("BACKUP_COMPONENT_ACTIVE", {item["code"] for item in self.plan()["blockers"]})
        with process_lock(Config(self.app)):
            self.assertIn("BACKUP_WRITER_BUSY", {item["code"] for item in self.plan()["blockers"]})
        self.assertFalse(self.archive.exists())

    def test_occupied_port_is_not_stopped_or_adopted(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", self.port))
            sock.listen()
            planned = self.plan()
            self.assertFalse(planned["ready"])
            self.assertIn("BACKUP_PORT_UNAVAILABLE", {b["code"] for b in planned["blockers"]})
            self.code("BACKUP_BLOCKED", backup.create, self.cfg, self.config, self.archive, planned["plan_id"], crawler_workspace=self.crawler, port=self.port, key_env="TEST_BACKUP_KEY")

    def test_source_change_since_review_is_rejected(self):
        planned = self.plan()
        (self.app / "new.txt").write_text("changed", encoding="utf-8")
        self.code("BACKUP_PLAN_CHANGED", backup.create, self.cfg, self.config, self.archive, planned["plan_id"], crawler_workspace=self.crawler, port=self.port, key_env="TEST_BACKUP_KEY")
        self.assertFalse(self.archive.exists())

    def test_change_during_capture_leaves_no_complete_output(self):
        (self.app / "value.txt").write_text("before", encoding="utf-8")
        planned = self.plan()
        original, calls = inv.copy_sources, []
        def copy(*args):
            original(*args)
            calls.append(True)
            if len(calls) == 2:
                (self.app / "value.txt").write_text("concurrent write", encoding="utf-8")
        with patch.object(inv, "copy_sources", side_effect=copy):
            self.code("BACKUP_SOURCE_CHANGED", backup.create, self.cfg, self.config, self.archive, planned["plan_id"], crawler_workspace=self.crawler, port=self.port, key_env="TEST_BACKUP_KEY")
        self.assertFalse(self.archive.exists())
        self.assertFalse(list(self.base.glob(".backup-*")))

    def test_missing_and_wrong_development_key_are_blocking_without_replacement(self):
        Store(self.app)
        key = self.app / "control-development.key"
        key.unlink()
        self.assertIn("BACKUP_VAULT_KEY", {b["code"] for b in self.plan()["blockers"]})
        self.assertFalse(key.exists())
        key.write_bytes(Fernet.generate_key())
        self.assertIn("BACKUP_VAULT_KEY", {b["code"] for b in self.plan()["blockers"]})

    def test_production_master_key_is_external_and_required_to_restore(self):
        master = Fernet.generate_key()
        Store(self.app, master)
        with patch.dict(os.environ, {"STOCK_PREDICT_MAILER_MASTER_KEY": master.decode()}):
            self.create()
            manifest, payloads, _ = backup._unseal(self.archive, "TEST_BACKUP_KEY")
            self.assertEqual(manifest["vaults"], {"production": "external_master_key_required"})
            self.assertFalse(any(master in raw for raw in payloads.values()))
        self.code("BACKUP_VAULT_KEY", self.restore)
        self.assertFalse(self.target.exists())
        with patch.dict(os.environ, {"STOCK_PREDICT_MAILER_MASTER_KEY": master.decode()}):
            self.restore()
        self.assertFalse((self.target / "app" / "control-development.key").exists())

    def test_wrong_archive_key_and_tampered_ciphertext_are_rejected_before_restore(self):
        self.create()
        with patch.dict(os.environ, {"TEST_BACKUP_KEY": Fernet.generate_key().decode()}):
            self.code("BACKUP_AUTH", self.restore)
        raw = bytearray(self.archive.read_bytes())
        raw[len(raw) // 2] ^= 1
        self.archive.write_bytes(raw)
        self.code("BACKUP_AUTH", self.restore)
        self.assertFalse(self.target.exists())

    def test_missing_backup_key_is_not_generated_or_written(self):
        with patch.dict(os.environ, {"TEST_BACKUP_KEY": ""}):
            self.code("BACKUP_KEY", backup.create, self.cfg, self.config, self.archive, self.plan()["plan_id"], crawler_workspace=self.crawler, port=self.port, key_env="TEST_BACKUP_KEY")
        self.assertFalse(self.archive.exists())

    def test_existing_archive_is_never_overwritten(self):
        self.archive.write_bytes(b"existing user data")
        self.code("BACKUP_EXISTS", backup.create, self.cfg, self.config, self.archive, self.plan()["plan_id"], crawler_workspace=self.crawler, port=self.port, key_env="TEST_BACKUP_KEY")
        self.assertEqual(self.archive.read_bytes(), b"existing user data")

    def test_archive_cannot_be_published_inside_source(self):
        self.code("BACKUP_TARGET", backup.create, self.cfg, self.config, self.app / "inside.spmbak", self.plan()["plan_id"], crawler_workspace=self.crawler, port=self.port, key_env="TEST_BACKUP_KEY")

    def test_archive_publish_race_preserves_other_file_and_cleans_staging(self):
        def collide(source, target):
            Path(target).write_bytes(b"other operation")
            raise FileExistsError()
        with patch("os.link", side_effect=collide):
            self.code("BACKUP_EXISTS", self.create)
        self.assertEqual(self.archive.read_bytes(), b"other operation")
        self.assertFalse(list(self.base.glob(".backup-*")))

    def test_publish_failure_does_not_leave_partial_package(self):
        with patch("os.link", side_effect=OSError("private filesystem details")):
            self.code("BACKUP_PUBLISH", self.create)
        self.assertFalse(self.archive.exists())
        self.assertFalse(list(self.base.glob(".backup-*")))

    def test_restore_existing_empty_or_populated_target_is_refused(self):
        self.create()
        self.target.mkdir()
        self.code("BACKUP_EXISTS", self.restore)
        (self.target / "keep.txt").write_text("keep", encoding="utf-8")
        self.code("BACKUP_EXISTS", self.restore)
        self.assertEqual((self.target / "keep.txt").read_text(), "keep")

    def test_restore_cannot_target_descendant_of_original_source(self):
        self.create()
        self.code("BACKUP_TARGET", backup.restore, self.archive, self.app / "nested", key_env="TEST_BACKUP_KEY")
        self.assertFalse((self.app / "nested").exists())

    def test_restore_publish_race_preserves_existing_target(self):
        self.create()
        original = backup._publish_directory
        def collide(source, target):
            target.mkdir()
            (target / "keep.txt").write_text("other restore", encoding="utf-8")
            original(source, target)
        with patch.object(backup, "_publish_directory", side_effect=collide):
            self.code("BACKUP_PUBLISH", self.restore)
        self.assertEqual((self.target / "keep.txt").read_text(), "other restore")
        self.assertFalse(list(self.base.glob(".restore-*")))

    def test_restore_interruption_never_publishes_a_half_workspace(self):
        self.create()
        with patch.object(backup, "quarantine", side_effect=OSError("simulated interruption")):
            with self.assertRaises(OSError):
                self.restore()
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.base.glob(".restore-*")))
        self.restore()

    def test_plaintext_payload_tamper_fails_authenticated_manifest_check(self):
        (self.app / "value.txt").write_text("original", encoding="utf-8")
        self.create()
        bad = self.rewrite(lambda manifest, data: data.update({"app/value.txt": b"tampered"}))
        self.code("BACKUP_INTEGRITY", self.restore, bad)
        self.assertFalse(self.target.exists())

    def test_untrusted_paths_are_rejected_before_filesystem_extraction(self):
        (self.app / "value.txt").write_text("value", encoding="utf-8")
        self.create()
        for name in ("app/../../escape.txt", "C:/escape.txt", "app/a\\b", "app/CON.txt", "app/a:stream", "app/file. "):
            with self.subTest(name=name):
                def change(manifest, data, name=name):
                    item = next(i for i in manifest["files"] if i["path"] == "app/value.txt")
                    data[name] = data.pop(item["path"])
                    item["path"] = name
                self.code("BACKUP_PATH", self.restore, self.rewrite(change))
                self.assertFalse(self.target.exists())

    def test_case_collision_and_extra_unlisted_file_are_rejected(self):
        (self.app / "value.txt").write_text("value", encoding="utf-8")
        self.create()
        bad = self.rewrite(lambda manifest, data: data.update({"APP/VALUE.TXT": b"other"}))
        self.code("BACKUP_FORMAT", self.restore, bad)
        bad = self.rewrite(lambda manifest, data: data.update({"app/unlisted.txt": b"other"}))
        self.code("BACKUP_FORMAT", self.restore, bad)

    def test_symbolic_link_zip_member_is_never_restored(self):
        (self.app / "value.txt").write_text("value", encoding="utf-8")
        self.create()
        raw = Fernet(self.key).decrypt(self.archive.read_bytes())
        result = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(result, "w") as target:
            for item in source.infolist():
                if item.filename == "app/value.txt":
                    item.external_attr = (stat.S_IFLNK | 0o777) << 16
                target.writestr(item, source.read(item.filename))
        bad = self.base / "symlink.spmbak"
        bad.write_bytes(Fernet(self.key).encrypt(result.getvalue()))
        self.code("BACKUP_FORMAT", self.restore, bad)

    def test_incompatible_version_and_runtime_members_are_blocked(self):
        self.create()
        bad = self.rewrite(lambda manifest, data: manifest.update(app_version="999.0.0"))
        self.code("BACKUP_VERSION", self.restore, bad)
        def runtime(manifest, data):
            item = manifest["files"][0]
            data["app/.RUNTIME/console/state.json"] = data.pop(item["path"])
            item["path"] = "app/.RUNTIME/console/state.json"
        self.code("BACKUP_FORMAT", self.restore, self.rewrite(runtime))

    def test_archive_origin_never_triggers_network_path_resolution(self):
        self.create()
        bad = self.rewrite(lambda manifest, data: manifest["origins"].update(app="//untrusted-server/share"))
        with patch("socket.socket", side_effect=AssertionError("no network from archive")):
            self.code("BACKUP_FORMAT", self.restore, bad)

    def test_inventory_limits_are_explicit_without_truncation(self):
        (self.app / "value.txt").write_bytes(b"large fixture")
        with patch.object(inv, "MAX_FILE", 4):
            self.code("BACKUP_LIMIT", self.plan)
        with patch.object(inv, "MAX_FILES", 1):
            self.code("BACKUP_LIMIT", self.plan)
        with patch.object(inv, "MAX_TOTAL", 10):
            self.code("BACKUP_LIMIT", self.plan)
        self.assertFalse(self.archive.exists())

    def test_orphan_wal_and_rollback_journal_are_not_silently_ignored(self):
        path = self.app / "missing.sqlite3-wal"
        path.write_bytes(b"orphan")
        self.code("BACKUP_WAL", self.plan)
        path.unlink()
        (self.app / "database.sqlite3-journal").write_bytes(b"pending transaction")
        self.code("BACKUP_JOURNAL", self.plan)

    def test_wal_cannot_hide_ordinary_file_with_same_basename(self):
        (self.app / "ordinary").write_bytes(b"file")
        (self.app / "ordinary-wal").write_bytes(b"must not be dropped")
        self.code("BACKUP_WAL", self.plan)

    def test_restored_research_training_queue_is_also_paused(self):
        with connect(Config(self.app)) as con:
            con.execute("CREATE TABLE training_jobs(job_id,status,stage,worker_pid,heartbeat_at,finished_at,cancel_requested,error_category,error_message)")
            con.executemany("INSERT INTO training_jobs VALUES (?,?,?,?,?,?,?,?,?)", [
                ("queued", "queued", "queued", None, None, None, 0, None, None),
                ("running", "training", "training", 123, "2026-01-01", None, 0, None, None),
                ("done", "succeeded", "succeeded", None, None, "2026-01-01", 0, None, None)])
        self.create()
        restored = self.restore()
        self.assertEqual(restored["quarantined"]["training_jobs"], 2)
        with database(self.target / "app" / "state.sqlite3") as con:
            self.assertEqual(con.execute("SELECT status,worker_pid,heartbeat_at FROM training_jobs WHERE job_id='running'").fetchone(), ("interrupted", None, None))
            self.assertEqual(con.execute("SELECT status FROM training_jobs WHERE job_id='done'").fetchone()[0], "succeeded")

    def test_cancelled_and_completed_crawler_history_remains_safe(self):
        jobs = JobStore(self.crawler)
        first, second = jobs.submit("catalog")["id"], jobs.submit("catalog")["id"]
        with jobs.db(True) as con:
            con.execute("UPDATE jobs SET state='cancelling',cancel_requested=1 WHERE id=?", (first,))
            con.execute("UPDATE jobs SET state='completed' WHERE id=?", (second,))
        self.create()
        self.restore()
        with database(self.target / "crawler" / "jobs" / "crawler-jobs.sqlite3") as con:
            self.assertEqual(dict(con.execute("SELECT id,state FROM jobs")), {first: "cancelled", second: "completed"})

    def test_verify_preserves_sources_and_never_constructs_a_runtime_or_service(self):
        self.populate()
        self.create()
        before = self.files()
        with patch.object(Store, "__init__", side_effect=AssertionError("no service")), patch.object(Component, "__enter__", side_effect=AssertionError("no runtime")):
            self.assertTrue(backup.verify(self.archive, key_env="TEST_BACKUP_KEY")["valid"])
            self.restore()
        self.assertEqual(before, self.files())

    def test_bad_source_database_schema_blocks_ready_plan(self):
        with database(self.app / "agent-mail.sqlite3") as con:
            con.execute("CREATE TABLE unrelated(value)")
        planned = self.plan()
        self.assertFalse(planned["ready"])
        self.assertIn("BACKUP_SCHEMA", {b["code"] for b in planned["blockers"]})

    def test_normalization_temp_does_not_collide_with_user_filename(self):
        with database(self.app / "custom.sqlite3") as con:
            con.execute("CREATE TABLE value(item)")
            con.execute("INSERT INTO value VALUES ('preserve')")
        (self.app / "custom.sqlite3.normalized").write_text("unrelated original file", encoding="utf-8")
        self.create()
        self.restore()
        self.assertEqual((self.target / "app" / "custom.sqlite3.normalized").read_text(), "unrelated original file")

    def test_corrupt_source_database_fails_in_private_clone_without_source_changes(self):
        (self.app / "custom.sqlite3").write_bytes(b"not a database")
        before = self.files()
        result = self.plan()
        self.assertFalse(result["ready"])
        self.assertIn("BACKUP_DATABASE", {b["code"] for b in result["blockers"]})
        self.assertEqual(before, self.files())

    def test_source_symlink_policy_is_tested_without_os_link_privilege(self):
        (self.app / "value.txt").write_text("value", encoding="utf-8")
        original = inv.linked
        with patch.object(inv, "linked", side_effect=lambda p: p.name == "value.txt" or original(p)):
            self.code("BACKUP_PATH", self.plan)

    def test_verify_and_restore_do_not_require_original_cli_config(self):
        self.create()
        self.config.unlink()
        for args in (["verify", "--archive", str(self.archive)], ["restore", "--archive", str(self.archive), "--target", str(self.target)]):
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--config", str(self.config), "backup", *args, "--key-env", "TEST_BACKUP_KEY"])
            self.assertEqual(code, 0, output.getvalue())
            self.assertFalse(json.loads(output.getvalue())["sends_mail"])

    def test_cli_plan_create_verify_restore_and_structured_auth_errors(self):
        def invoke(*args):
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--config", str(self.config), "backup", *args])
            return code, json.loads(output.getvalue())
        code, planned = invoke("plan", "--crawler-workspace", str(self.crawler), "--port", str(self.port))
        self.assertEqual(code, 0)
        code, made = invoke("create", "--crawler-workspace", str(self.crawler), "--port", str(self.port), "--output", str(self.archive), "--expected-plan", planned["plan_id"], "--key-env", "TEST_BACKUP_KEY")
        self.assertEqual(code, 0, made)
        self.assertEqual(invoke("verify", "--archive", str(self.archive), "--key-env", "TEST_BACKUP_KEY")[0], 0)
        self.assertEqual(invoke("restore", "--archive", str(self.archive), "--target", str(self.target), "--key-env", "TEST_BACKUP_KEY")[0], 0)
        with patch.dict(os.environ, {"TEST_BACKUP_KEY": "invalid-secret"}):
            code, error = invoke("verify", "--archive", str(self.archive), "--key-env", "TEST_BACKUP_KEY")
        self.assertEqual(code, 2)
        self.assertEqual(error["error"]["code"], "BACKUP_KEY")
        self.assertNotIn("invalid-secret", json.dumps(error))


if __name__ == "__main__":
    unittest.main()
