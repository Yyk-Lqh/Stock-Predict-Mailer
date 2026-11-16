"""Operational preflight fixtures never contact providers, collect or deliver."""
import io
import json
import os
import socket
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet

from mcp_server.jobs import JobStore
from stock_predict_mailer.cli import main
from stock_predict_mailer.control.store import Store
from stock_predict_mailer.core import Config
from stock_predict_mailer.delivery import outbox_schema, process_lock
from stock_predict_mailer.mail_core import MailCore
from stock_predict_mailer.operations import diagnostics, probes
from stock_predict_mailer.private_knowledge.service import Knowledge


@contextmanager
def writable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        with con:
            yield con
    finally:
        con.close()


class DoctorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.parent = Path(tmp.name).resolve()
        self.root = self.parent / "app"
        self.crawler = self.parent / "crawler"
        self.cfg = {"workspace": self.root, "mail": {"transport": "file"}}
        self.addCleanup(patch.stopall)
        patch("stock_predict_mailer.operations.diagnostics.env", return_value="").start()

    def report(self, **kwargs):
        return diagnostics.diagnose(self.cfg, crawler_workspace=self.crawler, check_port=False, **kwargs)

    def codes(self, report=None):
        return {item["code"] for item in (report or self.report())["checks"]}

    def check(self, report, component, code):
        return next(item for item in report["checks"] if item["component"] == component and item["code"] == code)

    def files(self):
        return {p.relative_to(self.parent).as_posix(): p.read_bytes() for p in self.parent.rglob("*") if p.is_file()}

    def mail(self, status="pending", attempts=0):
        core = MailCore(self.root, {})
        with core.db() as con:
            con.execute("INSERT INTO mail VALUES (?,?,?,?,?,?,?,?,?,?)", ("a" * 64, "private-recipient@example.com", "private-sender@example.com",
                "file", status, attempts, "2026-01-01T00:00:00Z", None, "b" * 64, "private-analysis-content"))
        return core

    def store(self):
        self.key = Fernet.generate_key()
        return Store(self.root, self.key)

    def test_missing_workspaces_are_not_created(self):
        result = self.report()
        self.assertEqual(result["status"], "warning")
        self.assertFalse(self.root.exists())
        self.assertFalse(self.crawler.exists())
        self.assertIn("VAULT_NOT_INITIALIZED", self.codes(result))

    def test_empty_existing_workspace_is_valid_preflight_without_initialization(self):
        self.root.mkdir()
        self.crawler.mkdir()
        before = self.files()
        self.assertEqual(self.report()["status"], "ok")
        self.assertEqual(before, self.files())

    def test_workspace_file_is_explained_without_initialization(self):
        self.root.write_text("not a directory", encoding="utf-8")
        self.assertEqual(self.report()["status"], "error")
        self.assertIn("WORKSPACE_NOT_DIRECTORY", self.codes())

    def test_readonly_queue_summary_avoids_sensitive_fields_and_effectful_services(self):
        self.mail("uncertain", 2)
        store = self.store()
        kb = Knowledge(store)
        with kb.db() as con:
            con.execute("INSERT INTO documents(id,owner,logical,filename,hash,metadata,uploaded,status,step) VALUES (?,?,?,?,?,?,?,?,?)",
                ("private-doc-id", "private-owner", "private-doc", "private-filename.txt", "hash", "{}", "2026-01-01", "pending", "received"))
        before = self.files()
        with patch.object(Store, "__init__", side_effect=AssertionError("must not initialize")), \
             patch.object(Knowledge, "__init__", side_effect=AssertionError("must not initialize")), \
             patch.object(MailCore, "__init__", side_effect=AssertionError("must not initialize")), \
             patch.object(JobStore, "claim", side_effect=AssertionError("must not recover")):
            result = self.report()
        self.assertEqual(before, self.files())
        raw = json.dumps(result)
        for private in ("private-recipient", "private-sender", "private-analysis", "private-filename", "private-owner"):
            self.assertNotIn(private, raw)
        self.assertIn("MAIL_BINDING_REVIEW", self.codes(result))
        self.assertIn("MAIL_OUTCOME_REVIEW", self.codes(result))
        self.assertIn("WORKER_REQUIRED", self.codes(result))

    def test_corrupt_database_does_not_prevent_other_checks(self):
        self.root.mkdir()
        (self.root / "agent-mail.sqlite3").write_bytes(b"sensitive-corrupt-database-body")
        JobStore(self.crawler).submit("catalog")
        result = self.report()
        self.assertIn("DB_CORRUPT", self.codes(result))
        self.assertEqual(self.check(result, "crawler", "DB_READABLE")["details"]["queues"]["jobs"], {"queued": 1})
        self.assertNotIn("sensitive-corrupt", json.dumps(result))
        (self.root / "agent-mail.sqlite3").write_bytes(b"SQLite format 3\x00")
        self.assertIn("DB_CORRUPT", self.codes())

    def test_schema_error_in_existing_optional_binding_is_reported(self):
        self.mail()
        with writable(self.root / "agent-mail.sqlite3") as con:
            con.execute("DROP TABLE mail_binding")
            con.execute("CREATE TABLE mail_binding(message_id TEXT)")
        self.assertIn("DB_SCHEMA_INCOMPATIBLE", self.codes())

    def test_old_agent_schema_is_read_without_migration(self):
        self.mail("retry", 1)
        with writable(self.root / "agent-mail.sqlite3") as con:
            con.execute("DROP TABLE mail_binding")
        before = self.files()
        result = self.report()
        self.assertIn("DB_READABLE", self.codes(result))
        self.assertIn("MAIL_BINDING_REVIEW", self.codes(result))
        self.assertEqual(self.files(), before)

    def test_completed_unbound_history_does_not_request_impossible_rebind(self):
        self.mail("simulated", 1)
        with writable(self.root / "agent-mail.sqlite3") as con:
            con.execute("DROP TABLE mail_binding")
        self.assertNotIn("MAIL_BINDING_REVIEW", self.codes())

    def test_historical_mcp_receipts_require_review_without_rewriting_them(self):
        store = self.store()
        with store.db() as con:
            con.execute("CREATE TABLE mcp_mail(id TEXT PRIMARY KEY,status TEXT)")
            con.execute("INSERT INTO mcp_mail VALUES ('private-old-marker','sending')")
        before = self.files()
        result = self.report()
        self.assertIn("MCP_HISTORY_PRESENT", self.codes(result))
        self.assertNotIn("private-old-marker", json.dumps(result))
        self.assertEqual(before, self.files())

    def test_containment_and_resolution_failure_are_explicit(self):
        with self.assertRaises(probes.ProbeError) as caught:
            probes.contained(self.root, self.parent / "outside.sqlite3")
        self.assertEqual(caught.exception.code, "PATH_OUTSIDE_WORKSPACE")
        with patch.object(Path, "resolve", side_effect=RuntimeError("private-loop")):
            with self.assertRaises(probes.ProbeError) as caught:
                probes.contained(self.root, self.root / "db")
        self.assertEqual(caught.exception.code, "PATH_UNREADABLE")

    def test_exclusive_database_lock_returns_bounded_busy(self):
        self.mail()
        with writable(self.root / "agent-mail.sqlite3") as con:
            con.execute("BEGIN EXCLUSIVE")
            result = self.report()
        self.assertIn("DB_BUSY", self.codes(result))

    def test_query_budget_maps_to_limit_instead_of_corruption(self):
        self.mail()
        with self.assertRaises(probes.ProbeError) as caught:
            with probes.database(self.root, "agent-mail.sqlite3", seconds=-1) as con:
                con.execute("WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<100000) SELECT SUM(x) FROM n").fetchone()
        self.assertEqual(caught.exception.code, "DB_CHECK_LIMIT")

    def test_wal_database_without_sidecars_is_deferred_without_creating_them(self):
        self.root.mkdir()
        with writable(self.root / "state.sqlite3") as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE runs(status)")
        before = self.files()
        result = self.report()
        self.assertEqual(before, self.files())
        self.assertIn("DB_WAL_CHECK_DEFERRED", self.codes(result))
        self.assertNotIn("DB_CORRUPT", self.codes(result))

    def test_live_wal_commits_are_never_reported_as_empty_healthy_snapshot(self):
        self.root.mkdir()
        with writable(self.root / "agent-mail.sqlite3") as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE mail(id,status,attempts)")
            con.execute("INSERT INTO mail VALUES ('sensitive-id','sending',1)")
            con.commit()
            before = self.files()
            result = self.report()
            self.assertEqual(before, self.files())
        self.assertIn("DB_WAL_CHECK_DEFERRED", self.codes(result))
        self.assertFalse(any(c["component"] == "mail" and c["code"] == "DB_READABLE" for c in result["checks"]))

    def test_lock_file_presence_is_not_worker_identity_and_file_never_changes(self):
        private = self.root / "private-knowledge"
        private.mkdir(parents=True)
        path = private / "pipeline.lock"
        path.write_bytes(b"0")
        self.assertEqual(probes.lock_state(self.root, "private-knowledge/pipeline.lock"), "available")
        with process_lock(Config(private)):
            self.assertEqual(probes.lock_state(self.root, "private-knowledge/pipeline.lock"), "busy")
        self.assertEqual(path.read_bytes(), b"0")
        self.assertEqual(self.check(self.report(), "knowledge_worker", "WRITER_LOCK")["details"]["process_identity"], "unknown")

    def test_empty_and_unreadable_locks_are_unknown(self):
        self.root.mkdir()
        (self.root / "empty.lock").touch()
        self.assertEqual(probes.lock_state(self.root, "empty.lock"), "unknown" if os.name == "nt" else "available")
        with patch.object(Path, "open", side_effect=PermissionError("private-path")):
            self.assertEqual(probes.lock_state(self.root, "empty.lock"), "unknown")
        self.assertEqual(probes.lock_state(self.root, "absent.lock"), "absent")

    def test_empty_posix_lock_is_probed_without_writing_and_busy_is_preserved(self):
        import errno
        from unittest.mock import Mock
        self.root.mkdir()
        path = self.root / "empty.lock"
        path.touch()
        flock = Mock()
        module = SimpleNamespace(LOCK_SH=1, LOCK_NB=4, LOCK_UN=8, flock=flock)
        with patch.object(probes, "os", SimpleNamespace(name="posix")), patch.dict("sys.modules", {"fcntl": module}):
            self.assertEqual(probes.lock_state(self.root, "empty.lock"), "available")
            self.assertEqual(flock.call_count, 2)
            flock.side_effect = BlockingIOError(errno.EAGAIN, "held by writer")
            self.assertEqual(probes.lock_state(self.root, "empty.lock"), "busy")
        self.assertEqual(path.read_bytes(), b"")

    def test_running_crawler_with_no_lock_is_suspected_not_recovered(self):
        store = JobStore(self.crawler)
        job = store.submit("catalog")
        with store.db(True) as con:
            con.execute("UPDATE jobs SET state='running' WHERE id=?", (job["id"],))
        before = self.files()
        result = self.report()
        self.assertEqual(before, self.files())
        self.assertIn("INTERRUPTION_SUSPECTED", self.codes(result))
        self.assertEqual(store.get(job["id"])["state"], "running")

    def test_pending_crawler_missing_dependencies_is_actionable(self):
        JobStore(self.crawler).submit("catalog")
        with patch("importlib.util.find_spec", return_value=None):
            result = self.report()
        self.assertIn("CRAWLER_DEPENDENCY_MISSING", self.codes(result))

    def test_smtp_presence_check_never_exposes_credentials_or_email(self):
        self.cfg["mail"] = {"transport": "smtp", "sender": "private@example.com", "user_env": "DOCTOR_USER", "password_env": "DOCTOR_PASSWORD"}
        with patch.dict(os.environ, {"DOCTOR_USER": "private-login", "DOCTOR_PASSWORD": "private-password"}):
            result = self.report()
        self.assertIn("SMTP_CREDENTIALS_PRESENT", self.codes(result))
        self.assertNotIn("private-", json.dumps(result))
        with patch.dict(os.environ, {"DOCTOR_USER": "", "DOCTOR_PASSWORD": ""}):
            self.assertIn("SMTP_CREDENTIALS_MISSING", self.codes())

    def test_production_key_check_uses_marker_without_selecting_profile_secrets(self):
        store = self.store()
        store.put("models", {"name": "private-profile", "api_key": "private-api-key"})
        before = self.files()
        original_connect = sqlite3.connect
        def connect(*args, **kwargs):
            con = original_connect(*args, **kwargs)
            def authorize(action, table, column, db, source):
                if action == sqlite3.SQLITE_READ and table == "profiles" and column in ("body", "secrets"):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            con.set_authorizer(authorize)
            return con
        with patch("stock_predict_mailer.operations.diagnostics.env", return_value=self.key.decode()), patch("sqlite3.connect", side_effect=connect):
            result = self.report()
        self.assertIn("VAULT_KEY_MATCH", self.codes(result))
        self.assertEqual(before, self.files())
        self.assertNotIn("private-profile", json.dumps(result))
        self.assertNotIn(self.key.decode(), json.dumps(result))

    def test_wrong_or_invalid_key_is_redacted(self):
        self.store()
        with patch("stock_predict_mailer.operations.diagnostics.env", return_value=Fernet.generate_key().decode()):
            self.assertIn("VAULT_KEY_MISMATCH", self.codes())
        with patch("stock_predict_mailer.operations.diagnostics.env", return_value="private-invalid-key"):
            result = self.report()
        self.assertIn("VAULT_KEY_INVALID", self.codes(result))
        self.assertNotIn("private-invalid-key", json.dumps(result))

    def test_existing_development_database_without_key_does_not_generate_replacement(self):
        store = self.store()
        os.replace(store.db_path, self.root / "control-development.sqlite3")
        before = self.files()
        self.assertIn("VAULT_KEY_MISSING", self.codes())
        self.assertEqual(before, self.files())
        (self.root / "control-development.key").write_bytes(self.key)
        self.assertIn("VAULT_KEY_MATCH", self.codes())

    def test_missing_marker_is_unverified_without_secret_fallback(self):
        store = self.store()
        with store.db() as con:
            con.execute("DELETE FROM state WHERE id='vault_check'")
        with patch("stock_predict_mailer.operations.diagnostics.env", return_value=self.key.decode()):
            self.assertIn("VAULT_KEY_UNVERIFIED", self.codes())

    def test_unselected_production_database_is_explicit(self):
        self.store()
        self.assertIn("PRODUCTION_VAULT_NOT_SELECTED", self.codes())

    def test_control_task_limits_unknown_json_and_unconfirmed_runtime(self):
        store = self.store()
        with store.db() as con:
            con.executemany("INSERT INTO tasks VALUES (?,?)", [("first", json.dumps({"status": {"state": "working"}})), ("second", "malformed-private-text"), ("third", "{}")])
        with patch.object(diagnostics, "MAX_TASKS", 2):
            result = self.report()
        self.assertIn("TASK_SCAN_LIMIT", self.codes(result))
        self.assertFalse(self.check(result, "control", "DB_READABLE")["details"]["counts_complete"])
        self.assertIn("QUEUE_STATE_UNKNOWN", self.codes(result))
        self.assertIn("ANALYSIS_RUNTIME_UNKNOWN", self.codes(result))
        self.assertNotIn("malformed-private-text", json.dumps(result))

    def test_task_byte_limits_are_reported_without_large_output(self):
        store = self.store()
        with store.db() as con:
            con.execute("INSERT INTO tasks VALUES ('a',?)", ('x' * 100,))
        with patch.object(diagnostics, "MAX_JSON_BYTES", 10):
            result = self.report()
        self.assertIn("QUEUE_STATE_UNKNOWN", self.codes(result))
        with patch.object(diagnostics, "MAX_TOTAL_JSON", 10):
            result = self.report()
        self.assertIn("TASK_SCAN_LIMIT", self.codes(result))

    def test_legacy_rollback_schema_and_unknown_state(self):
        self.root.mkdir()
        with writable(self.root / "state.sqlite3") as con:
            con.execute("CREATE TABLE runs(status)")
            con.execute("INSERT INTO runs VALUES ('running')")
            outbox_schema(con)
            con.execute("INSERT INTO outbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("a" * 64, "b" * 64, "private-owner", "private@example.com",
                "sender@example.com", "unknown-private-state", 1, "2026-01-01", "2026-01-01", "message-id", "hash", None))
        result = self.report()
        self.assertIn("QUEUE_STATE_UNKNOWN", self.codes(result))
        self.assertIn("INTERRUPTION_SUSPECTED", self.codes(result))
        self.assertNotIn("unknown-private-state", json.dumps(result))

    def test_skip_port_check_never_constructs_socket(self):
        with patch("socket.socket", side_effect=AssertionError("offline inspection")):
            self.assertIn("PORT_CHECK_SKIPPED", self.codes())

    def test_occupied_loopback_port_is_not_misidentified_as_console(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            port = sock.getsockname()[1]
            result = diagnostics.diagnose(self.cfg, crawler_workspace=self.crawler, port=port)
        item = self.check(result, "console_port", "PORT_UNAVAILABLE")
        self.assertEqual(item["details"]["state"], "unavailable")
        self.assertEqual(probes.port_state(port), "available")

    def test_invalid_port_is_structured_and_does_not_initialize(self):
        for port in (0, -1, 65536, True):
            with self.subTest(port=port), self.assertRaises(Exception) as caught:
                self.report(port=port)
            self.assertEqual(caught.exception.code, "INVALID_INPUT")
        self.assertFalse(self.root.exists())

    def test_cli_exit_codes_json_and_no_mail_service_construction(self):
        config = self.parent / "config.toml"
        config.write_text('workspace="app"\n[mail]\ntransport="file"\nsender="preview@example.invalid"\n', encoding="utf-8")
        self.crawler.mkdir()
        def invoke():
            output = io.StringIO()
            with redirect_stdout(output), patch.object(MailCore, "__init__", side_effect=AssertionError("not a mail command")):
                code = main(["--config", str(config), "doctor", "--skip-port-check", "--crawler-workspace", str(self.crawler)])
            return code, json.loads(output.getvalue())
        self.assertEqual(invoke()[0], 1)
        self.root.mkdir()
        self.assertEqual(invoke()[0], 0)
        (self.root / "agent-mail.sqlite3").write_bytes(b"broken")
        code, result = invoke()
        self.assertEqual(code, 2)
        self.assertEqual(result["mode"], "read_only_preflight")

    def test_crawler_environment_default_matches_existing_entrypoint(self):
        with patch.dict(os.environ, {"STOCK_PREDICT_MAILER_CRAWLER_WORKSPACE": str(self.crawler)}):
            result = diagnostics.diagnose(self.cfg, check_port=False)
        self.assertEqual(result["crawler_workspace"], str(self.crawler.resolve()))

    def test_outside_workspace_database_is_not_followed(self):
        self.root.mkdir()
        with writable(self.parent / "outside.sqlite3") as con:
            con.execute("CREATE TABLE private_data(secret)")
        try:
            (self.root / "agent-mail.sqlite3").symlink_to(self.parent / "outside.sqlite3")
        except OSError:
            self.skipTest("symlink creation unavailable for this account")
        self.assertIn("PATH_OUTSIDE_WORKSPACE", self.codes())


if __name__ == "__main__":
    unittest.main()
