"""A2A knowledge search: read-only, role-scoped, and denied by default."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from stock_predict_mailer.control.a2a import A2AService, card
from stock_predict_mailer.control.orchestrator import Orchestrator
from stock_predict_mailer.control.store import Store

META = {"document_date": "2026-10-01", "available_date": "2026-10-01"}


class Fixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root, Fernet.generate_key())
        self.engine = Orchestrator(self.store)
        access = self.engine.memory.create_owner()
        self.owner, self.key = access["owner"], access["key"]
        self.kb = self.engine.knowledge

    def ready(self, logical, body):
        doc = self.kb.upload(self.owner, logical.rsplit("/", 1)[-1] + ".txt", body.encode(), META, logical)
        result = self.kb.process_one()
        if result is None or result["status"] != "ready":
            raise AssertionError(result)
        return doc["id"]

    def grant(self, role, domains):
        settings = self.store.settings()
        settings["agents"][role]["knowledge_domains"] = domains
        self.store.save_settings(settings)

    def ask(self, role, params, key=None):
        rpc = {"jsonrpc": "2.0", "id": "1", "method": "knowledge/search", "params": params}
        return asyncio.run(A2AService(self.engine).dispatch(rpc, role, owner_key=self.key if key is None else key))

    def close(self):
        self.tmp.cleanup()


class A2AKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(self.f.close)
        self.f.ready("研报/中金公司/半导体设备跟踪", "半导体设备国产化率提升，供应链风险可控")
        self.f.ready("公告/甲公司/回购股份", "甲公司回购股份，供应链风险未提及")

    def test_every_role_is_denied_until_granted(self):
        for role in ("main", "prediction", "risk", "advice"):
            error = self.f.ask(role, {"query": "供应链风险"})["error"]
            self.assertEqual((error["code"], error["data"]["code"]), (-32003, "PERMISSION_DENIED"))

    def test_role_reads_only_granted_domains(self):
        self.f.grant("risk", ["研报"])
        result = self.f.ask("risk", {"query": "供应链风险"})["result"]
        self.assertEqual(result["domains"], ["研报"])
        self.assertEqual((result["role"], result["effect"]), ("risk", "read"))
        self.assertTrue(result["results"])
        self.assertTrue(all(item["logical"].startswith("研报/") for item in result["results"]))
        self.assertTrue(all(group["logical"].startswith("研报/") for group in result["groups"]))

    def test_limit_counts_only_permitted_versions(self):
        self.f.ready("研报/中信证券/产能跟踪", "产能扩张与供应链风险并存")
        self.f.grant("risk", ["研报"])
        result = self.f.ask("risk", {"query": "供应链风险", "limit": 1})["result"]
        self.assertEqual(len(result["results"]), 1)
        # 三份资料里只有两份属于研报；越权的公告版本不计入命中数。
        self.assertEqual((result["logical_total"], result["limit"]), (2, 1))

    def test_unknown_role_and_missing_key_are_refused(self):
        self.assertEqual(self.f.ask("hacker", {"query": "供应链"})["error"]["data"]["code"], "PERMISSION_DENIED")
        self.f.grant("risk", ["研报"])
        self.assertEqual(self.f.ask("risk", {"query": "供应链"}, key="")["error"]["data"]["code"], "FORBIDDEN")
        self.assertEqual(self.f.ask("risk", {"query": "供应链"}, key="not-a-key")["error"]["data"]["code"], "FORBIDDEN")

    def test_params_are_validated(self):
        self.f.grant("risk", ["研报"])
        for params in ({}, {"query": "供应链", "domains": ["公告"]}, {"query": "供应链", "limit": 21},
                       {"query": "供应链", "as_of": "2026/10/01"}):
            body = self.f.ask("risk", params)
            self.assertIn("error", body, params)
            self.assertIn(body["error"]["data"]["code"], ("INVALID_PARAMS", "INVALID_INPUT"))

    def test_card_advertises_read_only_search(self):
        skills = {skill["id"]: skill for skill in card("http://127.0.0.1:8767", "risk")["skills"]}
        self.assertIn("knowledge.search", skills)
        self.assertIn("read", skills["knowledge.search"]["tags"])
        self.assertIn("X-Memory-Key", skills["knowledge.search"]["description"])


if __name__ == '__main__':
    unittest.main()
