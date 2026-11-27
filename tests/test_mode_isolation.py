"""Mode-scoped console resources, conversation context and migration."""
import json
import time
import unittest
import uuid
from unittest.mock import AsyncMock, patch

import test_control
from stock_predict_mailer.agent_service.adapters import MockPredictionAdapter
from stock_predict_mailer.control.memory import Memory
from stock_predict_mailer.control.orchestrator import a2a_task

STANDARD = {"X-Analysis-Mode": "standard"}
PROFESSIONAL = {"X-Analysis-Mode": "professional"}
LEGACY = {"X-Analysis-Mode": "legacy"}


class ModeIsolationTests(unittest.TestCase):
    setUp = test_control.ConsoleAPITests.setUp
    tearDown = test_control.ConsoleAPITests.tearDown

    def owner(self):
        access = self.client.post("/api/memory/access").json()
        self.client.headers["X-Memory-Key"] = access["key"]
        return self.server.engine.memory.owner(access["key"])

    def new(self, mode):
        response = self.client.post("/api/conversations", headers=mode, json={})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def run_task(self, cid, mode, **request):
        if mode == PROFESSIONAL:
            request["workflow"] = {"mode": "system", "key": uuid.uuid4().hex}
        response = self.client.post("/api/tasks", headers=mode, json={"conversation_id": cid, **request})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()["id"]

    def terminal(self, tid, mode, state="completed"):
        for _ in range(250):
            task = self.client.get("/api/tasks/" + tid, headers=mode).json()
            if task["status"]["state"] not in ("working", "submitted") and tid not in self.server.engine.active:
                self.assertEqual(task["status"]["state"], state, task)
                return task
            time.sleep(.02)
        self.fail("Task did not reach " + state)

    def test_conversations_and_tasks_enforce_mode_and_keep_global_history(self):
        self.owner()
        normal, pro = self.new(STANDARD), self.new(PROFESSIONAL)
        p = MockPredictionAdapter().fetch()
        for verb, path in (("GET", ""), ("GET", "/export"), ("DELETE", "")):
            self.assertEqual(self.client.request(verb, "/api/conversations/" + pro + path, headers=STANDARD).status_code, 403)
        for mode, cid in ((STANDARD, normal), (PROFESSIONAL, pro)):
            page = self.client.get("/api/conversations?limit=1", headers=mode).json()
            self.assertEqual([item["id"] for item in page["items"]], [cid])
            self.assertIsNone(page["next_before"])
        self.assertEqual(self.client.post("/api/tasks", headers=STANDARD,
                                         json={"conversation_id": pro, "prediction": p}).status_code, 403)
        self.assertEqual(self.client.post("/api/tasks", headers=PROFESSIONAL,
                                         json={"conversation_id": pro, "prediction": p}).status_code, 400)
        normal_id = self.run_task(normal, STANDARD, prediction=p, message="标准上下文")
        pro_id = self.run_task(pro, PROFESSIONAL, prediction={**p, "subject": "PRO.SZ"}, message="专业上下文")
        for mode, own, other in ((STANDARD, normal_id, pro_id), (PROFESSIONAL, pro_id, normal_id)):
            for suffix in ("", "/events", "/report", "/analysis", "/mail"):
                self.assertEqual(self.client.get("/api/tasks/" + other + suffix, headers=mode).status_code, 403)
            self.assertEqual(self.client.post(f"/api/tasks/{other}/cancel", headers=mode, json={}).status_code, 403)
            self.assertEqual(self.client.delete("/api/tasks/" + other, headers=mode).status_code, 403)
            self.terminal(own, mode)
        self.assertEqual(self.client.get("/api/workflows/runs", headers=STANDARD).status_code, 403)
        runs = self.client.get("/api/workflows/runs", headers=PROFESSIONAL).json()["items"]
        self.assertEqual([item["id"] for item in runs], [pro_id])
        by_id = {item["id"]: item["metadata"]["mode"] for item in self.client.get("/api/tasks").json()["items"]}
        self.assertEqual(by_id, {normal_id: "standard", pro_id: "professional"})
        for mode, tid in ((STANDARD, normal_id), (PROFESSIONAL, pro_id)):
            self.assertEqual([item["id"] for item in self.client.get("/api/tasks", headers=mode).json()["items"]], [tid])
        self.assertEqual(self.client.delete("/api/tasks/" + normal_id, headers=STANDARD).status_code, 200)
        self.assertEqual(self.client.get("/api/tasks/" + normal_id).status_code, 404)
        self.assertEqual(self.client.get("/api/tasks/" + pro_id + "/report", headers=PROFESSIONAL).status_code, 200)
        conversation = self.client.get("/api/conversations/" + normal, headers=STANDARD).json()
        self.assertIsNone(conversation["task"])
        self.assertEqual(conversation["messages"][0]["message"], "标准上下文")
        self.assertNotIn("task", conversation["messages"][0])

    def test_automatic_memory_and_dedup_are_mode_local(self):
        self.owner()
        normal, pro = self.new(STANDARD), self.new(PROFESSIONAL)
        p = MockPredictionAdapter().fetch()
        first = self.run_task(normal, STANDARD, prediction=p, message="请记住我偏好简版报告")
        self.terminal(first, STANDARD)
        pro_id = self.run_task(pro, PROFESSIONAL, prediction=p, message="查看报告")
        result = self.terminal(pro_id, PROFESSIONAL)["artifacts"][0]["parts"][0]["data"]["analysis"]
        self.assertNotEqual(result.get("report_format"), "brief")
        second = self.run_task(pro, PROFESSIONAL, message="请记住我偏好标准版报告")
        self.terminal(second, PROFESSIONAL)
        normal_memory = self.client.get("/api/memory", headers=STANDARD).json()
        pro_memory = self.client.get("/api/memory", headers=PROFESSIONAL).json()
        self.assertEqual([item["report_format"] for item in normal_memory], ["brief"])
        self.assertEqual([item["report_format"] for item in pro_memory], ["standard"])
        mid = pro_memory[0]["id"]
        self.assertEqual(self.client.delete("/api/memory/" + mid, headers=STANDARD).status_code, 403)
        self.assertEqual(self.client.delete("/api/memory/" + mid, headers=PROFESSIONAL).status_code, 200)
        self.assertEqual(self.client.get("/api/memory", headers=STANDARD).json(), normal_memory)

    def test_run_tool_selection_cannot_expand_shared_permissions(self):
        self.owner()
        cid = self.new(STANDARD)
        request = {"conversation_id": cid, "prediction": MockPredictionAdapter().fetch(), "tools": ["unknown:read"]}
        rejected = self.client.post("/api/tasks", headers=STANDARD, json=request)
        self.assertEqual(rejected.status_code, 403)
        request["tools"] = []
        response = self.client.post("/api/tasks", headers=STANDARD, json=request)
        self.assertEqual(response.status_code, 202, response.text)
        self.terminal(response.json()["id"], STANDARD)

    def test_explicit_model_is_used_without_mutating_the_shared_role(self):
        self.owner()
        store = self.server.store
        model = store.put("models", {"name": "Mode model", "provider": "mock"})
        settings = store.settings()
        configured = settings["default_model_id"]
        settings["agents"]["main"]["model_id"] = configured
        store.save_settings(settings)
        adapter = self.server.engine.models
        with patch.object(adapter, "generate", AsyncMock(wraps=adapter.generate)) as generate:
            tid = self.run_task(self.new(STANDARD), STANDARD, prediction=MockPredictionAdapter().fetch(),
                                complexity="simple", model_id=model["id"])
            task = self.terminal(tid, STANDARD)
            self.assertEqual(generate.await_args.args[:2], (model["id"], "main"))
        self.assertEqual(task["metadata"]["request"]["model_id"], model["id"])
        self.assertEqual(store.settings()["agents"]["main"]["model_id"], configured)

    def test_legacy_migration_is_idempotent_and_keeps_mixed_sessions_readable(self):
        owner = self.owner()
        memory = self.server.engine.memory
        store = self.server.store
        normal, pro, mixed, unknown = [memory.new(owner)["id"] for _ in range(4)]
        with store.db() as con:
            for table in ("conversations", "memory_pending", "memory_vectors"):
                con.execute(f"ALTER TABLE {table} DROP COLUMN mode")
            for cid, label, workflow in ((normal, "standard", None), (pro, "professional", {"mode": "system"}),
                                         (mixed, "mixed-standard", None), (mixed, "mixed-pro", {"mode": "system"})):
                task = a2a_task(label, "completed", brief={"conversation_id": cid}, workflow=workflow)
                con.execute("INSERT INTO tasks(id,body) VALUES (?,?)", (label, json.dumps(task)))
                con.execute("INSERT INTO memory_tasks VALUES (?,?,?)", (label, owner, cid))
                con.execute("INSERT INTO conversation_turns(conversation,body) VALUES (?,?)",
                            (cid, memory.seal({"message": label, "task": label})))
            task = a2a_task("child", "completed", context_id="professional")
            con.execute("INSERT INTO tasks(id,body) VALUES (?,?)", ("child", json.dumps(task)))
            con.execute("INSERT INTO tasks(id,body) VALUES (?,?)", ("unknown", json.dumps(a2a_task("unknown", "completed"))))
            con.execute("INSERT INTO memory_vectors VALUES (?,?,?,?,?,?,?)",
                        ("old", owner, "old-dedup", "preference", None, memory.seal({"id":"old", "source_conversation":pro}), memory.seal({})))
        for _ in range(2):
            Memory(store)
            for cid, mode in ((normal, STANDARD), (pro, PROFESSIONAL), (mixed, LEGACY), (unknown, LEGACY)):
                data = self.client.get("/api/conversations/" + cid, headers=mode).json()
                self.assertEqual(data["mode"], mode["X-Analysis-Mode"])
            self.assertEqual(self.client.get("/api/tasks/child", headers=PROFESSIONAL).status_code, 200)
            self.assertEqual(self.client.get("/api/tasks/unknown", headers=LEGACY).status_code, 200)
            self.assertEqual(self.client.delete("/api/tasks/unknown", headers=STANDARD).status_code, 403)
            self.assertEqual(len(self.client.get("/api/conversations/" + mixed, headers=LEGACY).json()["messages"]), 2)
            self.assertEqual(self.client.get("/api/memory", headers=STANDARD).json(), [])
            self.assertEqual(self.client.get("/api/memory", headers=PROFESSIONAL).json()[0]["id"], "old")
        with store.db() as con:
            self.assertEqual(con.execute("SELECT dedup FROM memory_vectors WHERE id='old'").fetchone()[0], "professional:old-dedup")
