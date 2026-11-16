"""Migration prerequisites use synthetic encrypted backups and never write sources."""
import io
import json
import os
import socket
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from stock_predict_mailer.agent_service.config import load
from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.cli import main
from stock_predict_mailer.operations import backup
from stock_predict_mailer.operations import migration_preflight as mp
from stock_predict_mailer.operations import schema_planning as schema
from stock_predict_mailer.operations.schema_models import catalogue, execute_group


class PreflightTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.app, self.crawler = self.root / "app", self.root / "crawler"
        self.app.mkdir()
        self.crawler.mkdir()
        self.config = self.root / "agent.toml"
        self.config.write_text('workspace="app"\n[mail]\ntransport="file"\nsender="preview@example.invalid"\n', encoding="utf-8")
        self.cfg = load(self.config)
        self.path = self.app / "agent-mail.sqlite3"
        con = sqlite3.connect(self.path)
        try:
            execute_group(con, catalogue()["groups"]["mail.core"])
            con.commit()
        finally:
            con.close()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        env = patch.dict(os.environ, {"PREFLIGHT_TEST_KEY": Fernet.generate_key().decode()})
        env.start()
        self.addCleanup(env.stop)
        self.archive = self.root / "test.spmbak"
        planned = backup.plan(self.cfg, self.config, crawler_workspace=self.crawler, port=self.port)
        backup.create(self.cfg, self.config, self.archive, planned["plan_id"], crawler_workspace=self.crawler,
                      port=self.port, key_env="PREFLIGHT_TEST_KEY")
        self.plan_id = schema.plan(self.cfg, crawler_workspace=self.crawler)["plan_id"]

    def check(self, **kwargs):
        return mp.check(self.cfg, self.config, kwargs.pop("archive", self.archive), kwargs.pop("expected_plan", self.plan_id),
                        crawler_workspace=kwargs.pop("crawler_workspace", self.crawler), port=kwargs.pop("port", self.port),
                        key_env="PREFLIGHT_TEST_KEY", **kwargs)

    def files(self):
        return {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def blocked(self, code, **kwargs):
        before = self.files()
        result = self.check(**kwargs)
        self.assertFalse(result["ready"], result)
        self.assertIn(code, [b["code"] for b in result["blockers"]])
        self.assertEqual(self.files(), before)
        return result

    def test_matching_backup_is_readonly_deterministic_and_not_apply(self):
        before = self.files()
        first, second = self.check(), self.check()
        self.assertTrue(first["ready"], first)
        self.assertEqual(first["preflight_id"], second["preflight_id"])
        self.assertEqual(first["changes"], 1)
        self.assertFalse(first["ready_for_apply"])
        self.assertEqual(first["source_writes"], 0)
        self.assertEqual(self.files(), before)

    def test_valid_backup_from_different_source_content_is_rejected(self):
        (self.app / "note.txt").write_text("PRIVATE-CONTENT", encoding="utf-8")
        result = self.blocked("MIGRATION_BACKUP_MISMATCH")
        self.assertTrue(result["backup_verified"])
        self.assertNotIn("PRIVATE-CONTENT", json.dumps(result))

    def test_configuration_content_changes_invalidate_backup(self):
        self.config.write_text(self.config.read_text() + "\n# changed\n", encoding="utf-8")
        self.blocked("MIGRATION_BACKUP_MISMATCH")

    def test_other_workspace_or_port_cannot_reuse_backup(self):
        other = self.root / "other-crawler"
        other.mkdir()
        with patch.object(mp.inv, "quiescence", return_value=[]):
            updated = schema.plan(self.cfg, crawler_workspace=other)["plan_id"]
            self.blocked("MIGRATION_BACKUP_MISMATCH", crawler_workspace=other, expected_plan=updated)
            self.blocked("MIGRATION_BACKUP_MISMATCH", port=self.port % 65535 + 1)

    def test_stale_schema_plan_skips_backup_decryption(self):
        with patch.object(backup, "verify", side_effect=AssertionError("must not decrypt")):
            self.blocked("SCHEMA_PLAN_CHANGED", expected_plan="0" * 64)

    def test_unknown_schema_is_blocked(self):
        con = sqlite3.connect(self.path)
        con.execute("PRAGMA user_version=42")
        con.close()
        plan = schema.plan(self.cfg, crawler_workspace=self.crawler)
        self.blocked("SCHEMA_BLOCKED", expected_plan=plan["plan_id"])

    def test_active_writer_does_not_decrypt_or_stop_services(self):
        with patch.object(mp.inv, "quiescence", return_value=[{"code": "BACKUP_COMPONENT_ACTIVE", "component": "console"}]), patch.object(backup, "verify", side_effect=AssertionError("no decrypt")):
            self.blocked("BACKUP_COMPONENT_ACTIVE")

    def test_wrong_key_and_tampering_do_not_expose_plaintext(self):
        with patch.dict(os.environ, {"PREFLIGHT_TEST_KEY": Fernet.generate_key().decode()}):
            result = self.check()
        self.assertFalse(result["ready"])
        self.assertFalse(result["backup_verified"])
        self.archive.write_bytes(b"PRIVATE-TAMPERED-BACKUP")
        self.assertNotIn("PRIVATE-TAMPERED", json.dumps(self.check()))

    def test_source_changes_during_verification_are_rejected(self):
        original = backup.verify
        def race(*args, **kwargs):
            value = original(*args, **kwargs)
            (self.app / "raced.txt").write_text("new", encoding="utf-8")
            return value
        with patch.object(backup, "verify", side_effect=race):
            value = self.check()
        self.assertIn("MIGRATION_SOURCE_CHANGED", [b["code"] for b in value["blockers"]])

    def test_writer_starting_after_verification_is_rejected(self):
        with patch.object(mp.inv, "quiescence", side_effect=[[], [{"code": "BACKUP_WRITER_BUSY"}]]):
            self.blocked("BACKUP_WRITER_BUSY")

    def test_invalid_plan_reference_is_an_input_error(self):
        for value in (None, True, "", "not-a-hash"):
            with self.subTest(value=value), self.assertRaises(ServiceError) as caught:
                self.check(expected_plan=value)
            self.assertEqual(caught.exception.code, "INVALID_INPUT")

    def test_missing_archive_is_reported_without_initializing_anything(self):
        result = self.check(archive=self.root / "missing.spmbak")
        self.assertFalse(result["ready"])
        self.assertFalse((self.root / "missing.spmbak").exists())

    def test_cli_exit_codes_and_json_contract(self):
        args = ["--config", str(self.config), "db", "preflight", "--crawler-workspace", str(self.crawler),
                "--archive", str(self.archive), "--expected-plan", self.plan_id, "--port", str(self.port), "--key-env", "PREFLIGHT_TEST_KEY"]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args), 0)
        self.assertEqual(json.loads(output.getvalue())["mode"], "read_only_migration_preflight")
        (self.app / "new.txt").write_text("new", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 2)
