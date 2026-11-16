"""Offline forecast lifecycle, point-in-time gates and immutable evidence."""
import copy
import io
import json
import socket
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from stock_predict_mailer.agent_service.config import load
from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.agent_service.forecast_archive import ForecastArchive
from stock_predict_mailer.agent_service.input_evidence import canonical
from stock_predict_mailer.agent_service.mail import MailService
from stock_predict_mailer.cli import main
from stock_predict_mailer.core import Config
from stock_predict_mailer.delivery import process_lock
from stock_predict_mailer.operations import backup

UTC = timezone.utc


class ForecastTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.workspace = self.base / "app"
        self.archive = ForecastArchive(self.workspace)
        self.generated = datetime(2026, 11, 16, 9, tzinfo=UTC)
        self.registered = self.generated + timedelta(minutes=1)
        self.target = self.generated + timedelta(hours=1)
        self.end = self.target + timedelta(minutes=10)
        self.p = {"schema_version": "1", "prediction_id": "fixture-v1", "subject": "DEMO.SZ", "generated_at": self.generated.isoformat(),
                  "valid_until": (self.generated + timedelta(minutes=30)).isoformat(), "horizon": {"value": 1, "unit": "hours"},
                  "model_version": "fixture-model", "synthetic": True, "direction": "up", "value": 110, "value_unit": "CNY"}
        self.d = {"schema_version": "1", "target_at": self.target.isoformat(), "timezone": "Asia/Shanghai", "metric": "close_unadjusted",
                  "unit": "CNY", "flat_tolerance": 0.1,
                  "reference": {"value": 100, "source": "synthetic-reference", "synthetic": True,
                                "observed_at": (self.generated - timedelta(hours=1)).isoformat(), "available_at": self.generated.isoformat()}}
        self.actual = {"schema_version": "1", "subject": "DEMO.SZ", "metric": "close_unadjusted", "unit": "CNY", "value": 112,
                       "observed_at": self.target.isoformat(), "available_at": (self.target + timedelta(minutes=5)).isoformat(),
                       "source": "synthetic-observation", "synthetic": True}

    def register(self):
        return self.archive.register(self.p, self.d, now=self.registered)["record"]

    def code(self, expected, function, *args, **kwargs):
        with self.assertRaises(ServiceError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected)

    def files(self):
        return {str(p): p.read_bytes() for p in self.workspace.rglob("*") if p.is_file()}

    def test_full_lifecycle_keeps_reception_expiry_separate_from_maturity(self):
        r = self.register()
        key = r["forecast_id"]
        self.assertEqual(self.archive.show(key, now=self.registered)["state"], "pending")
        self.assertEqual(self.archive.show(key, now=self.end)["state"], "due")
        result = self.archive.evaluate(key, self.actual, now=self.end)
        self.assertTrue(result["persisted"])
        self.assertEqual(result["evaluation"]["metrics"], {"unit": "CNY", "change_from_reference": 12,
                         "realized_direction": "up", "direction_correct": True, "signed_error": 2, "absolute_error": 2})
        self.assertEqual(self.archive.show(key, now=self.end)["state"], "evaluated")
        self.assertEqual(self.archive.listing(now=self.end)["records"][0]["state"], "evaluated")

    def test_registration_is_idempotent_and_input_is_not_modified(self):
        before = copy.deepcopy((self.p, self.d))
        first = self.register()
        result = self.archive.register(self.p, self.d, now=self.registered + timedelta(seconds=30))
        self.assertFalse(result["created"])
        self.assertEqual(result["record"], first)
        self.assertEqual((self.p, self.d), before)

    def test_changed_prediction_or_definition_cannot_replace_same_identity(self):
        self.register()
        before = self.files()
        for p, d in (({**self.p, "value": 109}, self.d), (self.p, {**self.d, "flat_tolerance": 20})):
            self.code("FORECAST_CONFLICT", self.archive.register, p, d, now=self.registered)
        self.assertEqual(self.files(), before)

    def test_expired_prediction_cannot_be_backfilled(self):
        self.code("STALE_RESULT", self.archive.register, self.p, self.d, now=self.end)
        self.assertFalse(self.workspace.exists())

    def test_elapsed_target_cannot_be_registered_even_if_prediction_is_valid(self):
        self.p["valid_until"] = (self.end + timedelta(days=1)).isoformat()
        self.code("INVALID_INPUT", self.archive.register, self.p, self.d, now=self.end)
        self.assertFalse(self.workspace.exists())

    def test_reference_must_have_been_available_when_prediction_was_generated(self):
        for field in ("observed_at", "available_at"):
            raw = copy.deepcopy(self.d)
            raw["reference"][field] = self.registered.isoformat()
            self.code("INVALID_INPUT", self.archive.register, self.p, raw, now=self.registered)
        self.assertFalse(self.workspace.exists())

    def test_definition_rejects_unknown_fields_units_timezone_and_negative_threshold(self):
        for changes in ({"timezone": "unknown/zone"}, {"unit": "USD"}, {"flat_tolerance": -1}, {"arbitrary_sql": "PRIVATE"}):
            self.code("INVALID_INPUT", self.archive.register, self.p, {**self.d, **changes}, now=self.registered)

    def test_hours_require_exact_target(self):
        self.d["target_at"] = (self.target + timedelta(seconds=1)).isoformat()
        self.code("INVALID_INPUT", self.archive.register, self.p, self.d, now=self.registered)

    def test_calendar_day_horizon_respects_declared_timezone_across_dst(self):
        generated = datetime(2026, 3, 7, 15, tzinfo=UTC)  # New York 10:00, before DST.
        self.p.update(generated_at=generated.isoformat(), valid_until=(generated + timedelta(hours=2)).isoformat(), horizon={"value": 1, "unit": "calendar_days"})
        self.d.update(target_at=(generated + timedelta(hours=23)).isoformat(), timezone="America/New_York")
        self.d["reference"].update(observed_at=generated.isoformat(), available_at=generated.isoformat())
        record = self.archive.register(self.p, self.d, now=generated + timedelta(minutes=1))["record"]
        self.assertEqual(record["definition"]["target_at"], (generated + timedelta(hours=23)).isoformat())

    def trading(self):
        self.p["horizon"] = {"value": 5, "unit": "trading_days"}
        self.d["target_at"] = "2026-11-23T07:00:00+00:00"
        self.d["calendar"] = {"source": "declared-fixture-calendar", "sessions": ["2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-23"]}

    def test_trading_days_require_explicit_declared_calendar(self):
        self.trading()
        missing = {k: v for k, v in self.d.items() if k != "calendar"}
        self.code("INVALID_INPUT", self.archive.register, self.p, missing, now=self.registered)
        self.assertEqual(self.register()["definition"]["calendar"]["sessions"][-1], "2026-11-23")

    def test_calendar_cannot_have_duplicates_wrong_count_or_wrong_target(self):
        self.trading()
        for changes in (["2026-11-17"] * 5, ["2026-11-17"], ["2026-11-18", "2026-11-17", "2026-11-19", "2026-11-20", "2026-11-23"]):
            raw = copy.deepcopy(self.d)
            raw["calendar"]["sessions"] = changes
            self.code("INVALID_INPUT", self.archive.register, self.p, raw, now=self.registered)
        self.d["target_at"] = "2026-11-21T07:00:00+00:00"
        self.code("INVALID_INPUT", self.archive.register, self.p, self.d, now=self.registered)

    def test_not_due_and_missing_or_unavailable_observations_do_not_write(self):
        key = self.register()["forecast_id"]
        before = self.files()
        result = self.archive.evaluate(key, self.actual, now=self.registered)
        self.assertEqual(result["state"], "not_due")
        self.assertNotIn("evaluation", result)
        self.assertEqual(self.archive.evaluate(key, now=self.end)["state"], "awaiting_observation")
        self.assertEqual(self.archive.evaluate(key, self.actual, now=self.target)["state"], "awaiting_observation")
        self.assertEqual(self.files(), before)

    def test_observation_subject_metric_unit_synthetic_and_target_must_match(self):
        key = self.register()["forecast_id"]
        for changes in ({"subject": "OTHER.SZ"}, {"metric": "adjusted_close"}, {"unit": "USD"}, {"synthetic": False},
                        {"observed_at": (self.target + timedelta(days=1)).isoformat()}, {"available_at": self.generated.isoformat()}):
            self.code("INVALID_INPUT", self.archive.evaluate, key, {**self.actual, **changes}, now=self.end)

    def test_direction_only_and_value_only_are_scored_without_fabricating_missing_metrics(self):
        del self.p["value"], self.p["value_unit"]
        key = self.register()["forecast_id"]
        metrics = self.archive.evaluate(key, self.actual, now=self.end)["evaluation"]["metrics"]
        self.assertNotIn("absolute_error", metrics)
        self.p.update(prediction_id="second", value=112, value_unit="CNY")
        del self.p["direction"]
        key = self.register()["forecast_id"]
        metrics = self.archive.evaluate(key, self.actual, now=self.end)["evaluation"]["metrics"]
        self.assertIsNone(metrics["direction_correct"])
        self.assertEqual(metrics["absolute_error"], 0)

    def test_flat_threshold_is_precommitted_and_direction_can_be_wrong(self):
        self.p["direction"] = "flat"
        self.d["flat_tolerance"] = 2
        key = self.register()["forecast_id"]
        value = self.archive.evaluate(key, {**self.actual, "value": 102}, now=self.end)["evaluation"]
        self.assertEqual(value["metrics"]["realized_direction"], "flat")
        value = self.archive.evaluate(key, {**self.actual, "value": 97}, now=self.end)["evaluation"]
        self.assertFalse(value["metrics"]["direction_correct"])
        self.assertEqual(value["metrics"]["realized_direction"], "down")
        self.p.update(prediction_id="decimal-boundary", value=0.4)
        self.d["reference"]["value"] = 0.1
        self.d["flat_tolerance"] = 0.3
        key = self.register()["forecast_id"]
        value = self.archive.evaluate(key, {**self.actual, "value": 0.4}, now=self.end)["evaluation"]
        self.assertEqual(value["metrics"]["realized_direction"], "flat")
        self.assertEqual(value["metrics"]["change_from_reference"], 0.3)

    def test_repeated_observation_reuses_first_receipt_and_revision_is_append_only(self):
        key = self.register()["forecast_id"]
        first = self.archive.evaluate(key, self.actual, now=self.end)
        second = self.archive.evaluate(key, self.actual, now=self.end + timedelta(hours=1))
        self.assertEqual(first["evaluation"], second["evaluation"])
        self.archive.evaluate(key, {**self.actual, "value": 111, "source": "corrected-source"}, now=self.end + timedelta(hours=1))
        self.assertEqual(len(self.archive.show(key, now=self.end + timedelta(hours=1))["evaluations"]), 2)
        self.assertEqual(len(self.archive.show(key, now=self.end)["evaluations"]), 1)

    def test_dry_run_and_historical_queries_are_readonly(self):
        key = self.register()["forecast_id"]
        before = self.files()
        result = self.archive.evaluate(key, self.actual, now=self.end, dry_run=True)
        self.assertFalse(result["persisted"])
        self.archive.show(key, now=self.end)
        self.archive.listing(now=self.end)
        self.assertEqual(self.files(), before)

    def test_historical_cutoff_cannot_reveal_later_registration_or_evaluation(self):
        key = self.register()["forecast_id"]
        earlier = (self.registered - timedelta(seconds=1)).isoformat()
        self.code("FORECAST_NOT_YET_REGISTERED", self.archive.show, key, as_of=earlier, now=self.end)
        self.assertEqual(self.archive.listing(as_of=earlier, now=self.end)["total"], 0)
        self.archive.evaluate(key, self.actual, now=self.end)
        self.assertEqual(self.archive.show(key, as_of=self.target.isoformat(), now=self.end)["state"], "due")
        self.code("INVALID_INPUT", self.archive.listing, as_of=(self.end + timedelta(seconds=1)).isoformat(), now=self.end)

    def test_missing_workspace_queries_never_initialize(self):
        self.assertEqual(self.archive.listing(now=self.registered)["total"], 0)
        self.code("FORECAST_NOT_FOUND", self.archive.show, "a" * 64, now=self.end)
        self.assertFalse(self.workspace.exists())

    def test_prediction_and_reference_synthetic_flags_cannot_be_mixed(self):
        self.d["reference"]["synthetic"] = False
        self.code("INVALID_INPUT", self.archive.register, self.p, self.d, now=self.registered)

    def test_overflow_and_nonfinite_or_boolean_values_are_rejected(self):
        key = self.register()["forecast_id"]
        for value in (True, float("inf"), float("nan")):
            self.code("INVALID_INPUT", self.archive.evaluate, key, {**self.actual, "value": value}, now=self.end)
        self.p.update(prediction_id="large", value=-1e308)
        self.d["reference"]["value"] = -1e308
        key = self.register()["forecast_id"]
        self.code("INVALID_INPUT", self.archive.evaluate, key, {**self.actual, "value": 1e308}, now=self.end)

    def test_pagination_can_reach_older_records(self):
        first = self.register()["forecast_id"]
        self.p["prediction_id"] = "later"
        self.archive.register(self.p, self.d, now=self.registered + timedelta(seconds=1))
        page = self.archive.listing(now=self.end, limit=1)
        self.assertEqual(page["next_offset"], 1)
        self.assertEqual(self.archive.listing(now=self.end, offset=1, limit=1)["records"][0]["record"]["forecast_id"], first)
        for kwargs in ({"limit": True}, {"limit": 101}, {"offset": -1}):
            self.code("INVALID_INPUT", self.archive.listing, now=self.end, **kwargs)

    def test_invalid_ids_and_unknown_json_names_are_rejected(self):
        for key in ("../outside", "", "x" * 64, None):
            self.code("INVALID_INPUT", self.archive.show, key, now=self.end)
        self.register()
        (self.workspace / "forecasts/records/unknown.json").write_text("{}", encoding="utf-8")
        self.code("FORECAST_PATH", self.archive.listing, now=self.end)

    def test_corrupt_record_and_metrics_are_detected_even_after_resigning_wrapper(self):
        from stock_predict_mailer.agent_service.forecast_archive import seal
        key = self.register()["forecast_id"]
        record_path = self.workspace / "forecasts/records" / (key + ".json")
        original = record_path.read_bytes()
        value = json.loads(original)
        value["prediction"]["value"] = 999
        record_path.write_bytes(canonical(seal({k: v for k, v in value.items() if k != "integrity_id"})))
        self.code("FORECAST_CORRUPT", self.archive.show, key, now=self.end)
        record_path.write_bytes(original)
        receipt = self.archive.evaluate(key, self.actual, now=self.end)["evaluation"]
        receipt["metrics"]["absolute_error"] = 0
        path = self.workspace / "forecasts/evaluations" / key / (receipt["evaluation_id"] + ".json")
        path.write_bytes(canonical(seal({k: v for k, v in receipt.items() if k != "integrity_id"})))
        self.code("FORECAST_CORRUPT", self.archive.show, key, now=self.end)

    def test_file_read_and_archive_count_limits(self):
        key = self.register()["forecast_id"]
        from stock_predict_mailer.agent_service import forecast_archive as mod
        with patch.object(mod, "MAX_FILE", 10):
            self.code("FORECAST_LIMIT", self.archive.show, key, now=self.end)
        with patch.object(mod, "MAX_READ", 10):
            self.code("FORECAST_LIMIT", self.archive.show, key, now=self.end)
        self.p["prediction_id"] = "extra"
        with patch.object(mod, "MAX_RECORDS", 1):
            self.code("FORECAST_LIMIT", self.register)

    def test_assessment_revision_limit_preserves_existing_receipts(self):
        from stock_predict_mailer.agent_service import forecast_archive as mod
        key = self.register()["forecast_id"]
        self.archive.evaluate(key, self.actual, now=self.end)
        before = self.files()
        with patch.object(mod, "MAX_EVALUATIONS", 1):
            self.code("FORECAST_LIMIT", self.archive.evaluate, key, {**self.actual, "value": 113}, now=self.end)
        self.assertEqual(self.files(), before)

    def test_failed_atomic_publish_does_not_leave_partial_record(self):
        with patch("stock_predict_mailer.agent_service.forecast_archive.os.link", side_effect=OSError("PRIVATE")):
            self.code("FORECAST_PUBLISH", self.register)
        self.assertEqual(list((self.workspace / "forecasts/records").iterdir()), [])

    def test_existing_business_lock_blocks_archive_write(self):
        with process_lock(Config(self.workspace)):
            self.code("FORECAST_BUSY", self.register)
        self.assertFalse((self.workspace / "forecasts").exists())

    def test_symlinked_archive_and_lock_never_write_outside_workspace(self):
        outside = self.base / "outside"
        outside.mkdir()
        self.workspace.mkdir()
        link = self.workspace / "forecasts"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlink privilege unavailable")
        self.code("FORECAST_PATH", self.register)
        self.assertEqual(list(outside.iterdir()), [])
        link.unlink()
        lock = self.workspace / "pipeline.lock"
        lock.unlink()
        target = outside / "lock"
        target.write_bytes(b"")
        lock.symlink_to(target)
        self.code("FORECAST_PATH", self.register)
        self.assertEqual(target.read_bytes(), b"")

    def test_parallel_registration_cannot_overwrite_first_definition(self):
        def submit(_):
            try:
                return ForecastArchive(self.workspace).register(self.p, self.d, now=self.registered)
            except ServiceError as exc:
                self.assertEqual(exc.code, "FORECAST_BUSY")
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = [v for v in pool.map(submit, range(8)) if v]
        self.assertEqual(sum(v["created"] for v in values), 1)
        self.assertEqual(self.archive.listing(now=self.end)["total"], 1)

    def test_cli_register_list_show_evaluate_without_constructing_mail(self):
        self.config = self.base / "config.toml"
        self.config.write_text('workspace="app"\n[mail]\ntransport="file"\nsender="fixture@example.invalid"\n', encoding="utf-8")
        def file(name, value):
            path = self.base / name
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            return str(path)
        p, d, actual = file("prediction.json", self.p), file("definition.json", self.d), file("observation.json", self.actual)
        def command(*args, now):
            output = io.StringIO()
            with patch("stock_predict_mailer.agent_service.forecast_archive.utcnow", return_value=now), redirect_stdout(output):
                code = main(["--config", str(self.config), "forecast", *args])
            return code, json.loads(output.getvalue())
        with patch.object(MailService, "__init__", side_effect=AssertionError("no mail construction")):
            code, value = command("register", "--prediction", p, "--definition", d, now=self.registered)
            self.assertEqual(code, 0)
            key = value["record"]["forecast_id"]
            self.assertEqual(command("evaluate", key, now=self.registered)[0], 1)
            self.assertEqual(command("evaluate", key, now=self.end)[0], 1)
            self.assertEqual(command("evaluate", key, "--observation", actual, now=self.end)[0], 0)
            self.assertEqual(command("show", key, now=self.end)[1]["state"], "evaluated")
            self.assertEqual(command("list", "--offset", "0", now=self.end)[1]["total"], 1)
            self.assertEqual(command("show", "invalid", now=self.end)[0], 2)

    def test_encrypted_backup_and_isolated_restore_preserve_forecast_evidence(self):
        from cryptography.fernet import Fernet
        key = self.register()["forecast_id"]
        self.archive.evaluate(key, self.actual, now=self.end)
        before = self.files()
        config = self.base / "config.toml"
        config.write_text('workspace="app"\n[mail]\ntransport="file"\nsender="fixture@example.invalid"\n', encoding="utf-8")
        cfg = load(config)
        crawler = self.base / "crawler"
        encrypted = self.base / "evidence.spmbak"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with patch.dict("os.environ", {"FORECAST_TEST_BACKUP_KEY": Fernet.generate_key().decode()}):
            plan = backup.plan(cfg, config, crawler_workspace=crawler, port=port)
            self.assertTrue(plan["ready"], plan)
            backup.create(cfg, config, encrypted, plan["plan_id"], crawler_workspace=crawler, port=port, key_env="FORECAST_TEST_BACKUP_KEY")
            target = self.base / "restored"
            backup.restore(encrypted, target, key_env="FORECAST_TEST_BACKUP_KEY")
        after = self.files()
        self.assertTrue(all(after.get(path) == raw for path, raw in before.items()))
        restored = ForecastArchive(target / "app")
        self.assertEqual(restored.show(key, now=self.end)["state"], "evaluated")
        for path, raw in before.items():
            if "forecasts" in Path(path).parts:
                self.assertEqual((target / "app" / Path(path).relative_to(self.workspace)).read_bytes(), raw)
