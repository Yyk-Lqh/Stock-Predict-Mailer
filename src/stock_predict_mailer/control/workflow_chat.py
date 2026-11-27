"""Saved workflow revisions and the conversation entry point to the task runner."""
import base64
import binascii
import json
import re
import uuid
from datetime import datetime

from ..agent_service.analysis import identity
from ..agent_service.contracts import ServiceError, utcnow
from .execution import PRESETS
from .memory import LOCAL_KNOWLEDGE_OWNER
from .modes import PROFESSIONAL, TASK_MODE_SQL
from .workflow import STEP_ID, freeze, workflow_issues
from .workflow_values import bind_fields, dataflow, needs_knowledge
from .workflow_wiring import WiringError, draft_graph, issue

FIELDS = {
    "prediction": {"label": "预测数据", "type": "object"},
    "context": {"label": "客观事实", "type": "object"},
    "chart_data": {"label": "图表序列", "type": "object"},
    "evaluation_definition": {"label": "预测评价定义", "type": "object"},
    "constraints": {"label": "分析约束", "type": "lines"},
    "goal": {"label": "分析目标", "type": "choice", "options": {"overview": "综合解读", "risk": "风险分析", "comparison": "历史预测对比"}},
    "knowledge_query": {"label": "知识库检索问题", "type": "text"},
    "knowledge_to_model": {"label": "允许向模型提供检索证据", "type": "boolean"},
}
DEFAULT_INPUTS = {"prediction": True, "context": False, "chart_data": False, "constraints": False,
                  "knowledge_query": False, "knowledge_to_model": False}
IDENT = re.compile(r"[A-Za-z0-9_-]{1,64}")
IMAGE_LIMIT = 512 * 1024
IMAGE_TYPES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF", b"WEBP"),
}


def image_value(raw):
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"mime", "data"}:
        raise ServiceError("INVALID_INPUT", "流程图像需要 mime 和 base64 data")
    mime, encoded = raw["mime"], raw["data"]
    signatures = IMAGE_TYPES.get(mime)
    if signatures is None or not isinstance(encoded, str) or len(encoded) > IMAGE_LIMIT * 2:
        raise ServiceError("INVALID_INPUT", "仅支持不超过 512 KiB 的 PNG、JPEG 或 WebP 图像")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ServiceError("INVALID_INPUT", "流程图像不是有效的 base64 内容") from None
    if len(decoded) > IMAGE_LIMIT:
        raise ServiceError("INVALID_INPUT", "流程图像不能超过 512 KiB")
    if mime == "image/webp":
        valid = len(decoded) >= 12 and decoded[:4] == b"RIFF" and decoded[8:12] == b"WEBP"
    else:
        valid = any(decoded.startswith(signature) for signature in signatures)
    if not valid:
        raise ServiceError("INVALID_INPUT", "流程图像内容与声明格式不匹配")
    return {"mime": mime, "data": encoded}


def input_schema(raw):
    if (not isinstance(raw, dict) or raw.get("prediction") is not True or set(raw) - FIELDS.keys()
            or any(type(value) is not bool for value in raw.values())):
        raise ServiceError("INVALID_INPUT", "开始节点必须包含预测数据，其他参数须使用已登记的输入字段")
    return {key: required for key, required in raw.items()}


class WorkflowChat:
    def __init__(self, engine):
        self.engine = engine
        self.store = engine.store
        with self.store.db() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS workflow_definitions (
                    owner TEXT NOT NULL, id TEXT NOT NULL, revision TEXT NOT NULL, graph_version TEXT NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(owner,id,revision));
                CREATE INDEX IF NOT EXISTS workflow_definition_graph ON workflow_definitions(owner,graph_version,id);
            """)

    def system(self):
        spec = freeze({"mode": "system", "key": "system"}, self.engine, self.store.settings())
        return {"id": "system", "mode": "system", "name": "系统分析流程", "description": "校验预测与事实，汇集分析依据并生成报告。",
                "revision": spec["version"], "graph_version": spec["version"], "graph": spec["graph"], "inputs": DEFAULT_INPUTS}

    def get(self, owner, flow_id, revision=None):
        if flow_id == "system":
            value = self.system()
            if revision is None or revision == value["revision"]:
                return value
        else:
            with self.store.db() as con:
                row = con.execute("""SELECT body FROM workflow_definitions WHERE owner=? AND id=?
                    AND (? IS NULL OR revision=?) ORDER BY rowid DESC LIMIT 1""",
                                  (owner, flow_id, revision, revision)).fetchone()
            if row:
                return json.loads(row[0])
        raise ServiceError("NOT_FOUND", "流程或执行版本不存在")

    @staticmethod
    def submission(flow, key):
        return {"mode": flow["mode"], "key": key, **({"graph": flow["graph"]} if flow["mode"] == "custom" else {})}

    def list(self, owner, *, model=None, tools=None):
        with self.store.db() as con:
            rows = con.execute("""SELECT body FROM workflow_definitions WHERE rowid IN (
                SELECT max(rowid) FROM workflow_definitions WHERE owner=? GROUP BY id) ORDER BY rowid DESC""", (owner,)).fetchall()
        flows = [self.system(), *(json.loads(row[0]) for row in rows)]
        for flow in flows:
            try:
                if flow.get("draft_edits"):
                    raise WiringError([issue("NODE_DRAFT", "请先保存节点参数", node=node) for node, _ in flow["draft_edits"]])
                settings = self.engine.execution_settings(self.store.settings(), model, tools)
                if flow["mode"] == "system":
                    selected = settings["agents"]["main"]["model_id"] or settings["default_model_id"]
                    if not selected or not self.store.get("models", selected)["enabled"]:
                        raise ServiceError("MODEL_REQUIRED", "请先配置或选择启用的主分析模型")
                else:
                    freeze(self.submission(flow, "validate"), self.engine, settings)
            except ServiceError as error:
                flow.update(runnable=False, reason=error.message)
                if isinstance(error, WiringError):
                    flow["issues"] = error.issues
            else:
                flow.update(runnable=True, reason=None)
        return {"items": flows, "fields": FIELDS, "image_limit": IMAGE_LIMIT, "image_types": sorted(IMAGE_TYPES)}

    def save(self, owner, raw, *, flow_id=None):
        if set(raw) - {"name", "description", "graph", "inputs", "base_revision", "import_key", "model_id", "tools", "image",
                       "draft", "draft_edits"}:
            raise ServiceError("INVALID_INPUT", "流程定义包含未知字段")
        name, description = raw.get("name"), raw.get("description", "")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or not isinstance(description, str) or len(description) > 400:
            raise ServiceError("INVALID_INPUT", "请填写流程名称，描述须不超过 400 字")
        legacy = raw.get("import_key")
        if legacy is not None and (flow_id or not isinstance(legacy, str) or not IDENT.fullmatch(legacy)):
            raise ServiceError("INVALID_INPUT", "导入标识无效")
        current = None
        with self.engine.lock:
            if legacy:
                flow_id = "local-" + identity(legacy)[:40]
                try:
                    return self.get(owner, flow_id)
                except ServiceError as error:
                    if error.code != "NOT_FOUND":
                        raise
            elif flow_id:
                if flow_id == "system":
                    raise ServiceError("FORBIDDEN", "请将系统模板另存为自定义流程")
                current = self.get(owner, flow_id)
                if current["revision"] != raw.get("base_revision"):
                    raise ServiceError("WORKFLOW_CONFLICT", "流程已有更新，请重新打开再保存")
            draft = raw.get("draft", False)
            if type(draft) is not bool or "draft_edits" in raw and not draft:
                raise ServiceError("INVALID_INPUT", "草稿参数无效")
            pending = raw.get("draft_edits", [])
            saved = draft_graph(raw.get("graph"))
            ids = {node["id"] for node in saved["nodes"]}
            if (not isinstance(pending, list) or len(pending) > 24
                    or any(not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], str)
                           or pair[0] not in ids or not isinstance(pair[1], dict) for pair in pending)
                    or len(json.dumps(pending, ensure_ascii=True)) > 32768):
                raise ServiceError("INVALID_INPUT", "节点参数草稿无效或超过 32 KiB")
            submission = {"mode": "custom", "graph": saved, "key": "save"}
            settings = self.store.settings()
            problems = []
            try:
                settings = self.engine.execution_settings(settings, raw.get("model_id"), raw.get("tools"))
                if pending:
                    raise WiringError([issue("NODE_DRAFT", "请先保存节点参数", node=node) for node, _ in pending])
                spec = freeze(submission, self.engine, settings)
                saved, version = spec["graph"], spec["version"]
            except ServiceError as error:
                if not draft:
                    raise
                problems = workflow_issues(submission, self.engine, settings)
                if hasattr(error, "issues") and pending:
                    problems.extend(error.issues)
                if not any(item["severity"] == "error" for item in problems):
                    problems.append(issue(error.code, error.message))
                version = identity(saved)
            start = next((node for node in saved["nodes"] if node["data"].get("type") == "input"), None)
            declared = start["data"].get("config", {}).get("fields", []) if start else []
            variables = declared if isinstance(declared, list) else []
            typed = dataflow(saved)
            inputs = {} if typed else input_schema(raw.get("inputs", DEFAULT_INPUTS))
            value = {"id": flow_id or uuid.uuid4().hex, "mode": "custom", "name": name.strip(),
                     "description": description.strip(), "graph": saved, "graph_version": version,
                     "start": start["id"] if start else None, "inputs": inputs,
                     "image": image_value(raw.get("image", current.get("image") if current else None)),
                     "updated_at": utcnow().isoformat(), **({"fields": variables} if typed else {}),
                     **({"draft": True, "issues": problems} if problems else {}),
                     **({"draft_edits": pending} if pending else {})}
            value["revision"] = identity(value)
            with self.store.db() as con:
                # Reverting to an earlier revision also makes it the latest revision.
                con.execute("INSERT OR REPLACE INTO workflow_definitions VALUES (?,?,?,?,?)",
                            (owner, value["id"], value["revision"], value["graph_version"], json.dumps(value, ensure_ascii=False)))
            return value

    def submit(self, owner, flow_id, raw, *, knowledge_owner=None):
        if set(raw) - {"revision", "key", "message", "parameters", "model_id", "tools", "reasoning_effort"}:
            raise ServiceError("INVALID_INPUT", "提交包含未知字段")
        effort = raw.get("reasoning_effort")
        if effort is not None and (not isinstance(effort, str) or effort not in PRESETS):
            raise ServiceError("INVALID_INPUT", "请选择有效的推理强度")
        revision, key, message, params = (raw.get(field) for field in ("revision", "key", "message", "parameters"))
        if (not isinstance(revision, str) or not isinstance(key, str) or not IDENT.fullmatch(key)
                or not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000 or not isinstance(params, dict)):
            raise ServiceError("INVALID_INPUT", "需要流程版本、提交标识和 1 至 4000 字的需求")
        flow = self.get(owner, flow_id, revision)
        if flow.get("draft_edits"):
            raise WiringError([issue("NODE_DRAFT", "请先保存节点参数", node=node) for node, _ in flow["draft_edits"]])
        if flow.get("draft"):
            settings = self.engine.execution_settings(self.store.settings(), raw.get("model_id"), raw.get("tools"))
            freeze(self.submission(flow, key), self.engine, settings)
        variables = "fields" in flow
        if variables:
            bind_fields(flow["fields"], params, flow["start"])
        elif set(params) - flow["inputs"].keys():
            raise ServiceError("INVALID_INPUT", "包含开始节点未声明的参数")
        for field, required in flow["inputs"].items():
            value = params.get(field)
            if required and (value is None or value == "" or value == {} or value == []):
                raise ServiceError("INVALID_INPUT", f"请填写{FIELDS[field]['label']}")
        with self.engine.lock:
            cid = self.engine.memory.flow_conversation(owner, flow_id)
            ref = {"id": flow_id, "name": flow["name"], "revision": revision,
                   "input": {"message": message.strip(), "parameters": params},
                   "choices": {field: raw[field] for field in ("model_id", "tools", "reasoning_effort") if field in raw}}
            request = {**({"parameters": params} if variables else params), **ref["choices"], "message": message.strip(), "conversation_id": cid,
                       "workflow": self.submission(flow, key)}
            if callable(knowledge_owner):
                knowledge_owner = knowledge_owner() if (needs_knowledge(flow["graph"]) if variables else params.get("knowledge_query")) else None
            if knowledge_owner:
                ref["choices"]["knowledge_scope"] = "local" if knowledge_owner == LOCAL_KNOWLEDGE_OWNER else "private"
            return self.engine.submit(request, owner, knowledge_owner=knowledge_owner, mode=PROFESSIONAL, workflow_ref=ref)

    def history(self, owner, flow_id, *, before, task_id=None, node_id=None, node_type=None):
        self.get(owner, flow_id)
        with self.store.db() as con:
            versions = [row[0] for row in con.execute("""
                SELECT graph_version FROM workflow_definitions WHERE owner=? GROUP BY graph_version
                HAVING count(DISTINCT id)=1 AND min(id)=?""", (owner, flow_id))]
            rows = con.execute(f"""
                SELECT t.rowid,t.body FROM tasks t LEFT JOIN memory_tasks m ON m.task=t.id
                WHERE t.rowid<? AND (m.owner IS NULL OR m.owner=?) AND {TASK_MODE_SQL}='professional'
                  AND json_extract(t.body,'$.metadata.workflow.debug') IS NULL
                  AND json_extract(t.body,'$.contextId')=t.id
                  AND (? IS NULL OR t.id=?)
                  AND (json_extract(t.body,'$.metadata.workflow.flow.id')=?
                    OR (json_extract(t.body,'$.metadata.workflow.flow.id') IS NULL AND
                       ((?='system' AND json_extract(t.body,'$.metadata.workflow.mode')='system') OR
                         json_extract(t.body,'$.metadata.workflow.version') IN (SELECT value FROM json_each(?)))))
                  AND (? IS NULL OR (
                    EXISTS (SELECT 1 FROM json_each(t.body,'$.metadata.workflow.graph.nodes') AS n
                            WHERE json_extract(n.value,'$.id')=? AND json_extract(n.value,'$.data.type')=?)
                    AND EXISTS (SELECT 1 FROM task_events e WHERE e.task_id=t.id
                                AND json_extract(e.body,'$.step')=CASE json_extract(t.body,'$.metadata.workflow.mode')
                                    WHEN 'system' THEN ? ELSE ? END
                                AND json_extract(e.body,'$.kind') IN ('step','node_result')
                                AND json_extract(e.body,'$.status') IN ('running','completed','degraded','failed','canceled'))))
                ORDER BY t.rowid DESC LIMIT 21
                """, (before, owner, task_id, task_id, flow_id, flow_id, json.dumps(versions),
                      node_id, node_id, node_type, STEP_ID.get(node_id, node_id), node_id)).fetchall()
        if task_id:
            if not rows:
                raise ServiceError("NOT_FOUND", "此流程没有对应运行")
            return self.receipt(json.loads(rows[0][1]), detail=True)
        return {"items": [self.receipt(json.loads(raw)) for _, raw in rows[:20]],
                "next_before": rows[19][0] if len(rows) > 20 else None}

    def receipt(self, task, *, detail=False):
        meta = task["metadata"]
        workflow, brief = meta["workflow"], meta.get("request", {})
        flow = workflow.get("flow") or {}
        provided = flow.get("input")
        if detail and provided is None and (cid := brief.get("conversation_id")):
            with self.store.db() as con:
                if self.engine.memory.task_owner(task["id"]):
                    for (body,) in con.execute("SELECT body FROM conversation_turns WHERE conversation=? ORDER BY seq DESC", (cid,)):
                        turn = self.engine.memory.open(body)
                        if turn.get("task") == task["id"]:
                            provided = {"message": turn.get("message", ""), "parameters": {
                                key: turn[key] for key in ("prediction", "constraints", "goal") if key in turn}}
                            break
        result = {"id": task["id"], "status": task["status"], "flow_id": flow.get("id"), "name": flow.get("name"),
                  "version": flow.get("revision", workflow["version"]), "graph_version": workflow["version"],
                  "summary": (provided or {}).get("message", "")[:140] or brief.get("subject") or "历史分析",
                  "started_at": workflow.get("started_at")}
        if result["started_at"] and task["status"]["state"] in ("completed", "failed", "canceled"):
            started = datetime.fromisoformat(result["started_at"])
            result["duration_ms"] = max(0, round((datetime.fromisoformat(task["status"]["timestamp"]) - started).total_seconds() * 1000))
        if detail:
            result.update(task=task, input=provided, choices=flow.get("choices", {}))
        return result
