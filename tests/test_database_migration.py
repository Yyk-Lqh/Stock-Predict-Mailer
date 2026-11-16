"""Real migration writes only disposable synthetic databases with verified backups."""
import io
import json
import sqlite3
import subprocess
import sys
import unittest
from contextlib import contextmanager, redirect_stdout
from unittest.mock import patch

import test_migration_preflight as fixtures
from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.cli import main
from stock_predict_mailer.operations import backup, migration, schema_planning
from stock_predict_mailer.operations.components import Component
from stock_predict_mailer.operations.schema_models import APPLICATION_ID, DATABASE_VERSION, catalogue, classify, execute_group


class MigrationTests(unittest.TestCase):
    def setUp(self):
        fixtures.PreflightTests.setUp(self)
        self.ready = fixtures.PreflightTests.check(self)
        self.assertTrue(self.ready["ready"], self.ready)

    def prepare(self):
        self.archive.unlink()
        value = backup.plan(self.cfg, self.config, crawler_workspace=self.crawler, port=self.port)
        backup.create(self.cfg, self.config, self.archive, value["plan_id"], crawler_workspace=self.crawler,
                      port=self.port, key_env="PREFLIGHT_TEST_KEY")
        self.plan_id = schema_planning.plan(self.cfg, crawler_workspace=self.crawler)["plan_id"]
        self.ready = fixtures.PreflightTests.check(self)
        self.assertTrue(self.ready["ready"], self.ready)

    def migrate(self, **kwargs):
        return migration.apply(self.cfg, self.config, self.archive, kwargs.pop("expected_plan", self.plan_id),
            kwargs.pop("expected_preflight", self.ready["preflight_id"]), store=kwargs.pop("store", "mail"),
            crawler_workspace=self.crawler, port=self.port, key_env="PREFLIGHT_TEST_KEY", **kwargs)

    def code(self, expected, **kwargs):
        with self.assertRaises(ServiceError) as caught:
            self.migrate(**kwargs)
        self.assertEqual(caught.exception.code, expected)
        self.assertNotIn("PRIVATE", caught.exception.message)

    def read(self, path=None, family="mail"):
        con = sqlite3.connect(path or self.path)
        try:
            return classify(con, family)
        finally:
            con.close()

    def test_atomic_upgrade_and_registered_marker_recognition(self):
        old_archive = self.archive.read_bytes()
        result = self.migrate()
        self.assertTrue(result["committed"])
        self.assertEqual(result["source_writes"], 1)
        self.assertEqual(result["operations"][0]["id"], "mail.bindings.initialize")
        record = self.read()
        self.assertEqual((record["state"], record["application_id"], record["user_version"]), ("current", APPLICATION_ID, DATABASE_VERSION))
        self.assertEqual(record["version_source"], "registered_and_structurally_verified")
        self.assertEqual(self.archive.read_bytes(), old_archive)
        self.assertEqual(schema_planning.report(self.cfg, crawler_workspace=self.crawler)["state"], "current")

    def test_ddl_failure_rolls_back_structure_and_markers(self):
        before = self.path.read_bytes()
        original = migration._execute
        def failing(con, operations):
            original(con, operations)
            raise sqlite3.OperationalError("PRIVATE-DDL-ERROR")
        with patch.object(migration, "_execute", side_effect=failing):
            self.code("MIGRATION_DATABASE")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.read()["user_version"], 0)

    def test_target_verification_failure_rolls_back(self):
        before = self.path.read_bytes()
        with patch.object(migration, "_validate", side_effect=ServiceError("MIGRATION_TARGET", "PRIVATE")):
            self.code("MIGRATION_TARGET")
        self.assertEqual(self.path.read_bytes(), before)

    def test_stale_schema_and_preflight_ids_do_not_write(self):
        before = self.path.read_bytes()
        self.code("MIGRATION_BLOCKED", expected_plan="0" * 64)
        self.code("MIGRATION_PREFLIGHT_CHANGED", expected_preflight="0" * 64)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_inputs_do_not_write(self):
        before = self.path.read_bytes()
        for kwargs in ({"store": "all"}, {"store": []}, {"expected_plan": "bad"}, {"expected_preflight": None}, {"accept_authorization_change": "yes"}):
            self.code("INVALID_INPUT", **kwargs)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_store_is_not_created(self):
        self.code("MIGRATION_MISSING", store="legacy")
        self.assertFalse((self.app / "state.sqlite3").exists())

    def test_source_change_after_barrier_is_rejected(self):
        original = migration.inv.barriers
        @contextmanager
        def racing(source):
            with original(source):
                (self.app / "external-change.txt").write_text("external", encoding="utf-8")
                yield
        before = self.path.read_bytes()
        with patch.object(migration.inv, "barriers", side_effect=racing):
            self.code("MIGRATION_SOURCE_CHANGED")
        self.assertEqual(self.path.read_bytes(), before)

    def test_wal_sources_are_rejected_before_source_connection(self):
        con = sqlite3.connect(self.path)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            self.prepare()
            before = {str(p): p.read_bytes() for p in self.app.rglob("*") if p.is_file()}
            with patch.object(migration, "_connect", side_effect=AssertionError("no source open")):
                self.code("MIGRATION_WAL_UNSUPPORTED")
            self.assertEqual({str(p): p.read_bytes() for p in self.app.rglob("*") if p.is_file()}, before)
        finally:
            con.close()

    def test_active_component_blocks_migration(self):
        before = self.path.read_bytes()
        with Component(self.app, "knowledge_worker"):
            self.code("MIGRATION_BLOCKED")
        self.assertEqual(self.path.read_bytes(), before)

    def test_sqlite_writer_lock_cannot_be_bypassed(self):
        con = sqlite3.connect(self.path)
        try:
            con.execute("BEGIN IMMEDIATE")
            self.code("MIGRATION_DATABASE")
        finally:
            con.rollback()
            con.close()
        self.assertEqual(self.read()["user_version"], 0)

    def test_old_plan_cannot_replay_after_commit(self):
        self.migrate()
        before = self.path.read_bytes()
        self.code("MIGRATION_BLOCKED")
        self.assertEqual(self.path.read_bytes(), before)

    def test_fresh_backup_of_registered_store_makes_repeat_a_noop(self):
        self.migrate()
        self.prepare()
        before = self.path.read_bytes()
        result = self.migrate()
        self.assertEqual(result["state"], "already_current")
        self.assertFalse(result["committed"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_registered_markers_do_not_hide_drift_or_missing_target(self):
        self.migrate()
        con = sqlite3.connect(self.path)
        try:
            con.execute("DROP TABLE mail_binding")
            con.execute("DROP TABLE mail_alias")
            con.execute("DROP TABLE mail_control")
            con.commit()
        finally:
            con.close()
        record = self.read()
        self.assertEqual(record["state"], "blocked")
        self.assertIn("REGISTERED_SCHEMA_INCOMPLETE", [i["code"] for i in record["issues"]])

    def test_partial_or_future_marker_pairs_are_blocked(self):
        con = sqlite3.connect(self.path)
        try:
            for app, version in ((APPLICATION_ID, 0), (0, DATABASE_VERSION), (APPLICATION_ID, DATABASE_VERSION + 1)):
                con.execute(f"PRAGMA application_id={app}")
                con.execute(f"PRAGMA user_version={version}")
                self.assertEqual(classify(con, "mail")["state"], "blocked")
        finally:
            con.close()

    def test_permission_backfill_requires_explicit_ack_and_updates_only_selected_store(self):
        path = self.app / "state.sqlite3"
        con = sqlite3.connect(path)
        try:
            for group in ("legacy.runs", "legacy.authorizations"):
                execute_group(con, catalogue()["groups"][group], [])
            con.execute("INSERT INTO dataset_authorizations VALUES ('snapshot','owner',1,1,'PRIVATE-NOTE','2026-11-16')")
            con.commit()
        finally:
            con.close()
        self.prepare()
        before = path.read_bytes()
        self.code("MIGRATION_AUTHORIZATION_REVIEW", store="legacy")
        self.assertEqual(path.read_bytes(), before)
        mail_before = self.path.read_bytes()
        result = self.migrate(store="legacy", accept_authorization_change=True)
        self.assertEqual(result["operations"][0]["data_rows_changed"], 1)
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(self.path.read_bytes(), mail_before)
        con = sqlite3.connect(path)
        try:
            self.assertEqual(con.execute("SELECT replay_enabled FROM dataset_authorizations").fetchone()[0], 1)
        finally:
            con.close()

    def test_changes_to_other_known_files_abort_before_commit(self):
        note = self.app / "note.txt"
        note.write_text("before", encoding="utf-8")
        self.prepare()
        original = migration._execute
        def racing(con, operations):
            result = original(con, operations)
            note.write_text("external", encoding="utf-8")
            return result
        before = self.path.read_bytes()
        with patch.object(migration, "_execute", side_effect=racing):
            self.code("MIGRATION_SOURCE_CHANGED")
        self.assertEqual(self.path.read_bytes(), before)

    def test_commit_failure_reports_uncertainty_instead_of_claiming_no_write(self):
        original = migration._connect
        class Connection:
            def __init__(self, con):
                self.con = con
            def __getattr__(self, name):
                return getattr(self.con, name)
            def commit(self):
                raise sqlite3.OperationalError("PRIVATE-COMMIT-FAILURE")
        with patch.object(migration, "_connect", side_effect=lambda path: Connection(original(path))):
            self.code("MIGRATION_COMMIT_OUTCOME_UNKNOWN")
        self.assertEqual(self.read()["user_version"], 0)

    def test_commit_then_error_is_not_reported_as_unchanged(self):
        original = migration._connect
        class Connection:
            def __init__(self, con):
                self.con = con
            def __getattr__(self, name):
                return getattr(self.con, name)
            def commit(self):
                self.con.commit()
                raise OSError("PRIVATE-POST-COMMIT")
        with patch.object(migration, "_connect", side_effect=lambda path: Connection(original(path))):
            self.code("MIGRATION_COMMIT_OUTCOME_UNKNOWN")
        self.assertEqual(self.read()["user_version"], DATABASE_VERSION)

    def test_cleanup_error_after_commit_is_explicit(self):
        original = migration.inv.barriers
        @contextmanager
        def failing(source):
            with original(source):
                yield
            raise OSError("PRIVATE-CLEANUP")
        with patch.object(migration.inv, "barriers", side_effect=failing):
            self.code("MIGRATION_COMMITTED_RECHECK_REQUIRED")
        self.assertEqual(self.read()["user_version"], DATABASE_VERSION)

    def test_cli_migrate_requires_fences_and_returns_receipt(self):
        args = ["--config", str(self.config), "db", "migrate", "--store", "mail", "--archive", str(self.archive),
                "--expected-plan", self.plan_id, "--expected-preflight", self.ready["preflight_id"],
                "--crawler-workspace", str(self.crawler), "--port", str(self.port), "--key-env", "PREFLIGHT_TEST_KEY"]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args), 0)
        self.assertTrue(json.loads(output.getvalue())["committed"])

    def test_registered_backup_restores_without_automatic_replay(self):
        self.migrate()
        self.prepare()
        restored = self.root / "restored"
        backup.restore(self.archive, restored, key_env="PREFLIGHT_TEST_KEY")
        record = self.read(restored / "app/agent-mail.sqlite3")
        self.assertEqual(record["state"], "current")
        self.assertEqual(record["user_version"], DATABASE_VERSION)

    def test_known_current_unregistered_store_can_be_stamped_without_ddl(self):
        con = sqlite3.connect(self.path)
        try:
            execute_group(con, catalogue()["groups"]["mail.bindings"])
            con.commit()
        finally:
            con.close()
        self.prepare()
        result = self.migrate()
        self.assertEqual(result["operations"], [])
        self.assertTrue(result["committed"])
        self.assertEqual(self.read()["user_version"], DATABASE_VERSION)

    def test_abrupt_process_exit_leaves_no_committed_schema_or_marker(self):
        script = """
import os,sqlite3,sys
from stock_predict_mailer.operations.schema_models import APPLICATION_ID,DATABASE_VERSION,catalogue
con=sqlite3.connect(sys.argv[1])
con.execute('PRAGMA cache_size=1')
con.execute('BEGIN IMMEDIATE')
for sql in catalogue()['groups']['mail.bindings']['ddl']:
    con.execute(sql)
con.execute(f'PRAGMA application_id={APPLICATION_ID}')
con.execute(f'PRAGMA user_version={DATABASE_VERSION}')
os._exit(99)
"""
        result = subprocess.run([sys.executable, "-c", script, str(self.path)], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 99, result.stderr)
        report = schema_planning.report(self.cfg, crawler_workspace=self.crawler, store="mail")
        self.assertEqual(report["state"], "blocked")
        self.assertEqual(report["databases"][0]["issues"][0]["code"], "SCHEMA_JOURNAL")
        # A separate operator recovery opens SQLite here; the read-only report
        # above deliberately did not recover/checkpoint the original file.
        recovered = self.read()
        self.assertEqual(recovered["user_version"], 0)
        self.assertEqual(recovered["state"], "upgrade_available")
