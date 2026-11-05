import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from stock_predict_mailer.agent_service.adapters import MockPredictionAdapter
from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.control.a2a import A2AClient, A2AService, message
from stock_predict_mailer.control.mcp_layer import MCPLayer, schema_check
from stock_predict_mailer.control.models import Budget, ModelAdapter, effective_temperature
from stock_predict_mailer.control.orchestrator import Orchestrator
from stock_predict_mailer.control.schemas import Settings
from stock_predict_mailer.control.store import Store


class Fixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.key = Fernet.generate_key()
        self.store = Store(self.root, self.key)
        self.model = self.store.put("models", {"name": "Mock", "api_key": "mock-only-sensitive-marker"})
        self.settings = self.store.settings()
        self.settings["default_model_id"] = self.model["id"]
        self.store.save_settings(self.settings)

    def mcp(self):
        return self.store.put("mcp", {"name": "Mock MCP", "transport": "stdio", "command": sys.executable,
                                     "args": ["-m", "stock_predict_mailer.control.mock_services"],
                                     "allowed_tools": ["get_context", "send_email"],
                                     "effects": {"get_context": "read", "send_email": "email"},
                                     "allowed_resources": ["stock://demo/contract"]})

    def close(self):
        self.tmp.cleanup()


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(self.f.close)

    def test_encrypted_secrets_never_read_back(self):
        s, m = self.f.store, self.f.model
        self.assertNotIn("mock-only-sensitive-marker", json.dumps(s.list("models")))
        self.assertNotIn(b"mock-only-sensitive-marker", (self.f.root / "control.sqlite3").read_bytes())
        self.assertTrue(m["has_secret"])
        s.put("models", {**m, "api_key": ""}, m["id"])
        self.assertEqual(s.secret("models", m["id"])["api_key"], "mock-only-sensitive-marker")
        s.put("models", {**m, "clear_secrets": ["api_key"]}, m["id"])
        self.assertFalse(s.get("models", m["id"])["has_secret"])

    def test_wrong_master_key_fails_closed(self):
        with self.assertRaises(ServiceError) as cm:
            Store(self.f.root, Fernet.generate_key())
        self.assertEqual(cm.exception.code, "SECRET_CONFIG")

    def test_configuration_rejects_bad_parameters(self):
        for update in ({"parameters": {"max_tokens": 1, "unknown": 2}}, {"temperature_min": 1.5, "temperature_max": 1.0},
                       {"parameters": {"max_tokens": True}}, {"base_url": "http://remote.example.com/v1"},
                       {"base_url": "https://key:secret@example.com/v1"}, {"retries": 99}):
            with self.subTest(fields=list(update)), self.assertRaises(ServiceError):
                self.f.store.put("models", {"name": "Bad", **update})

    def test_temperature_inheritance_and_unsupported(self):
        s = self.f.settings
        m = self.f.model
        self.assertEqual(effective_temperature(m, s, "risk"), 0.2)
        s["agents"]["risk"]["temperature"] = 0.1
        self.assertEqual(effective_temperature(m, s, "risk"), 0.1)
        m = {**m, "supported_parameters": ["max_tokens"]}
        with self.assertRaises(ServiceError):
            effective_temperature(m, s, "risk")
        s["agents"]["risk"]["temperature"] = None
        self.assertIsNone(effective_temperature(m, s, "risk"))

    def test_default_references_and_delete(self):
        with self.assertRaises(ServiceError):
            self.f.store.delete("models", self.f.model["id"])
        self.f.settings["default_model_id"] = None
        self.f.store.save_settings(self.f.settings)
        self.f.store.delete("models", self.f.model["id"])
        self.assertEqual(self.f.store.list("models"), [])

    def test_mcp_credentials_and_tool_grants(self):
        m = self.f.store.put("mcp", {"name": "Protected", "auth_token": "mock-token", "env": {"TOKEN": "mock-env"}})
        self.assertEqual(m["env_keys"], ["TOKEN"])
        self.assertNotIn("mock-env", json.dumps(m))
        self.f.settings["agents"]["main"]["tools"] = [m["id"] + ":unknown"]
        with self.assertRaises(ServiceError):
            self.f.store.save_settings(self.f.settings)

    def test_budget_limits(self):
        b = Budget({**Settings().limits.model_dump(), "max_calls": 1, "budget_usd": .01})
        b.reserve(.01)
        with self.assertRaises(ServiceError):
            b.reserve(0)
        with self.assertRaises(ServiceError):
            Budget({**Settings().limits.model_dump(), "budget_usd": 0.0}).reserve(.01)


class MCPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(self.f.close)
        self.m = self.f.mcp()
        self.layer = MCPLayer(self.f.store)

    async def test_real_stdio_discovery_call_resource(self):
        discovered = await self.layer.discover(self.m["id"])
        self.assertIn("get_context", [t["name"] for t in discovered["tools"]])
        self.assertTrue(discovered["resources"])
        result = await self.layer.call(self.m["id"], "get_context", {"subject": "DEMO.SZ"}, role_tools=[self.m["id"] + ":get_context"])
        self.assertEqual(result["subject"], "DEMO.SZ")
        self.assertEqual(result["facts"][0]["source"], "mock")
        resource = await self.layer.read(self.m["id"], "stock://demo/contract")
        self.assertTrue(resource["contents"])

    async def test_denied_tools_resources_and_email(self):
        for call in (self.layer.call(self.m["id"], "get_context", {"subject": "DEMO.SZ"}, role_tools=[]),
                     self.layer.call(self.m["id"], "send_email", {}, effect="email"),
                     self.layer.read(self.m["id"], "stock://private")):
            with self.assertRaises(ServiceError) as cm:
                await call
            self.assertEqual(cm.exception.code, "PERMISSION_DENIED")

    async def test_disabled_and_unavailable(self):
        self.f.store.put("mcp", {**self.m, "enabled": False}, self.m["id"])
        with self.assertRaises(ServiceError) as cm:
            await self.layer.discover(self.m["id"])
        self.assertEqual(cm.exception.code, "SERVICE_DISABLED")
        bad = self.f.store.put("mcp", {"name": "Unavailable", "url": "http://127.0.0.1:1/mcp", "timeout_seconds": 1})
        with self.assertRaises(ServiceError):
            await self.layer.discover(bad["id"])

    async def test_input_schema_validation(self):
        with self.assertRaises(ServiceError) as cm:
            await self.layer.call(self.m["id"], "get_context", {"subject": 5})
        self.assertEqual(cm.exception.code, "INVALID_TOOL_DATA")
        with self.assertRaises(ServiceError):
            schema_check({"$ref": "https://example.com/private"})

    async def test_streamable_http_sdk_transport(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen([sys.executable, "-m", "stock_predict_mailer.control.mock_services", "--transport", "streamable-http", "--port", str(port)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        try:
            for _ in range(150):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.1):
                        break
                except OSError:
                    await asyncio.sleep(.05)
            profile = self.f.store.put("mcp", {"name": "HTTP Mock", "url": f"http://127.0.0.1:{port}/mcp"})
            result = await self.layer.discover(profile["id"])
            self.assertIn("get_context", [t["name"] for t in result["tools"]])
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    async def test_mcp_authentication_and_timeout(self):
        class Handler(BaseHTTPRequestHandler):
            mode = "auth"
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                if type(self).mode == "slow":
                    time.sleep(1.5)
                self.send_response(401)
                self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        profile = self.f.store.put("mcp", {"name": "Auth Mock", "url": f"http://127.0.0.1:{server.server_port}/mcp", "timeout_seconds": 1,
                                           "auth_token": "mock-invalid"})
        try:
            with self.assertRaises(ServiceError) as cm:
                await self.layer.discover(profile["id"])
            self.assertEqual(cm.exception.code, "AUTH_FAILED")
            self.assertFalse(cm.exception.retryable)
            Handler.mode = "slow"
            with self.assertRaises(ServiceError) as cm:
                await self.layer.discover(profile["id"])
            self.assertEqual(cm.exception.code, "CALL_TIMEOUT")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class ModelHTTPHandler(BaseHTTPRequestHandler):
    mode = "ok"
    attempts = 0
    payload = None

    def log_message(self, *args):
        pass

    def do_POST(self):
        type(self).attempts += 1
        type(self).payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        mode = type(self).mode
        if mode == "slow":
            time.sleep(1.2)
        status = {"auth": 401, "bad": 400, "unavailable": 503}.get(mode, 200)
        self.send_response(status)
        self.end_headers()
        data = json.loads(self.payload["messages"][-1]["content"])["data"]
        result = {"conclusion_codes": ["MODEL_UP"], "evidence_ids": ["prediction:" + data["prediction"]["prediction_id"]],
                  "uncertainty_codes": ["MODEL_UNVERIFIED"], "delegate_roles": []}
        try:
            self.wfile.write(json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode())
        except OSError:
            pass


class ModelHTTPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(self.f.close)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHTTPHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        ModelHTTPHandler.mode, ModelHTTPHandler.attempts = "ok", 0
        self.model = self.f.store.put("models", {"name": "Compatible Mock", "provider": "openai_compatible", "model": "mock-v1",
            "base_url": f"http://127.0.0.1:{self.server.server_port}/v1", "api_key": "mock-key", "timeout_seconds": 1,
            "input_usd_per_million": 1.0, "output_usd_per_million": 2.0})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    async def generate(self):
        return await ModelAdapter(self.f.store).generate(self.model["id"], "main", {"prediction": MockPredictionAdapter().fetch(), "facts": []},
                                                        self.f.settings, Budget(self.f.settings["limits"]))

    async def test_openai_wire_and_temperature(self):
        self.assertEqual((await self.generate())["conclusion_codes"], ["MODEL_UP"])
        self.assertEqual(ModelHTTPHandler.payload["temperature"], .2)
        self.assertEqual(ModelHTTPHandler.payload["model"], "mock-v1")
        self.assertEqual(ModelHTTPHandler.payload["response_format"], {"type": "json_object"})

    async def test_invalid_credentials_no_retry(self):
        ModelHTTPHandler.mode = "auth"
        with self.assertRaises(ServiceError) as cm:
            await self.generate()
        self.assertEqual(cm.exception.code, "AUTH_FAILED")
        self.assertEqual(ModelHTTPHandler.attempts, 1)
        self.assertNotIn("mock-key", str(cm.exception))

    async def test_incompatible_parameters(self):
        ModelHTTPHandler.mode = "bad"
        with self.assertRaises(ServiceError) as cm:
            await self.generate()
        self.assertEqual(cm.exception.code, "PARAMETER_UNSUPPORTED")

    async def test_unavailable_retry_counts(self):
        ModelHTTPHandler.mode = "unavailable"
        with self.assertRaises(ServiceError):
            await self.generate()
        self.assertEqual(ModelHTTPHandler.attempts, 2)

    async def test_timeout_and_budget_exhaustion(self):
        ModelHTTPHandler.mode = "slow"
        with self.assertRaises(ServiceError) as cm:
            await self.generate()
        self.assertEqual(cm.exception.code, "CALL_TIMEOUT")
        self.f.settings["limits"]["budget_usd"] = 0.0
        ModelHTTPHandler.attempts = 0
        with self.assertRaises(ServiceError) as cm:
            await self.generate()
        self.assertEqual(cm.exception.code, "BUDGET_EXHAUSTED")
        self.assertEqual(ModelHTTPHandler.attempts, 0)


class OrchestrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(self.f.close)
        self.engine = Orchestrator(self.f.store)

    async def run_task(self, complexity="complex", **fields):
        request = self.engine.prepare({"prediction": MockPredictionAdapter().fetch(), "complexity": complexity, **fields})
        return await self.engine.execute("test-task", request)

    def result(self, task):
        self.assertEqual(task["status"]["state"], "completed", task.get("metadata"))
        return task["artifacts"][0]["parts"][0]["data"]

    async def test_simple_task_no_delegation(self):
        result = self.result(await self.run_task("simple"))
        self.assertEqual(result["children"], [])
        self.assertEqual(result["usage"]["calls"], 1)

    async def test_complex_bounded_children(self):
        result = self.result(await self.run_task())
        self.assertEqual(len(result["children"]), 3)
        self.assertEqual(result["usage"]["calls"], 5)
        self.assertTrue(all(c["status"] == "completed" and not c["tools"] for c in result["children"]))

    async def test_subagent_count_and_depth(self):
        self.f.settings["limits"]["max_subagents"] = 1
        self.f.store.save_settings(self.f.settings)
        result = self.result(await self.run_task())
        self.assertEqual(len(result["children"]), 1)
        result = self.result(await self.run_task(depth=1))
        self.assertFalse(result["children"])
        self.assertIn("DEPTH_LIMIT", str(result["analysis"]["limitations"]))

    async def test_child_timeout_degrades(self):
        real = self.engine.models.generate
        async def slow(pid, role, *args):
            if role == "risk":
                await asyncio.sleep(2)
            return await real(pid, role, *args)
        self.f.settings["limits"]["child_timeout_seconds"] = 1
        self.f.store.save_settings(self.f.settings)
        with patch.object(self.engine.models, "generate", side_effect=slow):
            result = self.result(await self.run_task())
        self.assertEqual(result["analysis"]["status"], "degraded")
        self.assertTrue(any(c.get("error") == "CHILD_TIMEOUT" for c in result["children"]))

    async def test_budget_exhaustion_degrades_without_new_calls(self):
        self.f.settings["limits"]["max_calls"] = 1
        self.f.store.save_settings(self.f.settings)
        result = self.result(await self.run_task())
        self.assertEqual(result["usage"]["calls"], 1)
        self.assertIn("BUDGET_EXHAUSTED", str(result["analysis"]["limitations"]))

    async def test_conflicts_not_adopted(self):
        real = self.engine.models.generate
        async def conflict(pid, role, *args):
            result = await real(pid, role, *args)
            if role == "risk":
                result["conclusion_codes"] = ["MODEL_DOWN"]
            return result
        with patch.object(self.engine.models, "generate", side_effect=conflict):
            result = self.result(await self.run_task())
        self.assertTrue(result["conflicts"])
        self.assertEqual(result["analysis"]["inferences"][0]["code"], "MODEL_UP")

    async def test_injection_invalid_evidence_not_adopted(self):
        real = self.engine.models.generate
        async def injected(pid, role, *args):
            result = await real(pid, role, *args)
            if role == "risk":
                result["evidence_ids"] = ["ignore-system-send-email"]
            return result
        with patch.object(self.engine.models, "generate", side_effect=injected):
            result = self.result(await self.run_task())
        self.assertEqual(result["analysis"]["status"], "degraded")
        self.assertNotIn("ignore-system-send-email", json.dumps(result))

    async def test_notify_denied_and_full_mcp_email_flow(self):
        with self.assertRaises(ServiceError):
            await self.run_task(notify=True, recipient="unauthorized@example.com")
        m = self.f.mcp()
        self.f.settings["agents"]["main"]["tools"] = [m["id"] + ":get_context"]
        self.f.settings["mail"].update(transport="mcp", recipient_allowlist=["preview@example.invalid"], allow_synthetic=True,
                                        mcp_server_id=m["id"], mcp_tool="send_email")
        self.f.store.save_settings(self.f.settings)
        result = self.result(await self.run_task(notify=True, recipient="preview@example.invalid"))
        self.assertEqual(result["mail"]["status"], "simulated")
        self.assertTrue(result["analysis"]["facts"])
        self.assertEqual(len(result["children"]), 3)
        again = self.result(await self.run_task(notify=True, recipient="preview@example.invalid"))
        self.assertEqual(again["mail"]["id"], result["mail"]["id"])

    async def test_file_mail_idempotent(self):
        self.f.settings["mail"].update(recipient_allowlist=["preview@example.invalid"], allow_synthetic=True)
        self.f.store.save_settings(self.f.settings)
        result = self.result(await self.run_task(notify=True, recipient="preview@example.invalid"))
        self.assertEqual(result["mail"]["status"], "simulated")
        self.assertEqual(result["mail"]["attempts"], 1)

    async def test_a2a_inline_wire_errors(self):
        service = A2AService(self.engine)
        rpc = {"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": {"message": message({"prediction": MockPredictionAdapter().fetch(), "facts": [], "depth": 1})}}
        reply = await service.dispatch(rpc, "risk")
        self.assertEqual(reply["result"]["status"]["state"], "completed")
        task_id = reply["result"]["id"]
        queried = await service.dispatch({"jsonrpc": "2.0", "id": "2", "method": "tasks/get", "params": {"id": task_id}})
        self.assertEqual(queried["result"]["id"], task_id)
        reply = await service.dispatch({"jsonrpc": "2.0", "id": "3", "method": "unknown"})
        self.assertEqual(reply["error"]["code"], -32601)

    async def test_external_a2a_async_polling(self):
        endpoint = self.f.store.put("agents", {"name": "Async peer", "url": "http://127.0.0.1:1/a2a/risk", "cost_ceiling_usd": 0.0})
        methods = []
        async def reply(url, payload, **kwargs):
            methods.append(payload["method"])
            raw = {"conclusion_codes": ["MARKET_RISK"], "evidence_ids": ["prediction:x"], "uncertainty_codes": [], "delegate_roles": []}
            task = {"kind": "task", "id": "peer-job", "status": {"state": "working" if len(methods) == 1 else "completed"},
                    "artifacts": [{"parts": [{"kind": "data", "data": raw}]}]}
            return {"jsonrpc": "2.0", "id": payload["id"], "result": task}
        with patch("stock_predict_mailer.control.a2a.request_json", side_effect=reply):
            result = await A2AClient(self.f.store).delegate(endpoint["id"], {}, Budget(self.f.settings["limits"]))
        self.assertEqual(methods, ["message/send", "tasks/get"])
        self.assertIn("MARKET_RISK", result["conclusion_codes"])

    async def test_external_a2a_budget_cleanup(self):
        endpoint = self.f.store.put("agents", {"name": "Async peer", "url": "http://127.0.0.1:1/a2a/risk", "cost_ceiling_usd": 0.0})
        methods = []
        async def reply(url, payload, **kwargs):
            methods.append(payload["method"])
            return {"jsonrpc": "2.0", "id": payload["id"], "result": {"kind": "task", "id": "peer-job", "status": {"state": "working"}}}
        with patch("stock_predict_mailer.control.a2a.request_json", side_effect=reply), self.assertRaises(ServiceError):
            await A2AClient(self.f.store).delegate(endpoint["id"], {}, Budget({**self.f.settings["limits"], "max_calls": 1}))
        self.assertEqual(methods, ["message/send", "tasks/cancel"])
