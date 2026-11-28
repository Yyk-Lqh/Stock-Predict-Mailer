"""Execute the remaining node types through saved workflows and the task APIs."""
import json
import os
import time
import unittest
import uuid
from unittest.mock import patch

import httpx

import test_workflow_nodes as existing
from stock_predict_mailer.control import workflow_http
from test_workflow_chat import BASE, MODE
from test_workflow_nodes import edge, node


def field(name, kind, *, required=True):
    return {"name": name, "type": kind, "required": required}


def chain(*nodes):
    return {"version": 2, "nodes": list(nodes),
            "edges": [edge(left["id"], right["id"]) for left, right in zip(nodes[:-1], nodes[1:], strict=True)]}


class ExtendedWorkflowTests(unittest.TestCase):
    setUp = existing.VariableWorkflowTests.setUp
    tearDown = existing.VariableWorkflowTests.tearDown
    access = existing.VariableWorkflowTests.access
    save = existing.VariableWorkflowTests.save
    terminal = existing.VariableWorkflowTests.terminal
    submit = existing.VariableWorkflowTests.submit
    run_flow = existing.VariableWorkflowTests.run_flow
    result = existing.VariableWorkflowTests.result

    def test_catalog_computation_branch_and_bounds(self):
        self.access()
        catalog = self.client.get("/api/workflows/catalog").json()["nodes"]
        self.assertTrue(all(catalog[kind]["variables"] for kind in ("human", "iteration", "loop", "code", "http")))
        graph = chain(node("start", "input", fields=[field("items", "list")]),
                      node("each", "iteration", source="start.items", expression="item * 2 + index", limit=3, on_error="skip"),
                      node("code", "code", source="each.value", expression="value[0] + value[1]", value_type="number"),
                      node("loop", "loop", source="code.value", expression="state + 2", until="state >= 13", limit=2),
                      node("output", "output", fields=[field("result", "number"), field("rounds", "number"),
                                                       field("skipped", "number")], format="json"))
        graph["edges"][-1]["input"] = "result"
        graph["edges"] += [{**edge("loop", "output", "rounds"), "input": "rounds"},
                           {**edge("each", "output", "skipped"), "input": "skipped"}]
        flow = self.save("计算节点", graph)
        self.assertEqual(self.result(self.run_flow(flow, "计算", items=[2, "错误项", 3])),
                         {"result": 14, "rounds": 1, "skipped": 1})
        exceeded = self.run_flow(flow, "超出上限", items=[1, 2, 3, 4])
        self.assertEqual(exceeded["metadata"]["error"]["code"], "WORKFLOW_ITERATION_LIMIT")
        failed = self.run_flow(flow, "循环停止条件未满足", items=[0, 0])
        self.assertEqual(failed["metadata"]["error"]["code"], "WORKFLOW_LOOP_LIMIT")
        graph["nodes"][2]["data"]["config"]["expression"] = "value.pop()"
        checked = self.client.post("/api/workflows/validate", headers=MODE, json={
            "workflow": {"mode": "custom", "key": uuid.uuid4().hex, "graph": graph}}).json()
        self.assertFalse(checked["runnable"])
        self.assertTrue(any(item.get("node") == "code" for item in checked["issues"]))
        graph = chain(node("start", "input", fields=[field("items", "list")]),
                      node("each", "iteration", source="start.items", expression="item", limit=2, on_error="stop"),
                      node("output", "output", source="each.value", format="json"))
        self.assertEqual(self.result(self.run_flow(self.save("空迭代", graph), "空列表", items=[])), [])

    def waiting(self, task):
        for _ in range(100):
            events = self.client.get(f"/api/tasks/{task}/events", headers=MODE).json()["events"]
            if waiting := next((item for item in events if item.get("status") == "needs_input"), None):
                return waiting
            time.sleep(.02)
        self.fail("node did not request input")

    def test_pause_validate_resume_cancel_and_timeout(self):
        key = self.access()
        graph = chain(node("start", "input", fields=[]),
                      node("approval", "human", prompt="请确认复核人", fields=[field("reviewer", "text")], wait_seconds=5),
                      node("output", "output", source="approval.reviewer", format="text"))
        flow = self.save("人工复核", graph)
        task = self.submit(flow, {"revision": flow["revision"], "key": uuid.uuid4().hex, "message": "复核", "parameters": {}})
        waiting = self.waiting(task)
        self.assertEqual(waiting["prompt"], "请确认复核人")
        path = f"/api/tasks/{task}/continue"
        payload = {"request_id": waiting["request_id"], "node": "approval", "values": {"reviewer": "甲"}}
        self.access()
        self.assertEqual(self.client.post(path, headers=MODE, json=payload).status_code, 403)
        self.client.headers["X-Memory-Key"] = key
        self.assertEqual(self.client.post(path, headers={"X-Analysis-Mode": "standard"}, json=payload).status_code, 403)
        self.assertEqual(self.client.post(path, headers=MODE, json={**payload, "values": {}}).status_code, 400)
        self.assertEqual(self.client.post(path, headers=MODE, json={**payload, "node": "start"}).status_code, 400)
        self.assertEqual(self.client.post(path, headers=MODE, json=payload).status_code, 202)
        self.assertEqual(self.result(self.terminal(task)), "甲")
        self.assertEqual(self.client.post(path, headers=MODE, json=payload).status_code, 400)
        receipt = self.client.get(f"{BASE}/{flow['id']}/runs/{task}", headers=MODE).json()
        self.assertEqual(receipt["task"]["id"], task)
        direct = {"workflow": {"mode": "custom", "key": uuid.uuid4().hex, "graph": graph}, "message": "取消"}
        canceled = self.client.post("/api/tasks", json=direct, headers=MODE).json()["id"]
        self.waiting(canceled)
        self.assertEqual(self.client.post(f"/api/tasks/{canceled}/cancel", headers=MODE, json={}).status_code, 200)
        self.assertEqual(self.terminal(canceled)["status"]["state"], "canceled")
        timed_out = self.client.post("/api/tasks", json={**direct, "workflow": {**direct["workflow"], "key": uuid.uuid4().hex}},
                                     headers=MODE).json()["id"]
        self.waiting(timed_out)
        self.assertEqual(self.terminal(timed_out)["metadata"]["error"]["code"], "WORKFLOW_INPUT_TIMEOUT")

    def test_http_uses_exact_authorized_target_and_bounded_transport(self):
        self.access()
        secret_name = "SPM_WORKFLOW_HTTP_TOKEN_QUOTES"
        targets = {"quotes": {"url": "https://api.example.test/prices?market=CN", "method": "GET", "token_env": secret_name}}
        graph = chain(node("start", "input", fields=[field("params", "object")]),
                      node("request", "http", target="quotes", source="start.params", timeout=3),
                      node("output", "output", source="request.value", format="json"))
        seen = []
        response_status = 200

        def handler(request):
            seen.append(request)
            if response_status == 200:
                return httpx.Response(200, json={"quote": 12})
            if response_status == 206:
                return httpx.Response(206, text="x" * 10_001)
            return httpx.Response(response_status, headers={"location": "https://different.example.test/"})

        http_client = httpx.AsyncClient
        with patch.dict(os.environ, {workflow_http.TARGETS_ENV: json.dumps(targets), secret_name: "test-token"}), \
                patch.object(httpx, "AsyncClient", side_effect=lambda **kwargs: http_client(
                    **kwargs, transport=httpx.MockTransport(handler))) as client:
            flow = self.save("授权行情 HTTP", graph)
            self.assertEqual(self.result(self.run_flow(flow, "测试", params={"symbol": "TEST", "market": "override"})), {"quote": 12})
            self.assertEqual((seen[0].method, seen[0].url.host, seen[0].url.path), ("GET", "api.example.test", "/prices"))
            self.assertEqual(dict(seen[0].url.params), {"symbol": "TEST", "market": "CN"})
            self.assertEqual(seen[0].headers["authorization"], "Bearer test-token")
            self.assertFalse(client.call_args.kwargs["follow_redirects"])
            self.assertNotIn("test-token", json.dumps(self.client.get("/api/workflows/catalog").json()))
            response_status = 302
            error = self.run_flow(flow, "禁止重定向", params={})["metadata"]["error"]
            self.assertEqual(error["code"], "WORKFLOW_HTTP_STATUS")
            self.assertEqual(len(seen), 2)
            response_status = 206
            error = self.run_flow(flow, "响应超限", params={})["metadata"]["error"]
            self.assertEqual(error["code"], "WORKFLOW_HTTP_RESPONSE")
            targets["quotes"]["method"] = "POST"
            os.environ[workflow_http.TARGETS_ENV] = json.dumps(targets)
            response_status = 200
            self.assertEqual(self.result(self.run_flow(flow, "POST", params={"symbol": "TEST"})), {"quote": 12})
            self.assertEqual(seen[-1].method, "POST")
            self.assertEqual(json.loads(seen[-1].content), {"symbol": "TEST"})
            os.environ[workflow_http.TARGETS_ENV] = "{}"
            response = self.client.post(f"{BASE}/{flow['id']}/runs", headers=MODE, json={
                "key": uuid.uuid4().hex, "message": "授权过期", "parameters": {"params": {}}, "revision": flow["revision"]})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(len(seen), 4)
