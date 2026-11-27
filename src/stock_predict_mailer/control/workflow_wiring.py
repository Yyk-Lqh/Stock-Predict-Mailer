"""Workflow draft storage and diagnostics for typed, directed connections."""
import json
import re
from collections import defaultdict
from functools import lru_cache
from graphlib import CycleError, TopologicalSorter

from ..agent_service.contracts import ServiceError
from . import workflow_values as values

ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
BRANCHES = {"branch", "classifier"}


def issue(code, message, *, severity="error", **location):
    return {"code": code, "message": message, "severity": severity, **location}


class WiringError(ServiceError):
    def __init__(self, issues, code="INVALID_WORKFLOW"):
        first = next(item for item in issues if item["severity"] == "error")
        message = first["message"]
        if first.get("node") and not message.startswith(first["node"] + " · "):
            message = first["node"] + " · " + message
        super().__init__(code, message)
        self.issues = issues

    def as_dict(self):
        result = super().as_dict()
        result["error"]["issues"] = self.issues
        return result


def draft_graph(raw):
    """Bound the stored shape while retaining semantically incomplete graphs."""
    if (not isinstance(raw, dict) or raw.get("version") != 2 or not isinstance(raw.get("nodes"), list)
            or not isinstance(raw.get("edges"), list) or len(raw["nodes"]) > 24 or len(raw["edges"]) > 64):
        raise ServiceError("INVALID_WORKFLOW", "草稿需要第 2 版格式，最多 24 个节点和 64 条连线")
    graph = {"version": 2, "nodes": [], "edges": []}
    for node in raw["nodes"]:
        data = node.get("data") if isinstance(node, dict) else None
        xy = node.get("position", {}) if isinstance(node, dict) else None
        if (not isinstance(data, dict) or not isinstance(node.get("id"), str) or not ID.fullmatch(node["id"])
                or not isinstance(xy, dict) or any(type(xy.get(k, 0)) not in (int, float)
                                                     or not -20000 <= xy.get(k, 0) <= 20000 for k in ("x", "y"))
                or not isinstance(data.get("config", {}), dict)
                or any(not isinstance(data.get(k, ""), str) for k in ("type", "label", "detail"))):
            raise ServiceError("INVALID_WORKFLOW", "草稿节点格式或画布位置无效")
        graph["nodes"].append({"id": node["id"], "position": {k: xy.get(k, 0) for k in ("x", "y")},
                               "data": {k: data[k] for k in ("type", "label", "detail", "enabled", "failurePolicy",
                                                            "config", "legacy", "modelVersion") if k in data}})
    for edge in raw["edges"]:
        if (not isinstance(edge, dict) or any(not isinstance(edge.get(k), str) or not ID.fullmatch(edge[k])
                                               for k in ("source", "target"))
                or any(k in edge and (not isinstance(edge[k], str) or len(edge[k]) > 250)
                       for k in ("id", "input", "output", "field", "condition"))):
            raise ServiceError("INVALID_WORKFLOW", "草稿连线格式无效")
        graph["edges"].append({k: edge[k] for k in ("id", "source", "target", "input", "output", "field", "condition") if k in edge})
    try:
        size = len(json.dumps(graph, ensure_ascii=True, allow_nan=False))
    except (TypeError, ValueError, RecursionError):
        raise ServiceError("INVALID_WORKFLOW", "草稿配置需要有效的 JSON 数据") from None
    if size > 32768:
        raise ServiceError("INVALID_WORKFLOW", "流程配置超过 32 KiB")
    return graph


def edge_location(edge, index):
    return {"node": edge["target"], "edge": edge.get("id"), "edge_index": index,
            "source": edge["source"], "output": edge.get("output", "value"), "input": edge.get("input", "value")}


def schema(node):
    try:
        return set(values.ports(node)), values.input_ports(node), values.outputs(node)
    except (KeyError, TypeError, ValueError):
        return set(), {}, {}


def topology(graph, registry, conditions, *, debug=None, strict=False):
    """Return structured issues and the executable edge order when it is defined."""
    nodes, edges = {item["id"]: item["data"] for item in graph["nodes"]}, graph["edges"]
    typed = values.dataflow(graph)
    ports = {key: schema(node) for key, node in nodes.items()} if typed else {}
    parents = {key: [] for key in nodes}
    outgoing, incoming, bound = defaultdict(list), defaultdict(list), defaultdict(set)
    seen, issues, clean = set(), [], []
    if len(nodes) != len(graph["nodes"]):
        issues.append(issue("DUPLICATE_NODE", "节点 ID 重复"))
    for index, edge in enumerate(edges):
        source, target = edge["source"], edge["target"]
        out, port = edge.get("output", "value"), edge.get("input", "value")
        condition = edge.get("condition", "always")
        where = edge_location(edge, index)
        if source not in nodes or target not in nodes:
            issues.append(issue("MISSING_NODE", "连线指向不存在的节点", **where))
            continue
        field = values.edge_reference(nodes[source], edge) if typed and (port != "value" or "field" in edge) else None
        identity = (source, out, field, target, port) if typed else (source, target)
        if identity in seen:
            issues.append(issue("DUPLICATE_EDGE", "同一端口组合已有连线", **where))
            continue
        seen.add(identity)
        if source == target:
            issues.append(issue("CYCLE", "节点连线指向自身", **where))
        parents[target].append(source)
        outgoing[source].append((index, edge))
        incoming[target].append((index, edge))
        item = {"source": source, "target": target, "condition": condition}
        if condition not in conditions or typed and condition != "always":
            issues.append(issue("CONDITION", "连线条件无效，请在分支节点配置条件", **where))
        if typed:
            source_ports, _, source_fields = ports[source]
            _, target_ports, _ = ports[target]
            if out not in source_ports or nodes[target].get("type") == "input" or port != "value" and port not in target_ports:
                issues.append(issue("PORT", f"端口不匹配或已删除（{source}.{out} → {target}.{port}）", **where))
            elif "field" in edge and (edge["field"] not in source_fields or
                  nodes[source].get("type") not in BRANCHES and out != "value" and edge["field"] != out):
                issues.append(issue("PORT", f"字段 {edge['field']} 与源端口 {out} 不匹配", **where))
            elif port != "value":
                actual = source_fields.get(values.edge_reference(nodes[source], edge).split(".", 1)[1])
                expected = target_ports[port]["type"]
                collecting = expected == "list" and not target_ports[port].get("single")
                if actual is None or not collecting and actual not in ("any", expected) and expected != "any":
                    issues.append(issue("TYPE", f"端口 {port} 需要 {expected}，当前连接提供 {actual or '未定义字段'}", **where))
                if (strict and actual in values.TYPES and nodes[target]["type"] == "branch" and port == "source"
                        and any(case["operation"] == "equals" and not values.matches_type(case["match"], actual)
                                for case in nodes[target]["config"]["cases"])):
                    issues.append(issue("TYPE", f"条件比较值应与端口 source 的 {actual} 类型一致", **where))
                bound[target].add(port)
            item["output"] = out
            if port != "value":
                item["input"] = port
            if "field" in edge:
                item["field"] = edge["field"]
        else:
            actual = registry.get(nodes[source].get("type"), (None, None))[1]
            expected = registry.get(nodes[target].get("type"), (None, None))[0]
            if actual is None or actual != expected or out not in ("value", actual) or port not in ("value", expected) or "field" in edge:
                issues.append(issue("PORT", f"端口不匹配（{source}.{actual} → {target}.{expected}）", **where))
        clean.append(item)

    def reaches(start, end):
        todo, visited = [start], set()
        while todo:
            key = todo.pop()
            if key == end:
                return True
            if key not in visited:
                visited.add(key)
                todo.extend(edge["target"] for _, edge in outgoing[key])
        return False

    try:
        order = list(TopologicalSorter(parents).static_order())
    except CycleError:
        order = []
        for index, edge in enumerate(edges):
            if edge["source"] != edge["target"] and reaches(edge["target"], edge["source"]):
                issues.append(issue("CYCLE", "此连线形成循环依赖，请移除或改用专用节点", **edge_location(edge, index)))
    roots = [key for key, links in parents.items() if not links]
    starts = [key for key, node in nodes.items() if node.get("type") == "input"]
    if len(starts) != 1:
        issues.append(issue("ENTRY", "流程需要唯一的用户输入节点", **({"node": starts[0]} if starts else {})))
    for key in roots:
        if key not in starts:
            issues.append(issue("UNREACHABLE", "节点没有可达的上游，请连接到流程入口", node=key))
    outputs = {key for key, node in nodes.items() if node.get("type") == ("output" if typed else "report")}
    if not debug and (not outputs or not typed and len(outputs) != 1):
        issues.append(issue("OUTPUT", "变量流程至少需要一个输出节点" if typed else "分析流程需要且仅需要一个报告节点"))
    if strict and typed and order and not any(item["severity"] == "error" for item in issues):
        issues.extend(paths(nodes, order, incoming, outgoing, ports, outputs, debug))
    elif strict and not typed and order and not any(item["severity"] == "error" for item in issues):
        issues.extend(legacy_joins(nodes, order, incoming, outgoing, outputs if not debug else ()))
    return issues, clean, order, parents, bound


def paths(nodes, order, incoming, outgoing, ports, outputs, debug):
    """Propagate mutually exclusive branch choices and available values in dependency order."""
    domains = {key: ports[key][0] for key in nodes if nodes[key]["type"] in BRANCHES}
    on, scope, signal, issues = {}, {}, {}, []
    universal = frozenset()

    def combine(a, b):
        merged = dict(a)
        for key, choice in b:
            if key in merged and merged[key] != choice:
                return None
            merged[key] = choice
        return frozenset(merged.items())

    @lru_cache(maxsize=8192)
    def covered(cube, options):
        if any(option <= cube for option in options):
            return True
        compatible = [option for option in options if combine(cube, option) is not None]
        if not compatible:
            return False
        key, _ = next(iter(compatible[0] - cube))
        return all(covered(cube | {(key, choice)}, frozenset(compatible)) for choice in domains[key])

    def available(refs, active):
        return all(covered(cube, frozenset(refs)) for cube in active)

    def optional(node, field):
        return node["type"] in ("input", "extract") and any(item["name"] == field and not item["required"]
                                                          and "default" not in item for item in node["config"]["fields"])

    for key in order:
        node = nodes[key]
        links = incoming[key]
        on[key] = {cube for index, _ in links for cube in signal[index]} if links else {universal}
        seen = scope[key] = defaultdict(set)
        groups = defaultdict(list)
        for index, edge in links:
            source = edge["source"]
            option = frozenset({(source, edge.get("output", "value"))}) if source in domains else universal
            for ref, cubes in scope[source].items():
                seen[ref].update(test for cube in cubes if (test := combine(cube, option)) is not None)
            port = edge.get("input", "value")
            if port != "value":
                groups[port].append((index, edge))
        for port, spec in ports[key][1].items():
            links_at_port = groups[port]
            if not links_at_port and (node["type"] != "output" or "fields" not in node["config"]):
                continue
            collecting = spec["type"] == "list" and not spec.get("single")
            if not collecting:
                conflicts = set()
                for offset, (index, _) in enumerate(links_at_port):
                    for other, _ in links_at_port[:offset]:
                        if any(combine(a, b) is not None for a in signal[index] for b in signal[other]):
                            conflicts.update((index, other))
                issues.extend(issue("SINGLE_INPUT", f"单值端口 {port} 可能同时接收多个来源，请分配到不同字段或使用变量聚合器",
                                    **edge_location(edge, index)) for index, edge in links_at_port if index in conflicts)
            if spec.get("required") and "default" not in spec:
                delivered = {cube for index, edge in links_at_port for cube in signal[index]
                             if not optional(nodes[edge["source"]], values.edge_reference(nodes[edge["source"]], edge).split(".", 1)[1])}
                if not available(delivered, on[key]):
                    issues.append(issue("MISSING_INPUT", f"必填端口 {port} 在某些路径没有可用来源", node=key, input=port))
        if node["type"] != "aggregate" or node["config"]["empty"] == "error":
            for ref, _ in values.reference_requirements(node, groups.keys()):
                if isinstance(ref, str) and seen.get(ref) and not available(seen[ref], on[key]):
                    issues.append(issue("VARIABLE_PATH", f"变量 {ref} 在此节点的部分执行路径上不会产生", node=key, field=ref))
        for field in ports[key][2]:
            seen[key + "." + field].update(on[key])
        for index, edge in outgoing[key]:
            option = frozenset({(key, edge.get("output", "value"))}) if key in domains else universal
            signal[index] = {test for cube in on[key] if (test := combine(cube, option)) is not None}
        if sum(len(cubes) for cubes in seen.values()) > 8192 or len(on[key]) > 2048:
            issues.append(issue("PATH_LIMIT", "分支路径组合超出校验范围，请分解此汇合节点", node=key))
            return issues

    if not debug:
        finished = {cube for key in outputs for cube in on[key]}
        for key in domains:
            connected = {edge.get("output", "value") for _, edge in outgoing[key]}
            for port in domains[key] - connected:
                issues.append(issue("OPEN_BRANCH", f"出口 {port} 尚未连接下游", severity="warning", node=key, output=port))
            for index, edge in outgoing[key]:
                if signal[index] and not available(finished, signal[index]):
                    issues.append(issue("OUTPUT_PATH", "此分支有执行路径无法到达输出节点", **edge_location(edge, index)))
        for key in nodes.keys() - outputs:
            if not outgoing[key] and on[key]:
                issues.append(issue("UNUSED_END", "此路径到达末端节点，未连接输出", severity="warning", node=key))
    return issues


def legacy_joins(nodes, order, incoming, outgoing, outputs):
    """Legacy ports merge identical state, or use the dedicated analysis merge."""
    states, facts, signals, issues = {}, {}, {}, []
    mutators = {"database", "retrieval", "analysis"}
    neutral = {"input", "validation", "tool"}
    for key in order:
        node = nodes[key]
        links = incoming[key]
        compatible = [signals[index] for index, _ in links]
        provenance = {source for _, edge in links for source in states[edge["source"]]}
        if node["type"] != "merge":
            for offset, (index, edge) in enumerate(links):
                source = edge["source"]
                if any(states[source] != states[other["source"]] and
                       any(all(name not in a or a[name] == value for name, value in b.items())
                           for a in signals[index] for b in signals[other_index])
                       for other_index, other in links[:offset]):
                    issues.append(issue("SINGLE_INPUT", "此端口可能收到多个不同的上游状态，请设置互斥条件或使用汇总节点",
                                        **edge_location(edge, index)))
        enabled = node.get("enabled", True)
        states[key] = {key} if enabled and node["type"] not in neutral else provenance or {key}
        inherited = {value for _, edge in links for value in facts[edge["source"]]}
        facts[key] = {key} if enabled and node["type"] in mutators else inherited or {key}
        cubes = [dict(item) for item in {frozenset(cube.items()) for signal in compatible for cube in signal}] if links else [{}]
        if key in outputs and not cubes:
            issues.append(issue("OUTPUT_PATH", "连线条件互斥，此报告节点无法执行", node=key))
        for index, edge in outgoing[key]:
            condition = edge.get("condition", "always")
            if condition == "always":
                signals[index] = cubes
                continue
            flag = "notify" if condition in ("notify", "no_notify") else "facts:" + (next(iter(facts[key])) if len(facts[key]) == 1 else key)
            value = condition in ("notify", "has_facts")
            signals[index] = [{**item, flag: value} for item in cubes if flag not in item or item[flag] == value]
        if len(cubes) > 2048:
            return [*issues, issue("PATH_LIMIT", "条件路径组合超出校验范围，请拆分汇合节点", node=key)]
    return issues
