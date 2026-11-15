"""Instance ownership/lifecycle tests use only isolated synthetic workspaces."""
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
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from mcp_server.job_worker import run_once
from mcp_server.jobs import JobStore
from stock_predict_mailer.agent_service.config import load
from stock_predict_mailer.agent_service.contracts import ServiceError, utcnow
from stock_predict_mailer.cli import main
from stock_predict_mailer.operations import components, lifecycle, processes
from stock_predict_mailer.operations.components import Component, directory, logs, request_stop, status
from stock_predict_mailer.operations.diagnostics import diagnose
from stock_predict_mailer.private_knowledge.service import Knowledge
from stock_predict_mailer.private_knowledge.worker import run as knowledge_run


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root, self.crawler = self.base / "app", self.base / "crawler"
        self.config = self.base / "agent.toml"
        self.config.write_text('workspace="app"\n[mail]\ntransport="file"\nsender="preview@example.invalid"\n', encoding="utf-8")
        self.cfg = load(self.config)
        environment = patch.dict(os.environ, {"STOCK_PREDICT_MAILER_MASTER_KEY": "", "SPM_MASTER_KEY": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.addCleanup(self.cleanup_components)

    def cleanup_components(self):
        for name in components.COMPONENTS:
            root = self.crawler if name == "crawler_worker" else self.root
            view = status(root, name)
            if view["ownership"] == "verified":
                lifecycle.stop(root, name, view["instance"], wait=10)

    def code(self, code, function, *args, **kwargs):
        with self.assertRaises(ServiceError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def read_record(self, name="console", root=None):
        return json.loads((directory(root or self.root, name) / "state.json").read_text(encoding="utf-8"))

    def change_record(self, **values):
        record = self.read_record()
        record.update(values)
        (directory(self.root, "console") / "state.json").write_text(json.dumps(record), encoding="utf-8")

    def free_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def start(self, name, **kwargs):
        return lifecycle.start(self.cfg, self.config, name, crawler_workspace=self.crawler, poll=.2, **kwargs)

    def test_process_creation_identity_is_stable_and_pid_validation_is_strict(self):
        state, birth = processes.birth(os.getpid())
        self.assertEqual(state, "alive")
        self.assertTrue(birth)
        self.assertEqual(processes.birth(os.getpid()), (state, birth))
        for invalid in (0, -1, True, "123", 2**40):
            self.assertEqual(processes.birth(invalid), ("unknown", None))

    def test_status_and_logs_on_empty_workspace_create_nothing(self):
        self.assertEqual(status(self.root, "console")["state"], "not_registered")
        self.assertEqual(logs(self.root, "console"), [])
        self.assertFalse(self.root.exists())

    def test_duplicate_component_does_not_replace_owner_or_release_its_lock(self):
        with Component(self.root, "console", interval=10) as lease:
            lease.phase("running")
            self.code("RUNTIME_BUSY", Component(self.root, "console").__enter__)
            self.assertEqual(status(self.root, "console")["instance"], lease.instance)
            self.assertEqual(status(self.root, "console")["state"], "verified")

    def test_independent_components_do_not_share_lifetime_locks(self):
        with Component(self.root, "console") as console, Component(self.root, "knowledge_worker") as worker:
            console.phase("running")
            worker.phase("idle")
            self.assertEqual(status(self.root, "knowledge_worker")["state"], "verified")
            self.assertEqual(status(self.root, "console")["state"], "verified")

    def test_heartbeat_updates_while_main_thread_is_idle(self):
        with Component(self.root, "console", interval=.05) as lease:
            first = self.read_record()["updated_at"]
            self.assertFalse(lease.wait(.16))
            self.assertNotEqual(self.read_record()["updated_at"], first)

    def test_stale_heartbeat_does_not_mean_process_is_dead(self):
        with Component(self.root, "console", interval=10) as lease:
            lease.phase("running")
            self.change_record(started_at=(utcnow() - timedelta(minutes=1)).isoformat(), updated_at=(utcnow() - timedelta(seconds=20)).isoformat())
            view = status(self.root, "console")
            self.assertEqual((view["state"], view["ownership"]), ("stale", "verified"))

    def test_future_heartbeat_is_clock_skew(self):
        with Component(self.root, "console", interval=10):
            self.change_record(updated_at=(utcnow() + timedelta(minutes=1)).isoformat())
            self.assertEqual(status(self.root, "console")["state"], "clock_skew")

    def test_reused_pid_is_never_stopped(self):
        with Component(self.root, "console", interval=10) as lease, patch.object(components, "birth", return_value=("alive", "different-birth")):
            self.assertEqual(status(self.root, "console")["state"], "pid_reused")
            self.code("RUNTIME_UNVERIFIED", request_stop, self.root, "console", lease.instance)
            self.assertFalse((lease.folder / "stop.json").exists())

    def test_permission_unknown_and_different_host_refuse_control(self):
        with Component(self.root, "console", interval=10) as lease:
            with patch.object(components, "birth", return_value=("unknown", None)):
                self.assertEqual(status(self.root, "console")["state"], "unknown")
                self.code("RUNTIME_UNVERIFIED", request_stop, self.root, "console", lease.instance)
            self.change_record(host="0" * 64)
            self.assertEqual(status(self.root, "console")["state"], "different_host")
            self.code("RUNTIME_UNVERIFIED", request_stop, self.root, "console", lease.instance)

    def test_missing_lease_lock_is_not_verified_by_pid_alone(self):
        with Component(self.root, "console", interval=10):
            record = self.read_record()
        record["phase"] = "running"
        (directory(self.root, "console") / "state.json").write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(status(self.root, "console")["state"], "unknown")

    def test_corrupt_extra_and_cross_workspace_records_are_redacted(self):
        with Component(self.root, "console", interval=10):
            record = self.read_record()
        folder = directory(self.root, "console")
        (folder / "state.json").write_text('{"private-secret":', encoding="utf-8")
        self.assertNotIn("private-secret", json.dumps(status(self.root, "console")))
        (folder / "state.json").write_text(json.dumps(dict(record, secret="private-secret")), encoding="utf-8")
        self.assertEqual(status(self.root, "console")["state"], "invalid_record")
        (folder / "state.json").write_text(json.dumps(dict(record, workspace=str(self.crawler))), encoding="utf-8")
        self.assertEqual(status(self.root, "console")["state"], "invalid_record")

    def test_unknown_components_and_private_configuration_are_rejected_without_writes(self):
        self.code("INVALID_INPUT", Component, self.root, "../../other")
        self.code("INVALID_INPUT", Component, self.root, "console", {"password": "private-secret"})
        self.code("INVALID_INPUT", Component, self.root, "console", [], interval=.05)
        self.code("INVALID_INPUT", Component, self.root, "console", interval=float("nan"))
        self.assertFalse(self.root.exists())

    def test_wrong_instance_stop_is_noop_and_cross_workspace_is_not_created(self):
        with Component(self.root, "console") as lease:
            self.code("RUNTIME_INSTANCE_CHANGED", request_stop, self.root, "console", "a" * 32)
            self.code("RUNTIME_INSTANCE_CHANGED", request_stop, self.crawler, "console", lease.instance)
            self.assertFalse((lease.folder / "stop.json").exists())
            self.assertFalse(self.crawler.exists())

    def test_old_stop_requests_do_not_stop_new_instances(self):
        with Component(self.root, "console", interval=.05) as first:
            request_stop(self.root, "console", first.instance)
            self.assertTrue(first.wait(1))
        with Component(self.root, "console", interval=.05) as second:
            self.assertNotEqual(first.instance, second.instance)
            self.assertFalse(second.wait(.15))
            request_stop(self.root, "console", second.instance)
            self.assertTrue(second.wait(1))
        self.assertEqual(status(self.root, "console")["state"], "stopped")

    def test_nonblocking_stop_returns_only_request_and_never_signals_pid(self):
        with Component(self.root, "console", interval=.05) as lease, patch("os.kill", side_effect=AssertionError("no signals")):
            result = lifecycle.stop(self.root, "console", lease.instance, wait=0)
            self.assertEqual(result["state"], "stop_requested")
            self.assertTrue(lease.wait(1))

    def test_bounded_stop_wait_does_not_claim_unfinished_component_stopped(self):
        with Component(self.root, "console", interval=10) as lease:
            result = lifecycle.stop(self.root, "console", lease.instance, wait=.1)
            self.assertEqual((result["state"], result["timed_out"]), ("stopping", True))
            self.assertEqual(status(self.root, "console")["ownership"], "verified")

    def test_component_failure_logs_only_fixed_events(self):
        with self.assertRaises(RuntimeError):
            with Component(self.root, "console"):
                raise RuntimeError("private-provider-response-and-password")
        self.assertEqual(status(self.root, "console")["state"], "failed")
        self.assertEqual(logs(self.root, "console")[-1]["event"], "failed")
        self.assertNotIn("private-provider", (directory(self.root, "console") / "events.jsonl").read_text())

    def test_heartbeat_write_failure_stops_component_and_marks_failed(self):
        with Component(self.root, "console", interval=.05) as lease:
            with patch.object(components, "atomic_write", side_effect=OSError("private-storage-error")):
                self.assertTrue(lease.wait(1))
        self.assertEqual(status(self.root, "console")["state"], "failed")
        self.assertIn("heartbeat_failed", [e["event"] for e in logs(self.root, "console")])

    def test_log_rotation_is_bounded_and_limit_selects_latest_events(self):
        with patch.object(components, "LOG_BYTES", 512):
            with Component(self.root, "console") as lease:
                for index in range(40):
                    lease.phase("busy" if index % 2 else "idle")
            paths = list(lease.folder.glob("events.jsonl*"))
            self.assertLessEqual(len(paths), 4)
            self.assertTrue(all(path.stat().st_size <= 512 for path in paths))
            selected = logs(self.root, "console", 2)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[-1]["event"], "stopped")

    def test_unknown_or_oversized_log_content_is_not_returned(self):
        with Component(self.root, "console") as lease:
            pass
        path = lease.folder / "events.jsonl"
        path.write_text('{"password":"private-log-value"}\n', encoding="utf-8")
        self.code("RUNTIME_LOG_INVALID", logs, self.root, "console")
        path.write_bytes(b"x" * (components.LOG_BYTES + components.MAX_RECORD + 1))
        self.code("RUNTIME_LOG_INVALID", logs, self.root, "console")
        self.code("INVALID_INPUT", logs, self.root, "console", 0)

    def test_start_refuses_oversized_existing_logs_without_overwriting(self):
        folder = directory(self.root, "console")
        folder.mkdir(parents=True)
        path = folder / "events.jsonl"
        original = b"x" * (components.LOG_BYTES + components.MAX_RECORD + 1)
        path.write_bytes(original)
        self.code("RUNTIME_LOG_INVALID", Component(self.root, "console").__enter__)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((folder / "state.json").exists())

    def test_doctor_verifies_idle_registered_worker_without_socket_or_store_writes(self):
        JobStore(self.crawler).submit("catalog")
        with Component(self.crawler, "crawler_worker") as lease:
            lease.phase("idle")
            with patch("socket.socket", side_effect=AssertionError("offline doctor")):
                report = diagnose(self.cfg, crawler_workspace=self.crawler, check_port=False)
        checks = [c for c in report["checks"] if c["component"] == "crawler_worker"]
        self.assertTrue(any(c["code"] == "COMPONENT_VERIFIED" for c in checks))
        self.assertTrue(any(c["code"] == "WORKER_CONFIRMED" and c["status"] == "info" for c in checks))

    def test_crawler_cooperative_stop_preserves_interruption_without_executing_or_resuming(self):
        store = JobStore(self.crawler)
        job = store.submit("catalog")
        event = threading.Event()
        event.set()
        execute = Mock(side_effect=AssertionError("must not collect"))
        result = run_once(store, execute, stop_event=event)
        self.assertEqual(result["state"], "interrupted")
        self.assertEqual(store.get(job["id"])["state"], "interrupted")
        execute.assert_not_called()

    def test_lifetime_registration_does_not_block_crawler_business_lock(self):
        store = JobStore(self.crawler)
        store.submit("catalog")
        with Component(self.crawler, "crawler_worker"):
            result = run_once(store, lambda *args: {"ok": True})
        self.assertEqual(result["state"], "completed")

    def test_knowledge_stop_waits_for_current_task_boundary(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def process_one(*args, **kwargs):
            entered.set()
            release.wait(5)
            return {"status": "ready"}
        def worker():
            try:
                knowledge_run(self.root, poll=.1)
            except BaseException as exc:
                errors.append(type(exc).__name__)
        with patch.object(Knowledge, "process_one", side_effect=process_one) as process:
            thread = threading.Thread(target=worker)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                view = status(self.root, "knowledge_worker")
                result = lifecycle.stop(self.root, "knowledge_worker", view["instance"], wait=.1)
                self.assertEqual(result["state"], "stopping")
                self.assertTrue(thread.is_alive())
            finally:
                release.set()
                thread.join(8)
            self.assertFalse(thread.is_alive())
            self.assertEqual(process.call_count, 1)
        self.assertEqual(errors, [])
        self.assertEqual(status(self.root, "knowledge_worker")["state"], "stopped")

    def test_managed_console_start_idempotence_conflict_doctor_and_stop(self):
        port = self.free_port()
        view = self.start("console", port=port)
        self.assertEqual((view["state"], view["phase"]), ("verified", "running"))
        self.assertTrue(self.start("console", port=port)["already_running"])
        self.code("RUNTIME_CONFIG_CONFLICT", self.start, "console", port=self.free_port())
        report = diagnose(self.cfg, crawler_workspace=self.crawler, port=port)
        self.assertIn("PORT_REGISTERED_COMPONENT", {c["code"] for c in report["checks"]})
        self.assertEqual(lifecycle.stop(self.root, "console", view["instance"], wait=8)["state"], "stopped")

    def test_shutdown_admission_rejects_new_tasks_before_preparation_or_provider_calls(self):
        from stock_predict_mailer.control.orchestrator import Orchestrator
        from stock_predict_mailer.control.store import Store
        engine = Orchestrator(Store(self.root))
        self.assertEqual(engine.close_admission(), [])
        with patch.object(engine, "prepare", side_effect=AssertionError("no new task effects")):
            self.code("SERVICE_STOPPING", engine.submit, {})
        self.assertEqual(engine.active, {})

    def test_console_lease_remains_stopping_until_active_task_unwinds(self):
        from stock_predict_mailer.control.server import serve
        called = threading.Event()
        engine = Mock()
        engine.active = {"task": {}}
        engine.close_admission.return_value = ["task"]
        engine.cancel.side_effect = lambda tid: called.set()
        server = Mock(engine=engine, server_port=8767)
        server.handle_request.side_effect = lambda: time.sleep(.01)
        errors = []
        def runner():
            try:
                serve(self.root)
            except BaseException as exc:
                errors.append(type(exc).__name__)
        with patch("stock_predict_mailer.control.server.make_server", return_value=server), redirect_stdout(io.StringIO()):
            thread = threading.Thread(target=runner)
            thread.start()
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    view = status(self.root, "console")
                    if view["state"] == "verified":
                        break
                    time.sleep(.02)
                request_stop(self.root, "console", view["instance"])
                self.assertTrue(called.wait(3))
                self.assertTrue(thread.is_alive())
                self.assertEqual(status(self.root, "console")["phase"], "stopping")
            finally:
                engine.active.clear()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(status(self.root, "console")["state"], "stopped")

    def test_managed_empty_crawler_has_heartbeat_without_creating_job_database(self):
        view = self.start("crawler_worker")
        self.assertEqual(view["state"], "verified")
        self.assertFalse(JobStore(self.crawler).path.exists())
        self.assertEqual(lifecycle.stop(self.crawler, "crawler_worker", view["instance"], wait=8)["state"], "stopped")

    def test_managed_empty_knowledge_worker_starts_and_stops(self):
        view = self.start("knowledge_worker")
        self.assertEqual(view["state"], "verified")
        self.assertTrue((self.root / "private-knowledge" / "knowledge.sqlite3").exists())
        self.assertEqual(lifecycle.stop(self.root, "knowledge_worker", view["instance"], wait=8)["state"], "stopped")

    def test_occupied_port_never_launches_or_initializes_console(self):
        with socket.socket() as sock, patch("subprocess.Popen", side_effect=AssertionError("no adoption")):
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            self.code("RUNTIME_PORT_UNAVAILABLE", self.start, "console", port=sock.getsockname()[1])
        self.assertFalse((self.root / "control-development.sqlite3").exists())

    def test_start_does_not_overwrite_invalid_registry(self):
        folder = directory(self.root, "console")
        folder.mkdir(parents=True)
        (folder / "state.json").write_text("private-invalid-registry", encoding="utf-8")
        with patch("subprocess.Popen", side_effect=AssertionError("no unknown ownership")):
            self.code("RUNTIME_UNVERIFIED", self.start, "console")

    def test_dead_process_record_survives_crash_and_allows_explicit_new_instance(self):
        script = "from pathlib import Path; import os; from stock_predict_mailer.operations.components import Component; c=Component(Path(os.environ['FIXTURE_ROOT']),'console'); c.__enter__(); os._exit(7)"
        env = {**os.environ, "FIXTURE_ROOT": str(self.root)}
        result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 7)
        previous = status(self.root, "console")
        self.assertEqual(previous["state"], "dead")
        self.code("RUNTIME_UNVERIFIED", request_stop, self.root, "console", previous["instance"])
        current = self.start("console", port=self.free_port())
        self.assertNotEqual(current["instance"], previous["instance"])

    def test_invalid_launch_arguments_are_rejected(self):
        for port in (0, -1, True, 65536):
            self.code("INVALID_INPUT", self.start, "console", port=port)
        self.code("INVALID_INPUT", lifecycle.start, self.cfg, self.config, "crawler_worker", poll=45)
        self.code("INVALID_INPUT", lifecycle.stop, self.root, "console", "x", wait=float("nan"))

    def test_child_refuses_changed_workspace_before_service_initialization(self):
        from stock_predict_mailer.operations.launcher import main as launch
        changed = self.base / "other.toml"
        changed.write_text('workspace="other"', encoding="utf-8")
        code = launch(["--config", str(changed), "--workspace", str(self.root), "--root", str(self.root), "--component", "console",
            "--instance", "a" * 32, "--port", "8767", "--poll", "2"])
        self.assertEqual(code, 2)
        self.assertFalse((self.base / "other").exists())

    def test_cli_status_logs_and_stop_require_fenced_instance(self):
        def invoke(*args):
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--config", str(self.config), "runtime", *args])
            return code, json.loads(output.getvalue())
        self.assertEqual(invoke("status", "console")[1]["state"], "not_registered")
        self.assertEqual(invoke("logs", "console")[1]["events"], [])
        self.assertFalse(self.root.exists())
        with Component(self.root, "console", interval=.05) as lease:
            lease.phase("running")
            self.assertEqual(invoke("status", "console")[0], 0)
            self.assertEqual(invoke("stop", "console", "--instance", "b" * 32)[0], 2)
            code, result = invoke("stop", "console", "--instance", lease.instance, "--wait", "0")
            self.assertEqual((code, result["state"]), (0, "stop_requested"))
            self.assertTrue(lease.wait(1))


if __name__ == "__main__":
    unittest.main()
