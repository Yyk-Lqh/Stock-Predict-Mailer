"""Bounded orchestration is independent of A2A transport and model providers."""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from concurrent.futures import Future
from typing import Literal

from pydantic import Field, ValidationError

from ..agent_service.analysis import INFERENCES, RECOMMENDATIONS, AnalysisAgent, identity, validate_analysis
from ..agent_service.charts import build_charts, chart_data, chart_svg
from ..agent_service.contracts import ServiceError, context, prediction, utcnow
from ..agent_service.forecast_archive import ForecastArchive
from ..agent_service.forecast_contracts import definition as forecast_definition
from ..agent_service.mail import MailService
from ..agent_service.reporting import save_report
from ..delivery import address
from ..mail_core.transports import MCPTransport
from ..private_knowledge.service import Knowledge
from .a2a import A2AClient
from .execution import DEFAULT_EFFORT, LABELS, Effort, Progress, envelope
from .mcp_layer import MCPLayer
from .memory import LOCAL_KNOWLEDGE_OWNER, Memory, MemoryEntry, ReportFormat, explicit_memory
from .models import Budget, ModelAdapter
from .modes import MODES, PROFESSIONAL, STANDARD, require_mode, task_mode
from .schemas import Closed
from .workflow import freeze

RISK_TEXT = {"DATA_LIMITED": "现有事实不足以验证模型可靠性，应补充独立资料。", "MARKET_RISK": "市场波动、模型偏差及分布漂移可能导致损失。"}
UNCERTAINTY = {"NO_CONFIDENCE": "上游未提供置信度。", "NO_CONTEXT": "未提供可验证上下文。", "MODEL_UNVERIFIED": "模型输出尚未独立验证。"}


class TaskRequest(Closed):
    prediction: dict | None = None
    evaluation_definition: dict | None = None
    context: dict | None = None
    complexity: Literal["auto", "simple", "complex"] = "auto"
    notify: bool = False
    recipient: str | None = None
    recipients: list[str] = Field(default_factory=list, max_length=50)
    depth: int = Field(default=0, ge=0, le=3)
    reasoning_effort: Effort | None = None
    model_id: str | None = None
    tools: list[str] | None = None
    chart_data: dict | None = None
    goal: Literal["overview", "risk", "comparison"] = "overview"
    conversation_id: str | None = None
    message: str = Field(default="", max_length=4000)
    constraints: list[str] = Field(default_factory=list, max_length=12)
    report_format: ReportFormat | None = None
    remember: list[MemoryEntry] = Field(default_factory=list, max_length=10)
    fresh_context: bool = False
    knowledge_query: str = Field(default="", max_length=4000)
    knowledge_to_model: bool = False


def validate_result(raw, role, p, facts, knowledge_ids=()):
    fields = {"conclusion_codes", "evidence_ids", "uncertainty_codes", "delegate_roles"}
    allowed = set(INFERENCES) | set(RECOMMENDATIONS) | set(RISK_TEXT)
    if not isinstance(raw, dict) or set(raw) != fields:
        raise ServiceError("INVALID_AGENT_RESULT", "Agent 返回字段不合规")
    for k in fields:
        if not isinstance(raw[k], list) or len(raw[k]) > 20 or any(not isinstance(v, str) for v in raw[k]):
            raise ServiceError("INVALID_AGENT_RESULT", "Agent 返回必须为有限字符串数组")
    references = {"prediction:" + p["prediction_id"], *(f["id"] for f in facts), *knowledge_ids}
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


def a2a_task(tid, state, *, context_id=None, result=None, error=None, brief=None, workflow=None, mode=None):
    value = {"kind": "task", "id": tid, "contextId": context_id or tid,
             "status": {"state": state, "timestamp": utcnow().isoformat()}, "artifacts": []}
    if result is not None:
        value["artifacts"] = [{"artifactId": tid + "-result", "name": "analysis", "parts": [{"kind": "data", "data": result}]}]
    metadata = {}
    # 任务清单只读元数据：让列表在不解析产物的前提下显示标的与方向。
    if brief:
        metadata["request"] = brief
    if error:
        metadata["error"] = error
    if workflow:
        metadata["workflow"] = workflow
    if mode:
        metadata["mode"] = mode
    if metadata:
        value["metadata"] = metadata
    return value


def task_brief(request):
    p = request.get("prediction") or {}
    return {"subject": p.get("subject"), "direction": p.get("direction"),
            "horizon": p.get("horizon"), "confidence": p.get("confidence"),
            "synthetic": p.get("synthetic"), "notify": bool(request.get("notify")),
            "recipient": request.get("recipient"), "recipients": request.get("recipients", []), "goal": request.get("goal"),
            "conversation_id": request.get("conversation_id"), "model_id": request.get("model_id")}


class Orchestrator:
    def __init__(self, store):
        self.store, self.models, self.mcp, self.a2a = store, ModelAdapter(store), MCPLayer(store), A2AClient(store)
        self.memory = Memory(store)
        self.knowledge = Knowledge(store)
        self.active = {}
        self.accepting = True
        self.lock = threading.RLock()
        with self.store.db() as con:
            previous_tasks = con.execute("SELECT id,body FROM tasks WHERE json_valid(body)").fetchall()
        for tid, body in previous_tasks:
            previous = json.loads(body)
            if previous["status"]["state"] in ("working", "submitted"):
                meta = previous.get("metadata", {})
                self.store.task(tid, a2a_task(tid, "failed", context_id=previous.get("contextId"),
                                             brief=meta.get("request"), workflow=meta.get("workflow"), mode=task_mode(previous),
                                             error={"code": "INTERRUPTED", "message": "进程重启，中断任务未自动重跑"}))

    def prepare(self, raw, owner=None, *, knowledge_owner=None, mode=STANDARD):
        cid = raw.get("conversation_id")
        state = {}
        if cid is not None:
            if not owner:
                raise ServiceError("FORBIDDEN", "会话任务需要记忆访问密钥")
            if not isinstance(cid, str):
                raise ServiceError("INVALID_INPUT", "会话 ID 无效")
            state = self.memory.state(owner, cid, mode)
        elif raw.get("remember") or raw.get("message"):
            raise ServiceError("INVALID_INPUT", "请先创建会话")
        raw = dict(raw)
        previous = state.get("request", {})
        replacement = raw.get("prediction")
        same_subject = replacement is None or (isinstance(replacement, dict) and
                                               replacement.get("subject") == previous.get("prediction", {}).get("subject"))
        if cid and previous and same_subject:
            for key in ("constraints", "goal", "complexity", "reasoning_effort", "report_format"):
                if key in previous:
                    raw.setdefault(key, previous[key])
        if cid and previous and replacement is None:
            raw["prediction"] = previous["prediction"]
            if not raw.get("fresh_context") and "context" not in raw:
                raw["context"] = previous.get("context")
            if "chart_data" not in raw:
                raw["chart_data"] = previous.get("chart_data")
        try:
            request = TaskRequest.model_validate(raw).model_dump()
        except ValidationError:
            raise ServiceError("INVALID_INPUT", "任务字段无效") from None
        request["_mode"] = mode
        if request["knowledge_query"]:
            if not cid and knowledge_owner != LOCAL_KNOWLEDGE_OWNER:
                raise ServiceError("FORBIDDEN", "引用私有资料需要所属会话")
            request["_knowledge_owner"] = knowledge_owner or owner
        if request["prediction"] is None:
            raise ServiceError("INVALID_INPUT", "请先提供该会话的预测结果")
        request["prediction"] = prediction(request["prediction"])
        if request["evaluation_definition"] is not None:
            request["evaluation_definition"] = forecast_definition(request["evaluation_definition"], request["prediction"], utcnow())
        if any(not item or len(item) > 240 for item in request["constraints"]):
            raise ServiceError("INVALID_INPUT", "每条约束须为 1 至 240 字符")
        request["context"] = context(request["context"], request["prediction"]["subject"])
        request["chart_data"] = chart_data(request["chart_data"], request["prediction"])
        if cid:
            request["_owner"] = owner
            memory_enabled = self.memory.settings(owner)["enabled"]
            if request["remember"] and not memory_enabled:
                raise ServiceError("MEMORY_DISABLED", "长期记忆已关闭，请开启后再保存")
            if memory_enabled and not request["remember"]:
                explicit = explicit_memory(request["message"], request["prediction"]["subject"])
                if explicit:
                    request["remember"] = [explicit]
            request["fresh_context"] = request["fresh_context"] or ("context" in raw and raw["context"] != previous.get("context"))
            for item in request["remember"]:
                if item["kind"] == "prediction":
                    p = request["prediction"]
                    item.update(subject=p["subject"], applies_at=p["generated_at"], data_version=p["model_version"],
                                content=json.dumps(p, ensure_ascii=False)[:800])
        if request["notify"]:
            policy = self.store.settings()["mail"]
            try:
                request["recipients"] = list(dict.fromkeys(address(item) for item in
                    (request["recipients"] or ([request["recipient"]] if request["recipient"] else []))))
            except ValueError:
                raise ServiceError("INVALID_INPUT", "收件邮箱格式无效") from None
            if not request["recipients"]:
                raise ServiceError("INVALID_INPUT", "请至少填写一个收件邮箱")
            request["recipient"] = request["recipients"][0]
            if any(item not in policy["recipient_allowlist"] for item in request["recipients"]):
                raise ServiceError("PERMISSION_DENIED", "收件人不在预授权范围内")
            if request["prediction"]["synthetic"] and not policy["allow_synthetic"]:
                raise ServiceError("PERMISSION_DENIED", "未授权合成报告邮件投递")
        return request

    def close_admission(self):
        with self.lock:
            self.accepting = False
            return list(self.active)

    def execution_settings(self, settings, model=None, tools=None):
        main = dict(settings["agents"]["main"])
        if model is not None:
            if not isinstance(model, str) or not self.store.get("models", model)["enabled"]:
                raise ServiceError("MODEL_REQUIRED", "所选模型不可用")
            main["model_id"] = model
            settings = {**settings, "default_model_id": model}
        if tools is not None:
            if not isinstance(tools, list) or any(not isinstance(tool, str) or tool not in main["tools"] for tool in tools):
                raise ServiceError("PERMISSION_DENIED", "本轮仅可使用主 Agent 已授权的工具")
            main["tools"] = list(dict.fromkeys(tools))
        return {**settings, "agents": {**settings["agents"], "main": main}}

    def submit(self, raw, owner=None, *, knowledge_owner=None, mode=None, workflow_ref=None):
        tid, event = uuid.uuid4().hex, threading.Event()
        raw = dict(raw)
        graph = raw.pop("workflow", None)
        mode = mode or (PROFESSIONAL if graph is not None else STANDARD)
        if mode not in MODES or (graph is not None) != (mode == PROFESSIONAL):
            raise ServiceError("INVALID_INPUT", "任务模式与工作流输入不匹配")
        workflow = None
        with self.lock:
            if isinstance(raw.get("conversation_id"), str) and owner:
                self.memory.state(owner, raw["conversation_id"], mode)
                bound_workflow = self.memory.flow_for(owner, raw["conversation_id"])
                if bound_workflow != (workflow_ref["id"] if workflow_ref else None):
                    raise ServiceError("FORBIDDEN", "会话属于其他流程")
            if graph is not None:
                key = graph.get("key") if isinstance(graph, dict) else None
                scope = identity([owner, "workflow-chat", workflow_ref["id"], key]) if workflow_ref else identity([owner, raw.get("conversation_id"), key])
                fingerprint = identity([workflow_ref, graph, knowledge_owner] if workflow_ref else
                                       [raw, graph, knowledge_owner] if knowledge_owner else [raw, graph])
                if isinstance(key, str):
                    with self.store.db() as con:
                        prior = con.execute("SELECT body FROM tasks WHERE json_extract(body,'$.metadata.workflow.submission')=?",
                                            (scope,)).fetchone()
                    if prior:
                        saved = json.loads(prior[0])
                        require_mode(task_mode(saved), mode)
                        if saved["metadata"]["workflow"]["fingerprint"] != fingerprint:
                            raise ServiceError("WORKFLOW_CONFLICT", "此提交标识已用于其他输入或流程版本")
                        return saved
            if not self.accepting:
                raise ServiceError("SERVICE_STOPPING", "控制台正在停止，不再接收新的分析任务", True)
            if len(self.active) >= 4:
                raise ServiceError("BUSY", "最多同时运行 4 个主任务，请稍后再试", True)
            settings = self.execution_settings(self.store.settings(), raw.get("model_id"), raw.get("tools"))
            if graph is not None:
                workflow = freeze(graph, self, settings)
                workflow.update(submission=scope, fingerprint=fingerprint, started_at=utcnow().isoformat())
                if workflow_ref:
                    main = settings["agents"]["main"]
                    workflow["flow"] = {**workflow_ref, "selection": {
                        "model_id": main["model_id"] or settings["default_model_id"], "tools": main["tools"],
                        "knowledge_scope": workflow_ref["choices"].get("knowledge_scope")}}
            variables = workflow and workflow.get("variables")
            if variables:
                from .workflow_values import prepare

                if not owner:
                    raise ServiceError("FORBIDDEN", "变量流程运行需要所属工作区")
                request = {**prepare(workflow["graph"], raw, knowledge_owner), "_mode": mode}
            else:
                request = self.prepare(raw, owner, knowledge_owner=knowledge_owner, mode=mode)
            brief = task_brief(request)
            submitted = a2a_task(tid, "submitted", brief=brief, workflow=workflow, mode=mode)
            if (cid := request["conversation_id"]) and not (workflow and (workflow["debug"] or variables)):
                previous = self.memory.state(owner, cid)
                if previous.get("task") in self.active:
                    raise ServiceError("BUSY", "会话任务正在收尾", True)
                self.memory.begin(owner, cid, tid, request, submitted)
            else:
                if cid or variables:
                    self.memory.bind_child(owner, cid or "", tid)
                self.store.task(tid, submitted)
            self.active[tid] = {"event": event}
        def worker():
            try:
                asyncio.run(self.execute(tid, request, event, workflow=workflow, frozen_settings=settings))
            finally:
                with self.lock:
                    self.active.pop(tid, None)
        threading.Thread(target=worker, daemon=True, name="analysis-" + tid[:8]).start()
        return self.store.task(tid)

    def cancel(self, tid, mode=None):
        with self.lock:
            task = self.store.task(tid)
            require_mode(task_mode(task), mode)
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

    def delete_task(self, tid, mode):
        with self.lock:
            task = self.store.task(tid)
            require_mode(task_mode(task), mode)
            if tid in self.active or task["status"]["state"] in ("submitted", "working"):
                raise ServiceError("BUSY", "请先取消或等待任务结束", True)
            self.memory.delete_task(tid)
        return {"status": "deleted"}

    async def wait_for_workflow_input(self, node, label, config, budget):
        progress = budget.progress
        request_id, response = uuid.uuid4().hex, Future()
        budget.check()
        with self.lock:
            task = self.active[progress.tid]
            task["input"] = {"id": request_id, "node": node, "future": response, "fields": config["fields"]}
        started = time.monotonic()
        budget.timer.reschedule(None)
        try:
            progress.emit("step", step=node, label=label, status="needs_input", request_id=request_id,
                          prompt=config["prompt"], fields=config["fields"], wait_seconds=config["wait_seconds"])
            async with asyncio.timeout(config["wait_seconds"]):
                values = await asyncio.shield(asyncio.wrap_future(response))
        except TimeoutError:
            raise ServiceError("WORKFLOW_INPUT_TIMEOUT", f"{node} · 等待用户处理超时", True) from None
        finally:
            with self.lock:
                task.pop("input", None)
                response.cancel()
            budget.deadline += time.monotonic() - started
            budget.timer.reschedule(asyncio.get_running_loop().time() + max(0, budget.deadline - time.monotonic()))
        budget.check()
        progress.emit("step", step=node, label=label, status="running")
        return values

    def continue_workflow(self, tid, owner, body):
        from .workflow_values import bind_fields

        if (not owner or self.memory.task_owner(tid) != owner):
            raise ServiceError("FORBIDDEN", "仅运行所有者可以提交人工输入")
        require_mode(task_mode(self.store.task(tid)), PROFESSIONAL)
        if (set(body) != {"request_id", "node", "values"} or not isinstance(body["request_id"], str)
                or not isinstance(body["node"], str) or not isinstance(body["values"], dict)):
            raise ServiceError("INVALID_INPUT", "人工输入需要请求标识、节点和字段值")
        with self.lock:
            active = self.active.get(tid)
            pending = active.get("input") if active else None
            if (not pending or active["event"].is_set() or pending["id"] != body["request_id"]
                    or pending["node"] != body["node"] or pending["future"].done()):
                raise ServiceError("WORKFLOW_CONFLICT", "此节点已处理或本次运行已停止", True)
            values = bind_fields(pending["fields"], body["values"], pending["node"])
            if len(json.dumps(values, ensure_ascii=False, allow_nan=False).encode()) > 4000:
                raise ServiceError("INVALID_INPUT", "人工输入超过 4 KB")
            pending["future"].set_result(values)
        return {"status": "accepted"}

    async def execute(self, tid, request, event=None, *, workflow=None, frozen_settings=None):
        settings = frozen_settings or self.execution_settings(self.store.settings(), request.get("model_id"), request.get("tools"))
        mode = request.get("_mode", STANDARD)
        brief = task_brief(request)
        level = request.get("reasoning_effort") or settings.get("default_reasoning_effort", DEFAULT_EFFORT)
        limits = envelope(level, settings["limits"])
        settings = {**settings, "reasoning_effort": level, "limits": limits}
        budget = Budget(limits, event)
        progress = Progress(self.store, tid, budget)
        budget.progress = progress
        if (cid := request.get("conversation_id")) and not (workflow and workflow.get("variables")):
            owner = request["_owner"]
            budget.memory_context = lambda size: self.memory.context(owner, cid, request, size, progress)
        if tid in self.active:
            self.active[tid].update(loop=asyncio.get_running_loop(), task=asyncio.current_task())
        def persist(state, **details):
            self.store.task(tid, a2a_task(tid, state, brief=brief, workflow=workflow, mode=mode, **details))

        try:
            budget.check()
            persist("working")
            async with asyncio.timeout(settings["limits"]["timeout_seconds"]) as timer:
                if workflow and workflow.get("variables"):
                    from .workflow_values import run

                    budget.timer = timer
                    output = await run(self, workflow, request, settings, budget, progress)
                elif workflow and workflow["mode"] == "custom":
                    from .workflow_runtime import run

                    output = await run(self, workflow, request, settings, budget, progress)
                else:
                    output = await self.analyze(tid, request, settings, budget, progress)
                budget.check()
                persist("completed", result=output)
        except (ServiceError, TimeoutError) as exc:
            error = exc.as_dict()["error"] if isinstance(exc, ServiceError) else {"code": "TASK_TIMEOUT", "message": "任务超时", "retryable": True}
            persist("canceled" if error["code"] == "CANCELLED" else "failed", **({} if error["code"] == "CANCELLED" else {"error": error}))
        except asyncio.CancelledError:
            persist("canceled")
        except Exception:
            persist("failed", error={"code": "INTERNAL_ERROR", "message": "任务执行失败", "retryable": False})
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
                if role == "main" and budget.memory_context:
                    budget.recalled = budget.memory_context(0)["recalled"]
                raise ServiceError("MODEL_REQUIRED", "请先配置默认模型或此角色模型")
            raw = await self.models.generate(mid, role, data, settings, budget)
        budget.check()
        return validate_result(raw, role, data["prediction"], data.get("facts", []),
                               [r["citation_id"] for r in data.get("source_material", {}).get("results", [])] if role == "main" else [])

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

    async def collect(self, p, facts, series, tools, progress, notes, *, step="tools"):
        for index, binding in enumerate(tools):
            sid, name = binding.split(":", 1)
            safe_name = name if re.fullmatch(r"[\w.-]{1,80}", name) else "已授权行情工具"
            for attempt in range(1, 3):
                try:
                    progress.tool_attempt()
                except ServiceError as exc:
                    notes.append(f"{exc.code}：停止补查，报告使用已校验的数据。")
                    progress.emit("adjustment", label=notes[-1], step=step, code=exc.code)
                    return facts, series
                progress.emit("tool", step=step, status="running", label=f"调用 {safe_name} 补充上下文", attempt=attempt)
                try:
                    raw = await self.mcp.call(sid, name, {"subject": p["subject"]}, role_tools=tools)
                    extra = chart_data(raw.get("chart_data"), p)
                    validated = context({k: v for k, v in raw.items() if k != "chart_data"}, p["subject"])
                    incoming = validated["facts"]
                    if {f["id"] for f in facts} & {f["id"] for f in incoming}:
                        raise ServiceError("INVALID_TOOL_DATA", "外部事实 ID 与已有事实冲突")
                except ServiceError as exc:
                    progress.emit("tool", step=step, status="failed", label=f"{safe_name} 调用失败", code=exc.code, attempt=attempt)
                    retry = exc.retryable and attempt == 1 and progress.tools < progress.budget.limits["max_tool_calls"]
                    if retry:
                        progress.retries[step] = progress.retries.get(step, 0) + 1
                        progress.emit("adjustment", step=step, label=f"{exc.code}：在预算内重试 {safe_name}。")
                        continue
                    notes.append(f"{exc.code}：{safe_name} 未补充数据，后续结论仅使用已有事实。")
                    progress.emit("adjustment", step=step, label=notes[-1])
                    break
                facts = [*facts, *incoming]
                if extra and series and extra["unit"] == series["unit"]:
                    series = {**series, "series": {**extra["series"], **series["series"]}}
                else:
                    series = series or extra
                dates = sorted(point["at"] for s in (extra or {}).get("series", {}).values() for point in s["points"])
                detail = f"，覆盖 {dates[0][:10]} 至 {dates[-1][:10]} UTC" if dates else ""
                progress.emit("tool", step=step, status="completed",
                              label=f"{safe_name} 返回 {len(incoming)} 条事实、{len(dates)} 个图表点{detail}")
                if index + 1 < len(tools):
                    if facts and {"observed", "forecast", "backtest"} <= (series or {}).get("series", {}).keys():
                        progress.emit("adjustment", step=step, label="事实与三类时间序列已齐备，跳过剩余补查。")
                        return facts, series
                    progress.emit("adjustment", step=step, label="事实或图表序列仍有缺项，继续查询下一项获准工具。")
                break
        return facts, series

    def workflow_evidence(self, owner, knowledge_result, main_data, notes):
        evidence = []
        if knowledge_result:
            # Keep whole excerpts: never silently truncate financial statements.
            for item in knowledge_result["results"]:
                current = self.knowledge.citation(owner, item["citation_id"])
                if current["document"]["status"] != "ready" or current["document"]["hash"] != item["source_hash"] or current["document"]["metadata"] != {k: v for k, v in item["metadata"].items() if k in current["document"]["metadata"]}:
                    continue
                entry = {k: item[k] for k in ("citation_id", "document_id", "source_hash", "filename", "location", "text", "metadata", "warnings", "trust")}
                if len(json.dumps(evidence + [entry], ensure_ascii=False).encode()) <= min(4000, max(0, 8000 - len(json.dumps(main_data, ensure_ascii=False).encode()))):
                    evidence.append(entry)
        if knowledge_result and len(evidence) < len(knowledge_result["results"]):
            notes.append("KNOWLEDGE_BUDGET：部分资料未进入模型证据包；请在知识检索中查看完整来源。")
        return evidence

    @staticmethod
    def integrate_analysis(p, c, forecast, results, notes, progress):
        conflicts = []
        analysis = AnalysisAgent().analyze(p, c, forecast_record=forecast["record"] if forecast else None)
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
            progress.emit("adjustment", label=notes[-1], step="report")
        if accepted & set(RECOMMENDATIONS):
            analysis["recommendations"] = [RECOMMENDATIONS[k] for k in sorted(accepted & set(RECOMMENDATIONS))]
        analysis["risks"] += [RISK_TEXT[k] for k in sorted(accepted & set(RISK_TEXT))]
        for code in sorted({u for result in results for u in result["uncertainty"]}):
            if UNCERTAINTY[code] not in analysis["limitations"]:
                analysis["limitations"].append(UNCERTAINTY[code])
        return analysis, conflicts

    async def analyze(self, tid, request, settings, budget, progress):
        from .workflow_runtime import summary

        p, c = request["prediction"], request["context"]
        forecast = None
        facts = c["facts"] if c else []
        notes, children, results = [], [], []
        tools = settings["agents"]["main"]["tools"]
        series = request.get("chart_data")
        cid, owner = request.get("conversation_id"), request.get("_owner")
        checkpoint = self.memory.state(owner, cid).get("checkpoint", {}) if cid else {}
        goal = request.get("goal", "overview")
        focus = {"overview": "综合解读", "risk": "风险分析", "comparison": "历史预测对比"}[goal]
        subject = p["subject"] if re.fullmatch(r"[\w.-]{1,40}", p["subject"]) else "所选股票"
        plan = [("validate", "校验预测与数据"), ("main", "主 Agent 分析"), ("charts", "生成分析图表"), ("report", "汇总并保存报告")]
        if tools:
            plan.insert(1, ("tools", "通过 MCP 补充数据"))
        if request.get("knowledge_query"):
            plan.insert(1, ("knowledge", "检索已授权的知识资料"))
        if request.get("evaluation_definition") is not None:
            plan.insert(1, ("forecast", "固定预测与评价定义"))
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
        progress.emit("step", step="input", status="completed", label="已读取预测资料",
                      summary={"synthetic": p["synthetic"], "confidence": p["confidence"], "source": p["model_version"]})
        with progress.step("validate", f"校验 {subject} 未来 {p['horizon']['value']} {p['horizon']['unit']} 的预测结果"):
            prediction(p)
            context(c, p["subject"])
        progress.emit("node_result", step="validate", label="资料校验输出摘要", status="completed",
                      summary=summary({"request": request, "facts": facts, "series": series}))
        if request.get("evaluation_definition") is not None:
            with progress.step("forecast", "归档本次预测与事前评价定义"):
                forecast = ForecastArchive(self.store.root).register(p, request["evaluation_definition"])
            progress.emit("forecast", step="forecast", label="事前预测已归档", forecast_id=forecast["record"]["forecast_id"],
                          created=forecast["created"])
        budget.check()
        knowledge_result = None
        if request.get("knowledge_query"):
            with progress.step("knowledge", "检索已授权的知识资料", count=False):
                knowledge_result = await asyncio.to_thread(self.knowledge.answer, request["_knowledge_owner"], request["knowledge_query"],
                                                            as_of=p["generated_at"][:10])
            progress.emit("node_result", step="knowledge", label="知识检索来源", status="completed",
                          summary=summary({"request": request, "facts": facts, "series": series, "knowledge": knowledge_result}))
        if tools:
            with progress.step("tools", f"为 {subject} 补充行情与事实"):
                if checkpoint.get("tools") == tools and "facts" in checkpoint:
                    try:
                        saved_context = context({"schema_version": "1", "context_id": "checkpoint", "subject": p["subject"],
                                                 "facts": checkpoint["facts"]}, p["subject"])
                        facts, series = saved_context["facts"], series or checkpoint.get("chart_data")
                        progress.emit("memory", label="已复用同一预测的校验数据步骤")
                    except ServiceError:
                        progress.emit("memory", label="会话数据已过期，重新执行补查")
                        facts, series = await self.collect(p, facts, series, tools, progress, notes)
                else:
                    facts, series = await self.collect(p, facts, series, tools, progress, notes)
                if cid and not notes:
                    self.memory.checkpoint(owner, cid, facts=facts, chart_data=series, tools=tools, completed_step="tools")
            progress.emit("node_result", step="tools", label="MCP 上下文输出摘要", status="degraded" if notes else "completed", attempts=progress.tools,
                          retries=progress.retries.get("tools", 0), summary=summary({"request": request, "facts": facts, "series": series}))
        c = {"schema_version": "1", "context_id": "task-" + tid, "subject": p["subject"], "facts": facts} if facts else None
        data = {"prediction": p, "facts": facts}
        main_data = {**data, "goal": goal, "user_constraints": request.get("constraints", []),
                     "report_format": request.get("report_format")}
        evidence = self.workflow_evidence(request.get("_knowledge_owner"), knowledge_result, main_data, notes)
        if evidence and request.get("knowledge_to_model"):
            main_data["source_material"] = {"trust": "untrusted_source_material", "as_of": knowledge_result["as_of"], "results": evidence}
        try:
            with progress.step("main", "主 Agent 分析预测、风险与建议"):
                main = await self.role("main", main_data, settings, budget)
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
        planned_roles = planned[:limit["max_subagents"]]
        if planned_roles:
            progress.emit("adjustment", label="复杂任务需要分工，加入 A2A 子步骤。",
                          steps=[{"id": role, "label": role} for role in planned_roles])
        final_plan = list(plan)
        if planned_roles:
            after_main = next(i + 1 for i, (key, _) in enumerate(plan) if key == "main")
            final_plan[after_main:after_main] = [(role, role) for role in planned_roles] + [("merge", "复核子 Agent 结果")]
        progress.emit("plan", label=f"{subject} · {focus}最终执行计划", execution=execution, finalized=True,
                      steps=[{"id": key, "label": label} for key, label in final_plan])
        for role in planned_roles:
            budget.check()
            started = time.monotonic()
            child_id = uuid.uuid4().hex
            if cid:
                self.memory.bind_child(owner, cid, child_id)
            child = {"id": child_id, "role": role, "status": "working", "depth": request["depth"] + 1,
                     "tools": [], "data_fields": ["prediction", "facts"]}
            self.store.task(child_id, a2a_task(child_id, "working", context_id=tid, mode=request.get("_mode", STANDARD)))
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
                self.store.task(child_id, a2a_task(child_id, "completed", context_id=tid, result=result, mode=request.get("_mode", STANDARD)))
                progress.emit("step", step=role, status="completed", label=f"{role} 子 Agent 已完成", summary=result["conclusions"],
                              duration_ms=round((time.monotonic() - started) * 1000))
            except (ServiceError, TimeoutError) as exc:
                code = exc.code if isinstance(exc, ServiceError) else "CHILD_TIMEOUT"
                child.update(status="degraded", error=code)
                notes.append(f"{role}/{code}：子 Agent 失败，未采纳其结论。")
                self.store.task(child_id, a2a_task(child_id, "failed", context_id=tid, error={"code": code}, mode=request.get("_mode", STANDARD)))
                progress.emit("step", step=role, status="degraded", label=notes[-1], code=code,
                              duration_ms=round((time.monotonic() - started) * 1000))
            except asyncio.CancelledError:
                self.store.task(child_id, a2a_task(child_id, "canceled", context_id=tid, mode=request.get("_mode", STANDARD)))
                progress.emit("step", step=role, status="canceled", label=f"{role} 子 Agent 已取消",
                              duration_ms=round((time.monotonic() - started) * 1000))
                raise
            children.append(child)
        if children and results:
            progress.emit("adjustment", label="加入子 Agent 结果汇总步骤。",
                          steps=[{"id": "merge", "label": "复核子 Agent 结果"}])
            try:
                with progress.step("merge", "复核与汇总子 Agent 结果"):
                    merged = await self.role("main", {**main_data, "peer_results": results}, settings, budget)
                results.append(merged)
            except ServiceError as exc:
                notes.append(exc.code + "：汇总调用失败，采用经过校验的已有结论。")
        analysis, conflicts = self.integrate_analysis(p, c, forecast, results, notes, progress)
        progress.emit("analysis", label="已有分析可预览", preview={"inferences": analysis["inferences"], "risks": analysis["risks"]})
        with progress.step("charts", "根据已校验数据生成图表"):
            figures, chart_notes = build_charts(series)
            if goal == "comparison":
                figures.reverse()
            if figures:
                analysis["charts"] = figures
            for chart in figures:
                progress.emit("chart", label=chart["title"] + "已生成", svg=chart_svg(chart), caption=chart["caption"])
            if chart_notes:
                progress.emit("adjustment", step="charts", label=" ".join(chart_notes))
        progress.emit("node_result", step="charts", label="图表输出摘要", status="completed", reason=None if figures else "暂无可绘制的序列",
                      summary=summary({"request": request, "facts": facts, "series": series, "analysis": analysis}))
        analysis["limitations"] += notes + chart_notes
        if cid:
            preference = next((item["report_format"] for item in budget.recalled if item.get("report_format")), None)
            analysis["report_format"] = request.get("report_format") or preference or "standard"
            analysis["user_constraints"] = request.get("constraints", [])
        if evidence:
            analysis["knowledge_evidence"] = {"as_of": knowledge_result["as_of"], "results": evidence,
                                              "used_ids": sorted({eid for result in results for eid in result["evidence_ids"]
                                                                  if eid in {e["citation_id"] for e in evidence}})}
        analysis["status"] = "degraded" if notes else "ok"
        analysis["mode"] = "orchestrated_bounded"
        analysis["analysis_id"] = identity({k: v for k, v in analysis.items() if k != "analysis_id"})
        with progress.step("report", "校验并保存分析报告"):
            validate_analysis(analysis)
            folder = save_report(self.store.root, analysis)
            if cid:
                self.memory.checkpoint(owner, cid, completed_step="report", analysis_id=analysis["analysis_id"])
        progress.emit("report", step="report", label="分析报告已保存",
                      preview={"inferences": analysis["inferences"], "risks": analysis["risks"], "limitations": analysis["limitations"]})
        mail = None
        if request["notify"]:
            try:
                with progress.step("mail", "交付已授权的邮件报告"):
                    mail = await self.notify_many(analysis, request["recipients"], budget, progress)
                progress.emit("mail", step="mail", label=f"邮件状态：{mail['status']}", status=mail["status"])
            except ServiceError as exc:
                mail = {"status": "uncertain" if exc.code == "MAIL_UNCERTAIN" else "failed", "error": exc.code}
                progress.emit("mail", step="mail", label=exc.message, status=mail["status"], code=exc.code)
        return {"analysis": analysis, "children": children, "conflicts": conflicts, "usage": budget.snapshot(),
                "execution": execution, "mail": mail, "report_path": str(folder / "report.html"), "knowledge": knowledge_result}

    async def notify_many(self, analysis, recipients, budget, progress):
        if len(recipients) == 1:
            return await self.notify(analysis, recipients[0], budget, progress)
        deliveries = []
        for recipient in recipients:
            try:
                result = await self.notify(analysis, recipient, budget, progress)
            except ServiceError as exc:
                result = {"status": "uncertain" if exc.code == "MAIL_UNCERTAIN" else "failed", "error": exc.code}
            deliveries.append({**result, "recipient": recipient})
            progress.emit("mail_recipient", step="mail", recipient=recipient, status=result["status"], label="邮箱投递状态")
        statuses = {item["status"] for item in deliveries}
        return {"status": next(iter(statuses)) if len(statuses) == 1 else "partial",
                "recipients": recipients, "deliveries": deliveries}

    async def notify(self, analysis, recipient, budget, progress):
        # Always reload authorization immediately before the external effect.
        policy = self.store.settings()["mail"]
        if recipient not in policy["recipient_allowlist"] or (analysis["prediction"]["synthetic"] and not policy["allow_synthetic"]):
            raise ServiceError("PERMISSION_DENIED", "邮件授权已撤销或收件人未授权")
        if policy["transport"] != "mcp":
            service = MailService(self.store.root, policy)
            budget.reserve()
            queued = service.enqueue(analysis, recipient)
            return await asyncio.to_thread(service.deliver, queued["id"])
        from ..mail_core.bindings import mcp_profile
        from ..mail_core.history import historical_result, require_new_prediction
        key = identity([analysis["analysis_id"], recipient, policy["sender"], policy["mcp_server_id"], policy["mcp_tool"]])
        historical = historical_result(self.store.root, key)
        if historical is not None:
            return historical
        service = MailService(self.store.root, policy)
        require_new_prediction(service, analysis)
        selected = mcp_profile(self.store, policy)
        queued = service.enqueue(analysis, recipient, mcp_profile=selected)

        def authorize():
            budget.check()
            current = self.store.settings()["mail"]
            if (current["transport"] != "mcp" or current["sender"] != policy["sender"]
                    or recipient not in current["recipient_allowlist"]
                    or (analysis["prediction"]["synthetic"] and not current["allow_synthetic"])):
                raise ServiceError("PERMISSION_DENIED", "邮件投递授权已经变化")
            if mcp_profile(self.store, current) != selected:
                raise ServiceError("MAIL_ENDPOINT_CHANGED", "邮件投递端点已经变化")
            profile = self.store.get("mcp", selected["server_id"])
            if not profile["enabled"] or selected["tool"] not in profile["allowed_tools"] or profile["effects"].get(selected["tool"]) != "email":
                raise ServiceError("PERMISSION_DENIED", "MCP 邮件工具授权已经撤销")

        async def bound_call(sid, tool, arguments, **kwargs):
            return await self.mcp.call(sid, tool, arguments, expected_endpoint=selected["endpoint"], before_call=authorize, **kwargs)

        if queued["status"] in ("pending", "retry"):
            authorize()
            progress.tool_attempt()
            progress.emit("tool", step="mail", status="running", label="调用已授权的 MCP 邮件工具")
        try:
            return await service.deliver_mcp(queued["id"], selected,
                MCPTransport(bound_call, selected["server_id"], selected["tool"]), authorize)
        except ServiceError as exc:
            if exc.code == "MAIL_UNCERTAIN":
                return service.public(service.get(queued["id"]))
            raise
        except RuntimeError:
            raise ServiceError("MAIL_BUSY", "另一个邮件投递正在执行，请稍后重试") from None
