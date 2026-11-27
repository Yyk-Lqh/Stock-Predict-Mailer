"""Saved workflow versions run through the real task and event APIs."""
import asyncio
import base64
import time
import unittest
import uuid
from unittest.mock import patch

import test_control
from stock_predict_mailer.agent_service.adapters import MockPredictionAdapter
from test_workflow import graph

MODE = {"X-Analysis-Mode": "professional"}
BASE = "/api/workflows/definitions"


class WorkflowChatTests(unittest.TestCase):
    setUp = test_control.ConsoleAPITests.setUp
    tearDown = test_control.ConsoleAPITests.tearDown

    def access(self):
        result = self.client.post("/api/memory/access").json()
        self.client.headers["X-Memory-Key"] = result["key"]
        return result["key"]

    def save(self, name, value=None, **extra):
        response = self.client.post(BASE, headers=MODE, json={"name": name, "graph": value or graph(), **extra})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def payload(self, flow, **parameters):
        return {"revision": flow["revision"], "key": uuid.uuid4().hex, "message": "核对预测和风险",
                "parameters": {"prediction": MockPredictionAdapter().fetch(), **parameters}}

    def submit(self, flow, payload):
        response = self.client.post(f"{BASE}/{flow['id']}/runs", headers=MODE, json=payload)
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()["id"]

    def terminal(self, tid):
        for _ in range(250):
            task = self.client.get(f"/api/tasks/{tid}", headers=MODE).json()
            if task["status"]["state"] in ("completed", "failed", "canceled") and tid not in self.server.engine.active:
                return task
            time.sleep(.02)
        self.fail("run was not terminal")

    def history(self, flow):
        return self.client.get(f"{BASE}/{flow['id']}/runs", headers=MODE).json()["items"]

    def test_pinned_versions_inputs_owner_scope_and_idempotence(self):
        key = self.access()
        first = self.save("流程甲", inputs={"prediction": True, "constraints": True})
        value = graph()
        value["nodes"][3]["id"] = "review"
        for edge in value["edges"]:
            for name in ("source", "target"):
                if edge[name] == "main":
                    edge[name] = "review"
        second = self.save("流程乙", value)
        missing = self.client.post(f"{BASE}/{first['id']}/runs", headers=MODE, json=self.payload(first))
        self.assertEqual(missing.status_code, 400)
        invalid_effort = self.client.post(f"{BASE}/{first['id']}/runs", headers=MODE,
                                         json={**self.payload(first, constraints=["核对数据"]), "reasoning_effort": "unknown"})
        self.assertEqual(invalid_effort.status_code, 400)
        self.assertEqual(self.history(first), [])
        a = {**self.payload(first, constraints=["只分析现有事实"]), "reasoning_effort": "ultra"}
        b = self.payload(second)
        tid = self.submit(first, a)
        self.assertEqual(self.submit(first, a), tid)
        effort_conflict = self.client.post(f"{BASE}/{first['id']}/runs", headers=MODE, json={**a, "reasoning_effort": "high"})
        self.assertEqual(effort_conflict.status_code, 400)
        conflict = self.client.post(f"{BASE}/{first['id']}/runs", headers=MODE, json={**a, "message": "其他需求"})
        self.assertEqual(conflict.status_code, 400)
        other = self.submit(second, b)
        self.assertNotEqual(tid, other)
        for fid, task_id, step in ((first, tid, "main"), (second, other, "review")):
            task = self.terminal(task_id)
            self.assertEqual(task["status"]["state"], "completed", task.get("metadata"))
            self.assertEqual(task["metadata"]["workflow"]["flow"]["revision"], fid["revision"])
            self.assertEqual([row["id"] for row in self.history(fid)], [task_id])
            events = self.client.get(f"/api/tasks/{task_id}/events", headers=MODE).json()["events"]
            self.assertTrue(any(e.get("step") == step and e.get("status") == "completed" for e in events))
            if task_id == tid:
                self.assertTrue(any(e.get("execution", {}).get("effort") == "ultra" for e in events))
        self.assertEqual(self.client.get("/api/conversations", headers=MODE).json(), [])
        cid = self.terminal(tid)["metadata"]["request"]["conversation_id"]
        bypass = self.client.post("/api/tasks", headers=MODE, json={
            "conversation_id": cid, "prediction": a["parameters"]["prediction"],
            "workflow": {"mode": "system", "key": "wrong-context"},
        })
        self.assertEqual(bypass.status_code, 403)
        value = graph()
        value["nodes"][3]["data"]["label"] = "已更新节点"
        path = f"{BASE}/{first['id']}"
        revision = self.client.put(path, headers=MODE, json={"name": first["name"], "graph": value,
                                   "base_revision": first["revision"], "inputs": first["inputs"]}).json()
        self.assertNotEqual(revision["revision"], first["revision"])
        self.assertEqual(self.submit(first, a), tid)
        detail = self.client.get(f"{path}/runs/{tid}", headers=MODE).json()
        self.assertEqual(detail["input"]["parameters"], a["parameters"])
        self.assertEqual(detail["choices"]["reasoning_effort"], "ultra")
        self.assertEqual(detail["version"], first["revision"])
        self.assertEqual(detail["task"]["metadata"]["workflow"]["graph"], first["graph"])
        self.assertIn("duration_ms", detail)
        self.assertEqual(self.client.get(f"{path}/runs/{other}", headers=MODE).status_code, 404)
        self.assertEqual(self.client.get(BASE, headers={"X-Analysis-Mode": "standard"}).status_code, 403)
        self.access()
        self.assertEqual(self.client.get(f"{path}/runs/{tid}", headers=MODE).status_code, 404)
        self.assertEqual(self.client.get(f"/api/tasks/{tid}/events", headers=MODE).status_code, 403)
        self.client.headers["X-Memory-Key"] = key

    def test_cancel_retry_and_legacy_version_matching(self):
        self.access()
        first = self.save("核对事实")
        self.assertEqual(self.save("导入的流程", import_key="local").get("id"),
                         self.save("重新迁移", import_key="local").get("id"))
        old = self.server.engine.submit({"prediction": MockPredictionAdapter().fetch(),
                                         "workflow": {"mode": "custom", "key": "old", "graph": graph()}})
        self.terminal(old["id"])
        self.assertEqual(self.history(first), [])  # Several definitions share the old graph.
        value = graph()
        value["nodes"][3]["data"]["label"] = "可唯一匹配的旧节点"
        unique = self.save("可匹配旧运行", value)
        legacy = self.server.engine.submit({"prediction": MockPredictionAdapter().fetch(),
                                            "workflow": {"mode": "custom", "key": "legacy", "graph": value}})
        self.terminal(legacy["id"])
        self.assertEqual([row["id"] for row in self.history(unique)], [legacy["id"]])
        generate = self.server.engine.models.generate

        async def slow(*args, **kwargs):
            await asyncio.sleep(.25)
            return await generate(*args, **kwargs)

        with patch.object(self.server.engine.models, "generate", slow):
            request = self.payload(first)
            cancelled = self.submit(first, request)
            other = self.submit(unique, self.payload(unique))
            self.assertEqual(self.client.post(f"/api/tasks/{cancelled}/cancel", headers=MODE, json={}).status_code, 200)
            self.assertEqual(self.terminal(cancelled)["status"]["state"], "canceled")
            self.assertEqual(self.terminal(other)["status"]["state"], "completed")
        later = self.submit(first, {**request, "key": uuid.uuid4().hex})
        self.assertEqual(self.terminal(later)["status"]["state"], "completed")
        self.assertEqual([item["id"] for item in self.history(first)], [later, cancelled])

    def test_recalled_memory_stays_in_its_workflow(self):
        self.access()
        first = self.save("简版", import_key="brief")
        second = self.save("标准版", import_key="full")
        initial = self.payload(first)
        initial["message"] = "请记住我偏好简版报告"
        own = self.terminal(self.submit(first, initial))
        separate = self.terminal(self.submit(second, self.payload(second)))
        self.assertEqual(own["status"]["state"], "completed", own.get("metadata"))
        self.assertEqual(separate["status"]["state"], "completed", separate.get("metadata"))
        events = self.client.get(f"/api/tasks/{separate['id']}/events", headers=MODE).json()["events"]
        self.assertFalse(any("preference" in event.get("types", []) for event in events))
        followup = self.terminal(self.submit(first, self.payload(first)))
        events = self.client.get(f"/api/tasks/{followup['id']}/events", headers=MODE).json()["events"]
        self.assertTrue(any("preference" in event.get("types", []) for event in events))

    def test_flow_card_image_is_validated_persisted_and_updatable(self):
        self.access()
        png = base64.b64encode(b"\x89PNG\r\n\x1a\ncard").decode()
        flow = self.save("带图流程", image={"mime": "image/png", "data": png})
        listed = next(item for item in self.client.get(BASE, headers=MODE).json()["items"] if item["id"] == flow["id"])
        self.assertEqual(listed["image"], {"mime": "image/png", "data": png})
        invalid = self.client.put(f"{BASE}/{flow['id']}", headers=MODE, json={"name": flow["name"], "graph": graph(),
            "inputs": flow["inputs"], "base_revision": flow["revision"], "image":{"mime":"image/png","data":base64.b64encode(b"bad").decode()}})
        self.assertEqual(invalid.status_code, 400)
        changed = self.client.put(f"{BASE}/{flow['id']}", headers=MODE, json={"name": "无图流程", "graph": graph(),
            "inputs": flow["inputs"], "base_revision": flow["revision"], "image": None}).json()
        self.assertEqual(changed["image"], None)
        self.assertEqual(next(item for item in self.client.get(BASE, headers=MODE).json()["items"] if item["id"] == flow["id"])["name"], "无图流程")
