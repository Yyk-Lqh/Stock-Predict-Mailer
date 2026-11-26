"""Structural inference and transaction rehearsal never open original SQLite files."""
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from mcp_server.jobs import JobStore
from stock_predict_mailer.agent_service.config import load
from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.cli import main
from stock_predict_mailer.control.memory import Memory
from stock_predict_mailer.control.store import Store
from stock_predict_mailer.mail_core import MailCore
from stock_predict_mailer.operations import schema_planning as sp
from stock_predict_mailer.operations.schema_models import catalogue, execute_group
from stock_predict_mailer.private_knowledge.service import Knowledge


@contextmanager
def database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        with con:
            yield con
    finally:
        con.close()


class SchemaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.app, self.crawler = self.base / "app", self.base / "crawler"
        self.config = self.base / "agent.toml"
        self.config.write_text('workspace="app"\n[mail]\ntransport="file"\nsender="preview@example.invalid"\n', encoding="utf-8")
        self.cfg = load(self.config)

    def path(self, store):
        return (self.crawler if store == "crawler" else self.app) / sp.STORES[store][0]

    def create(self, store, *groups, additions=None):
        with database(self.path(store)) as con:
            for group in groups:
                execute_group(con, catalogue()["groups"][group], additions)

    def plan(self, store="all", **kwargs):
        return sp.plan(self.cfg, crawler_workspace=self.crawler, store=store, **kwargs)

    def rehearse(self, store="all"):
        value = self.plan(store)
        self.assertTrue(value["ready"], value)
        return self.plan(store, rehearse=True, expected_plan=value["plan_id"])

    def files(self):
        return {str(p): p.read_bytes() for root in (self.app, self.crawler) for p in root.rglob("*") if p.is_file()}

    def code(self, code, function, *args, **kwargs):
        with self.assertRaises(ServiceError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def assert_blocked(self, store, code):
        before = self.files()
        value = self.plan(store)
        self.assertEqual(value["state"], "blocked", value)
        self.assertFalse(value["ready"])
        self.assertEqual(value["databases"][0]["operations"], [])
        self.assertIn(code, [i["code"] for i in value["databases"][0]["issues"]])
        self.assertEqual(self.files(), before)
        return value

    def test_missing_is_informational_and_creates_nothing(self):
        value = self.plan()
        self.assertEqual(value["state"], "not_initialized")
        self.assertEqual(len(value["databases"]), 6)
        self.assertEqual(self.rehearse()["rehearsal"], [])
        self.assertFalse(self.app.exists())
        self.assertFalse(self.crawler.exists())

    def test_actual_current_constructors_all_match_without_reinitialization(self):
        with MailCore(self.app, {"transport": "file"}).db():
            pass
        production = Store(self.app, Fernet.generate_key())
        Memory(production)
        Knowledge(production)
        with patch.dict(os.environ, {"STOCK_PREDICT_MAILER_MASTER_KEY": "", "SPM_MASTER_KEY": ""}):
            Store(self.app)
        with JobStore(self.crawler).db(True):
            pass
        self.create("legacy", "legacy.runs", "legacy.authorizations")
        before = self.files()
        with patch.object(Store, "__init__", side_effect=AssertionError("no constructor")), patch.object(MailCore, "__init__", side_effect=AssertionError("no mail")), patch.object(Knowledge, "__init__", side_effect=AssertionError("no knowledge")):
            value = self.plan()
        self.assertEqual(value["state"], "current", value)
        self.assertEqual(value["changes"], 0)
        self.assertTrue(all(d["user_version"] == 0 for d in value["databases"]))
        self.assertEqual(self.files(), before)
        self.assertTrue(all(d["target_verified"] for d in self.rehearse()["rehearsal"]))
        self.assertEqual(self.files(), before)

    def test_old_mail_only_adds_empty_binding_tables(self):
        self.create("mail", "mail.core")
        before = self.files()
        value = self.plan("mail")
        self.assertEqual(value["changes"], 1)
        self.assertEqual(value["databases"][0]["operations"][0]["data_effect"], "creates_empty_binding_tables_without_deriving_history")
        result = self.rehearse("mail")
        self.assertEqual(result["rehearsal"][0]["operations"][0]["statements"], 3)
        self.assertFalse(result["rehearsal"][0]["committed"])
        self.assertEqual(self.files(), before)
        with database(self.path("mail")) as con:
            self.assertIsNone(con.execute("SELECT name FROM sqlite_master WHERE name='mail_binding'").fetchone())

    def test_returned_initialize_statements_cannot_poison_catalogue(self):
        self.create("mail", "mail.core")
        first = self.plan("mail")
        first["databases"][0]["operations"][0]["statements"].append("DROP TABLE mail")
        self.assertEqual(len(self.plan("mail")["databases"][0]["operations"][0]["statements"]), 3)

    def test_partial_binding_group_is_blocked(self):
        self.create("mail", "mail.core", "mail.bindings")
        with database(self.path("mail")) as con:
            con.execute("DROP TABLE mail_alias")
        self.assert_blocked("mail", "INCOMPLETE_FEATURE_GROUP")

    def test_old_knowledge_preserves_rows_and_fts_in_source(self):
        self.create("knowledge", "knowledge.core", additions=[])
        with database(self.path("knowledge")) as con:
            con.execute("INSERT INTO owners(owner) VALUES ('CONFIDENTIAL-OWNER')")
            con.execute("INSERT INTO chunk_fts(terms) VALUES ('CONFIDENTIAL-TEXT')")
        before = self.files()
        value = self.plan("knowledge")
        self.assertEqual(value["changes"], 7, value)
        operations = {item["id"]: item for item in value["databases"][0]["operations"]}
        self.assertIn("knowledge.profile", operations)
        self.assertNotIn("CONFIDENTIAL", json.dumps(value))
        self.assertTrue(self.rehearse("knowledge")["rehearsal"][0]["target_verified"])
        self.assertEqual(self.files(), before)
        with database(self.path("knowledge")) as con:
            self.assertNotIn("cleaner_config", [r[1] for r in con.execute("PRAGMA table_info(owners)")])
            self.assertEqual(con.execute("SELECT terms FROM chunk_fts").fetchone()[0], "CONFIDENTIAL-TEXT")

    def test_supported_partial_knowledge_additions(self):
        self.create("knowledge", "knowledge.core", additions=["knowledge.extraction"])
        self.assertEqual(self.plan("knowledge")["changes"], 6)
        self.assertTrue(self.rehearse("knowledge")["rehearsal"][0]["target_verified"])

    def test_new_knowledge_workers_and_owner_map_are_recognized(self):
        self.create("control", "control.base", "control.knowledge_owners")
        self.assertEqual(self.plan("control")["state"], "current")
        self.create("knowledge", "knowledge.core")
        value = self.plan("knowledge")
        self.assertEqual(value["changes"], 1)
        self.assertEqual(value["databases"][0]["operations"][0]["id"], "knowledge.workers.initialize")
        before = self.files()
        self.rehearse("knowledge")
        self.assertEqual(self.files(), before)

    def test_historical_legacy_knowledge_remains_recognizable(self):
        self.create("legacy", "legacy.runs", "legacy.knowledge")
        self.assertEqual(self.plan("legacy")["state"], "current")
        self.assertTrue(self.rehearse("legacy")["rehearsal"][0]["target_verified"])

    def test_unsupported_column_order_is_not_rewritten(self):
        self.create("knowledge", "knowledge.core", additions=["knowledge.review"])
        self.assert_blocked("knowledge", "UNSUPPORTED_ADDITION_ORDER")

    def test_training_additions_rehearse_without_loading_research(self):
        self.create("legacy", "legacy.runs", "legacy.training", additions=[])
        self.assertEqual(self.plan("legacy")["changes"], 2)
        before = self.files()
        self.assertTrue(self.rehearse("legacy")["rehearsal"][0]["target_verified"])
        self.assertEqual(self.files(), before)

    def old_authorizations(self):
        self.create("legacy", "legacy.runs", "legacy.authorizations", additions=[])
        with database(self.path("legacy")) as con:
            con.executemany("INSERT INTO dataset_authorizations VALUES (?,?,1,?,'PRIVATE-NOTE','2026-11-15')", [("one", "owner", 1), ("two", "owner", 0), ("three", "owner", 0)])

    def test_authorization_backfill_explicit_and_rolled_back(self):
        self.old_authorizations()
        before = self.files()
        value = self.plan("legacy")
        self.assertTrue(value["requires_permission_review"])
        self.assertIn("enables_replay", value["databases"][0]["operations"][0]["data_effect"])
        self.assertNotIn("PRIVATE-NOTE", json.dumps(value))
        result = self.rehearse("legacy")
        self.assertEqual(result["rehearsal"][0]["operations"][0]["data_rows_changed"], 1)
        self.assertEqual(result["source_writes"], 0)
        self.assertFalse(result["ready_for_apply"])
        self.assertEqual(self.files(), before)

    def test_row_changes_keep_schema_id_but_invalidate_plan(self):
        self.old_authorizations()
        first = self.plan("legacy")
        with database(self.path("legacy")) as con:
            con.execute("UPDATE dataset_authorizations SET note='changed' WHERE snapshot_id='one'")
        second = self.plan("legacy")
        self.assertEqual(first["databases"][0]["schema_id"], second["databases"][0]["schema_id"])
        self.assertNotEqual(first["databases"][0]["source_id"], second["databases"][0]["source_id"])
        self.code("SCHEMA_PLAN_CHANGED", self.plan, "legacy", rehearse=True, expected_plan=first["plan_id"])

    def test_rehearsal_requires_matching_reviewed_plan(self):
        self.code("INVALID_INPUT", self.plan, rehearse=True)
        self.code("INVALID_INPUT", self.plan, expected_plan="wrong")
        self.code("SCHEMA_PLAN_CHANGED", self.plan, rehearse=True, expected_plan="wrong")

    def test_catalogue_identity_fences_rehearsal(self):
        self.create("control", "control.base")
        first = self.plan("control")
        changed = {**catalogue(), "catalogue_revision": "next"}
        with patch.object(sp, "catalogue", return_value=changed):
            self.code("SCHEMA_PLAN_CHANGED", self.plan, "control", rehearse=True, expected_plan=first["plan_id"])

    def test_nonzero_user_version_is_never_stamped_over(self):
        self.create("control", "control.base")
        with database(self.path("control")) as con:
            con.execute("PRAGMA user_version=7")
        self.assert_blocked("control", "UNREGISTERED_USER_VERSION")

    def test_foreign_application_id_is_blocked(self):
        self.create("control", "control.base")
        with database(self.path("control")) as con:
            con.execute("PRAGMA application_id=123")
        self.assert_blocked("control", "FOREIGN_APPLICATION_ID")

    def test_unknown_objects_and_private_sql_are_not_exposed(self):
        self.create("control", "control.base")
        with database(self.path("control")) as con:
            con.executescript("CREATE TABLE PRIVATE_TABLE(secret TEXT DEFAULT 'PRIVATE-DEFAULT'); CREATE VIEW PRIVATE_VIEW AS SELECT * FROM PRIVATE_TABLE; CREATE TRIGGER PRIVATE_TRIGGER AFTER INSERT ON PRIVATE_TABLE BEGIN UPDATE PRIVATE_TABLE SET secret='PRIVATE-TRIGGER'; END;")
        value = self.assert_blocked("control", "UNKNOWN_SCHEMA_OBJECTS")
        self.assertNotIn("PRIVATE", json.dumps(value))

    def test_check_constraint_drift_is_blocked(self):
        self.create("legacy", "legacy.runs")
        group = catalogue()["groups"]["legacy.outbox"]
        with database(self.path("legacy")) as con:
            sql = group["ddl"][0].replace("status TEXT NOT NULL", "status TEXT NOT NULL CHECK(status != 'PRIVATE-STATUS')")
            self.assertNotEqual(sql, group["ddl"][0])
            con.execute(sql)
        value = self.assert_blocked("legacy", "STRUCTURAL_DRIFT")
        self.assertNotIn("PRIVATE-STATUS", json.dumps(value))

    def test_column_type_default_and_foreign_key_drift_are_blocked(self):
        for replacement in ("body INTEGER", "body TEXT DEFAULT 'PRIVATE-DEFAULT'", "body TEXT REFERENCES profiles(id)"):
            with self.subTest(replacement=replacement):
                path = self.path("control")
                if path.exists():
                    path.unlink()
                with database(path) as con:
                    for sql in catalogue()["groups"]["control.base"]["ddl"]:
                        con.execute(sql.replace("body TEXT", replacement))
                self.assert_blocked("control", "STRUCTURAL_DRIFT")

    def test_changed_index_definition_is_blocked(self):
        self.create("control", "control.base")
        with database(self.path("control")) as con:
            con.execute("DROP INDEX task_events_lookup")
            con.execute("CREATE UNIQUE INDEX task_events_lookup ON task_events(seq,task_id)")
        self.assert_blocked("control", "STRUCTURAL_DRIFT")

    def test_optional_memory_absent_is_not_initialized(self):
        self.create("control", "control.base")
        value = self.plan("control")
        self.assertEqual(value["state"], "current")
        feature = next(f for f in value["databases"][0]["features"] if f["name"] == "control.memory")
        self.assertEqual(feature["state"], "not_initialized")

    def test_partial_optional_memory_blocks(self):
        self.create("control", "control.base", "control.memory")
        with database(self.path("control")) as con:
            con.execute("DROP TABLE memory_owners")
        self.assert_blocked("control", "INCOMPLETE_FEATURE_GROUP")

    def test_fts_like_unknown_table_not_ignored(self):
        self.create("knowledge", "knowledge.core")
        with database(self.path("knowledge")) as con:
            con.execute("CREATE TABLE chunk_fts_private(value TEXT)")
        self.assert_blocked("knowledge", "UNKNOWN_SCHEMA_OBJECTS")

    def test_live_wal_latest_schema_seen_without_touching_main_wal_or_shm(self):
        self.create("control", "control.base")
        con = sqlite3.connect(self.path("control"))
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA wal_autocheckpoint=0")
            execute_group(con, catalogue()["groups"]["control.memory"])
            con.commit()
            before = self.files()
            self.assertTrue(self.path("control").with_name("control.sqlite3-wal").exists())
            value = self.plan("control")
            self.assertEqual(value["state"], "current", value)
            feature = next(f for f in value["databases"][0]["features"] if f["name"] == "control.memory")
            self.assertEqual(feature["state"], "current")
            self.assertEqual(self.files(), before)
        finally:
            con.close()

    def test_copy_race_blocks_instead_of_planning_stale_data(self):
        self.old_authorizations()
        original = shutil.copyfile
        def racing(source, target, *args, **kwargs):
            result = original(source, target, *args, **kwargs)
            if Path(source) == self.path("legacy"):
                with database(self.path("legacy")) as con:
                    con.execute("UPDATE dataset_authorizations SET note='changed'")
            return result
        with patch.object(sp.shutil, "copyfile", side_effect=racing):
            value = self.plan("legacy")
        self.assertEqual(value["databases"][0]["issues"][0]["code"], "SCHEMA_SOURCE_CHANGED")

    def test_failure_rolls_back_private_ddl_and_preserves_original(self):
        self.old_authorizations()
        before = self.files()
        first = self.plan("legacy")
        original = sp.snapshot
        rolled_back = []
        class FailingConnection:
            def __init__(self, con):
                self.con = con
            def execute(self, sql, *args):
                if sql.startswith("UPDATE dataset_authorizations"):
                    raise sqlite3.OperationalError("PRIVATE-FAILURE")
                return self.con.execute(sql, *args)
            def rollback(self):
                self.con.rollback()
                rolled_back.append(True)
                if "replay_enabled" in [r[1] for r in self.con.execute("PRAGMA table_info(dataset_authorizations)")]:
                    raise AssertionError("DDL was not rolled back")
        @contextmanager
        def failing(*args):
            with original(*args) as (con, source_id):
                yield FailingConnection(con), source_id
        with patch.object(sp, "snapshot", side_effect=failing):
            self.code("SCHEMA_DATABASE", self.plan, "legacy", rehearse=True, expected_plan=first["plan_id"])
        self.assertEqual(rolled_back, [True])
        self.assertEqual(self.files(), before)

    def test_corrupt_database_does_not_hide_other_store(self):
        self.create("control", "control.base")
        self.path("mail").write_bytes(b"PRIVATE-CORRUPT")
        value = self.plan()
        self.assertEqual(value["state"], "blocked")
        self.assertEqual(next(d for d in value["databases"] if d["store"] == "control")["state"], "current")
        self.assertNotIn("PRIVATE-CORRUPT", json.dumps(value))

    def test_rollback_journal_is_not_recovered(self):
        self.create("control", "control.base")
        self.path("control").with_name("control.sqlite3-journal").write_bytes(b"PRIVATE-JOURNAL")
        self.assert_blocked("control", "SCHEMA_JOURNAL")

    def test_orphan_wal_is_not_treated_as_uninitialized(self):
        self.app.mkdir()
        self.path("control").with_name("control.sqlite3-wal").write_bytes(b"PRIVATE-ORPHAN")
        self.assert_blocked("control", "SCHEMA_WAL")

    def test_file_and_metadata_limits_are_enforced(self):
        self.create("control", "control.base")
        with patch.object(sp.inv, "MAX_FILE", 32):
            self.assert_blocked("control", "SCHEMA_LIMIT")
        with database(self.path("control")) as con:
            for index in range(260):
                con.execute(f"CREATE TABLE extra_{index}(v)")
        self.assert_blocked("control", "SCHEMA_LIMIT")

    def test_link_is_rejected_without_reading_target(self):
        self.create("control", "control.base")
        with patch.object(sp.inv, "linked", side_effect=lambda p: p == self.path("control")):
            self.assert_blocked("control", "SCHEMA_PATH")

    def test_cli_current_pending_blocked_and_rehearsal_exit_codes(self):
        def cli(*args):
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--config", str(self.config), "db", *args, "--store", "mail", "--crawler-workspace", str(self.crawler)])
            return code, json.loads(output.getvalue())
        self.assertEqual(cli("status")[0], 0)
        self.create("mail", "mail.core")
        code, value = cli("plan")
        self.assertEqual(code, 1)
        self.assertEqual(cli("plan", "--rehearse", "--expected-plan", value["plan_id"])[0], 0)
        with database(self.path("mail")) as con:
            con.execute("PRAGMA user_version=9")
        self.assertEqual(cli("status")[0], 2)

    def test_catalogue_matches_current_sources(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(root / "scripts/build_schema_catalog.py"), "--check"], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
