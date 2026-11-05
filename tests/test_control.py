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

from cryptography.fernet import Fernet

from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.control.mcp_layer import MCPLayer, schema_check
from stock_predict_mailer.control.models import Budget, effective_temperature
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
