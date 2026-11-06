"""Bounded orchestration is independent of A2A transport and model providers."""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from typing import Literal

from pydantic import Field, ValidationError

from ..agent_service.analysis import INFERENCES, RECOMMENDATIONS, AnalysisAgent, identity, validate_analysis
from ..agent_service.charts import chart_data
from ..agent_service.contracts import ServiceError, context, prediction, utcnow
from ..agent_service.mail import MailService
from ..agent_service.reporting import render, save_report
from .a2a import A2AClient
from .execution import DEFAULT_EFFORT, LABELS, Effort, Progress, envelope
from .mcp_layer import MCPLayer
from .models import Budget, ModelAdapter
from .schemas import Closed

RISK_TEXT = {"DATA_LIMITED": "现有事实不足以验证模型可靠性，应补充独立资料。", "MARKET_RISK": "市场波动、模型偏差及分布漂移可能导致损失。"}
UNCERTAINTY = {"NO_CONFIDENCE": "上游未提供置信度。", "NO_CONTEXT": "未提供可验证上下文。", "MODEL_UNVERIFIED": "模型输出尚未独立验证。"}


class TaskRequest(Closed):
    prediction: dict
    context: dict | None = None
    complexity: Literal["auto", "simple", "complex"] = "auto"
    notify: bool = False
    recipient: str | None = None
    depth: int = Field(default=0, ge=0, le=3)
    reasoning_effort: Effort | None = None
    chart_data: dict | None = None
    goal: Literal["overview", "risk", "comparison"] = "overview"


def validate_result(raw, role, p, facts):
    fields = {"conclusion_codes", "evidence_ids", "uncertainty_codes", "delegate_roles"}
    allowed = set(INFERENCES) | set(RECOMMENDATIONS) | set(RISK_TEXT)
    if not isinstance(raw, dict) or set(raw) != fields:
        raise ServiceError("INVALID_AGENT_RESULT", "Agent 返回字段不合规")
    for k in fields:
        if not isinstance(raw[k], list) or len(raw[k]) > 20 or any(not isinstance(v, str) for v in raw[k]):
            raise ServiceError("INVALID_AGENT_RESULT", "Agent 返回必须为有限字符串数组")
    references = {"prediction:" + p["prediction_id"], *(f["id"] for f in facts)}
    if not raw["conclusion_codes"] or set(raw["conclusion_codes"]) - allowed or set(raw["evidence_ids"]) - references:
        raise ServiceError("INVALID_AGENT_RESULT", "Agent 结论或依据不在允许范围内")
    if not raw["evidence_ids"] or set(raw["uncertainty_codes"]) - set(UNCERTAINTY):
        raise ServiceError("INVALID_AGENT_RESULT", "Agent 缺少依据或不确定性不合规")
    if ("NO_CONFIDENCE" in raw["uncertainty_codes"] and p["confidence"] is not None) or ("NO_CONTEXT" in raw["uncertainty_codes"] and facts):
        raise ServiceError("INVALID_AGENT_RESULT", "Agent 的缺失数据声明与输入不一致")
    if set(raw["delegate_roles"]) - {"prediction", "risk", "advice"} or (role != "main" and raw["delegate_roles"]):
        raise ServiceError("DEPTH_LIMIT", "子 Agent 不能继续委派")
    return {"role": role, "status": "completed", "conclusions": raw["conclusion_codes"], "evidence_ids": raw["evidence_ids"],
            "uncertainty": raw["uncertainty_codes"], "delegate_roles": list(dict.fromkeys(raw["delegate_roles"]))}


def a2a_task(tid, state, *, context_id=None, result=None, error=None):
    value = {"kind": "task", "id": tid, "contextId": context_id or tid,
             "status": {"state": state, "timestamp": utcnow().isoformat()}, "artifacts": []}
    if result is not None:
        value["artifacts"] = [{"artifactId": tid + "-result", "name": "analysis", "parts": [{"kind": "data", "data": result}]}]
    if error:
        value["metadata"] = {"error": error}
    return value


class Orchestrator:
    def __init__(self, store):
        self.store, self.models, self.mcp, self.a2a = store, ModelAdapter(store), MCPLayer(store), A2AClient(store)
        self.active = {}
        self.lock = threading.RLock()
        with self.store.db() as con:
            previous_tasks = con.execute("SELECT id,body FROM tasks").fetchall()
        for tid, body in previous_tasks:
            previous = json.loads(body)
            if previous["status"]["state"] in ("working", "submitted"):
                self.store.task(tid, a2a_task(tid, "failed", error={"code": "INTERRUPTED", "message": "进程重启，中断任务未自动重跑"}))

    def prepare(self, raw):
        try:
            request = TaskRequest.model_validate(raw).model_dump()
        except ValidationError:
            raise ServiceError("INVALID_INPUT", "任务字段无效") from None
        request["prediction"] = prediction(request["prediction"])
        request["context"] = context(request["context"], request["prediction"]["subject"])
        request["chart_data"] = chart_data(request["chart_data"], request["prediction"])
        if request["notify"]:
            policy = self.store.settings()["mail"]
            if request["recipient"] not in policy["recipient_allowlist"]:
                raise ServiceError("PERMISSION_DENIED", "收件人不在预授权范围内")
            if request["prediction"]["synthetic"] and not policy["allow_synthetic"]:
                raise ServiceError("PERMISSION_DENIED", "未授权合成报告邮件投递")
        return request

    def submit(self, raw):
        request = self.prepare(raw)
        tid, event = uuid.uuid4().hex, threading.Event()
        with self.lock:
            if len(self.active) >= 4:
                raise ServiceError("BUSY", "最多同时运行 4 个主任务，请稍后再试", True)
            self.active[tid] = {"event": event}
            self.store.task(tid, a2a_task(tid, "submitted"))
        def worker():
            try:
                asyncio.run(self.execute(tid, request, event))
            finally:
                with self.lock:
                    self.active.pop(tid, None)
        threading.Thread(target=worker, daemon=True, name="analysis-" + tid[:8]).start()
        return self.store.task(tid)

    def cancel(self, tid):
        with self.lock:
            task = self.store.task(tid)
            running = self.active.get(tid)
            if task["status"]["state"] in ("completed", "failed", "canceled"):
                raise ServiceError("TASK_NOT_CANCELABLE", "任务已经结束")
            if running:
                running["event"].set()
                if running.get("loop") and running.get("task"):
                    running["loop"].call_soon_threadsafe(running["task"].cancel)
            task["status"]["state"] = "canceled"
            self.store.task(tid, task)
            return task

    async def execute(self, tid, request, event=None):
        settings = self.store.settings()
        level = request.get("reasoning_effort") or settings.get("default_reasoning_effort", DEFAULT_EFFORT)
        limits = envelope(level, settings["limits"])
        settings = {**settings, "reasoning_effort": level, "limits": limits}
        budget = Budget(limits, event)
        progress = Progress(self.store, tid, budget)
        budget.progress = progress
        if tid in self.active:
            self.active[tid].update(loop=asyncio.get_running_loop(), task=asyncio.current_task())
        self.store.task(tid, a2a_task(tid, "working"))
        try:
            async with asyncio.timeout(settings["limits"]["timeout_seconds"]):
                output = await self.analyze(tid, request, settings, budget, progress)
                budget.check()
                self.store.task(tid, a2a_task(tid, "completed", result=output))
        except (ServiceError, TimeoutError) as exc:
            error = exc.as_dict()["error"] if isinstance(exc, ServiceError) else {"code": "TASK_TIMEOUT", "message": "任务超时", "retryable": True}
            if isinstance(exc, ServiceError) and exc.code == "CANCELLED":
                self.store.task(tid, a2a_task(tid, "canceled"))
            else:
                self.store.task(tid, a2a_task(tid, "failed", error=error))
        except asyncio.CancelledError:
            self.store.task(tid, a2a_task(tid, "canceled"))
        except Exception:
            self.store.task(tid, a2a_task(tid, "failed", error={"code": "INTERNAL_ERROR", "message": "任务执行失败", "retryable": False}))
        return self.store.task(tid)

    async def role(self, role, data, settings, budget, *, local_only=False):
        budget.check()
        conf = settings["agents"][role]
        if conf["endpoint_id"] and not local_only:
            endpoint = self.store.get("agents", conf["endpoint_id"])
            raw = await self.a2a.delegate(conf["endpoint_id"], {"role": role, "prediction": data["prediction"],
                                           "facts": data.get("facts", []), "depth": 1, "tools": [],
                                           "cost_ceiling_usd": endpoint["cost_ceiling_usd"]}, budget)
        else:
            mid = conf["model_id"] or settings["default_model_id"]
            if not mid:
                raise ServiceError("MODEL_REQUIRED", "请先配置默认模型或此角色模型")
            raw = await self.models.generate(mid, role, data, settings, budget)
        budget.check()
        return validate_result(raw, role, data["prediction"], data.get("facts", []))

    async def peer(self, role, data, inline=None):
        if role not in ("prediction", "risk", "advice"):
            raise ServiceError("INVALID_PARAMS", "未知 Agent 角色")
        if not isinstance(data, dict) or set(data) - {"role", "prediction", "facts", "depth", "tools", "cost_ceiling_usd"}:
            raise ServiceError("INVALID_PARAMS", "子任务数据字段无效")
        if data.get("tools", []) or type(data.get("depth", 1)) is not int or data.get("depth", 1) != 1:
            raise ServiceError("DEPTH_LIMIT", "当前子 Agent 仅接受深度 1 且无外部工具的任务")
        p = prediction(data.get("prediction"))
        c = context({"schema_version": "1", "context_id": "peer", "subject": p["subject"], "facts": data.get("facts", [])}, p["subject"])
        tid = inline[2] if inline and len(inline) > 2 else uuid.uuid4().hex
        self.store.task(tid, a2a_task(tid, "working"))
        settings, budget = inline[:2] if inline else (self.store.settings(), None)
        peer_event = threading.Event()
        if budget is None:
            limits = {**settings["limits"]}
            ceiling = data.get("cost_ceiling_usd", limits["budget_usd"])
            if type(ceiling) not in (int, float) or not 0 <= ceiling <= 100:
                raise ServiceError("INVALID_PARAMS", "子任务费用上限无效")
            limits["budget_usd"] = min(limits["budget_usd"], ceiling)
            limits["max_calls"] = min(limits["max_calls"], 1)
            budget = Budget(limits, peer_event)
            with self.lock:
                if len(self.active) >= 4:
                    raise ServiceError("BUSY", "本机 Agent 并发上限已达到", True)
                self.active[tid] = {"event": peer_event, "loop": asyncio.get_running_loop(), "task": asyncio.current_task()}
        try:
            async with asyncio.timeout(settings["limits"]["child_timeout_seconds"]):
                result = await self.role(role, {"prediction": p, "facts": c["facts"]}, settings, budget, local_only=True)
            raw = {"conclusion_codes": result["conclusions"], "evidence_ids": result["evidence_ids"],
                   "uncertainty_codes": result["uncertainty"], "delegate_roles": []}
            task = a2a_task(tid, "completed", result=raw)
            self.store.task(tid, task)
            return task
        except asyncio.CancelledError:
            self.store.task(tid, a2a_task(tid, "canceled"))
            raise
        except (ServiceError, TimeoutError) as exc:
            code = exc.code if isinstance(exc, ServiceError) else "CHILD_TIMEOUT"
            self.store.task(tid, a2a_task(tid, "failed", error={"code": code}))
            raise ServiceError(code, "子 Agent 执行失败或超时") from None
        except Exception:
            self.store.task(tid, a2a_task(tid, "failed", error={"code": "CHILD_FAILED"}))
            raise
        finally:
            if not inline:
                with self.lock:
                    self.active.pop(tid, None)

    async def collect(self, p, facts, series, tools, progress, notes):
        for index, binding in enumerate(tools):
            sid, name = binding.split(":", 1)
            safe_name = name if re.fullmatch(r"[\w.-]{1,80}", name) else "已授权行情工具"
            for attempt in range(1, 3):
                try:
                    progress.tool_attempt()
                except ServiceError as exc:
                    notes.append(f"{exc.code}：停止补查，报告使用已校验的数据。")
                    progress.emit("adjustment", label=notes[-1], step="tools", code=exc.code)
                    return facts, series
                progress.emit("tool", step="tools", status="running", label=f"调用 {safe_name} 补充上下文", attempt=attempt)
                try:
                    raw = await self.mcp.call(sid, name, {"subject": p["subject"]}, role_tools=tools)
                    extra = chart_data(raw.get("chart_data"), p)
                    validated = context({k: v for k, v in raw.items() if k != "chart_data"}, p["subject"])
                    incoming = validated["facts"]
                    if {f["id"] for f in facts} & {f["id"] for f in incoming}:
                        raise ServiceError("INVALID_TOOL_DATA", "外部事实 ID 与已有事实冲突")
                except ServiceError as exc:
                    progress.emit("tool", step="tools", status="failed", label=f"{safe_name} 调用失败", code=exc.code, attempt=attempt)
                    retry = exc.retryable and attempt == 1 and progress.tools < progress.budget.limits["max_tool_calls"]
                    if retry:
                        progress.emit("adjustment", step="tools", label=f"{exc.code}：在预算内重试 {safe_name}。")
                        continue
                    notes.append(f"{exc.code}：{safe_name} 未补充数据，后续结论仅使用已有事实。")
                    progress.emit("adjustment", step="tools", label=notes[-1])
                    break
                facts = [*facts, *incoming]
                if extra and series and extra["unit"] == series["unit"]:
                    series = {**series, "series": {**extra["series"], **series["series"]}}
                else:
                    series = series or extra
                dates = sorted(point["at"] for s in (extra or {}).get("series", {}).values() for point in s["points"])
                detail = f"，覆盖 {dates[0][:10]} 至 {dates[-1][:10]} UTC" if dates else ""
                progress.emit("tool", step="tools", status="completed",
                              label=f"{safe_name} 返回 {len(incoming)} 条事实、{len(dates)} 个图表点{detail}")
                if index + 1 < len(tools):
                    if facts and {"observed", "forecast", "backtest"} <= (series or {}).get("series", {}).keys():
                        progress.emit("adjustment", step="tools", label="事实与三类时间序列已齐备，跳过剩余补查。")
                        return facts, series
                    progress.emit("adjustment", step="tools", label="事实或图表序列仍有缺项，继续查询下一项获准工具。")
                break
        return facts, series

    async def analyze(self, tid, request, settings, budget, progress):
        p, c = request["prediction"], request["context"]
        facts = c["facts"] if c else []
        notes, children, results, conflicts = [], [], [], []
        tools = settings["agents"]["main"]["tools"]
        series = request.get("chart_data")
        goal = request.get("goal", "overview")
        focus = {"overview": "综合解读", "risk": "风险分析", "comparison": "历史预测对比"}[goal]
        subject = p["subject"] if re.fullmatch(r"[\w.-]{1,40}", p["subject"]) else "所选股票"
        plan = [("validate", "校验预测与数据"), ("main", "主 Agent 分析"), ("charts", "生成分析图表"), ("report", "汇总并保存报告")]
        if tools:
            plan.insert(1, ("tools", "通过 MCP 补充数据"))
        if request["notify"]:
            plan.append(("mail", "按授权交付邮件"))
        mid = settings["agents"]["main"]["model_id"] or settings["default_model_id"]
        profile = self.store.get("models", mid) if mid else {}
        level = settings["reasoning_effort"]
        native = profile.get("reasoning_effort_map", {}).get(level) if profile.get("provider") == "openai_compatible" else None
        execution = {"effort": level, "label": LABELS[level], "limits": budget.limits,
                     "model": profile.get("model"), "native_reasoning_effort": native}
        progress.emit("plan", label=f"{subject} · {focus}计划", execution=execution,
                      steps=[{"id": key, "label": label} for key, label in plan])
        with progress.step("validate", f"校验 {subject} 未来 {p['horizon']['value']} {p['horizon']['unit']} 的预测结果"):
            prediction(p)
            context(c, p["subject"])
        if tools:
            with progress.step("tools", f"为 {subject} 补充行情与事实"):
                facts, series = await self.collect(p, facts, series, tools, progress, notes)
        c = {"schema_version": "1", "context_id": "task-" + tid, "subject": p["subject"], "facts": facts} if facts else None
        data = {"prediction": p, "facts": facts}
        try:
            with progress.step("main", "主 Agent 分析预测、风险与建议"):
                main = await self.role("main", {**data, "goal": goal}, settings, budget)
            results.append(main)
        except ServiceError as exc:
            main = {"delegate_roles": []}
            notes.append(exc.code + "：主 Agent 降级为确定性分析。")
            progress.emit("adjustment", label=notes[-1], step="main")
        complexity = request["complexity"]
        complex_task = complexity == "complex" or (complexity == "auto" and (len(facts) > 1 or bool(p["metrics"])))
        planned = main["delegate_roles"] if complex_task and budget.limits["max_subagents"] else []
        limit = settings["limits"]
        if request["depth"] >= limit["max_depth"]:
            if planned:
                notes.append("DEPTH_LIMIT：达到委派深度，主 Agent 直接完成。")
            planned = []
        if len(planned) > limit["max_subagents"]:
            notes.append("SUBAGENT_LIMIT：委派数量已按上限裁剪。")
        if planned:
            progress.emit("adjustment", label="复杂任务需要分工，加入 A2A 子步骤。",
                          steps=[{"id": role, "label": role} for role in planned[:limit["max_subagents"]]])
        for role in planned[:limit["max_subagents"]]:
            budget.check()
            child_id = uuid.uuid4().hex
            child = {"id": child_id, "role": role, "status": "working", "depth": request["depth"] + 1,
                     "tools": [], "data_fields": ["prediction", "facts"]}
            self.store.task(child_id, a2a_task(child_id, "working", context_id=tid))
            progress.steps += 1
            progress.emit("step", step=role, status="running", label=f"{role} 子 Agent 通过 A2A 分析", child_id=child_id)
            try:
                async with asyncio.timeout(min(limit["child_timeout_seconds"], max(0.01, budget.deadline - time.monotonic()))):
                    # Lifecycle belongs here; local child uses the same structured A2A contract.
                    from .a2a import A2AService, message
                    if settings["agents"][role]["endpoint_id"]:
                        result = await self.role(role, data, settings, budget)
                    else:
                        reply = await A2AService(self).dispatch({"jsonrpc": "2.0", "id": child_id, "method": "message/send",
                                                                "params": {"message": message({**data, "depth": 1, "tools": []}, tid)}}, role,
                                                               inline=(settings, budget, child_id))
                        if "error" in reply:
                            raise ServiceError(reply["error"]["data"]["code"], "子 Agent 失败")
                        raw = reply["result"]["artifacts"][0]["parts"][0]["data"]
                        result = validate_result(raw, role, p, facts)
                results.append(result)
                child.update(status="completed", result=result)
                self.store.task(child_id, a2a_task(child_id, "completed", context_id=tid, result=result))
                progress.emit("step", step=role, status="completed", label=f"{role} 子 Agent 已完成", summary=result["conclusions"])
            except (ServiceError, TimeoutError) as exc:
                code = exc.code if isinstance(exc, ServiceError) else "CHILD_TIMEOUT"
                child.update(status="degraded", error=code)
                notes.append(f"{role}/{code}：子 Agent 失败，未采纳其结论。")
                self.store.task(child_id, a2a_task(child_id, "failed", context_id=tid, error={"code": code}))
                progress.emit("step", step=role, status="failed", label=notes[-1], code=code)
            except asyncio.CancelledError:
                self.store.task(child_id, a2a_task(child_id, "canceled", context_id=tid))
                raise
            children.append(child)
        if children and results:
            progress.emit("adjustment", label="加入子 Agent 结果汇总步骤。",
                          steps=[{"id": "merge", "label": "复核子 Agent 结果"}])
            try:
                with progress.step("merge", "复核与汇总子 Agent 结果"):
                    merged = await self.role("main", {**data, "goal": goal, "peer_results": results}, settings, budget)
                results.append(merged)
            except ServiceError as exc:
                notes.append(exc.code + "：汇总调用失败，采用经过校验的已有结论。")
        analysis = AnalysisAgent().analyze(p, c)
        expected = "MODEL_" + p["direction"].upper() if "direction" in p else None
        accepted = set()
        for result in results:
            for code in result["conclusions"]:
                if code.startswith("MODEL_") and code != expected:
                    conflicts.append({"role": result["role"], "code": code, "reason": "与上游预测方向冲突"})
                else:
                    accepted.add(code)
        if conflicts:
            notes.append("RESULT_CONFLICT：存在与上游方向冲突的 Agent 结论，已排除；保留不确定性。")
        if accepted & set(RECOMMENDATIONS):
            analysis["recommendations"] = [RECOMMENDATIONS[k] for k in sorted(accepted & set(RECOMMENDATIONS))]
        analysis["risks"] += [RISK_TEXT[k] for k in sorted(accepted & set(RISK_TEXT))]
        for code in sorted({u for result in results for u in result["uncertainty"]}):
            if UNCERTAINTY[code] not in analysis["limitations"]:
                analysis["limitations"].append(UNCERTAINTY[code])
        analysis["limitations"] += notes
        analysis["status"] = "degraded" if notes else "ok"
        analysis["mode"] = "orchestrated_bounded"
        analysis["analysis_id"] = identity({k: v for k, v in analysis.items() if k != "analysis_id"})
        validate_analysis(analysis)
        folder = save_report(self.store.root, analysis)
        mail = None
        if request["notify"]:
            budget.check()
            mail = await self.notify(analysis, request["recipient"], budget)
        return {"analysis": analysis, "children": children, "conflicts": conflicts, "usage": budget.snapshot(),
                "mail": mail, "report_path": str(folder / "report.html")}

    async def notify(self, analysis, recipient, budget):
        # Always reload authorization immediately before the external effect.
        policy = self.store.settings()["mail"]
        if recipient not in policy["recipient_allowlist"] or (analysis["prediction"]["synthetic"] and not policy["allow_synthetic"]):
            raise ServiceError("PERMISSION_DENIED", "邮件授权已撤销或收件人未授权")
        if policy["transport"] != "mcp":
            service = MailService(self.store.root, policy)
            queued = service.enqueue(analysis, recipient)
            budget.reserve()
            return await asyncio.to_thread(service.deliver, queued["id"])
        key = identity([analysis["analysis_id"], recipient, policy["sender"], policy["mcp_server_id"], policy["mcp_tool"]])
        # Durable MCP mail marker. Ambiguous tool errors must never be retried automatically.
        with self.store.db() as con:
            con.execute("CREATE TABLE IF NOT EXISTS mcp_mail (id TEXT PRIMARY KEY,status TEXT)")
            row = con.execute("SELECT status FROM mcp_mail WHERE id=?", (key,)).fetchone()
            if row:
                status = "uncertain" if row[0] == "sending" else row[0]
                con.execute("UPDATE mcp_mail SET status=? WHERE id=?", (status, key))
                return {"id": key, "status": status}
            budget.reserve()
            con.execute("INSERT INTO mcp_mail VALUES (?,'sending')", (key,))
        text, html = render(analysis)
        try:
            result = await self.mcp.call(policy["mcp_server_id"], policy["mcp_tool"],
                                         {"recipient": recipient, "subject": "预测分析报告", "text": text, "html": html, "idempotency_key": key}, effect="email")
            status = ("submitted" if result.get("status") in ("submitted", "sent") else
                      "simulated" if result.get("status") == "simulated" else "uncertain")
        except (ServiceError, asyncio.CancelledError):
            with self.store.db() as con:
                con.execute("UPDATE mcp_mail SET status='uncertain' WHERE id=?", (key,))
            raise
        with self.store.db() as con:
            con.execute("UPDATE mcp_mail SET status=? WHERE id=?", (status, key))
        return {"id": key, "status": status}
