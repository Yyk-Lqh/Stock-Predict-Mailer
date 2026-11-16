"""Task-scoped forecast reads preserve private owners and archive bytes."""
import copy
import json
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_control
from stock_predict_mailer.agent_service.contracts import instant
from stock_predict_mailer.agent_service.forecast_archive import ForecastArchive
from stock_predict_mailer.control import forecast_views
from stock_predict_mailer.control.orchestrator import a2a_task
from test_forecast_tasks import inputs


class ForecastConsoleTests(unittest.TestCase):
    setUp = test_control.ConsoleAPITests.setUp
    tearDown = test_control.ConsoleAPITests.tearDown

    def record(self, tid, *, hours=0, owner=None, state="completed", evaluated=False):
        p, d = inputs()
        p["prediction_id"] = tid
        if hours:
            for key in ("generated_at", "valid_until"):
                p[key] = (instant(p[key]) - timedelta(hours=hours)).isoformat()
            d["target_at"] = (instant(d["target_at"]) - timedelta(hours=hours)).isoformat()
            for key in ("observed_at", "available_at"):
                d["reference"][key] = (instant(d["reference"][key]) - timedelta(hours=hours)).isoformat()
        at = instant(p["generated_at"]) + timedelta(seconds=10)
        r = ForecastArchive(self.f.root).register(p, d, now=at)["record"]
        result = {"analysis": {"forecast_evidence": {"forecast_id": r["forecast_id"]}}} if state == "completed" else None
        self.f.store.task(tid, a2a_task(tid, state, result=result))
        self.f.store.append_event(tid, {"kind": "forecast", "forecast_id": r["forecast_id"]})
        if owner is not None:
            with self.f.store.db() as con:
                con.execute("INSERT INTO memory_tasks VALUES (?,?,?)", (tid, owner, "fixture-conversation"))
        if evaluated:
            target = instant(d["target_at"])
            actual = {"schema_version": "1", "subject": p["subject"], "metric": d["metric"], "unit": d["unit"], "value": 112,
                      "observed_at": target.isoformat(), "available_at": target.isoformat(), "source": "synthetic-observation", "synthetic": True}
            ForecastArchive(self.f.root).evaluate(r["forecast_id"], actual)
        return r

    def files(self):
        folder = self.f.root / "forecasts"
        return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}

    def test_empty_list_is_readonly_and_initializes_no_archive(self):
        response = self.client.get("/api/forecasts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(response.json()["scanned_tasks"], 0)
        self.assertFalse((self.f.root / "forecasts").exists())

    def test_states_detail_and_metrics_are_readonly(self):
        pending = self.record("pending")
        self.record("due", hours=2)
        self.record("evaluated", hours=3, evaluated=True)
        before = self.files()
        page = self.client.get("/api/forecasts").json()
        self.assertEqual([r["state"] for r in page["items"]], ["evaluated", "due", "pending"])
        self.assertEqual(page["items"][0]["latest_metrics"]["absolute_error"], 2)
        detail = self.client.get("/api/tasks/pending/forecast")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["record"], pending)
        self.assertEqual(self.files(), before)

    def test_private_records_are_hidden_without_or_with_other_owner(self):
        a = self.server.engine.memory.create_owner()
        b = self.server.engine.memory.create_owner()
        self.record("public")
        secret = self.record("private", owner=a["owner"])
        for key in (None, b["key"]):
            if key:
                self.client.headers["X-Memory-Key"] = key
            page = self.client.get("/api/forecasts").json()
            self.assertEqual([r["task_id"] for r in page["items"]], ["public"])
            self.assertNotIn(secret["forecast_id"], json.dumps(page))
            self.assertEqual(self.client.get("/api/tasks/private/forecast").status_code, 403)
        self.client.headers["X-Memory-Key"] = a["key"]
        self.assertEqual(len(self.client.get("/api/forecasts").json()["items"]), 2)
        self.assertEqual(self.client.get("/api/tasks/private/forecast").json()["record"], secret)

    def test_unauthorized_private_record_is_not_opened(self):
        owner = self.server.engine.memory.create_owner()
        self.record("private", owner=owner["owner"])
        with patch.object(ForecastArchive, "show", side_effect=AssertionError("private file opened")):
            self.assertEqual(self.client.get("/api/tasks/private/forecast").status_code, 403)
            self.assertEqual(self.client.get("/api/forecasts").json()["items"], [])

    def test_session_origin_host_and_bad_memory_key_are_rejected(self):
        self.assertEqual(self.client.get("/api/forecasts", headers={"Cookie": ""}).status_code, 403)
        self.assertEqual(self.client.get("/api/forecasts", headers={"Origin": "https://evil.invalid"}).status_code, 403)
        self.assertEqual(self.client.get("/api/forecasts", headers={"Host": "evil.invalid"}).status_code, 403)
        self.assertEqual(self.client.get("/api/forecasts", headers={"X-Memory-Key": "invalid"}).status_code, 403)

    def test_list_and_detail_offer_no_write_endpoint(self):
        self.record("one")
        before = self.files()
        for path in ("/api/forecasts", "/api/tasks/one/forecast"):
            self.assertEqual(self.client.post(path, json={}).status_code, 404)
        self.assertEqual(self.files(), before)

    def test_cli_only_archive_cannot_be_enumerated_or_guessed(self):
        p, d = inputs()
        record = ForecastArchive(self.f.root).register(p, d)["record"]
        self.assertEqual(self.client.get("/api/forecasts").json()["items"], [])
        self.assertEqual(self.client.get("/api/forecasts/" + record["forecast_id"]).status_code, 404)
        self.assertEqual(self.client.get("/api/tasks/missing/forecast").status_code, 404)

    def test_failed_and_canceled_tasks_retain_archive_access(self):
        for state in ("failed", "canceled"):
            record = self.record(state, state=state)
            detail = self.client.get(f"/api/tasks/{state}/forecast")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["record"], record)
        self.assertEqual(len(self.client.get("/api/forecasts").json()["items"]), 2)

    def test_keyset_pages_scan_tasks_without_losing_older_forecasts(self):
        self.record("old")
        self.f.store.task("no-archive", a2a_task("no-archive", "failed"))
        self.record("new")
        page = self.client.get("/api/forecasts?limit=1").json()
        self.assertEqual(page["items"][0]["task_id"], "new")
        cursor = page["next_before"]
        empty = self.client.get(f"/api/forecasts?limit=1&before={cursor}").json()
        self.assertEqual(empty["items"], [])
        self.assertEqual(empty["scanned_tasks"], 1)
        last = self.client.get(f'/api/forecasts?limit=1&before={empty["next_before"]}').json()
        self.assertEqual(last["items"][0]["task_id"], "old")
        self.assertIsNone(last["next_before"])

    def test_state_filter_is_applied_before_output(self):
        self.record("pending")
        self.record("due", hours=2)
        for state, expected in (("pending", "pending"), ("due", "due"), ("evaluated", None)):
            page = self.client.get("/api/forecasts?state=" + state).json()
            self.assertEqual([r["task_id"] for r in page["items"]], [expected] if expected else [])
            self.assertEqual(page["scanned_tasks"], 2)

    def test_duplicate_prediction_is_merged_within_page(self):
        record = self.record("one")
        task = copy.deepcopy(self.f.store.task("one"))
        task["id"] = "two"
        self.f.store.task("two", task)
        page = self.client.get("/api/forecasts").json()
        self.assertEqual(page["scanned_tasks"], 2)
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["items"][0]["forecast_id"], record["forecast_id"])

    def test_bad_queries_and_detail_parameters_fail(self):
        for query in ("limit=0", "limit=51", "before=-1", "before=abc", "state=unknown", "limit=1&limit=2", "as_of=now", "limit="):
            response = self.client.get("/api/forecasts?" + query)
            self.assertEqual(response.status_code, 400, (query, response.text))
        self.record("one")
        self.assertEqual(self.client.get("/api/tasks/one/forecast?state=due").status_code, 400)

    def test_corrupt_archive_is_reported_without_partial_results(self):
        r = self.record("one")
        path = self.f.root / "forecasts" / "records" / (r["forecast_id"] + ".json")
        path.write_text("{}", encoding="utf-8")
        response = self.client.get("/api/forecasts")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "FORECAST_CORRUPT")
        self.assertNotIn("items", response.json())

    def test_read_and_response_budgets_fail_closed(self):
        self.record("one")
        for name in ("MAX_BODY", "MAX_READ", "MAX_RESPONSE"):
            with patch.object(forecast_views, name, 10):
                response = self.client.get("/api/forecasts")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], "FORECAST_LIMIT")

    def test_task_without_archive_returns_not_found(self):
        self.f.store.task("no-archive", a2a_task("no-archive", "completed", result={"analysis": {}}))
        self.assertEqual(self.client.get("/api/tasks/no-archive/forecast").status_code, 404)
        self.assertFalse((self.f.root / "forecasts").exists())

    def test_corrupt_task_body_is_reported(self):
        with self.f.store.db() as con:
            con.execute("INSERT INTO tasks VALUES (?,?)", ("bad", None))
        response = self.client.get("/api/forecasts")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "FORECAST_CORRUPT")

    def test_registration_event_with_missing_identity_is_reported(self):
        self.f.store.task("bad", a2a_task("bad", "canceled"))
        self.f.store.append_event("bad", {"kind": "forecast"})
        response = self.client.get("/api/forecasts")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "FORECAST_CORRUPT")


if __name__ == "__main__":
    unittest.main()
