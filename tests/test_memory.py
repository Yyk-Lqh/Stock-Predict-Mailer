import time
import unittest
from unittest.mock import AsyncMock, patch

import test_control
from stock_predict_mailer.agent_service.adapters import MockContextAdapter, MockPredictionAdapter


class MemoryFlowTests(unittest.TestCase):
    setUp = test_control.ConsoleAPITests.setUp
    tearDown = test_control.ConsoleAPITests.tearDown

    def access(self):
        result = self.client.post("/api/memory/access").json()
        self.client.headers["X-Memory-Key"] = result["key"]
        return result["key"]

    def conversation(self):
        response = self.client.post("/api/conversations")
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def run_task(self, cid, **fields):
        response = self.client.post("/api/tasks", json={"conversation_id": cid, **fields})
        self.assertEqual(response.status_code, 202, response.text)
        tid = response.json()["id"]
        for _ in range(150):
            task = self.client.get(f"/api/tasks/{tid}").json()
            if task["status"]["state"] in ("completed", "failed", "canceled"):
                break
            time.sleep(.02)
        self.assertEqual(task["status"]["state"], "completed", task)
        for _ in range(100):
            if tid not in self.server.engine.active:
                break
            time.sleep(.01)
        return tid, task["artifacts"][0]["parts"][0]["data"]["analysis"]

    def test_compacts_and_resumes_validated_steps_with_exact_conditions(self):
        self.access()
        cid = self.conversation()
        self.client.put("/api/memory/settings", json={"enabled": True, "context_bytes": 1024, "recent_turns": 1})
        profile = self.f.mcp()
        settings = self.f.store.settings()
        settings["agents"]["main"]["tools"] = [profile["id"] + ":get_context"]
        self.f.store.save_settings(settings)
        prediction = {**MockPredictionAdapter().fetch(), "value": 12.25, "value_unit": "CNY"}
        constraints = ["预测周期保持 5 个交易日", "以 CNY 报告，保留 12.25"]
        with patch.object(self.server.engine.mcp, "call", new=AsyncMock(return_value=MockContextAdapter().fetch())) as tool:
            self.run_task(cid, prediction=prediction, constraints=constraints, message="请保持预测周期。")
            for _ in range(3):
                tid, analysis = self.run_task(cid, message="刚才那只股票，按前面的条件继续分析")
            self.assertEqual(tool.await_count, 1)
        self.assertEqual(analysis["prediction"]["subject"], prediction["subject"])
        self.assertEqual(analysis["prediction"]["horizon"], prediction["horizon"])
        self.assertEqual(analysis["user_constraints"], constraints)
        session = self.client.get(f"/api/conversations/{cid}").json()
        earliest = session["summary"][0]
        self.assertEqual(earliest["prediction"]["value"], 12.25)
        self.assertEqual(earliest["prediction"]["value_unit"], "CNY")
        self.assertEqual(earliest["steps"]["tools"], "completed")
        self.assertTrue(earliest["facts"][0]["source"])
        events = self.client.get(f"/api/tasks/{tid}/events").json()["events"]
        self.assertTrue(any("已压缩" in event["label"] for event in events))
        self.assertTrue(any("复用" in event["label"] for event in events))
