"""Opt-in forecast binding across analysis, CLI, task admission and frozen mail."""
import asyncio
import io
import json
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import test_control
from stock_predict_mailer.agent_service.analysis import AnalysisAgent, identity, validate_analysis
from stock_predict_mailer.agent_service.contracts import ServiceError, instant, prediction, utcnow
from stock_predict_mailer.agent_service.forecast_archive import ForecastArchive, seal
from stock_predict_mailer.agent_service.forecast_contracts import forecast_id
from stock_predict_mailer.agent_service.mail import MailService
from stock_predict_mailer.agent_service.reporting import render
from stock_predict_mailer.cli import main
from stock_predict_mailer.control.orchestrator import Orchestrator
from stock_predict_mailer.core import Config
from stock_predict_mailer.delivery import process_lock


def inputs():
    generated = utcnow() - timedelta(minutes=1)
    p = {"schema_version": "1", "prediction_id": "task-fixture", "subject": "DEMO.SZ",
         "generated_at": generated.isoformat(), "valid_until": (generated + timedelta(minutes=30)).isoformat(),
         "horizon": {"value": 1, "unit": "hours"}, "model_version": "offline-v1", "synthetic": True,
         "direction": "up", "value": 110, "value_unit": "CNY"}
    d = {"schema_version": "1", "target_at": (generated + timedelta(hours=1)).isoformat(), "timezone": "Asia/Shanghai",
         "metric": "close_unadjusted", "unit": "CNY", "flat_tolerance": 0.1,
         "reference": {"value": 100, "source": "synthetic-reference", "synthetic": True,
                       "observed_at": generated.isoformat(), "available_at": generated.isoformat()}}
    return p, d


def completed(task):
    if task["status"]["state"] != "completed":
        raise AssertionError(task)
    return task["artifacts"][0]["parts"][0]["data"]


def resign(analysis):
    analysis["analysis_id"] = identity({k: v for k, v in analysis.items() if k != "analysis_id"})


class BindingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.p, self.d = inputs()
        self.record = ForecastArchive(self.root).register(self.p, self.d)["record"]

    def analysis(self):
        return AnalysisAgent().analyze(self.p, forecast_record=self.record)

    def test_binding_is_exact_self_contained_and_included_in_identity(self):
        analysis = self.analysis()
        self.assertEqual(validate_analysis(analysis), analysis)
        self.assertNotIn("prediction", analysis["forecast_evidence"])
        self.assertEqual({**analysis["forecast_evidence"], "prediction": analysis["prediction"]}, self.record)
        self.assertNotEqual(AnalysisAgent().analyze(self.p)["analysis_id"], analysis["analysis_id"])
        text, html = render(analysis)
        for value in (self.record["forecast_id"], self.record["content_id"], self.d["target_at"], self.d["metric"]):
            self.assertIn(value, text)
            self.assertIn(value, html)

    def test_rehashing_report_cannot_rebind_another_prediction(self):
        for changes in ({"direction": "down"}, {"value": 111}, {"prediction_id": "other"}, {"metrics": {"score": 1}}):
            with self.subTest(changes=changes):
                analysis = self.analysis()
                analysis["prediction"].update(changes)
                resign(analysis)
                with self.assertRaises(ServiceError):
                    validate_analysis(analysis)

    def test_definition_and_registration_tampering_fail_after_report_rehash(self):
        for key, value in (("definition", {**self.record["definition"], "flat_tolerance": 0.2}),
                           ("registered_at", self.p["generated_at"]), ("forecast_id", "a" * 64),
                           ("content_id", "b" * 64), ("integrity_id", "c" * 64)):
            with self.subTest(key=key):
                analysis = self.analysis()
                analysis["forecast_evidence"][key] = value
                resign(analysis)
                with self.assertRaises(ServiceError):
                    validate_analysis(analysis)

    def test_analysis_rejects_mismatched_record_before_provider(self):
        with patch("stock_predict_mailer.agent_service.analysis.http_json") as provider:
            with self.assertRaises(ServiceError):
                AnalysisAgent({"provider": "http", "url": "http://127.0.0.1:1"}).analyze(
                    {**self.p, "value": 111}, forecast_record=self.record)
        provider.assert_not_called()

    def test_future_registration_and_observation_fields_are_rejected(self):
        record = {k: v for k, v in self.record.items() if k != "integrity_id"}
        record["registered_at"] = (utcnow() + timedelta(minutes=1)).isoformat()
        with self.assertRaises(ServiceError):
            AnalysisAgent().analyze(self.p, forecast_record=seal(record))
        analysis = self.analysis()
        analysis["forecast_evidence"]["observation"] = {"value": 112}
        resign(analysis)
        with self.assertRaises(ServiceError):
            validate_analysis(analysis)

    def test_report_escapes_declared_sources_and_preserves_calendar(self):
        self.p["prediction_id"] = "calendar-fixture"
        self.p["horizon"] = {"value": 2, "unit": "trading_days"}
        day = instant(self.p["generated_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date()
        sessions = [(day + timedelta(days=i)).isoformat() for i in (1, 2)]
        self.d.update(target_at=sessions[-1] + "T15:00:00+08:00", calendar={"source": "<script>calendar</script>", "sessions": sessions})
        self.d["reference"]["source"] = "<script>reference</script>"
        record = ForecastArchive(self.root).register(self.p, self.d)["record"]
        text, html = render(AnalysisAgent().analyze(self.p, forecast_record=record))
        self.assertIn(", ".join(sessions), text)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;calendar", html)

    def test_frozen_mail_keeps_binding_without_archive_reads(self):
        analysis = self.analysis()
        mail = MailService(self.root, {"transport": "file", "sender": "research@example.invalid", "allow_synthetic": True})
        queued = mail.enqueue(analysis, "preview@example.invalid")
        archived = self.root / "forecasts" / "records" / (self.record["forecast_id"] + ".json")
        archived.unlink()
        self.assertEqual(mail.deliver(queued["id"])["status"], "simulated")
        stored = json.loads(mail.get(queued["id"])["analysis"])
        self.assertEqual(stored["forecast_evidence"], analysis["forecast_evidence"])
        msg = BytesParser(policy=policy.default).parsebytes((self.root / "sent" / (queued["id"] + ".eml")).read_bytes())
        self.assertIn(self.record["forecast_id"], msg.get_body(preferencelist=("plain",)).get_content())

    def test_mail_rejects_tampered_binding_before_queue_creation(self):
        analysis = self.analysis()
        analysis["forecast_evidence"]["content_id"] = "a" * 64
        resign(analysis)
        other = self.root / "empty"
        with self.assertRaises(ServiceError):
            MailService(other, {}).enqueue(analysis, "preview@example.invalid")
        self.assertFalse(other.exists())


class CLITaskTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.workspace = self.root / "app"
        self.p, self.d = inputs()
        self.prediction = self.root / "prediction.json"
        self.definition = self.root / "definition.json"
        self.prediction.write_text(json.dumps(self.p), encoding="utf-8")
        self.definition.write_text(json.dumps(self.d), encoding="utf-8")
        self.config = self.root / "config.toml"
        self.config.write_text('workspace = "app"\n[prediction]\nadapter = "file"\npath = "prediction.json"\n'
                               '[mail]\nallow_synthetic = true\n', encoding="utf-8")

    def run_cli(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["--config", str(self.config), "run", *args])
        return status, json.loads(output.getvalue())

    def opted(self, *args):
        return self.run_cli("--evaluation-definition", str(self.definition), *args)

    def test_opted_run_binds_report_and_mail_and_repeats_idempotently(self):
        status, output = self.opted("--send")
        self.assertEqual(status, 0, output)
        self.assertTrue(output["forecast"]["created"])
        analysis = json.loads((Path(output["report"]).parent / "analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(analysis["prediction"], prediction(self.p))
        self.assertEqual(analysis["forecast_evidence"]["forecast_id"], output["forecast"]["forecast_id"])
        self.assertEqual(output["mail"]["status"], "simulated")
        status, repeat = self.opted("--send")
        self.assertEqual(status, 0)
        self.assertFalse(repeat["forecast"]["created"])
        self.assertEqual(repeat["analysis_id"], output["analysis_id"])
        self.assertEqual(repeat["mail"]["id"], output["mail"]["id"])

    def test_default_run_preserves_analysis_and_initializes_no_archive(self):
        status, output = self.run_cli()
        self.assertEqual(status, 0)
        self.assertNotIn("forecast", output)
        self.assertFalse((self.workspace / "forecasts").exists())
        self.assertEqual(output["analysis_id"], AnalysisAgent().analyze(self.p)["analysis_id"])

    def test_invalid_definition_stops_context_analysis_and_mail(self):
        self.definition.write_text(json.dumps({**self.d, "unit": "USD"}), encoding="utf-8")
        with patch("stock_predict_mailer.cli.AnalysisAgent") as agent, patch.object(MailService, "enqueue") as enqueue:
            status, output = self.opted("--send")
        self.assertEqual((status, output["error"]["code"]), (2, "INVALID_INPUT"))
        agent.assert_not_called()
        enqueue.assert_not_called()
        self.assertFalse(self.workspace.exists())

    def test_conflict_stops_before_context_adapter(self):
        self.assertEqual(self.opted()[0], 0)
        self.definition.write_text(json.dumps({**self.d, "flat_tolerance": 0.5}), encoding="utf-8")
        from stock_predict_mailer.cli import adapter
        with patch("stock_predict_mailer.cli.adapter", wraps=adapter) as factory:
            status, output = self.opted("--send")
        self.assertEqual((status, output["error"]["code"]), (2, "FORECAST_CONFLICT"))
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(len(list((self.workspace / "analysis").iterdir())), 1)

    def test_bad_json_missing_file_and_size_limits_have_no_effects(self):
        for raw, code in ((b'{"x":1,"x":2}', "INVALID_INPUT"), (b"x" * (1024 * 1024 + 1), "INVALID_INPUT"), (None, "LOCAL_IO")):
            if raw is None:
                self.definition.unlink()
            else:
                self.definition.write_bytes(raw)
            status, output = self.opted()
            self.assertEqual((status, output["error"]["code"]), (2, code))
            self.assertFalse(self.workspace.exists())

    def test_archive_failure_stops_report_and_send(self):
        with patch.object(ForecastArchive, "_publish", side_effect=ServiceError("FORECAST_PUBLISH", "fixture")), \
                patch("stock_predict_mailer.cli.save_report") as report, patch.object(MailService, "deliver") as deliver:
            status, output = self.opted("--send")
        self.assertEqual((status, output["error"]["code"]), (2, "FORECAST_PUBLISH"))
        report.assert_not_called()
        deliver.assert_not_called()
        self.assertFalse((self.workspace / "agent-mail.sqlite3").exists())

    def test_later_context_failure_retains_registered_forecast(self):
        with self.config.open("a", encoding="utf-8") as stream:
            stream.write('[context]\nadapter = "file"\npath = "missing-context.json"\n')
        status, output = self.opted()
        self.assertEqual(status, 2, output)
        self.assertEqual(ForecastArchive(self.workspace).listing()["total"], 1)
        self.assertFalse((self.workspace / "agent-mail.sqlite3").exists())
        self.assertFalse((self.workspace / "analysis").exists())


class TaskFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = test_control.Fixture()
        self.addCleanup(self.f.close)
        self.engine = Orchestrator(self.f.store)
        self.p, self.d = inputs()

    def request(self, **changes):
        return self.engine.prepare({"prediction": self.p, "evaluation_definition": self.d,
                                    "complexity": "simple", "reasoning_effort": "high", **changes})

    async def test_archive_precedes_provider_and_is_in_report_and_progress(self):
        actual = self.engine.models.generate
        async def generate(*args):
            record = ForecastArchive(self.f.root).show(forecast_id(self.p))["record"]
            self.assertEqual(record["prediction"], prediction(self.p))
            return await actual(*args)
        with patch.object(self.engine.models, "generate", side_effect=generate):
            result = completed(await self.engine.execute("opted", self.request()))
        evidence = result["analysis"]["forecast_evidence"]
        self.assertIn(evidence["forecast_id"], Path(result["report_path"]).read_text(encoding="utf-8"))
        events = self.f.store.events("opted")
        event = next(e for e in events if e["kind"] == "forecast")
        self.assertEqual(event["forecast_id"], evidence["forecast_id"])
        self.assertLess(events.index(event), next(i for i, e in enumerate(events) if e.get("step") == "main"))
        again = completed(await self.engine.execute("repeat", self.request()))
        self.assertEqual(again["analysis"]["analysis_id"], result["analysis"]["analysis_id"])
        self.assertFalse(next(e for e in self.f.store.events("repeat") if e["kind"] == "forecast")["created"])

    async def test_conflict_prevents_model_mcp_knowledge_and_mail(self):
        ForecastArchive(self.f.root).register(self.p, self.d)
        request = self.request(evaluation_definition={**self.d, "flat_tolerance": 0.5})
        request.update(knowledge_query="fixture", _owner="unused")
        with patch.object(self.engine.models, "generate", new_callable=AsyncMock) as model, \
                patch.object(self.engine.mcp, "call", new_callable=AsyncMock) as mcp, \
                patch.object(self.engine.knowledge, "answer") as knowledge, \
                patch.object(self.engine, "notify_many", new_callable=AsyncMock) as notify:
            task = await self.engine.execute("conflict", request)
        self.assertEqual(task["status"]["state"], "failed")
        self.assertEqual(task["metadata"]["error"]["code"], "FORECAST_CONFLICT")
        for mocked in (model, mcp, knowledge, notify):
            mocked.assert_not_called()
        self.assertFalse((self.f.root / "analysis").exists())

    async def test_definition_revalidated_when_queued_target_has_passed(self):
        request = self.request()
        after = instant(self.d["target_at"]) + timedelta(seconds=1)
        with patch("stock_predict_mailer.agent_service.forecast_archive.utcnow", return_value=after), \
                patch.object(self.engine.models, "generate", new_callable=AsyncMock) as model:
            task = await self.engine.execute("expired", request)
        self.assertEqual(task["status"]["state"], "failed")
        model.assert_not_called()
        self.assertFalse((self.f.root / "forecasts").exists())

    async def test_cancellation_before_registration_creates_no_record(self):
        cancelled = threading.Event()
        cancelled.set()
        task = await self.engine.execute("cancel-before", self.request(), cancelled)
        self.assertEqual(task["status"]["state"], "canceled")
        self.assertFalse((self.f.root / "forecasts").exists())

    async def test_cancellation_after_registration_retains_record_without_mail(self):
        async def cancelled(*args):
            raise asyncio.CancelledError()
        with patch.object(self.engine.models, "generate", side_effect=cancelled):
            task = await self.engine.execute("cancel-after", self.request())
        self.assertEqual(task["status"]["state"], "canceled")
        self.assertEqual(ForecastArchive(self.f.root).listing()["total"], 1)
        self.assertFalse((self.f.root / "agent-mail.sqlite3").exists())

    async def test_forecast_lock_failure_prevents_analysis(self):
        request = self.request()
        # Hold from another thread so the archive cannot reenter the same owner lock.
        ready, release = threading.Event(), threading.Event()
        def holder():
            with process_lock(Config(self.f.root)):
                ready.set()
                release.wait(10)
        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(ready.wait(5))
        try:
            with patch.object(self.engine.models, "generate", new_callable=AsyncMock) as model:
                task = await self.engine.execute("locked", request)
            self.assertEqual(task["metadata"]["error"]["code"], "FORECAST_BUSY")
            model.assert_not_called()
        finally:
            release.set()
            thread.join(5)

    async def test_default_task_has_no_evidence_or_forecast_progress(self):
        result = completed(await self.engine.execute("default", self.request(evaluation_definition=None)))
        self.assertNotIn("forecast_evidence", result["analysis"])
        self.assertFalse((self.f.root / "forecasts").exists())
        self.assertFalse(any(e["kind"] == "forecast" for e in self.f.store.events("default")))

    async def test_file_notification_keeps_exact_forecast_evidence(self):
        settings = self.f.store.settings()
        settings["mail"].update(recipient_allowlist=["preview@example.invalid"], allow_synthetic=True)
        self.f.store.save_settings(settings)
        request = self.request(notify=True, recipient="preview@example.invalid")
        result = completed(await self.engine.execute("notify", request))
        self.assertEqual(result["mail"]["status"], "simulated")
        mail = MailService(self.f.root, settings["mail"])
        queued = json.loads(mail.get(result["mail"]["id"])["analysis"])
        self.assertEqual(queued["forecast_evidence"], result["analysis"]["forecast_evidence"])

    def test_invalid_definition_and_unauthorized_recipient_do_not_register(self):
        for changes, code in (({"evaluation_definition": {**self.d, "target_at": self.p["generated_at"]}}, "INVALID_INPUT"),
                              ({"notify": True, "recipient": "unauthorized@example.com"}, "PERMISSION_DENIED")):
            with self.assertRaises(ServiceError) as caught:
                self.request(**changes)
            self.assertEqual(caught.exception.code, code)
            self.assertFalse((self.f.root / "forecasts").exists())

    def test_definition_is_not_inherited_across_conversation_turns(self):
        owner = self.engine.memory.create_owner()["owner"]
        cid = self.engine.memory.new(owner)["id"]
        first = self.engine.prepare({"conversation_id": cid, "prediction": self.p, "evaluation_definition": self.d}, owner)
        self.engine.memory.save(owner, cid, {"request": first})
        for replacement in (None, self.p, {**self.p, "prediction_id": "next"}, {**self.p, "subject": "OTHER.SZ"}):
            raw = {"conversation_id": cid}
            if replacement is not None:
                raw["prediction"] = replacement
            following = self.engine.prepare(raw, owner)
            self.assertIsNone(following["evaluation_definition"])
        self.assertFalse((self.f.root / "forecasts").exists())


class TaskHTTPTests(unittest.TestCase):
    setUp = test_control.ConsoleAPITests.setUp
    tearDown = test_control.ConsoleAPITests.tearDown

    def test_http_task_parameter_and_durable_result(self):
        p, d = inputs()
        response = self.client.post("/api/tasks", json={"prediction": p, "evaluation_definition": d,
                                                       "complexity": "simple", "reasoning_effort": "high"})
        self.assertEqual(response.status_code, 202, response.text)
        tid = response.json()["id"]
        for _ in range(150):
            task = self.client.get("/api/tasks/" + tid).json()
            if task["status"]["state"] in ("completed", "failed", "canceled"):
                break
            time.sleep(.02)
        result = completed(task)
        self.assertEqual(result["analysis"]["forecast_evidence"]["forecast_id"], forecast_id(p))
        self.assertEqual(ForecastArchive(self.f.root).listing()["total"], 1)
        self.assertFalse((self.f.root / "agent-mail.sqlite3").exists())

    def test_http_invalid_definition_creates_no_task_or_archive(self):
        p, d = inputs()
        response = self.client.post("/api/tasks", json={"prediction": p, "evaluation_definition": {**d, "unit": "USD"}})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse((self.f.root / "forecasts").exists())
        self.assertEqual(self.client.get("/api/tasks").json()["items"], [])


if __name__ == "__main__":
    unittest.main()
