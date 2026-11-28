"""Versioned desktop workflow contracts and server-side graph validation."""
from __future__ import annotations

import json
import re

from ..agent_service.analysis import identity
from ..agent_service.contracts import ServiceError
from ..plugins.registry import renderer_options
from . import workflow_database, workflow_http, workflow_tools, workflow_values, workflow_wiring

# Input and output are named ports with one bounded business-object type each.
NODES = {
    "input": (None, "request", "资料输入", "读取当前任务或会话提供的预测资料", "任务表单"),
    "validation": ("request", "context", "资料校验", "校验预测、事实、来源时间与图表序列", "任务契约"),
    "forecast": ("context", "context", "预测归档", "有评价定义时固定预测与评价口径", "预测归档"),
    "knowledge": ("context", "context", "知识检索", "按预测日期检索当前会话有权访问的资料", "私有知识库"),
    "retrieval": ("context", "context", "MCP 上下文", "调用主 Agent 已授权的只读工具补充事实与序列", "主 Agent 工具权限"),
    "analysis": ("context", "analysis", "主分析", "通过配置的主 Agent 分析预测与证据", "主 Agent 配置"),
    "merge": ("analysis", "analysis", "结果汇总", "复核主分析，汇总已验证结论与证据", "主 Agent 配置"),
    "chart": ("analysis", "analysis", "图表", "仅使用已校验序列生成图表", "任务时间序列"),
    "report": ("analysis", "report", "报告", "校验分析并生成可阅读报告", "报告渲染器"),
    "delivery": ("report", "receipt", "邮件交付", "仅在启用通知并获得授权时投递已生成报告", "邮件策略与回执"),
    "database": ("context", "context", "数据库", "只读查询本机 SQLite 文件或项目任务库", "本机 SQLite"),
    "tool": ("context", "context", "内置工具", "调用只读检查或查询工具，结果写入运行记录", "工作流内置工具"),
    **{kind: ("value", None if kind == "output" else "value", label, detail, "变量流程")
       for kind, (label, detail) in workflow_values.KINDS.items()},
}
SYSTEM_STEPS = ("prediction", "evidence", "forecast", "knowledge", "context", "main", "merge", "charts", "report", "delivery")
SYSTEM_TYPES = ("input", "validation", "forecast", "knowledge", "retrieval", "analysis", "merge", "chart", "report", "delivery")
STEP_ID = dict(zip(SYSTEM_STEPS, ("input", "validate", "forecast", "knowledge", "tools", "main", "merge", "charts", "report", "mail"), strict=True))
CONDITIONS = {"always": "始终", "has_facts": "有已校验事实", "no_facts": "没有已校验事实", "notify": "启用邮件通知", "no_notify": "未启用邮件通知"}
PASS_THROUGH = {"forecast", "knowledge", "retrieval", "merge", "chart", "database", "tool"}
TEST_BLOCKED = {"forecast", "delivery"}
_IDENT = re.compile(r"[A-Za-z0-9_-]{1,64}")
_TOOL = re.compile(r"[A-Za-z0-9_-]{1,64}:[\w.-]{1,80}", re.ASCII)


def system_position(index):
    row, column = divmod(index, 4)
    return {"x": 36 + (3 - column if row % 2 else column) * 248, "y": 160 + row * 232}


def catalog():
    nodes = {}
    for kind, (incoming, outgoing, label, detail, source) in NODES.items():
        nodes[kind] = {"input": incoming, "output": outgoing, "label": label, "detail": detail, "source": source,
                       "testable": kind not in TEST_BLOCKED, "allow_skip": kind in PASS_THROUGH}
    nodes["input"]["label"] = "用户输入"
    nodes["analysis"]["label"] = "Agent"
    for kind in workflow_values.CONFIG:
        nodes[kind]["variables"] = True
    graph = {"version": 2, "nodes": [], "edges": []}
    nodes["database"]["options"] = workflow_database.options()
    nodes["tool"]["options"] = workflow_tools.catalog()
    nodes["http"]["options"] = workflow_http.options()
    for kind in ("chart", "report"):
        nodes[kind]["options"] = renderer_options(kind)
    for index, (key, kind) in enumerate(zip(SYSTEM_STEPS, SYSTEM_TYPES, strict=True)):
        graph["nodes"].append({"id": key, "position": system_position(index),
                               "data": {"type": kind, "label": NODES[kind][2], "detail": nodes[kind]["detail"],
                                        "actualKey": STEP_ID[key], "enabled": True, "failurePolicy": "stop", "config": {}}})
        if index:
            graph["edges"].append({"source": SYSTEM_STEPS[index - 1], "target": key, "condition": "always"})
    return {"nodes": nodes, "conditions": CONDITIONS, "system": graph}


def graph_error(message, node=None):
    raise ServiceError("INVALID_WORKFLOW", f"{node} · {message}" if node else message)


def condition_matches(condition, state):
    facts = bool(state["facts"])
    mail = state["request"]["notify"]
    return {"always": True, "has_facts": facts, "no_facts": not facts, "notify": mail, "no_notify": not mail}[condition]


def validate_node(item, engine, settings, dataflow):
    key = item.get("id") if isinstance(item, dict) else None
    if not isinstance(key, str) or not _IDENT.fullmatch(key):
        graph_error("节点 ID 重复或格式无效")
    data = item.get("data")
    if not isinstance(data, dict):
        graph_error("节点配置无效", key)
    kind, label, config = data.get("type"), data.get("label"), data.get("config", {})
    detail = data.get("detail", "")
    if not isinstance(kind, str) or kind not in NODES:
        graph_error("草稿节点缺少执行器，请选择受支持的类型", key)
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
        graph_error("名称须为 1 至 80 个字符", key)
    if not isinstance(detail, str) or len(detail) > 400:
        graph_error("节点说明须为不超过 400 个字符的文本", key)
    enabled, failure = data.get("enabled", True), data.get("failurePolicy", "stop")
    if type(enabled) is not bool or failure not in ("stop", "skip", "degrade") or (
        (not enabled or failure == "skip") and kind not in PASS_THROUGH
    ) or (failure == "degrade" and kind not in ("analysis", "merge", "retrieval")):
        graph_error("启用状态或失败策略与端口不兼容", key)
    if not dataflow and kind in workflow_values.KINDS:
        graph_error("请先在用户输入节点启用自定义输入字段", key)
    allowed = {"retrieval": {"binding"}, "analysis": {"model", "instruction", "tools"}, "merge": {"model"},
               "database": workflow_database.FIELDS, "tool": {"tool", "required"},
               "chart": {"renderer"}, "report": {"renderer"}}.get(kind, set())
    if dataflow:
        if not enabled or failure != "stop":
            graph_error("变量流程节点须启用，失败时停止执行", key)
        config = workflow_values.validate_config(kind, config, key)
    elif not isinstance(config, dict) or set(config) - allowed:
        graph_error("包含未登记的配置项", key)
    if "renderer" in config and (not isinstance(config["renderer"], str) or config["renderer"] not in renderer_options(kind)):
        graph_error("请选择与节点类型匹配的内置渲染插件", key)
    if kind == "database":
        try:
            config = workflow_database.config_for(config, engine.store, enabled=enabled)
        except ServiceError as exc:
            raise ServiceError(exc.code, f"{key} · {exc.message}") from None
    if kind == "tool":
        try:
            config = workflow_tools.validate(config)
        except ServiceError as exc:
            raise ServiceError(exc.code, f"{key} · {exc.message}") from None
    if kind == "http":
        workflow_http.binding(config, key)
    if "binding" in config:
        binding = config["binding"]
        if not isinstance(binding, str) or not _TOOL.fullmatch(binding):
            graph_error("工具须为已授权的服务 ID:工具名", key)
        if enabled:
            check_tool(engine, binding, settings, key)
    elif kind == "retrieval" and enabled:
        for binding in settings["agents"]["main"]["tools"]:
            check_tool(engine, binding, settings, key)
    if kind == "analysis":
        instruction, tools = config.get("instruction", ""), config.get("tools", [])
        if not isinstance(instruction, str) or len(instruction) > 2000:
            graph_error("任务指令不得超过 2000 字", key)
        if instruction and not config.get("model") and settings["agents"]["main"]["endpoint_id"]:
            graph_error("使用任务指令时请选择本工作区的模型", key)
        if not isinstance(tools, list) or len(tools) > 8 or any(not isinstance(tool, str) or not _TOOL.fullmatch(tool) for tool in tools):
            graph_error("请选择至多 8 个已授权 MCP 工具", key)
        if len(tools) != len(set(tools)):
            graph_error("工具重复", key)
        for tool in tools:
            check_tool(engine, tool, settings, key)
    if "model" in config:
        model = config["model"]
        if not isinstance(model, str) or not _IDENT.fullmatch(model):
            graph_error("模型须为已配置的模型 ID", key)
        if not profile_for(engine, "models", model, key)["enabled"]:
            raise ServiceError("PERMISSION_DENIED", f"{key} · 模型已停用")
    elif kind == "llm":
        model = settings["agents"]["main"]["model_id"] or settings["default_model_id"]
        if not model or not profile_for(engine, "models", model, key)["enabled"]:
            raise ServiceError("MODEL_REQUIRED", f"{key} · 请先选择已启用的模型")
    elif enabled and kind in ("analysis", "merge") and failure != "degrade":
        main = settings["agents"]["main"]
        model = main["model_id"] or settings["default_model_id"]
        if not main["endpoint_id"] and (not model or not profile_for(engine, "models", model, key)["enabled"]):
            raise ServiceError("MODEL_REQUIRED", f"{key} · 请先配置启用的主 Agent 模型")
    xy = item.get("position", {})
    if not isinstance(xy, dict) or any(type(xy.get(k, 0)) not in (int, float) or not -20000 <= xy.get(k, 0) <= 20000 for k in ("x", "y")):
        graph_error("位置超出画布范围", key)
    node = {"id": key, "position": {k: xy.get(k, 0) for k in ("x", "y")},
            "data": {"type": kind, "label": label.strip(), "detail": detail.strip(), "enabled": enabled,
                     "failurePolicy": failure, "config": dict(config)}}
    return node


def validate_graph(raw, engine, settings, *, debug=None):
    if not isinstance(raw, dict) or raw.get("version") != 2:
        graph_error("需要第 2 版工作流")
    vertices, edges = raw.get("nodes"), raw.get("edges")
    if not isinstance(vertices, list) or not 1 <= len(vertices) <= 24 or not isinstance(edges, list) or len(edges) > 64:
        graph_error("工作流须包含 1 至 24 个节点和最多 64 条连线")
    checked = workflow_wiring.draft_graph(raw)
    vertices, edges = checked["nodes"], checked["edges"]
    graph, nodes = {"version": 2, "nodes": [], "edges": []}, {}
    dataflow = workflow_values.dataflow(raw)
    errors = []
    for item in vertices:
        try:
            node = validate_node(item, engine, settings, dataflow)
        except ServiceError as error:
            key = item.get("id") if isinstance(item, dict) else None
            errors.append((workflow_wiring.issue(error.code, error.message, node=key), error.code))
            continue
        nodes[node["id"]] = node
        graph["nodes"].append(node)
    if errors:
        raise workflow_wiring.WiringError([item for item, _ in errors], errors[0][1])
    issues, clean, order, parents, bound = workflow_wiring.topology(
        {**graph, "edges": edges}, NODES, CONDITIONS, debug=debug, strict=True)
    if any(item["severity"] == "error" for item in issues):
        raise workflow_wiring.WiringError(issues)
    graph["edges"] = clean
    if debug and (debug not in nodes or nodes[debug]["data"]["type"] in TEST_BLOCKED or not nodes[debug]["data"]["enabled"]):
        graph_error("此节点不可单测", debug)
    if dataflow:
        workflow_values.validate_references(nodes, order, parents, bound)
    if sum(node["data"]["type"] == "delivery" for node in nodes.values()) > 1:
        graph_error("整图最多一个邮件交付节点")
    if len(json.dumps(graph, ensure_ascii=True)) > 32_768:
        graph_error("流程配置超过 32 KiB")
    return graph, order


def check_tool(engine, binding, settings, node):
    sid, name = binding.split(":", 1)
    if binding not in settings["agents"]["main"]["tools"]:
        raise ServiceError("PERMISSION_DENIED", f"{node} · 主 Agent 未获此 MCP 工具授权")
    profile = profile_for(engine, "mcp", sid, node)
    if not profile["enabled"] or name not in profile["allowed_tools"] or profile["effects"].get(name) != "read":
        raise ServiceError("PERMISSION_DENIED", f"{node} · MCP 工具必须启用并授权为只读")


def profile_for(engine, category, key, node):
    try:
        return engine.store.get(category, key)
    except ServiceError as exc:
        if exc.code != "NOT_FOUND":
            raise
        raise ServiceError("WORKFLOW_PROFILE", f"{node} · 引用的模型或服务已不存在") from None


def bindings(engine, graph, settings):
    groups = {"models": {}, "agents": {}, "mcp": {}}
    main = settings["agents"]["main"]
    for node in graph["nodes"]:
        key, data = node["id"], node["data"]
        config = data.get("config", {})
        if not data["enabled"]:
            continue
        if data["type"] in ("analysis", "merge", "llm"):
            category = "agents" if data["type"] != "llm" and main["endpoint_id"] and not config.get("model") else "models"
            reference = (main["endpoint_id"] if category == "agents" else
                         config.get("model") or main["model_id"] or settings["default_model_id"])
            if reference:
                groups[category][reference] = identity(profile_for(engine, category, reference, key))
            for tool in config.get("tools", []):
                sid = tool.split(":", 1)[0]
                groups["mcp"][sid] = identity(profile_for(engine, "mcp", sid, key))
        elif data["type"] == "retrieval":
            for binding in ([config["binding"]] if "binding" in config else main["tools"]):
                reference = binding.split(":", 1)[0]
                groups["mcp"][reference] = identity(profile_for(engine, "mcp", reference, key))
        elif data["type"] == "http":
            groups.setdefault("http", {})[key] = identity(workflow_http.binding(config, key))
    return groups


def workflow_issues(value, engine, settings):
    if isinstance(value, dict) and value.get("mode") == "custom":
        try:
            graph = workflow_wiring.draft_graph(value.get("graph"))
        except ServiceError as error:
            return [workflow_wiring.issue(error.code, error.message)]
        issues, _, _, _, _ = workflow_wiring.topology(graph, NODES, CONDITIONS)
        node_valid = True
        for node in graph["nodes"]:
            try:
                validate_node(node, engine, settings, workflow_values.dataflow(graph))
            except ServiceError as error:
                issues.append(workflow_wiring.issue(error.code, error.message, node=node["id"]))
                node_valid = False
        if not node_valid or any(item["severity"] == "error" for item in issues):
            return issues
    else:
        graph = None
    try:
        spec = freeze(value, engine, settings)
    except workflow_wiring.WiringError as error:
        return error.issues
    except ServiceError as error:
        key = error.message.split(" · ", 1)[0]
        node = key if graph and any(item["id"] == key for item in graph["nodes"]) else None
        return [workflow_wiring.issue(error.code, error.message, node=node)]
    if graph:
        issues, _, _, _, _ = workflow_wiring.topology(spec["graph"], NODES, CONDITIONS, strict=True)
        return issues
    model = settings["agents"]["main"]["model_id"] or settings["default_model_id"]
    try:
        enabled = bool(model and engine.store.get("models", model)["enabled"])
    except ServiceError:
        enabled = False
    if not enabled:
        return [workflow_wiring.issue("MODEL_REQUIRED", "请先配置或选择启用的主分析模型", node="main")]
    return []


def freeze(value, engine, settings):
    if not isinstance(value, dict) or set(value) - {"mode", "graph", "key", "debug"}:
        graph_error("运行参数包含未登记字段")
    mode, key, debug = value.get("mode"), value.get("key"), value.get("debug")
    if mode not in ("system", "custom") or not isinstance(key, str) or not _IDENT.fullmatch(key):
        graph_error("执行模式或提交标识无效")
    if debug is not None and (mode != "custom" or not isinstance(debug, str) or not _IDENT.fullmatch(debug)):
        graph_error("调试节点无效")
    try:
        graph, order = (catalog()["system"], list(SYSTEM_STEPS)) if mode == "system" else validate_graph(
            value.get("graph"), engine, settings, debug=debug)
    except workflow_wiring.WiringError:
        raise
    except ServiceError as error:
        name, separator, _ = error.message.partition(" · ")
        raise workflow_wiring.WiringError([workflow_wiring.issue(error.code, error.message,
                                                                 node=name if separator else None)], error.code) from error
    selected = bindings(engine, graph, settings) if mode == "custom" else {}
    return {"mode": mode, "key": key, "debug": debug, "version": identity(graph), "graph": graph, "order": order,
            "configuration_version": identity([settings, selected]), "bindings": selected,
            **({"variables": True} if mode == "custom" and workflow_values.dataflow(graph) else {})}
