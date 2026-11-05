import json
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from stock_predict_mailer.agent_service.contracts import ServiceError
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
