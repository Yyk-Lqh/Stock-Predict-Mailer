"""Workflow graph contracts, actual routing, debug safety and frozen history."""
import asyncio
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from stock_predict_mailer.agent_service.adapters import MockPredictionAdapter
from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.control.orchestrator import Orchestrator, a2a_task
from stock_predict_mailer.control.store import Store
from stock_predict_mailer.control.workflow import catalog, freeze
from stock_predict_mailer.control.workflow_database import DEFAULTS, discover, inspect, query
from stock_predict_mailer.control.workflow_runtime import preview
from stock_predict_mailer.control.workflow_tools import authorized_mcp, call


def graph():
    kinds = ("input", "validation", "retrieval", "analysis", "chart", "report", "delivery")
    keys = ("input", "validate", "mcp", "main", "charts", "report", "mail")
    nodes = [{"id": key, "data": {"type": kind, "label": key, "config": {},
                                 "failurePolicy": "degrade" if kind == "analysis" else "stop"}}
             for key, kind in zip(keys, kinds, strict=True)]
    edges = [{"source": a, "target": b, "condition": "always"} for a, b in zip(keys[:-1], keys[1:], strict=True)]
    edges[-3]["condition"] = "has_facts"
    edges += [{"source": "main", "target": "report", "condition": "no_facts"}]
    return {"version": 2, "nodes": nodes, "edges": edges}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name), Fernet.generate_key())
        self.engine = Orchestrator(self.store)
        self.model = self.store.put("models", {"name": "Mock"})
        settings = self.store.settings()
        settings["default_model_id"] = self.model["id"]
        self.store.save_settings(settings)

    def request(self, key="first", *, value=None, **kwargs):
        return {"prediction": MockPredictionAdapter().fetch(), "reasoning_effort": "high",
                "workflow": {"mode": "custom", "key": key, "graph": value or graph()}, **kwargs}

    def terminal(self, tid):
        for _ in range(480):
            task = self.store.task(tid)
            if task["status"]["state"] not in ("working", "submitted") and tid not in self.engine.active:
                return task
            time.sleep(.025)
        self.fail(f"Task timed out: {task['status']}; events: {[(e.get('step'), e.get('status')) for e in self.store.events(tid)]}")

    def test_system_default_uses_real_anchor_and_skips_optional_steps(self):
        request = self.request()
        request["workflow"] = {"mode": "system", "key": "system"}
        task = self.terminal(self.engine.submit(request)["id"])
        self.assertEqual(task["status"]["state"], "completed", task.get("metadata"))
        metadata = task["metadata"]["workflow"]
        self.assertEqual(metadata["graph"], catalog()["system"])
        events = self.store.events(task["id"])
        completed = [event["step"] for event in events if event["kind"] == "step" and event["status"] == "completed"]
        self.assertEqual(completed, ["input", "validate", "main", "charts", "report"])
        self.assertNotIn("mail", [step["id"] for step in next(event for event in events if event["kind"] == "plan")["steps"]])

    def test_conditional_branch_changes_execution_and_version(self):
        request = self.request()
        tid = self.engine.submit(request)["id"]
        same = self.engine.submit(deepcopy(request))
        self.assertEqual(same["id"], tid)
        first = self.terminal(tid)
        self.assertEqual(first["status"]["state"], "completed", first.get("metadata"))
        events = self.store.events(tid)
        self.assertIn(("charts", "skipped"), [(e.get("step"), e.get("status")) for e in events])
        self.assertIn(["main"], [event["selected"] for event in events if event["kind"] == "branch" and event["step"] == "report"])
        changed = deepcopy(request)
        changed["workflow"]["graph"]["edges"][-4]["condition"] = "always"
        with self.assertRaisesRegex(ServiceError, "提交标识"):
            self.engine.submit(changed)
        changed["workflow"]["key"] = "second"
        for edge in changed["workflow"]["graph"]["edges"]:
            if edge["target"] == "charts":
                edge["condition"] = "no_facts"
            if edge["source"] == "main" and edge["target"] == "report":
                edge["condition"] = "has_facts"
        second = self.terminal(self.engine.submit(changed)["id"])
        self.assertEqual(second["status"]["state"], "completed", second.get("metadata"))
        self.assertNotEqual(first["metadata"]["workflow"]["version"], second["metadata"]["workflow"]["version"])
        events = self.store.events(second["id"])
        self.assertIn(["charts"], [event["selected"] for event in events if event["kind"] == "branch" and event["step"] == "report"])
        result = next(event for event in events if event["kind"] == "node_result" and event["step"] == "charts")
        self.assertEqual(result["summary"]["charts"], 0)
        self.assertEqual(self.store.task(tid)["metadata"]["workflow"]["graph"], first["metadata"]["workflow"]["graph"])

    def test_rejects_invalid_graph_and_reports_preflight(self):
        def mutate_edge(data):
            data["edges"].append({"source": "validate", "target": "report"})

        for mutate in (
            mutate_edge,
            lambda data: data["edges"].append({"source": "mcp", "target": "mcp"}),
            lambda data: data["edges"].append(deepcopy(data["edges"][0])),
            lambda data: data["edges"].pop(0),
            lambda data: data["nodes"][2]["data"].update(type="trained"),
            lambda data: data["nodes"][2]["data"].update(config={"api_key": "never persist"}),
        ):
            value = graph()
            mutate(value)
            with self.subTest(graph=value), self.assertRaises(ServiceError):
                self.engine.submit(self.request(value=value))
        with self.store.db() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)
        request = self.request()
        spec = freeze(request["workflow"], self.engine, self.store.settings())
        prepared = self.engine.prepare({key: val for key, val in request.items() if key != "workflow"})
        self.assertIn("conditional", {node["state"] for node in preview(spec, prepared, self.store.settings())["nodes"]})

    def test_renderer_config_is_frozen_and_checked_against_node_kind(self):
        value = graph()
        chart, report = value["nodes"][4:6]
        chart["data"]["config"]["renderer"] = "chart_bar"
        report["data"]["config"]["renderer"] = "report_dashboard"
        workflow = self.request(value=value)["workflow"]
        spec = freeze(workflow, self.engine, self.store.settings())
        self.assertEqual(spec["graph"]["nodes"][4]["data"]["config"], {"renderer": "chart_bar"})
        self.assertEqual(spec["graph"]["nodes"][5]["data"]["config"], {"renderer": "report_dashboard"})
        for invalid in ("chart_bar", "report_text", "missing"):
            report["data"]["config"]["renderer"] = invalid
            with self.subTest(renderer=invalid), self.assertRaisesRegex(ServiceError, "内置渲染插件"):
                freeze(workflow, self.engine, self.store.settings())

    def test_debug_mcp_mail_and_cancel_are_visible_in_task_history(self):
        settings = self.store.settings()
        mcp = self.store.put("mcp", {"name": "Mock MCP", "transport": "stdio", "command": sys.executable,
                                    "args": ["-m", "stock_predict_mailer.control.mock_services"],
                                    "allowed_tools": ["get_context"], "effects": {"get_context": "read"}})
        settings["agents"]["main"]["tools"] = [mcp["id"] + ":get_context"]
        settings["mail"].update({"transport":"file", "recipient_allowlist":["qa@example.invalid"], "allow_synthetic":True})
        self.store.save_settings(settings)
        debug = self.request("debug")
        debug["workflow"]["debug"] = "mcp"
        task = self.terminal(self.engine.submit(debug)["id"])
        self.assertEqual(task["status"]["state"], "completed", task.get("metadata"))
        output = task["artifacts"][0]["parts"][0]["data"]
        self.assertEqual(output["summary"]["facts"], 1)
        self.assertTrue(output["workflow_debug"])
        self.assertFalse((self.store.root / "analysis").exists())

        request = self.request("mail", notify=True, recipient="qa@example.invalid")
        task = self.terminal(self.engine.submit(request)["id"])
        self.assertEqual(task["status"]["state"], "completed", task.get("metadata"))
        self.assertEqual(task["artifacts"][0]["parts"][0]["data"]["mail"]["status"], "simulated")
        self.assertTrue(list((self.store.root / "sent").glob("*.eml")))
        self.assertEqual(self.engine.submit(request)["id"], task["id"])

        async def model_wait(*args, **kwargs):
            await asyncio.sleep(20)

        async def no_tools(prediction, facts, series, *args, **kwargs):
            return facts, series

        with patch.object(self.engine, "collect", side_effect=no_tools), patch.object(
                self.engine.models, "generate", side_effect=model_wait):
            active = self.engine.submit(self.request("cancel"))["id"]
            for _ in range(200):
                if any(event.get("step") == "main" and event.get("status") == "running" for event in self.store.events(active)):
                    break
                time.sleep(.01)
            self.engine.cancel(active)
            canceled = self.terminal(active)
        self.assertEqual(canceled["status"]["state"], "canceled")
        self.assertTrue(any(event.get("step") == "main" and event.get("status") == "canceled" for event in self.store.events(active)))
        self.assertNotIn("token", json.dumps(canceled["metadata"]["workflow"]))

    def test_failing_node_retains_frozen_graph_and_locates_failure(self):
        value = graph()
        value["nodes"][3]["data"]["failurePolicy"] = "stop"

        async def fail(*args, **kwargs):
            await asyncio.sleep(.05)
            raise ServiceError("TEST_MODEL_FAILED", "模拟模型失败")

        with patch.object(self.engine.models, "generate", side_effect=fail):
            tid = self.engine.submit(self.request("failed", value=value))["id"]
            value["nodes"][3]["data"].update(label="edited after submission", config={"model": "changed"})
            task = self.terminal(tid)
        self.assertEqual(task["status"]["state"], "failed")
        self.assertEqual(task["metadata"]["error"]["code"], "TEST_MODEL_FAILED")
        saved = task["metadata"]["workflow"]["graph"]["nodes"][3]["data"]
        self.assertEqual((saved["label"], saved["config"]), ("main", {}))
        events = self.store.events(tid)
        event = next(e for e in events if e.get("step") == "main" and e.get("status") == "failed")
        self.assertGreaterEqual(event["duration_ms"], 0)
        self.assertFalse(any(e.get("step") == "report" for e in events))

    def test_database_options_filter_history_and_allow_single_node_debug(self):
        subject = self.request()["prediction"]["subject"]
        for tid, symbol, forecast in (("open", subject, None), ("private", subject, "private-id"),
                                      ("archived", subject, "forecast-id"), ("other", "OTHER", None)):
            analysis = {"forecast_evidence": {"forecast_id": forecast}}
            self.store.task(tid, a2a_task(tid, "completed", brief={"subject": symbol, "synthetic": True},
                                          result={"analysis": analysis}))
        self.engine.memory.bind_child("another-owner", "another-conversation", "private")
        value = graph()
        value["nodes"].append({"id": "db", "data": {"type": "database", "label": "数据库",
                                                   "config": {"query": "archived", "limit": 1, "include_fact": True}}})
        value["edges"][1]["target"] = "db"
        value["edges"].append({"source": "db", "target": "mcp"})
        debug = self.request("db-debug", value=value)
        debug["workflow"]["debug"] = "db"
        task = self.terminal(self.engine.submit(debug)["id"])
        self.assertEqual(task["status"]["state"], "completed")
        detail = task["artifacts"][0]["parts"][0]["data"]["summary"]
        self.assertEqual([row["task_id"] for row in detail["rows"]], ["archived"])
        self.assertFalse(detail["has_more"])
        result = query(self.store, {"prediction": {"subject": subject}, "_owner": "another-owner"},
                       {**DEFAULTS, "scope": "accessible", "limit": 2})
        self.assertEqual([row["task_id"] for row in result["rows"]], ["other", "archived"])
        self.assertTrue(result["has_more"])

        task = self.terminal(self.engine.submit(self.request("db-full", value=value))["id"])
        self.assertEqual(task["status"]["state"], "completed", task.get("metadata"))
        facts = task["artifacts"][0]["parts"][0]["data"]["analysis"]["facts"]
        self.assertEqual([(fact["name"], fact["value"]) for fact in facts], [("本地历史查询返回记录数", 1)])
        bad = deepcopy(value)
        bad["nodes"][-1]["data"]["config"]["limit"] = 31
        with self.assertRaisesRegex(ServiceError, "db ·"):
            self.engine.submit(self.request("db-invalid", value=bad))

    def test_database_node_connects_to_local_sqlite_in_read_only_mode(self):
        path = self.store.root / "market data.sqlite"
        request = self.request("sqlite-debug")
        subject = request["prediction"]["subject"]
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE "daily ""quotes""" ("stock symbol" TEXT, payload TEXT)')
            db.executemany('INSERT INTO "daily ""quotes""" VALUES (?,?)',
                           [(subject, "fixture-private-value"), (subject.lower(), "fixture-private-value"), ("OTHER", "outside")])
            db.execute('CREATE VIEW quote_view AS SELECT * FROM "daily ""quotes"""')
        db.close()
        original = path.read_bytes()
        self.assertEqual(inspect(self.store, str(path))["tables"], ['daily "quotes"'])
        with self.assertRaises(ServiceError):
            inspect(self.store, str(self.store.db_path))
        missing = path.with_name("missing.sqlite")
        with self.assertRaises(ServiceError):
            inspect(self.store, str(missing))
        self.assertFalse(missing.exists())

        value = request["workflow"]["graph"]
        config = {"source": "sqlite", "path": str(path), "table": 'daily "quotes"', "symbol_column": "stock symbol",
                  "limit": 1, "include_fact": True}
        value["nodes"].append({"id": "db", "data": {"type": "database", "label": "数据库", "config": config}})
        value["edges"][1]["target"] = "db"
        value["edges"].append({"source": "db", "target": "mcp"})
        request["workflow"]["debug"] = "db"
        task = self.terminal(self.engine.submit(request)["id"])
        self.assertEqual(task["status"]["state"], "completed", task.get("metadata"))
        summary = task["artifacts"][0]["parts"][0]["data"]["summary"]
        self.assertEqual((summary["row_count"], summary["has_more"], summary["subject"]), (1, True, subject))
        self.assertNotIn("fixture-private-value", json.dumps(self.store.events(task["id"])))
        self.assertEqual(path.read_bytes(), original)
        bad = deepcopy(request)
        bad["workflow"]["key"] = "sqlite-bad-column"
        bad["workflow"]["graph"]["nodes"][-1]["data"]["config"]["symbol_column"] = "missing"
        with self.assertRaisesRegex(ServiceError, "db ·"):
            self.engine.submit(bad)

    def test_database_discovery_lists_only_sqlite_files_and_keeps_manual_paths_available(self):
        search = self.store.root / "samples"
        search.mkdir()
        nested = search / "nested"
        nested.mkdir()
        path = nested / "market data.sqlite"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE quotes(symbol TEXT)")
        db.close()
        (search / "schema.sql").write_text("CREATE TABLE quotes(symbol TEXT);", encoding="utf-8")
        (search / "fake.db").write_bytes(b"ordinary text")
        (search / "sqlite-without-extension").write_bytes(path.read_bytes())
        (search / ".private.sqlite").write_bytes(path.read_bytes())
        with patch("stock_predict_mailer.control.workflow_database._search_roots", return_value=(search, search, self.store.root)):
            found = discover(self.store)
        self.assertEqual(found, {"files": [{"name": path.name, "path": str(path.resolve())}], "truncated": False})
        self.assertEqual(inspect(self.store, str(search / "sqlite-without-extension"))["tables"], ["quotes"])

    def test_database_discovery_can_scan_external_directories_and_disks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            deep = root / "one" / "two" / "three" / "four" / "five"
            deep.mkdir(parents=True)
            path = deep / "external.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE quotes(symbol TEXT)")
            db.close()
            with patch("stock_predict_mailer.control.workflow_database._search_roots", return_value=(root,)):
                self.assertEqual(discover(self.store)["files"], [])
            with patch("stock_predict_mailer.control.workflow_database._disk_roots", return_value=(root,)):
                self.assertEqual(discover(self.store, scope="disks")["files"][0]["path"], str(path))
            self.assertEqual(discover(self.store, scope="directory", directory=str(root))["files"][0]["path"], str(path))
            with self.assertRaises(ServiceError):
                discover(self.store, scope="directory", directory="relative/path")

    def test_workflow_tool_catalog_debug_and_required_checks(self):
        options = catalog()["nodes"]["tool"]["options"]
        self.assertEqual(len(options), 5)
        request = self.request("tools")
        value = request["workflow"]["graph"]
        data = {"type": "tool", "label": "内置工具", "config": {"tool": "facts_audit"}}
        value["nodes"].append({"id": "tool", "data": data})
        value["edges"][1]["target"] = "tool"
        value["edges"].append({"source": "tool", "target": "mcp"})
        request["workflow"]["debug"] = "tool"
        task = self.terminal(self.engine.submit(request)["id"])
        self.assertEqual(task["status"]["state"], "completed")
        detail = task["artifacts"][0]["parts"][0]["data"]["summary"]
        self.assertEqual((detail["tool"], detail["count"], detail["ready"]), ("facts_audit", 0, False))
        request["workflow"]["key"] = "tool-required"
        data["config"]["required"] = True
        denied = self.terminal(self.engine.submit(request)["id"])
        self.assertEqual(denied["metadata"]["error"]["code"], "WORKFLOW_TOOL_NOT_READY")
        request["workflow"]["key"] = "unknown-tool"
        data["config"]["tool"] = "unknown"
        with self.assertRaisesRegex(ServiceError, "tool ·"):
            self.engine.submit(request)

        state = {"request": self.engine.prepare({"prediction": request["prediction"]}), "facts": [], "series": None}
        for tool in options:
            with self.subTest(tool=tool):
                self.assertEqual(call(self.engine, state, {"tool": tool, "required": False}, "tool")["tool"], tool)

    def test_mcp_picker_exposes_only_main_role_enabled_read_tools(self):
        profile = self.store.put("mcp", {"name": "Fixture", "url": "http://127.0.0.1:9001/mcp",
                                         "allowed_tools": ["quotes", "mail", "other"],
                                         "effects": {"quotes": "read", "mail": "email", "other": "read"}})
        settings = self.store.settings()
        settings["agents"]["main"]["tools"] = [profile["id"] + ":quotes", profile["id"] + ":mail"]
        self.store.save_settings(settings)
        self.assertEqual(authorized_mcp(self.store), {profile["id"] + ":quotes": "Fixture · quotes"})
