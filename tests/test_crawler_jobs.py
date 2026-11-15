"""Local queue/process fixtures; no live collection, model or mail requests."""
import asyncio
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_server import jobs_cli, server
from mcp_server.job_worker import run_once
from mcp_server.jobs import JobControl, JobStore
from mcp_server.quality import DataQualityError, atomic_json, utc_now, write_snapshot
from mcp_server.runtime import JobStopped, current_control, path_for, using_paths, workspace_lock

ENV_KEY = "STOCK_PREDICT_MAILER_CRAWLER_WORKSPACE"
HAS_CRAWLER = all(importlib.util.find_spec(n) for n in ("pandas", "requests", "baostock"))
CHILD = """
import sys
from mcp_server.jobs import JobStore
from mcp_server.job_worker import run_once
from mcp_server.runtime import progress, pause
def execute(kind, parameters):
    progress(stage='waiting_for_test')
    pause(60)
    return {'ok': True}
run_once(JobStore(sys.argv[1]), execute)
"""


class QueueTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "workspace"
        self.store = JobStore(self.root)

    def test_readonly_operations_create_nothing(self):
        self.assertEqual(self.store.listing(), [])
        self.assertIsNone(run_once(self.store))
        with self.assertRaises(DataQualityError):
            self.store.get("a" * 32)
        self.assertFalse(self.root.exists())

    def test_submit_is_persistent_and_does_not_execute(self):
        with patch("builtins.__import__", wraps=__import__) as imports:
            result = self.store.submit("fundamental", {"max_stocks": 2})
        self.assertEqual(result["state"], "queued")
        self.assertNotIn("owner", result)
        self.assertIsNotNone(result["parameters"]["end_date"])
        self.assertEqual(JobStore(self.root).get(result["id"])["attempts"], 0)
        self.assertFalse(any(call.args[0].split(".")[0] in ("pandas", "requests", "baostock") for call in imports.call_args_list))

    def test_idempotent_submit_and_conflicting_key(self):
        first = self.store.submit("catalog", request_key="same")
        self.assertEqual(first["id"], self.store.submit("catalog", request_key="same")["id"])
        with self.assertRaises(DataQualityError) as caught:
            self.store.submit("catalog", {"force_refresh": True}, "same")
        self.assertEqual(caught.exception.code, "JOB_KEY_CONFLICT")
        self.assertEqual(len(self.store.listing()), 1)

    def test_concurrent_submit_has_one_identity(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.store.submit("catalog", request_key="concurrent"), range(6)))
        self.assertEqual(len({row["id"] for row in results}), 1)
        self.assertEqual(len(self.store.events(results[0]["id"])), 1)

    def test_invalid_parameters_do_not_create_database(self):
        for kind, values in (("unknown", {}), ("catalog", []), ("catalog", {"force_refresh": 1}),
                             ("catalog", {"max_cache_age_seconds": -1}), ("fundamental", {"max_stocks": True}),
                             ("fundamental", {"end_date": "9999-01-01"}), ("catalog", {"unknown": True})):
            with self.subTest(kind=kind, values=values), self.assertRaises(DataQualityError):
                self.store.submit(kind, values)
        self.assertFalse(self.root.exists())

    def test_queued_cancel_and_explicit_resume(self):
        job = self.store.submit("catalog")
        self.assertEqual(self.store.cancel(job["id"])["state"], "cancelled")
        self.assertIsNone(run_once(self.store, lambda *_: self.fail("cancelled job executed")))
        self.assertEqual(self.store.resume(job["id"])["state"], "queued")
        self.assertFalse(self.store.get(job["id"])["cancel_requested"])

    def test_completion_partial_and_failure_remain_distinct(self):
        for result, expected in (({"ok": True, "completeness": "partial", "run_complete": True}, "completed"),
                                 ({"ok": False, "completeness": "partial"}, "partial"),
                                 ({"ok": False}, "failed")):
            job = self.store.submit("catalog")
            actual = run_once(self.store, lambda *_, value=result: value)
            self.assertEqual(actual["id"], job["id"])
            self.assertEqual(actual["state"], expected)
            self.assertEqual(actual["attempts"], 1)

    def test_worker_exceptions_are_persisted_without_raw_exception_text(self):
        self.store.submit("catalog")
        def execute(*_):
            raise RuntimeError("untrusted raw provider detail")
        result = run_once(self.store, execute)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error"]["message"], "RuntimeError")

    def test_missing_dependencies_fail_with_install_hint(self):
        self.store.submit("catalog")
        def execute(*_):
            raise ModuleNotFoundError("requests")
        result = run_once(self.store, execute)
        self.assertEqual(result["error"]["code"], "DEPENDENCY_MISSING")
        self.assertIn("--extra crawler", result["error"]["hint"])

    def test_finished_job_cannot_be_resumed_or_claimed_again(self):
        job = self.store.submit("catalog")
        run_once(self.store, lambda *_: {"ok": True})
        with self.assertRaises(DataQualityError):
            self.store.resume(job["id"])
        self.assertIsNone(run_once(self.store, lambda *_: self.fail("completed job executed twice")))

    def test_claim_requires_os_writer_lock_and_fences_old_owner(self):
        job = self.store.submit("catalog")
        with self.assertRaises(DataQualityError):
            self.store.claim()
        with workspace_lock(self.store.data):
            row = self.store.claim()
            self.store.finish(job["id"], row["owner"], "failed")
            self.store.resume(job["id"])
            second = self.store.claim()
            with self.assertRaises(JobStopped):
                self.store.finish(job["id"], row["owner"], "completed")
            self.store.finish(job["id"], second["owner"], "completed")

    def test_event_pagination_and_checkpoint_events_are_bounded(self):
        job = self.store.submit("catalog")
        def execute(*_):
            control = current_control()
            control.prepare({"pool_sha256": "a" * 64, "as_of": "2026-11-15", "selected_codes": ["000001"]}, None)
            control.complete_stock("000001", "b" * 64)
            return {"ok": True}
        run_once(self.store, execute)
        first = self.store.events(job["id"], limit=2)
        rest = self.store.events(job["id"], after=first[-1]["seq"])
        self.assertTrue(all(event["seq"] > first[-1]["seq"] for event in rest))
        self.assertTrue(all("plan" not in event["body"] for event in rest if event["kind"] == "checkpoint"))

    def test_checkpoint_rejects_input_or_output_changes(self):
        job = self.store.submit("fundamental")
        with workspace_lock(self.store.data):
            row = self.store.claim()
            control = JobControl(self.store, row)
            plan = {"pool_sha256": "original", "as_of": "2026-11-15", "selected_codes": []}
            control.prepare(plan, "output")
            for changed, output in ((dict(plan, pool_sha256="changed"), "output"), (plan, "changed")):
                with self.assertRaises(DataQualityError):
                    control.prepare(changed, output)
            self.store.finish(job["id"], row["owner"], "interrupted")

    def test_thread_cannot_bypass_same_process_file_lock(self):
        errors = []
        def second():
            try:
                with workspace_lock(self.store.data):
                    errors.append("unexpectedly acquired")
            except DataQualityError as exc:
                errors.append(exc.code)
        with workspace_lock(self.store.data):
            with workspace_lock(self.store.data):
                worker = threading.Thread(target=second)
                worker.start()
                worker.join(5)
                self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ["WORKSPACE_BUSY"])

    def test_cli_management_and_empty_worker_do_not_collect(self):
        with patch.dict(os.environ, {ENV_KEY: str(self.root)}), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(server.main(["worker", "--once"]), 0)
        self.assertFalse(self.store.path.exists())
        self.assertFalse(self.store.data.exists())
        from stock_predict_mailer.operations.components import status
        self.assertEqual(status(self.root, "crawler_worker")["state"], "stopped")
        self.assertTrue(json.loads(output.getvalue())["ok"])
        with patch.dict(os.environ, {ENV_KEY: str(self.root)}), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(server.main(["jobs", "submit", "--kind", "catalog", "--request-key", "cli"]), 0)
        job_id = json.loads(output.getvalue())["result"]["id"]
        with patch.dict(os.environ, {ENV_KEY: str(self.root)}), redirect_stdout(io.StringIO()):
            self.assertEqual(server.main(["jobs", "cancel", job_id]), 0)
        self.assertEqual(self.store.get(job_id)["state"], "cancelled")

    def test_cli_rejects_duplicate_json_and_invalid_poll(self):
        with patch.dict(os.environ, {ENV_KEY: str(self.root)}), redirect_stdout(io.StringIO()):
            self.assertEqual(jobs_cli.main(["jobs", "submit", "--kind", "catalog", "--parameters", '{"force_refresh":true,"force_refresh":false}']), 2)
            self.assertEqual(jobs_cli.main(["worker", "--once", "--poll", "nan"]), 2)
        self.assertFalse(self.root.exists())

    def test_keyboard_stop_does_not_run_the_next_queued_job(self):
        first = self.store.submit("catalog")
        second = self.store.submit("catalog")
        with (patch.dict(os.environ, {ENV_KEY: str(self.root)}),
              patch("mcp_server.job_worker.execute", return_value={"ok": False, "stop_reason": "cancelled"}),
              redirect_stdout(io.StringIO())):
            self.assertEqual(server.main(["worker"]), 130)
        self.assertEqual(self.store.get(first["id"])["state"], "interrupted")
        self.assertEqual(self.store.get(second["id"])["state"], "queued")

    def test_path_override_does_not_leak_into_other_threads(self):
        values = []
        with using_paths({"OUTPUT_FILE": "job-specific"}):
            thread = threading.Thread(target=lambda: values.append(path_for("OUTPUT_FILE", "default")))
            thread.start()
            thread.join(5)
            self.assertEqual(path_for("OUTPUT_FILE", "default"), "job-specific")
        self.assertEqual(values, ["default"])
        self.assertEqual(path_for("OUTPUT_FILE", "default"), "default")

    @unittest.skipUnless(importlib.util.find_spec("requests"), "requires catalog dependency")
    def test_real_cached_catalog_worker_honors_explicit_store_root(self):
        from mcp_server import catalog_crawler as catalog

        atomic_json(self.root / "sessions" / "cache_stock_data.json", {
            "cache_version": 1, "metadata": {"source": "eastmoney", "source_url": catalog.URL,
                "fetched_at": utc_now().isoformat(), "source_as_of": None, "completeness": "complete",
                "row_count": 1, "expected_count": 1},
            "data": {"total": 1, "diff": [{"f12": "000001", "f14": "SYNTHETIC", "f2": 1200,
                "f15": 1300, "f16": 1100, "f17": 1200, "f18": 1200, "f5": 1}]}})
        job = self.store.submit("catalog")
        unrelated = self.root.parent / "unrelated" / "data.csv"
        with patch.object(catalog, "OUTPUT_FILE", str(unrelated)), patch.object(catalog, "_fetch_from_api", side_effect=AssertionError("must use cache")):
            result = run_once(self.store)
        self.assertEqual(result["id"], job["id"])
        self.assertEqual(result["state"], "completed")
        self.assertEqual(Path(result["result"]["output_file"]), self.store.data / "stock_data117.csv")
        self.assertFalse(unrelated.exists())


class ProcessTests(unittest.TestCase):
    setUp = QueueTests.setUp

    def start_child(self):
        self.job = self.store.submit("catalog")
        self.child = subprocess.Popen([sys.executable, "-c", CHILD, str(self.root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop_child)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.store.get(self.job["id"])["progress"].get("stage") == "waiting_for_test":
                return
            if self.child.poll() is not None:
                self.fail("synthetic child worker exited before readiness")
            time.sleep(0.05)
        self.fail("synthetic child worker did not start")

    def stop_child(self):
        if getattr(self, "child", None) is not None and self.child.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.child.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            else:
                self.child.terminate()
            self.child.wait(timeout=10)

    def test_live_worker_cannot_be_recovered_or_executed_twice(self):
        self.start_child()
        self.store.submit("catalog")
        with self.assertRaises(DataQualityError) as caught:
            run_once(self.store, lambda *_: self.fail("second writer ran"))
        self.assertEqual(caught.exception.code, "WORKSPACE_BUSY")
        self.assertEqual(self.store.get(self.job["id"])["state"], "running")

    def test_persisted_cancel_interrupts_long_pause_in_child(self):
        self.start_child()
        self.assertEqual(self.store.cancel(self.job["id"])["state"], "cancelling")
        self.child.wait(timeout=10)
        self.assertEqual(self.store.get(self.job["id"])["state"], "cancelled")

    def test_process_death_is_interrupted_and_requires_explicit_resume(self):
        self.start_child()
        self.stop_child()
        self.assertIsNone(run_once(self.store, lambda *_: self.fail("recovery must not auto-execute")))
        self.assertEqual(self.store.get(self.job["id"])["state"], "interrupted")
        self.store.resume(self.job["id"])
        result = run_once(self.store, lambda *_: {"ok": True})
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["attempts"], 2)


@unittest.skipUnless(HAS_CRAWLER, "requires crawler extra")
class FundamentalJobTests(unittest.TestCase):
    def setUp(self):
        previous = socket.getdefaulttimeout()
        self.addCleanup(socket.setdefaulttimeout, previous)
        from mcp_server import fundamental_crawler as fund
        self.fund = fund
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.store = JobStore(self.root)
        self.store.data.mkdir()
        for field, value in (("DATA_DIR", str(self.store.data)), ("POOL_FILE", str(self.store.data / "stock_data117.csv")),
                             ("OUTPUT_FILE", str(self.store.data / "fundamental_quarterly_new.csv")), ("LOG_FILE", str(self.store.data / "重采进度.log"))):
            context = patch.object(fund, field, value)
            context.start()
            self.addCleanup(context.stop)
        Path(fund.POOL_FILE).write_text("股票代码\n000001\n000002\n", encoding="utf-8-sig")
        for field, value in (("_preflight", lambda: True), ("_reconnect", lambda: None)):
            context = patch.object(fund, field, value)
            context.start()
            self.addCleanup(context.stop)
        context = patch.object(fund.bs, "logout")
        context.start()
        self.addCleanup(context.stop)
        self.job = self.store.submit("fundamental", {"allow_unverified_pool": True})

    def rows(self, code, *args, **kwargs):
        return [{"code": code, "report_date": "2026-09-30", "pubDate": "2026-10-25", "roeAvg": 0.1,
                 "publication_verified": True, "collected_at": utc_now().isoformat(), "provider_symbol": "sz." + code}]

    def cancel_after_first_stock(self):
        def execute(kind, params):
            control = current_control()
            original = control.progress
            def observe(values):
                original(values)
                if values.get("stage") == "stock_completed" and values.get("completed") == 1:
                    self.store.cancel(self.job["id"])
            with patch.object(control, "progress", side_effect=observe), patch.object(self.fund, "_fetch_stock", side_effect=self.rows):
                return self.fund.collect_fundamental(**params)
        return run_once(self.store, execute)

    def test_resume_skips_completed_stocks_and_restores_full_selected_progress(self):
        first = self.cancel_after_first_stock()
        self.assertEqual(first["state"], "cancelled")
        self.assertEqual(first["checkpoint"]["completed_codes"], ["000001"])
        self.store.resume(self.job["id"])
        with patch.object(self.fund, "_fetch_stock", side_effect=self.rows) as fetch:
            result = run_once(self.store)
        self.assertEqual([call.args[0] for call in fetch.call_args_list], ["000002"])
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["result"]["processed_count"], 2)
        self.assertTrue(result["result"]["view_metadata"]["run_complete"])

    def test_resume_rejects_changed_pool_without_fetching(self):
        self.cancel_after_first_stock()
        Path(self.fund.POOL_FILE).write_text("股票代码\n000001\n000003\n", encoding="utf-8-sig")
        self.store.resume(self.job["id"])
        with patch.object(self.fund, "_fetch_stock", side_effect=AssertionError("must not fetch")):
            result = run_once(self.store)
        self.assertEqual(result["error"]["code"], "INPUT_CHANGED")

    def test_resume_rejects_lost_output_instead_of_skipping_data(self):
        self.cancel_after_first_stock()
        Path(self.fund.OUTPUT_FILE).unlink()
        self.store.resume(self.job["id"])
        result = run_once(self.store)
        self.assertEqual(result["error"]["code"], "CHECKPOINT_CONFLICT")

    def test_resume_retries_failed_stock_only(self):
        def fetch(code, *args, **kwargs):
            if code == "000002":
                raise RuntimeError("synthetic failure")
            return self.rows(code)
        with patch.object(self.fund, "_fetch_stock", side_effect=fetch):
            result = run_once(self.store)
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["result"]["failed"], ["000002"])
        self.store.resume(self.job["id"])
        with patch.object(self.fund, "_fetch_stock", side_effect=self.rows) as calls:
            result = run_once(self.store)
        self.assertEqual(result["state"], "completed")
        self.assertEqual([call.args[0] for call in calls.call_args_list], ["000002"])

    def test_sync_collector_cannot_write_while_worker_lock_is_held(self):
        errors = []
        def sync():
            try:
                self.fund.collect_fundamental(allow_unverified_pool=True)
            except DataQualityError as exc:
                errors.append(exc.code)
        with workspace_lock(self.store.data):
            thread = threading.Thread(target=sync)
            thread.start()
            thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ["WORKSPACE_BUSY"])
        self.assertFalse(Path(self.fund.OUTPUT_FILE).exists())

    def test_frozen_pool_can_resume_after_cache_age_passes(self):
        from datetime import timedelta

        from mcp_server import quality
        self.store.cancel(self.job["id"])
        pool = Path(self.fund.POOL_FILE)
        stamp = utc_now()
        write_snapshot(pool, pool.read_bytes(), {"fetched_at": stamp.isoformat(), "completeness": "complete"})
        self.job = self.store.submit("fundamental")
        self.cancel_after_first_stock()
        self.store.resume(self.job["id"])
        with (patch.object(quality, "utc_now", return_value=stamp + timedelta(minutes=10)),
              patch.object(self.fund, "_fetch_stock", side_effect=self.rows)):
            result = run_once(self.store)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["result"]["pool_quality"]["cache_state"], "stale")


class JobProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_submit_read_cancel_without_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "workspace"
            args = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                         env=dict(os.environ, **{ENV_KEY: str(root)}))
            async with asyncio.timeout(25), stdio_client(args) as streams, ClientSession(streams[0], streams[1]) as client:
                await client.initialize()
                response = await client.call_tool("list_crawler_jobs", {})
                self.assertEqual(json.loads(response.content[0].text)["result"], [])
                self.assertFalse(root.exists())
                response = await client.call_tool("submit_crawler_job", {"kind": "catalog", "request_key": "mcp"})
                job = json.loads(response.content[0].text)["result"]
                self.assertEqual(job["state"], "queued")
                response = await client.call_tool("cancel_crawler_job", {"job_id": job["id"]})
                self.assertEqual(json.loads(response.content[0].text)["result"]["state"], "cancelled")
