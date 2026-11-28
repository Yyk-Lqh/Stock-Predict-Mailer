"""Real task runs for variable nodes, port identities and frozen output history."""
import unittest
import uuid
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import test_workflow_chat
from stock_predict_mailer.agent_service.adapters import MockPredictionAdapter
from test_workflow_chat import BASE, MODE


def node(key, kind, **config):
    return {"id": key, "position": {"x": 30, "y": 50},
            "data": {"type": kind, "label": key, "config": config}}


def edge(source, target, port="value"):
    return {"source": source, "target": target, "output": port}


def classification():
    return {"version": 2, "nodes": [
        node("start", "input", fields=[{"name": "count", "type": "number", "required": True, "default": 2}]),
        node("route", "classifier", source="start.message", fallback=False, cases=[
            {"id": "a", "label": "行情", "description": "读取价格", "match": "行情"},
            {"id": "b", "label": "财报", "description": "阅读报表", "match": "财报"}]),
        node("quote", "template", template="行情路径：{{start.count}}"),
        node("filing", "template", template="财报路径：{{start.message}}"),
        node("report", "aggregate", sources=["quote.value", "filing.value"], empty="omit"),
        node("reply", "output", source="report.value", format="json")], "edges": [
        edge("start", "route"), edge("route", "quote", "a"), edge("route", "filing", "b"),
        edge("quote", "report"), edge("filing", "report"), edge("report", "reply")]}


class VariableWorkflowTests(unittest.TestCase):
    setUp = test_workflow_chat.WorkflowChatTests.setUp
    tearDown = test_workflow_chat.WorkflowChatTests.tearDown
    access = test_workflow_chat.WorkflowChatTests.access
    save = test_workflow_chat.WorkflowChatTests.save
    submit = test_workflow_chat.WorkflowChatTests.submit
    terminal = test_workflow_chat.WorkflowChatTests.terminal

    def run_flow(self, flow, message, **parameters):
        return self.terminal(self.submit(flow, {"revision": flow["revision"], "key": uuid.uuid4().hex,
                                                "message": message, "parameters": parameters}))

    def events(self, task):
        return self.client.get(f"/api/tasks/{task['id']}/events", headers=MODE).json()["events"]

    def result(self, task):
        self.assertEqual(task["status"]["state"], "completed", task.get("metadata"))
        return task["artifacts"][0]["parts"][0]["data"]["workflow_outputs"][0]["value"]

    def multi_graph(self):
        def fields(*items):
            return [{"name": name, "type": kind, "required": True} for name, kind in items]

        return {"version": 2, "nodes": [
            node("start", "input", fields=[{"name": "count", "type": "number", "required": True, "default": 2}]),
            node("model", "llm", template="摘要 {{start.message}}", format="text"),
            node("detail", "template", template="数量 {{start.count}}"),
            node("reply", "output", format="json", fields=fields(("summary", "text"), ("notes", "list"))),
            node("audit", "output", format="json", fields=fields(("summary", "text"), ("quantity", "text"))),
        ], "edges": [
            edge("start", "model"), edge("start", "detail"),
            {**edge("model", "reply"), "input": "summary"},
            {**edge("model", "reply"), "input": "notes"},
            {**edge("detail", "reply"), "input": "notes"},
            {**edge("model", "audit"), "input": "summary"},
            {**edge("detail", "audit"), "input": "quantity"},
        ]}

    def test_named_fields_fan_out_and_rejoin_in_graph_order(self):
        self.access()
        value = self.multi_graph()
        flow = self.save("多输入多输出", value)
        task = self.run_flow(flow, "复核")
        self.result(task)
        outputs = task["artifacts"][0]["parts"][0]["data"]["workflow_outputs"]
        self.assertEqual({row["node"]: row["value"] for row in outputs},
                         {"reply": {"summary": "摘要 复核", "notes": ["摘要 复核", "数量 2"]},
                          "audit": {"summary": "摘要 复核", "quantity": "数量 2"}})
        self.assertEqual([row["input"] for row in flow["graph"]["edges"] if row["source"] == "model" and row["target"] == "reply"],
                         ["summary", "notes"])
        self.assertTrue(any(event.get("step") == "model" and event["kind"] == "model" for event in self.events(task)))

    def test_exclusive_single_input_and_skipped_nodes(self):
        self.access()
        value = classification()
        value["nodes"] = [item for item in value["nodes"] if item["id"] not in ("report", "reply")]
        value["nodes"].append(node("reply", "output", format="json",
                                   fields=[{"name": "summary", "type": "text", "required": True}]))
        value["edges"] = value["edges"][:3] + [{**edge(item, "reply"), "input": "summary"} for item in ("quote", "filing")]
        flow = self.save("互斥汇合", value)
        for message, answer, skipped in (("行情", "行情路径：2", "filing"), ("财报", "财报路径：财报", "quote")):
            task = self.run_flow(flow, message)
            self.assertEqual(self.result(task), {"summary": answer})
            self.assertTrue(any(e.get("step") == skipped and e.get("status") == "skipped" for e in self.events(task)))

    def test_invalid_graphs_save_as_drafts_and_block_both_entry_points(self):
        self.access()
        for code, change in (
            ("TYPE", lambda value: value["edges"].append({**edge("start", "reply", "count"), "input": "summary"})),
            ("MISSING_INPUT", lambda value: value["edges"].pop(2)),
            ("SINGLE_INPUT", lambda value: value["edges"].append({**edge("detail", "reply"), "input": "summary"})),
            ("CYCLE", lambda value: value["edges"].append(edge("model", "model"))),
            ("CYCLE", lambda value: value["edges"].extend([edge("model", "detail"), edge("detail", "model")])),
        ):
            with self.subTest(code=code):
                value = self.multi_graph()
                change(value)
                payload = {"workflow": {"mode": "custom", "key": uuid.uuid4().hex, "graph": value}}
                checked = self.client.post("/api/workflows/validate", headers=MODE, json=payload).json()
                errors = [item for item in checked["issues"] if item["code"] == code]
                self.assertFalse(checked["runnable"])
                self.assertTrue(errors and errors[0].get("node"), checked)
                flow = self.save(code, value, draft=True)
                self.assertTrue(flow["draft"])
                self.assertEqual(flow["graph"]["edges"], value["edges"])
                request = {"message": "复核", "parameters": {}, "key": uuid.uuid4().hex, "revision": flow["revision"]}
                for endpoint, body in ((f"{BASE}/{flow['id']}/runs", request),
                                       ("/api/tasks", {**payload, "message": "复核", "parameters": {}})):
                    response = self.client.post(endpoint, headers=MODE, json=body)
                    self.assertEqual(response.status_code, 400, response.text)
                    self.assertIn(code, [item["code"] for item in response.json()["error"]["issues"]])
                self.assertEqual(self.client.get(f"{BASE}/{flow['id']}/runs", headers=MODE).json()["items"], [])
        with self.server.store.db() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)
        repaired = self.client.put(f"{BASE}/{flow['id']}", headers=MODE, json={"name": flow["name"], "draft": True,
                                  "graph": self.multi_graph(), "base_revision": flow["revision"]})
        self.assertEqual(repaired.status_code, 200, repaired.text)
        self.assertFalse(repaired.json().get("draft"))
        self.assertEqual(self.result(self.run_flow(repaired.json(), "修正后"))["summary"], "摘要 修正后")

    def test_uncommitted_node_editor_fields_survive_as_a_draft(self):
        self.access()
        edits = [["model", {"label": "摘要待编辑", "config": {"template": "", "format": "text"}}]]
        flow = self.save("节点表单草稿", self.multi_graph(), draft=True, draft_edits=edits)
        self.assertTrue(flow["draft"])
        self.assertEqual(flow["draft_edits"], edits)
        listed = self.client.get(BASE, headers=MODE).json()["items"]
        current = next(item for item in listed if item["id"] == flow["id"])
        self.assertFalse(current["runnable"])
        self.assertEqual(current["draft_edits"], edits)
        denied = self.client.post(f"{BASE}/{flow['id']}/runs", headers=MODE,
                                  json={"revision": flow["revision"], "key": "draft-only", "message": "测试", "parameters": {}})
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(denied.json()["error"]["issues"][0]["node"], "model")

    def test_run_both_ports_and_preserve_prior_snapshot(self):
        self.access()
        graph = classification()
        flow = self.save("双路径", graph)
        self.assertEqual(flow["fields"][0]["default"], 2)
        first = self.run_flow(flow, "核对行情")
        self.assertEqual(self.result(first), ["行情路径：2"])
        self.assertTrue(any(e.get("step") == "filing" and e.get("status") == "skipped" for e in self.events(first)))
        self.assertEqual(self.client.get(f"/api/tasks/{first['id']}/report", headers=MODE).status_code, 400)
        second = self.run_flow(flow, "阅读财报")
        self.assertEqual(self.result(second), ["财报路径：阅读财报"])
        self.assertTrue(any(e.get("step") == "quote" and e.get("status") == "skipped" for e in self.events(second)))
        failed = self.run_flow(flow, "其他")
        self.assertEqual(failed["metadata"]["error"]["code"], "WORKFLOW_NO_MATCH")
        graph["nodes"][1]["data"]["config"]["cases"].reverse()
        path = f"{BASE}/{flow['id']}"
        response = self.client.put(path, headers=MODE, json={"name": flow["name"], "graph": graph, "base_revision": flow["revision"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.result(self.run_flow(response.json(), "核对行情")), ["行情路径：2"])
        old = self.client.get(f"{path}/runs/{first['id']}", headers=MODE).json()
        self.assertEqual(old["version"], flow["revision"])
        self.assertEqual(old["task"]["metadata"]["workflow"]["graph"], flow["graph"])
        self.access()
        self.assertEqual(self.client.get(f"/api/tasks/{first['id']}/events", headers=MODE).status_code, 403)

    def test_port_reference_types_and_conditions(self):
        self.access()
        graph = classification()
        for change in ("port", "outside", "type"):
            broken = deepcopy(graph)
            if change == "port":
                broken["edges"][1]["output"] = "removed"
            elif change == "outside":
                broken["nodes"][2]["data"]["config"]["template"] = "{{filing.value}}"
            else:
                broken["nodes"][1]["data"]["config"]["source"] = "start.count"
            response = self.client.post(BASE, headers=MODE, json={"name": change, "graph": broken})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], "INVALID_WORKFLOW")
        graph["nodes"][1] = node("route", "branch", source="start.count", fallback=True, cases=[
            {"id": "a", "label": "计数等于 2", "operation": "equals", "match": 2},
            {"id": "b", "label": "计数已填写", "operation": "exists"}])
        flow = self.save("条件默认分支", graph)
        self.assertEqual(self.result(self.run_flow(flow, "其他", count=2)), ["行情路径：2"])
        self.assertEqual(self.result(self.run_flow(flow, "其他", count=3)), ["财报路径：其他"])
        graph["nodes"][1]["data"]["config"]["cases"].reverse()
        revised = self.client.put(f"{BASE}/{flow['id']}", headers=MODE,
                                  json={"name": flow["name"], "graph": graph, "base_revision": flow["revision"]})
        self.assertEqual(revised.status_code, 200, revised.text)
        self.assertEqual(self.result(self.run_flow(revised.json(), "命中重排条件", count=2)), ["财报路径：命中重排条件"])
        invalid = self.client.post(f"{BASE}/{flow['id']}/runs", headers=MODE, json={
            "revision": flow["revision"], "key": "invalid", "message": "其他", "parameters": {"count": True}})
        self.assertEqual(invalid.status_code, 400)

    def test_node_history_returns_only_participating_snapshots(self):
        self.access()
        value = classification()
        flow = self.save("节点运行", value)
        first = self.run_flow(flow, "查看行情")
        latest = self.run_flow(flow, "查看财报")
        path = f"{BASE}/{flow['id']}/runs"

        def rows(node_id, kind):
            response = self.client.get(path, params={"node": node_id, "kind": kind}, headers=MODE)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()["items"]

        self.assertEqual([item["id"] for item in rows("quote", "template")], [first["id"]])
        self.assertEqual([item["id"] for item in rows("filing", "template")], [latest["id"]])
        self.assertEqual(rows("quote", "llm"), [])
        self.assertEqual(self.client.get(path, params={"node": "quote"}, headers=MODE).status_code, 400)
        self.assertEqual(self.client.get(path, params={"node": "quote", "kind": "template"},
                                         headers={"X-Analysis-Mode": "standard"}).status_code, 403)
        self.access()
        self.assertEqual(self.client.get(path, params={"node": "quote", "kind": "template"}, headers=MODE).status_code, 404)

    def test_extraction_list_assignment_and_mock_model(self):
        self.access()
        graph = {"version": 2, "nodes": [
            node("start", "input", fields=[]),
            node("extract", "extract", source="start.message", fields=[{"name": "items", "type": "list", "required": True}]),
            node("sort", "list", source="extract.items", operation="sort"),
            node("assign", "assign", source="sort.value", name="sorted", value_type="list"),
            node("llm", "llm", template="结果 {{assign.sorted}}", format="json"),
            node("reply", "output", source="llm.value", format="json")],
            "edges": [edge(a, b) for a, b in zip(("start", "extract", "sort", "assign", "llm"),
                                               ("extract", "sort", "assign", "llm", "reply"), strict=True)]}
        flow = self.save("转换与模型", graph)
        task = self.run_flow(flow, '{"items":[3,1,2]}')
        self.assertEqual(self.result(task), {"text": "结果 [1, 2, 3]"})
        self.assertTrue(any(event["kind"] == "model" and event.get("step") == "llm" for event in self.events(task)))
        wrong = self.run_flow(flow, '{"items":"3"}')
        self.assertEqual(wrong["metadata"]["error"]["code"], "WORKFLOW_VALUE")

    def test_document_and_knowledge_follow_the_run_scope(self):
        token = self.access()
        memory = self.server.engine.memory
        kb = self.server.engine.knowledge
        doc = kb.upload(memory.owner(token), "research.txt", b"Steel inventory declined in October.",
                        {"document_date": "2026-10-01", "available_date": "2026-10-01"})
        self.assertEqual(kb.process_one()["status"], "ready")
        graph = {"version": 2, "nodes": [
            node("start", "input", fields=[{"name": "file", "type": "text", "required": True, "default": doc["id"]}]),
            node("search", "knowledge", source="start.message", limit=3),
            node("document", "document", source="start.file"),
            node("aggregate", "aggregate", sources=["search.hits", "document.value", "document.source"], empty="error"),
            node("reply", "output", source="aggregate.value", format="json")
        ], "edges": [edge(a, b) for a, b in (("start", "search"), ("start", "document"), ("search", "aggregate"),
                                             ("document", "aggregate"), ("aggregate", "reply"))]}
        flow = self.save("私有资料", graph)
        hits, extracted, source = self.result(self.run_flow(flow, "Steel inventory"))
        self.assertTrue(any(hit["filename"] == "research.txt" and hit["citation_id"] for hit in hits))
        self.assertIn("Steel inventory", extracted)
        self.assertEqual(source["id"], doc["id"])
        self.access()
        other_flow = self.save("另一个资料空间", graph)
        failed = self.run_flow(other_flow, "Steel inventory")
        self.assertEqual(failed["status"]["state"], "failed")
        self.assertEqual(failed["metadata"]["error"]["code"], "NOT_FOUND")

    def test_analysis_agent_instruction_and_read_tool_authorization(self):
        self.access()
        service = self.f.mcp()
        binding = service["id"] + ":get_context"
        graph = {"version": 2, "nodes": [node("start", "input"), node("validate", "validation"),
                    node("agent", "analysis", instruction="对照库存信息", tools=[binding]), node("report", "report")],
                 "edges": [{"source": a, "target": b} for a, b in (("start", "validate"), ("validate", "agent"), ("agent", "report"))]}
        denied = self.client.post(BASE, headers=MODE, json={"name": "执行未经授权", "graph": graph})
        self.assertEqual(denied.status_code, 403)
        settings = self.server.store.settings()
        settings["agents"]["main"]["tools"] = [binding]
        self.server.store.save_settings(settings)
        flow = self.save("Agent 授权调用", graph)
        prediction = MockPredictionAdapter().fetch()
        engine = self.server.engine
        model = engine.models.generate
        seen = []

        async def generate(model_id, role, data, settings, budget):
            seen.append(data.get("task_instruction"))
            return await model(model_id, role, data, settings, budget)

        context = {"schema_version": "1", "context_id": "node-agent", "subject": prediction["subject"], "facts": []}
        with patch.object(engine.mcp, "call", new=AsyncMock(return_value=context)) as call, patch.object(engine.models, "generate", generate):
            task = self.run_flow(flow, "复核预测结果", prediction=prediction)
        self.assertEqual(task["status"]["state"], "completed", task.get("metadata"))
        self.assertEqual(seen, ["对照库存信息"])
        call.assert_awaited_once()
        self.assertTrue(any(e["kind"] == "tool" and e["step"] == "agent" and e["status"] == "completed" for e in self.events(task)))
