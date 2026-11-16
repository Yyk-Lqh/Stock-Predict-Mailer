"""Explicit observation parsing and task-scoped preview with no archive writes."""
import copy
import csv
import hashlib
import io
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import test_control
import test_forecast_console
from stock_predict_mailer.agent_service.contracts import ServiceError, instant, utcnow
from stock_predict_mailer.agent_service.forecast_archive import ForecastArchive
from stock_predict_mailer.agent_service.observation_input import FIELDS, MAX_INPUT, parse
from stock_predict_mailer.control import forecast_views
from test_forecast_tasks import inputs


def actual(record, **changes):
    d, p = record["definition"], record["prediction"]
    return {"schema_version": "1", "subject": p["subject"], "metric": d["metric"], "unit": d["unit"], "value": 112,
            "observed_at": d["target_at"], "available_at": d["target_at"], "source": "synthetic-observation", "synthetic": p["synthetic"], **changes}


def csv_text(value, *, header=FIELDS, rows=1):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(header)
    row = [str(value[key]).lower() if key == "synthetic" else value[key] for key in header]
    for _ in range(rows):
        writer.writerow(row)
    return output.getvalue()


class ObservationInputTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p, d = inputs()
        self.record = ForecastArchive(Path(tmp.name)).register(p, d)["record"]
        self.actual = actual(self.record)

    def reject(self, request):
        with self.assertRaises(ServiceError) as caught:
            parse(request, self.record)
        self.assertEqual(caught.exception.code, "INVALID_INPUT")

    def test_json_object_text_and_csv_produce_same_matched_observation(self):
        before = copy.deepcopy(self.actual)
        variants = [{"observation": self.actual}, {"format": "json", "content": json.dumps(self.actual)},
                    {"format": "csv", "content": csv_text(self.actual)}]
        result = [parse(value, self.record) for value in variants]
        self.assertTrue(all(r["observation"] == before for r in result))
        self.assertEqual(len({r["observation_id"] for r in result}), 1)
        self.assertEqual(self.actual, before)

    def test_bom_and_import_hash_preserve_original_text(self):
        for kind, text in (("json", json.dumps(self.actual)), ("csv", csv_text(self.actual))):
            raw = "\ufeff" + text
            result = parse({"format": kind, "content": raw}, self.record)
            self.assertEqual(result["input"]["content_sha256"], hashlib.sha256(raw.encode()).hexdigest())
            self.assertEqual(result["input"]["bytes"], len(raw.encode()))

    def test_csv_quoted_source_and_reordered_fields_are_explicit(self):
        value = actual(self.record, source='quoted, source\n<img src=x onerror="alert(1)">')
        parsed = parse({"format": "csv", "content": csv_text(value, header=tuple(reversed(FIELDS)))}, self.record)
        self.assertEqual(parsed["observation"]["source"], value["source"])

    def test_csv_rejects_duplicate_unknown_missing_headers_and_wrong_row_size(self):
        valid = csv_text(self.actual)
        for content in (valid.replace("schema_version", "subject", 1), valid.replace("unit", "price_unit", 1),
                        valid.replace("schema_version,", "", 1), valid + ",extra\n", valid.replace(",112,", ",112,extra,", 1)):
            with self.subTest(content=content[:50]):
                self.reject({"format": "csv", "content": content})

    def test_csv_never_selects_from_multiple_rows(self):
        for rows in (0, 2, 10):
            self.reject({"format": "csv", "content": csv_text(self.actual, rows=rows)})

    def test_json_duplicate_keys_and_trailing_or_unknown_fields_fail(self):
        valid = json.dumps(self.actual)
        for content in (valid.replace('"value": 112', '"value": 111, "value": 112'), valid + "{}", json.dumps({**self.actual, "adjustment": "guess"})):
            self.reject({"format": "json", "content": content})

    def test_values_must_be_finite_numbers_and_csv_flags_explicit(self):
        for token in ("NaN", "Infinity", "true", "null", "01"):
            content = csv_text(self.actual).replace(",112,", "," + token + ",")
            self.reject({"format": "csv", "content": content})
        for token in ("TRUE", "1", "yes", ""):
            self.reject({"format": "csv", "content": csv_text(self.actual).replace(",true\r", "," + token + "\r")})
        self.reject({"observation": actual(self.record, value=True)})
        self.reject({"observation": actual(self.record, value="112")})

    def test_exact_identity_units_metric_flags_and_times_are_required(self):
        for changes in ({"subject": "OTHER.SZ"}, {"metric": "close_adjusted"}, {"unit": "USD"}, {"synthetic": False},
                        {"observed_at": (instant(self.actual["observed_at"]) + timedelta(seconds=1)).isoformat()},
                        {"available_at": (instant(self.actual["observed_at"]) - timedelta(seconds=1)).isoformat()}, {"source": ""}):
            self.reject({"observation": {**self.actual, **changes}})

    def test_size_budget_is_utf8_bytes_and_invalid_unicode_fails(self):
        self.reject({"format": "json", "content": "观" * (MAX_INPUT // 3 + 1)})
        self.reject({"observation": actual(self.record, source="x" * MAX_INPUT)})
        self.reject({"format": "json", "content": "\ud800"})
        self.reject({"observation": actual(self.record, source="\ud800")})
        escaped = json.dumps(actual(self.record, source="\ud800"))
        self.reject({"format": "json", "content": escaped})

    def test_request_shapes_do_not_accept_paths_or_write_flags(self):
        for request in ({"format": "auto", "content": "x"}, {"format": "json", "content": {}}, {"path": "actual.json"},
                        {"observation": self.actual, "dry_run": False}, {"observation": self.actual, "content": "x"}, None):
            self.reject(request)

    def test_content_hash_distinguishes_serialization_while_observation_hash_does_not(self):
        a = parse({"format": "json", "content": json.dumps(self.actual)}, self.record)
        b = parse({"format": "json", "content": json.dumps(self.actual, indent=2)}, self.record)
        self.assertEqual(a["observation_id"], b["observation_id"])
        self.assertNotEqual(a["input"]["content_sha256"], b["input"]["content_sha256"])


class PreviewHTTPTests(unittest.TestCase):
    setUp = test_control.ConsoleAPITests.setUp
    tearDown = test_control.ConsoleAPITests.tearDown
    record = test_forecast_console.ForecastConsoleTests.record

    def post(self, tid, payload, **kwargs):
        return self.client.post(f"/api/tasks/{tid}/forecast/preview", json=payload, **kwargs)

    def snapshot(self):
        return {str(p.relative_to(self.f.root)): p.read_bytes() for p in self.f.root.rglob("*") if p.is_file()}

    def test_expired_intake_can_preview_matured_prediction_without_writing(self):
        r = self.record("due", hours=2)
        self.assertLess(instant(r["prediction"]["valid_until"]), utcnow())
        before = self.snapshot()
        response = self.post("due", {"observation": actual(r)})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["state"], "ready")
        self.assertFalse(result["persisted"])
        self.assertNotIn("evaluation", result)
        self.assertEqual(result["metrics"]["absolute_error"], 2)
        self.assertEqual(result["forecast_content_id"], r["content_id"])
        self.assertEqual(result["forecast_record_id"], r["integrity_id"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.client.get("/api/tasks/due/forecast").json()["state"], "due")

    def test_not_due_validates_input_without_metrics(self):
        r = self.record("pending")
        result = self.post("pending", {"observation": actual(r)}).json()
        self.assertEqual(result["state"], "not_due")
        self.assertNotIn("metrics", result)
        self.assertFalse(result["persisted"])
        invalid = self.post("pending", {"observation": actual(r, metric="wrong")})
        self.assertEqual(invalid.status_code, 400)

    def test_unavailable_observation_is_not_scored(self):
        r = self.record("due", hours=2)
        result = self.post("due", {"observation": actual(r, available_at=(utcnow() + timedelta(hours=1)).isoformat())}).json()
        self.assertEqual(result["state"], "awaiting_observation")
        self.assertNotIn("metrics", result)

    def test_exact_cutoff_boundary_and_time_validation(self):
        r = self.record("due", hours=2)
        target = instant(r["definition"]["target_at"])
        for at, state in ((target, "ready"), (target - timedelta(microseconds=1), "not_due")):
            result = self.post("due", {"observation": actual(r), "as_of": at.isoformat()}).json()
            self.assertEqual(result["state"], state)
        for at, code in (((utcnow() + timedelta(days=1)).isoformat(), "INVALID_INPUT"),
                         ((instant(r["registered_at"]) - timedelta(seconds=1)).isoformat(), "FORECAST_NOT_YET_REGISTERED"),
                         ("2026-11-16T12:00:00", "INVALID_INPUT"), (None, "INVALID_INPUT")):
            response = self.post("due", {"observation": actual(r), "as_of": at})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], code)

    def test_csv_and_raw_json_imports_are_matched_and_hashed(self):
        r = self.record("due", hours=2)
        values = []
        for kind, content in (("csv", csv_text(actual(r))), ("json", json.dumps(actual(r)))):
            response = self.post("due", {"format": kind, "content": content})
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result["input"]["content_sha256"], hashlib.sha256(content.encode()).hexdigest())
            values.append(result)
        self.assertEqual(values[0]["metrics"], values[1]["metrics"])
        self.assertEqual(values[0]["observation_id"], values[1]["observation_id"])

    def test_nested_json_duplicate_field_is_rejected(self):
        r = self.record("due", hours=2)
        text = json.dumps(actual(r)).replace('"value": 112', '"value": 111, "value": 112')
        self.assertEqual(self.post("due", {"format": "json", "content": text}).status_code, 400)

    def test_csrf_session_host_and_origin_are_required(self):
        self.record("due", hours=2)
        for headers in ({"X-CSRF-Token": ""}, {"Cookie": ""}, {"Host": "evil.invalid"}, {"Origin": "https://evil.invalid"}):
            response = self.client.post("/api/tasks/due/forecast/preview", content=b"", headers=headers)
            self.assertEqual(response.status_code, 403)

    def test_private_owner_is_checked_before_any_archive_read(self):
        owner = self.server.engine.memory.create_owner()
        other = self.server.engine.memory.create_owner()
        r = self.record("private", hours=2, owner=owner["owner"])
        with patch.object(ForecastArchive, "show", side_effect=AssertionError("private read")):
            self.assertEqual(self.post("private", {"observation": actual(r)}).status_code, 403)
            self.client.headers["X-Memory-Key"] = other["key"]
            self.assertEqual(self.post("private", {"observation": actual(r)}).status_code, 403)
        self.client.headers["X-Memory-Key"] = owner["key"]
        self.assertEqual(self.post("private", {"observation": actual(r)}).status_code, 200)

    def test_preview_does_not_call_evaluate_publish_or_write_lock(self):
        r = self.record("due", hours=2)
        with patch.object(ForecastArchive, "evaluate", side_effect=AssertionError("evaluate called")), \
                patch.object(ForecastArchive, "_publish", side_effect=AssertionError("publish called")), \
                patch.object(ForecastArchive, "_writer", side_effect=AssertionError("lock called")):
            response = self.post("due", {"observation": actual(r)})
        self.assertEqual(response.status_code, 200, response.text)

    def test_preview_keeps_existing_receipt_and_list_metrics(self):
        r = self.record("evaluated", hours=2, evaluated=True)
        before = self.snapshot()
        result = self.post("evaluated", {"observation": actual(r, value=113)}).json()
        self.assertEqual(result["metrics"]["absolute_error"], 3)
        self.assertEqual(self.snapshot(), before)
        detail = self.client.get("/api/tasks/evaluated/forecast").json()
        self.assertEqual(len(detail["evaluations"]), 1)
        self.assertEqual(detail["evaluations"][0]["metrics"]["absolute_error"], 2)
        self.assertEqual(self.client.get("/api/forecasts").json()["items"][0]["latest_metrics"]["absolute_error"], 2)

    def test_invalid_input_does_not_change_workspace(self):
        r = self.record("due", hours=2)
        before = self.snapshot()
        for data in ({"observation": actual(r, unit="USD")}, {"format": "csv", "content": csv_text(actual(r), rows=2)},
                     {"observation": actual(r), "persisted": True}, {"format": "json", "content": "观" * 90000}):
            self.assertEqual(self.post("due", data).status_code, 400)
        self.assertEqual(self.snapshot(), before)

    def test_missing_task_and_arbitrary_forecast_routes_fail(self):
        self.assertEqual(self.post("missing", {"observation": {}}).status_code, 404)
        self.assertEqual(self.client.post("/api/forecasts/" + "a" * 64 + "/preview", json={}).status_code, 404)
        self.assertFalse((self.f.root / "forecasts").exists())

    def test_wrong_method_query_and_non_json_body_fail(self):
        r = self.record("due", hours=2)
        self.assertEqual(self.client.get("/api/tasks/due/forecast/preview").status_code, 404)
        self.assertEqual(self.client.post("/api/tasks/due/forecast/preview?as_of=now", json={"observation": actual(r)}).status_code, 400)
        self.assertEqual(self.client.post("/api/tasks/due/forecast/preview", content=b"{}", headers={"Content-Type": "text/plain"}).status_code, 400)

    def test_read_and_response_limits_are_preserved(self):
        r = self.record("due", hours=2)
        for field in ("MAX_READ", "MAX_RESPONSE"):
            with patch.object(forecast_views, field, 10):
                response = self.post("due", {"observation": actual(r)})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], "FORECAST_LIMIT")


if __name__ == "__main__":
    unittest.main()
