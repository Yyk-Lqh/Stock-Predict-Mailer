"""Execute a frozen graph using the console's existing task and permission boundaries."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from ..agent_service.analysis import identity, validate_analysis
from ..agent_service.charts import build_charts, chart_svg
from ..agent_service.contracts import ServiceError, context, prediction
from ..agent_service.forecast_archive import ForecastArchive
from ..agent_service.reporting import render, save_report
from .execution import LABELS
from .workflow import NODES, SYSTEM_STEPS, TEST_BLOCKED, check_tool, condition_matches, profile_for
from .workflow_database import query as database_query
from .workflow_tools import call as call_tool


def _reason(kind, request, settings, debug):
    if debug and kind in TEST_BLOCKED:
        return "调试期间跳过有持久化或投递副作用的步骤"
    if kind == "forecast" and request["evaluation_definition"] is None:
        return "任务未提供评价定义"
    if kind == "knowledge" and not request["knowledge_query"]:
        return "任务未选择知识检索"
    if kind == "retrieval" and not settings["agents"]["main"]["tools"]:
        return "主 Agent 未配置授权工具"
    if kind == "delivery" and not request["notify"]:
        return "任务未启用邮件"
    return None


def _context(p, facts):
    return {"schema_version": "1", "context_id": "workflow", "subject": p["subject"], "facts": facts} if facts else None


def summary(state):
    p = state["request"]["prediction"]
    series = (state["series"] or {}).get("series", {})
    knowledge = (state.get("knowledge") or {}).get("results", [])
    return {
        "synthetic": p["synthetic"], "confidence": p["confidence"], "prediction_source": p["model_version"],
        "facts": len(state["facts"]),
        "citations": [{k: item[k] for k in ("citation_id", "document_id", "source_hash", "filename", "location") if k in item}
                      for item in knowledge[:10]],
        "series": [{"kind": kind, "source": item["source"], "point_at": item["points"][-1]["at"], "timezone": "UTC",
                    "freshness": "historical" if kind == "observed" else kind,
                    "points": len(item["points"]), "synthetic": p["synthetic"]} for kind, item in series.items()],
        "charts": len(state.get("analysis", {}).get("charts", [])),
        "analysis_id": state.get("analysis", {}).get("analysis_id") if state.get("report") else None,
        "mail_status": (state.get("mail") or {}).get("status"),
    }


def _check_binding(engine, frozen, category, reference, key):
    expected = frozen.get(category, {}).get(reference)
    if expected is not None and identity(profile_for(engine, category, reference, key)) != expected:
        raise ServiceError("WORKFLOW_PROFILE_CHANGED", f"{key} · 配置已更改，请重新校验后提交")


async def _node(engine, key, data, upstream, settings, budget, progress, spec):
    kind = data["type"]
    debug = spec["debug"]
    state = dict(upstream)
    request, p = state["request"], state["request"]["prediction"]
    facts = state["facts"]
    if kind == "validation":
        prediction(p)
        context(_context(p, facts), p["subject"])
    elif kind == "forecast":
        state["forecast"] = ForecastArchive(engine.store.root).register(p, request["evaluation_definition"])
    elif kind == "database":
        config = data["config"]
        result = database_query(engine.store, request, config)
        state["database"] = result
        if config["include_fact"]:
            name = "本机数据库查询返回记录数" if config.get("source") == "sqlite" else "本地历史查询返回记录数"
            fact = {"id": identity(["workflow_database", progress.tid, key]), "name": name,
                    "value": result["row_count"], "unit": "条", "source": result["source"],
                    "observed_at": result["queried_at"], "available_at": result["queried_at"]}
            state["facts"] = [*facts, fact]
    elif kind == "tool":
        state["tool_result"] = call_tool(engine, state, data["config"], key)
    elif kind == "knowledge":
        import asyncio

        state["knowledge"] = await asyncio.to_thread(engine.knowledge.answer, request["_owner"], request["knowledge_query"],
                                                     as_of=p["generated_at"][:10])
    elif kind == "retrieval":
        current = engine.store.settings()
        frozen = settings["agents"]["main"]["tools"]
        binding = data["config"].get("binding")
        tools = [binding] if binding else frozen
        for tool in tools:
            check_tool(engine, tool, current, key)
            _check_binding(engine, spec["bindings"], "mcp", tool.split(":", 1)[0], key)
        before = progress.tools
        notes = []
        state["facts"], state["series"] = await engine.collect(p, facts, state["series"], tools, progress, notes, step=key)
        state["attempts"] = progress.tools - before
        if notes and data["failurePolicy"] == "stop":
            raise ServiceError("WORKFLOW_MCP", "授权工具未能完整提供上下文；查看该节点的工具事件")
        state["notes"] = [*state["notes"], *notes]
        state["degraded"] = bool(notes)
    elif kind in ("analysis", "merge"):
        main = settings["agents"]["main"]
        model = data["config"].get("model")
        if main["endpoint_id"] and not model:
            _check_binding(engine, spec["bindings"], "agents", main["endpoint_id"], key)
        else:
            _check_binding(engine, spec["bindings"], "models", model or main["model_id"] or settings["default_model_id"], key)
        await _analysis(engine, data, state, settings, budget, progress)
    elif kind == "chart":
        analysis = deepcopy(state["analysis"])
        figures, notes = build_charts(state["series"])
        if request["goal"] == "comparison":
            figures.reverse()
        if figures:
            analysis["charts"] = figures
        analysis["limitations"] += notes
        for chart in figures:
            progress.emit("chart", step=key, label=chart["title"] + "已生成", svg=chart_svg(chart), caption=chart["caption"])
        state["analysis"] = analysis
    elif kind == "report":
        analysis = deepcopy(state["analysis"])
        analysis["analysis_id"] = identity({k: v for k, v in analysis.items() if k != "analysis_id"})
        validate_analysis(analysis)
        if debug:
            render(analysis)
        else:
            state["report_path"] = str(save_report(engine.store.root, analysis) / "report.html")
        state.update(analysis=analysis, report=True)
    elif kind == "delivery":
        state["mail"] = await engine.notify_many(state["analysis"], request["recipients"], budget, progress)
    return state


async def _analysis(engine, data, state, settings, budget, progress):
    request = state["request"]
    p, facts = request["prediction"], state["facts"]
    notes, results = list(state["notes"]), list(state.get("results", []))
    kind = data["type"]
    main_data = {"prediction": p, "facts": facts, "goal": request["goal"], "user_constraints": request["constraints"],
                 "report_format": request["report_format"]}
    evidence = engine.workflow_evidence(request.get("_owner"), state.get("knowledge"), main_data, notes)
    if evidence and request["knowledge_to_model"]:
        main_data["source_material"] = {"trust": "untrusted_source_material", "as_of": state["knowledge"]["as_of"], "results": evidence}
    if kind == "merge":
        main_data["peer_results"] = results
    model = data["config"].get("model")
    if model:
        settings = {**settings, "agents": {**settings["agents"], "main": {**settings["agents"]["main"], "model_id": model}}}
    try:
        results.append(await engine.role("main", main_data, settings, budget, local_only=bool(model)))
    except ServiceError as exc:
        if data["failurePolicy"] != "degrade" or exc.code == "CANCELLED":
            raise
        notes.append(exc.code + "：已使用通过校验的分析依据。")
        state["degraded"] = True
        state["error_code"] = exc.code
    analysis, conflicts = engine.integrate_analysis(p, _context(p, facts), state.get("forecast"), results, notes, progress)
    analysis["limitations"] += notes
    analysis["status"] = "degraded" if notes else "ok"
    analysis["mode"] = "orchestrated_bounded"
    if request.get("report_format"):
        analysis["report_format"] = request["report_format"]
        analysis["user_constraints"] = request["constraints"]
    if evidence:
        analysis["knowledge_evidence"] = {"as_of": state["knowledge"]["as_of"], "results": evidence,
                                          "used_ids": sorted({eid for result in results for eid in result["evidence_ids"]}
                                                             & {item["citation_id"] for item in evidence})}
    state.update(analysis=analysis, conflicts=conflicts, results=results, notes=notes)


def ancestors(target, incoming):
    nodes, pending = {target}, [target]
    while pending:
        for edge in incoming[pending.pop()]:
            if edge["source"] not in nodes:
                nodes.add(edge["source"])
                pending.append(edge["source"])
    return nodes


def preview(spec, request, settings):
    nodes = {node["id"]: node["data"] for node in spec["graph"]["nodes"]}
    incoming = defaultdict(list)
    for edge in spec["graph"]["edges"]:
        incoming[edge["target"]].append(edge)
    included = ancestors(spec["debug"], incoming) if spec["debug"] else set(nodes)
    statuses = {}
    state = {"request": request, "facts": (request["context"] or {}).get("facts", [])} if request else None
    for key in spec["order"] if spec["mode"] == "custom" else SYSTEM_STEPS:
        node = nodes[key]
        reason = "节点已停用" if not node["enabled"] else _reason(node["type"], request, settings, spec["debug"]) if request else None
        conditions = incoming[key]
        if conditions and spec["mode"] == "custom":
            # Tool enrichment is unknown until execution; never predict that fact-dependent edges will be taken.
            possible = [edge for edge in conditions if statuses[edge["source"]]["state"] != "blocked"]
            if state:
                possible = [edge for edge in possible if edge["condition"] not in ("notify", "no_notify")
                            or condition_matches(edge["condition"], state)]
            if not possible:
                statuses[key] = {"id": key, "state": "blocked", "reason": "上游条件不满足"}
                continue
        dynamic = conditions and any(edge["condition"] != "always" for edge in conditions)
        statuses[key] = {"id": key, "state": "blocked" if key not in included else "skip" if reason else
                         "conditional" if dynamic or (spec["mode"] == "system" and key == "merge") else "ready",
                         "reason": reason or ("取决于运行中的上游输出" if dynamic else None)}
    return {"version": spec["version"], "mode": spec["mode"], "nodes": list(statuses.values())}


def _join(upstream, alternatives, kind):
    if not alternatives or all(other == upstream for other in alternatives):
        return upstream
    keys = ("request", "facts", "series", "knowledge", "forecast")
    if kind != "merge" or any(any(other.get(key) != upstream.get(key) for key in keys) for other in alternatives):
        return None
    results, notes = [], []
    for state in (upstream, *alternatives):
        results.extend(result for result in state.get("results", []) if result not in results)
        notes.extend(note for note in state["notes"] if note not in notes)
    return {**upstream, "results": results, "notes": notes}


def _node_summary(kind, state):
    key = {"database": "database", "tool": "tool_result"}.get(kind)
    return state[key] if key in state else summary(state)


async def run(engine, spec, request, settings, budget, progress):
    graph, order, debug = spec["graph"], spec["order"], spec["debug"]
    nodes, incoming = {node["id"]: node["data"] for node in graph["nodes"]}, defaultdict(list)
    for edge in graph["edges"]:
        incoming[edge["target"]].append(edge)
    included = ancestors(debug, incoming) if debug else set(nodes)
    level = settings["reasoning_effort"]
    progress.emit("plan", label="单节点调试计划" if debug else "工作流执行计划", finalized=True,
                  execution={"effort": level, "label": LABELS[level], "limits": budget.limits},
                  steps=[{"id": key, "label": nodes[key]["label"]} for key in order if key in included])
    initial = {"request": request, "facts": (request["context"] or {}).get("facts", []),
               "series": request["chart_data"], "notes": []}
    values, result = {}, None
    for key in order:
        if key not in included:
            continue
        data = nodes[key]
        kind, label = data["type"], data["label"]
        links = incoming[key]
        selected = [edge["source"] for edge in links if edge["source"] in values
                    and condition_matches(edge["condition"], values[edge["source"]])]
        progress.emit("branch", step=key, label=f"{label} · 核对上游分支", selected=selected,
                      candidates=[{k: edge[k] for k in ("source", "condition")} for edge in links])
        if links and not selected:
            progress.emit("step", step=key, status="skipped", label=label, reason="没有匹配条件的上游输出")
            continue
        upstream = values[selected[0]] if selected else initial
        upstream = _join(upstream, [values[parent] for parent in selected[1:]], kind)
        if upstream is None:
            progress.emit("step", step=key, status="failed", label=label, code="WORKFLOW_AMBIGUOUS_INPUT")
            raise ServiceError("WORKFLOW_AMBIGUOUS_INPUT", f"{key} · 多条分支同时提供不同输出，请使用互斥条件")
        source = NODES[kind][4]
        reason = _reason(kind, request, settings, debug) if data["enabled"] else "节点已停用"
        if reason:
            progress.emit("step", step=key, status="skipped", label=label, source=source, reason=reason)
            if kind != "delivery":
                values[key] = upstream
            continue
        scoped = {k: value for k, value in upstream.items() if k not in ("attempts", "degraded", "error_code", "database", "tool_result")}
        try:
            with progress.step(key, label, source=source, input_summary=summary(scoped)):
                output = await _node(engine, key, data, scoped, settings, budget, progress, spec)
        except ServiceError as exc:
            if data["failurePolicy"] != "skip" or exc.code in (
                "CANCELLED", "STEP_LIMIT", "PERMISSION_DENIED", "WORKFLOW_PROFILE", "WORKFLOW_PROFILE_CHANGED"
            ):
                raise
            output = {**scoped, "degraded": True, "error_code": exc.code}
        values[key] = {k: v for k, v in output.items() if k not in ("database", "tool_result")}
        progress.emit("node_result", step=key, label=f"{label} · 输出摘要", status="degraded" if output.get("degraded") else "completed",
                      source=source, summary=_node_summary(kind, output),
                      code=output.get("error_code"), attempts=output.get("attempts", 0),
                      reason="暂无可绘制的序列" if kind == "chart" and not output["analysis"].get("charts") else None,
                      retries=progress.retries.get(key, 0))
        if kind == "report" or kind == "delivery" or key == debug:
            result = output
    if debug:
        detail = _node_summary(nodes[debug]["type"], result) if result else None
        return {"workflow_debug": True, "node": debug, "summary": detail,
                "usage": budget.snapshot()}
    if result is None or not result.get("report"):
        raise ServiceError("WORKFLOW_NO_REPORT", "本次分支没有生成报告，请检查报告节点的上游条件")
    return {"analysis": result["analysis"], "report_path": result["report_path"], "children": [], "conflicts": result.get("conflicts", []),
            "usage": budget.snapshot(), "mail": result.get("mail"), "knowledge": result.get("knowledge")}
