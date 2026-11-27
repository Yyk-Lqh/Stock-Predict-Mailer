"""Typed variables and bounded execution for workflows with configurable input."""
from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict

from ..agent_service.contracts import ServiceError, decode, utcnow
from .execution import LABELS, PRESETS

TYPES = ("text", "number", "boolean", "object", "list")
NAMES = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,39}")
REFERENCES = re.compile(r"[A-Za-z0-9_-]{1,64}\.[A-Za-z_][A-Za-z0-9_]{0,39}")
VARIABLE = re.compile(r"\{\{\s*(" + REFERENCES.pattern + r")\s*\}\}")
KINDS = {
    "classifier": ("问题分类器", "按关键词顺序匹配类别，可设默认出口"),
    "branch": ("条件分支", "按顺序判断上游变量，只选择第一个命中的出口"),
    "template": ("模板转换", "将上游变量渲染为文本"),
    "aggregate": ("变量聚合器", "按配置顺序汇合实际执行的上游变量"),
    "assign": ("变量赋值", "在当前运行的节点作用域内声明变量"),
    "extract": ("参数提取器", "从 JSON 文本提取并校验已声明字段"),
    "document": ("文档提取器", "读取有权访问且处理完成的知识库文件文本与来源"),
    "list": ("列表操作", "筛选标量值、排序、切片或取值"),
    "llm": ("LLM", "调用已配置模型并返回文本或 JSON 对象"),
    "output": ("输出", "返回选定的文本或结构化数据"),
}
CONFIG = {
    "input": {"fields"}, "classifier": {"source", "cases", "fallback"}, "branch": {"source", "cases", "fallback"},
    "template": {"template"}, "aggregate": {"sources", "empty"}, "assign": {"source", "name", "value_type"},
    "extract": {"source", "fields"}, "document": {"source"}, "list": {"source", "operation", "start", "end", "value"},
    "knowledge": {"source", "limit"}, "llm": {"model", "template", "format"}, "output": {"source", "format", "fields"},
}
FIELD_TYPES = dict(zip(TYPES, (str, (int, float), bool, dict, list), strict=True))


def error(node, message, code="INVALID_WORKFLOW"):
    raise ServiceError(code, f"{node} · {message}")


def dataflow(graph):
    return isinstance(graph, dict) and any(
        isinstance(node, dict) and isinstance(node.get("data"), dict) and node["data"].get("type") == "input"
        and isinstance(node["data"].get("config"), dict) and "fields" in node["data"]["config"]
        for node in (graph.get("nodes") if isinstance(graph.get("nodes"), list) else ()))


def matches_type(value, kind):
    expected = FIELD_TYPES.get(kind) if isinstance(kind, str) else None
    return expected is not None and type(value) in (expected if isinstance(expected, tuple) else (expected,))


def fields(config, key):
    declared = config.get("fields")
    if not isinstance(declared, list) or len(declared) > 12:
        error(key, "最多定义 12 个字段")
    names = {"message"} if config.get("_input") else set()
    for field in declared:
        if not isinstance(field, dict) or set(field) - {"name", "label", "type", "required", "default"}:
            error(key, "字段配置无效")
        name, kind = field.get("name"), field.get("type")
        if not isinstance(name, str) or not NAMES.fullmatch(name) or name in names or name in ("__proto__", "constructor", "prototype"):
            error(key, f"变量名无效或重复 · {name}")
        if not isinstance(field.get("label", name), str) or len(field.get("label", name)) > 80:
            error(key, f"{name} 的说明须为不超过 80 字的文本")
        if kind not in TYPES or type(field.get("required")) is not bool:
            error(key, f"{name} 的类型或必填设置无效")
        if "default" in field and not matches_type(field["default"], kind):
            error(key, f"{name} 的默认值与类型不匹配")
        names.add(name)
    return declared


def bind_fields(declared, provided, key, code="INVALID_INPUT"):
    names = {field["name"] for field in declared}
    if set(provided) - names:
        error(key, "包含未声明字段", code)
    values = {}
    for field in declared:
        name = field["name"]
        value = provided.get(name, field.get("default"))
        if value is None or (value == "" and field["required"]):
            if field["required"]:
                error(key, f"请填写 {field.get('label') or name}（{name}）", code)
            continue
        if not matches_type(value, field["type"]):
            error(key, f"{name} 应为 {field['type']}", code)
        values[name] = value
    return values


def prepare(graph, raw, knowledge_owner):
    if set(raw) - {"message", "parameters", "model_id", "tools", "reasoning_effort", "conversation_id"}:
        error("用户输入", "包含未登记的运行设置", "INVALID_INPUT")
    message = raw.get("message", "")
    provided = raw.get("parameters", {})
    effort = raw.get("reasoning_effort")
    if (not isinstance(message, str) or len(message) > 4000 or not isinstance(provided, dict)
            or (effort is not None and (not isinstance(effort, str) or effort not in PRESETS))):
        error("用户输入", "需求、参数或推理强度无效", "INVALID_INPUT")
    start = next(node for node in graph["nodes"] if node["data"]["type"] == "input")
    values = bind_fields(start["data"]["config"]["fields"], provided, start["id"])
    if len(json.dumps(values, ensure_ascii=False, allow_nan=False).encode()) > 12_000:
        error(start["id"], "参数超过 12 KB", "INVALID_INPUT")
    if needs_knowledge(graph) and not knowledge_owner:
        error("知识检索", "请选择有访问权的知识库", "FORBIDDEN")
    return {**raw, "message": message, "parameters": values, "conversation_id": raw.get("conversation_id"),
            "_knowledge_owner": knowledge_owner}


def needs_knowledge(graph):
    return dataflow(graph) and any(node["data"].get("type") in ("knowledge", "document") for node in graph["nodes"]
                                   if isinstance(node, dict) and isinstance(node.get("data"), dict))


def ports(node):
    if node["type"] == "output":
        return ()
    if node["type"] not in ("classifier", "branch"):
        return tuple(dict.fromkeys(("value", *outputs(node))))
    config = node["config"]
    return (*[case["id"] for case in config["cases"]], *(("default",) if config["fallback"] else ()))


def template_refs(template, key):
    if not isinstance(template, str) or not template.strip() or len(template) > 4000:
        error(key, "模板或提示词须为 1 至 4000 字")
    remaining = VARIABLE.sub("", template)
    if "{{" in remaining or "}}" in remaining:
        error(key, "变量格式应为 {{节点ID.字段名}}")
    return VARIABLE.findall(template)


def validate_config(kind, config, key):
    if not isinstance(config, dict) or kind not in CONFIG or set(config) - CONFIG[kind]:
        error(key, "变量流程节点包含未登记的配置")
    if kind in ("input", "extract"):
        fields({**config, "_input": kind == "input"}, key)
    if kind == "output" and "fields" in config:
        if (config.get("format") != "json" or not fields(config, key)
                or any(field["name"] == "value" for field in config["fields"])):
            error(key, "多字段输出需要 JSON 格式及非 value 的字段名称")
    if kind in ("classifier", "branch"):
        cases = config.get("cases")
        if not isinstance(cases, list) or not 1 <= len(cases) <= 8 or type(config.get("fallback")) is not bool:
            error(key, "请设置 1 至 8 个出口和默认出口选项")
        ids = {"default"}
        for case in cases:
            if not isinstance(case, dict) or set(case) - {"id", "label", "description", "match", "operation"}:
                error(key, "分支配置无效")
            port, label, description = case.get("id"), case.get("label"), case.get("description", "")
            if not isinstance(port, str) or not NAMES.fullmatch(port) or port in ids:
                error(key, "出口 ID 无效或重复")
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80 or not isinstance(description, str) or len(description) > 200:
                error(key, "出口名称必填，说明最多 200 字")
            if kind == "classifier":
                parts = case.get("match")
                if not isinstance(parts, str) or not parts.strip() or len(parts) > 240:
                    error(key, f"{label} · 请填写关键词")
            else:
                op = case.get("operation")
                if op not in ("equals", "contains", "exists") or (op == "contains" and
                        (not isinstance(case.get("match"), str) or not case["match"])):
                    error(key, f"{label} · 条件无效")
                if op == "equals" and "match" not in case:
                    error(key, f"{label} · 请填写比较值")
            ids.add(port)
    if kind in ("template", "llm"):
        template_refs(config.get("template"), key)
    if kind in ("llm", "output") and config.get("format") not in ("text", "json"):
        error(key, "请选择文本或 JSON 输出")
    if kind == "aggregate":
        if (not isinstance(config.get("sources", []), list) or len(config.get("sources", [])) > 12
                or config.get("empty") not in ("omit", "null", "error")):
            error(key, "请选择 1 至 12 个来源及空值行为")
    if kind == "assign":
        name = config.get("name")
        if not isinstance(name, str) or not NAMES.fullmatch(name) or config.get("value_type") not in TYPES:
            error(key, "请填写目标变量名和类型")
    if kind == "knowledge" and (type(config.get("limit")) is not int or not 1 <= config["limit"] <= 8):
        error(key, "检索条数须为 1 至 8")
    if kind == "list":
        op, start, end = (config.get(field) for field in ("operation", "start", "end"))
        if op not in ("filter", "sort", "slice", "item"):
            error(key, "请选择列表操作")
        if op in ("slice", "item") and (type(start) is not int or not -200 <= start <= 200):
            error(key, "索引须为 -200 至 200 的整数")
        if op == "slice" and (type(end) is not int or not -200 <= end <= 200):
            error(key, "结束索引须为 -200 至 200 的整数")
    return config


def outputs(node):
    kind, config = node["type"], node["config"]
    if kind in ("input", "extract"):
        return {**({"message": "text"} if kind == "input" else {}),
                **{field["name"]: field["type"] for field in config["fields"]}}
    if kind in ("classifier", "branch"):
        return {"selected": "text", "label": "text"}
    if kind == "assign":
        return {config["name"]: config["value_type"]}
    if kind == "knowledge":
        return {"hits": "list"}
    if kind == "document":
        return {"value": "text", "source": "object"}
    if kind == "aggregate":
        return {"value": "list"}
    if kind == "list":
        return {"value": "any" if config["operation"] == "item" else "list"}
    if kind == "output" and "fields" in config:
        return {"value": "object"}
    if kind in ("llm", "output"):
        return {"value": "text" if config["format"] == "text" else "any" if kind == "output" else "object"}
    return {"value": "text"}


def input_ports(node):
    kind, config = node["type"], node["config"]
    if kind == "output" and "fields" in config:
        return {field["name"]: field for field in config["fields"]}
    if kind == "aggregate":
        return {"sources": {"type": "list", "required": True}}
    if kind in ("classifier", "branch", "assign", "extract", "document", "knowledge", "list", "output"):
        expected = {"classifier": "text", "extract": "text", "document": "text", "knowledge": "text", "list": "list",
                    "assign": config.get("value_type")}.get(kind) or "any"
        if kind == "branch" and any(case["operation"] == "contains" for case in config["cases"]):
            expected = "text"
        return {"source": {"type": expected, "required": True, "single": True}}
    return {}


def edge_reference(node, edge):
    port = edge.get("output", "value")
    kind = node.get("type")
    default = "label" if kind in ("classifier", "branch") else "message" if kind == "input" and port == "value" else port
    return edge["source"] + "." + edge.get("field", default)


def reference_requirements(node, bound):
    config, kind = node["config"], node["type"]
    if kind in ("template", "llm"):
        return [(ref, "any") for ref in VARIABLE.findall(config["template"])]
    if kind == "aggregate":
        return [] if "sources" in bound else [(ref, "any") for ref in config.get("sources", [])]
    if "source" in input_ports(node) and "source" not in bound:
        return [(config.get("source"), input_ports(node)["source"]["type"])]
    return []


def validate_references(nodes, order, parents, bound):
    visible = {}
    for key in order:
        node = nodes[key]["data"]
        config, kind = node["config"], node["type"]
        upstream = {ancestor for parent in parents[key] for ancestor in (parent, *visible[parent])}
        visible[key] = upstream
        refs = reference_requirements(node, bound.get(key, ()))
        if kind == "aggregate" and not refs and "sources" not in bound.get(key, ()):
            error(key, "请选择上游聚合来源，或连接聚合端口")
        for ref, expected in refs:
            if not isinstance(ref, str) or not REFERENCES.fullmatch(ref):
                error(key, "请选择有效的上游变量")
            source, field = ref.split(".")
            actual = outputs(nodes[source]["data"]).get(field) if source in upstream else None
            if actual is None:
                error(key, f"变量引用无效 · {ref}")
            if actual not in (expected, "any") and expected != "any":
                error(key, f"变量 {ref} 为 {actual}，需要 {expected}")
            if kind == "branch" and actual != "any" and any(
                    case["operation"] == "equals" and not matches_type(case["match"], actual) for case in config["cases"]):
                error(key, f"比较值应与变量 {ref} 的 {actual} 类型一致")


def json_text(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)


def resolve(values, ref, key):
    if ref not in values:
        error(key, f"变量 {ref} 缺失，或其分支未执行", "WORKFLOW_VARIABLE_MISSING")
    return values[ref]


def choose_port(kind, config, values, key):
    source = config["source"]
    for case in config["cases"]:
        expected = case.get("match")
        if kind == "classifier":
            actual = resolve(values, source, key)
            if not isinstance(actual, str):
                error(key, "分类变量须为文本", "WORKFLOW_VALUE")
            actual = actual.casefold()
            matched = any(word.strip().casefold() in actual for word in expected.split(",") if word.strip())
        elif case["operation"] == "exists":
            matched = source in values and values[source] is not None
        else:
            actual = resolve(values, source, key)
            matched = expected in actual if case["operation"] == "contains" and isinstance(actual, str) else (
                equal(expected, actual) if case["operation"] == "equals" else False)
        if matched:
            return case["id"]
    if config["fallback"]:
        return "default"
    error(key, "没有匹配的出口，请补充规则或启用默认出口", "WORKFLOW_NO_MATCH")


def equal(left, right):
    same_kind = type(left) is type(right) or (matches_type(left, "number") and matches_type(right, "number"))
    return same_kind and left == right


def list_value(items, config, key):
    if not isinstance(items, list) or len(items) > 200:
        error(key, "列表操作需要不超过 200 项的列表", "WORKFLOW_VALUE")
    op = config["operation"]
    if op == "filter":
        return [item for item in items if equal(item, config.get("value"))]
    if op == "sort":
        try:
            if any(type(item) not in (str, int, float) for item in items):
                raise TypeError
            return sorted(items)
        except TypeError:
            error(key, "排序需要同类文本或数值", "WORKFLOW_VALUE")
    if op == "slice":
        return items[config["start"]:config["end"]]
    index = config["start"]
    return items[index] if -len(items) <= index < len(items) else None


async def evaluate(engine, node, request, values, settings, budget, spec, key, bound):
    kind, cfg = node["type"], node["config"]
    if kind == "input":
        return {"message": request["message"], **request["parameters"]}
    if kind in ("classifier", "branch"):
        scope = {**values, ".source": bound["source"]} if "source" in bound else values
        port = choose_port(kind, {**cfg, "source": ".source"} if "source" in bound else cfg, scope, key)
        label = next((case["label"] for case in cfg["cases"] if case["id"] == port), "默认出口")
        return {"selected": port, "label": label}
    if kind in ("template", "llm"):
        content = VARIABLE.sub(lambda match: json_text(resolve(values, match[1], key)), cfg["template"])
        if kind == "llm":
            from .workflow_runtime import _check_binding

            model = cfg.get("model") or settings["agents"]["main"]["model_id"] or settings["default_model_id"]
            _check_binding(engine, spec["bindings"], "models", model, key)
            content = await engine.models.workflow_generate(model, content, cfg["format"], settings, budget, key)
        return {"value": content}
    if kind == "aggregate":
        if "sources" in bound:
            return {"value": bound["sources"]}
        found = []
        for ref in cfg["sources"]:
            if ref in values or cfg["empty"] == "error":
                found.append(resolve(values, ref, key))
            elif cfg["empty"] == "null":
                found.append(None)
        return {"value": found}
    if kind == "output" and "fields" in cfg:
        return {"value": bind_fields(cfg["fields"], bound, key, "WORKFLOW_VALUE")}
    source = bound["source"] if "source" in bound else resolve(values, cfg["source"], key)
    if kind == "assign":
        if not matches_type(source, cfg["value_type"]):
            error(key, f"赋值需要 {cfg['value_type']}", "WORKFLOW_VALUE")
        return {cfg["name"]: source}
    if kind == "extract":
        try:
            parsed = decode(source.encode())
        except (ServiceError, AttributeError):
            parsed = None
        if not isinstance(parsed, dict):
            error(key, "参数来源必须是 JSON 对象文本", "WORKFLOW_VALUE")
        return bind_fields(cfg["fields"], {field["name"]: parsed[field["name"]]
                           for field in cfg["fields"] if field["name"] in parsed}, key, "WORKFLOW_VALUE")
    if kind == "knowledge":
        response = await asyncio.to_thread(engine.knowledge.answer, request["_knowledge_owner"], source,
                                           limit=cfg["limit"], as_of=utcnow().date().isoformat())
        hits = [{field: item[field] for field in ("citation_id", "filename", "logical", "text", "document_id") if field in item}
                for item in response.get("results", [])]
        return {"hits": hits}
    if kind == "document":
        if not isinstance(source, str) or not re.fullmatch(r"[a-f0-9]{32}", source):
            error(key, "请使用知识库文件 ID", "WORKFLOW_VALUE")
        doc = await asyncio.to_thread(engine.knowledge.document, request["_knowledge_owner"], source, True)
        if doc["status"] != "ready":
            error(key, "文档尚未完成处理", "WORKFLOW_VALUE")
        content = "\n".join(chunk.get("text", "") for chunk in doc["chunks"])
        return {"value": content.encode()[:12000].decode(errors="ignore"), "source": {
            field: doc[field] for field in ("id", "filename", "logical", "hash")}}
    if kind == "list":
        return {"value": list_value(source, cfg, key)}
    return {"value": json_text(source) if cfg["format"] == "text" else source}


def summarize(value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    return value if len(encoded) <= 1400 else encoded[:1400] + "…"


def bind_edges(node, links, nodes, values, key):
    ports = input_ports(node)
    grouped = defaultdict(list)
    for edge in links:
        port = edge.get("input", "value")
        if port not in ports:
            continue
        ref = edge_reference(nodes[edge["source"]], edge)
        if ref in values:
            grouped[port].append(values[ref])
        elif node["type"] == "aggregate" and node["config"]["empty"] == "null":
            grouped[port].append(None)
        elif node["type"] == "aggregate" and node["config"]["empty"] == "error":
            resolve(values, ref, key)
    bound = {}
    for port, items in grouped.items():
        spec = ports[port]
        if spec["type"] == "list" and not spec.get("single"):
            bound[port] = items
        elif len(items) == 1:
            if spec["type"] != "any" and not matches_type(items[0], spec["type"]):
                error(key, f"输入 {port} 需要 {spec['type']}", "WORKFLOW_VALUE")
            bound[port] = items[0]
        else:
            error(key, f"单值端口 {port} 同时收到多个输入", "WORKFLOW_VALUE")
    if "source" in ports and any(edge.get("input") == "source" for edge in links) and "source" not in bound:
        error(key, "输入端口 source 缺少值", "WORKFLOW_VARIABLE_MISSING")
    if node["type"] == "aggregate" and any(edge.get("input") == "sources" for edge in links):
        bound.setdefault("sources", [])
    return bound


async def run(engine, spec, request, settings, budget, progress):
    from .workflow_runtime import ancestors

    graph, debug = spec["graph"], spec["debug"]
    nodes = {node["id"]: node["data"] for node in graph["nodes"]}
    incoming = defaultdict(list)
    for edge in graph["edges"]:
        incoming[edge["target"]].append(edge)
    included = ancestors(debug, incoming) if debug else set(nodes)
    order = [key for key in spec["order"] if key in included]
    level = settings["reasoning_effort"]
    progress.emit("plan", label="变量流程执行计划", finalized=True,
                  execution={"effort": level, "label": LABELS[level], "limits": budget.limits},
                  steps=[{"id": key, "label": nodes[key]["label"]} for key in order])
    scopes, selected, results = {}, {}, []
    for key in order:
        budget.check()
        node, links = nodes[key], incoming[key]
        active = [edge for edge in links if edge["source"] in scopes and
                   (edge["source"] not in selected or selected[edge["source"]] == edge.get("output"))]
        if links and not active:
            progress.emit("step", step=key, status="skipped", label=node["label"], reason="上游出口未命中")
            continue
        values = {ref: value for edge in active for ref, value in scopes[edge["source"]].items()}
        try:
            with progress.step(key, node["label"], input_summary=summarize(values)):
                bound = bind_edges(node, active, nodes, values, key)
                output = await evaluate(engine, node, request, values, settings, budget, spec, key, bound)
                if len(json.dumps(output, ensure_ascii=False, allow_nan=False).encode()) > 16_384:
                    error(key, "节点输出超过 16 KiB", "WORKFLOW_VALUE")
        except ServiceError as exc:
            progress.emit("node_result", step=key, status="failed", label=node["label"], reason=exc.message, code=exc.code)
            raise
        if node["type"] in ("classifier", "branch"):
            progress.emit("branch", step=key, selected=[output["selected"]], label=node["label"])
        scopes[key] = {**values, **{key + "." + field: value for field, value in output.items()}}
        if "selected" in output and node["type"] in ("classifier", "branch"):
            selected[key] = output["selected"]
        progress.emit("node_result", step=key, status="completed", label=node["label"], summary=summarize(output))
        if node["type"] == "output":
            results.append({"node": key, "label": node["label"], "format": node["config"]["format"], **output})
    if debug:
        return {"workflow_debug": True, "node": debug, "summary": summarize(scopes.get(debug, {})), "usage": budget.snapshot()}
    if not results:
        error("输出", "本次分支未到达任一输出节点", "WORKFLOW_NO_OUTPUT")
    return {"workflow_outputs": results, "usage": budget.snapshot()}
