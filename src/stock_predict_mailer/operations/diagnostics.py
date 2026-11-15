"""Redacted runtime preflight; no Store, queue, recovery or transport construction."""
from __future__ import annotations

import importlib.util
import json
import os
from collections import Counter
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from ..agent_service.contracts import ServiceError, utcnow
from ..naming import env, version
from .probes import ProbeError, contained, database, lock_state, port_state

MAX_TASKS = 1000
MAX_JSON_BYTES = 1024 * 1024
MAX_TOTAL_JSON = 8 * 1024 * 1024
MAIL_STATES = {"pending", "retry", "sending", "failed", "uncertain", "submitted", "simulated"}
SPECS = (
    ("mail", "agent-mail.sqlite3", {"mail": {"id", "recipient", "sender", "transport", "status", "attempts", "next_attempt", "error", "payload_hash", "analysis"}},
     {"mail_binding": {"message_id", "kind", "principal", "source_id", "report_id", "source_record", "profile", "request", "binding_hash"}}),
    ("control", "control.sqlite3", {"profiles": {"kind", "id", "body", "secrets"}, "state": {"id", "body"}, "tasks": {"id", "body"}},
     {"mcp_mail": {"id", "status"}}),
    ("development", "control-development.sqlite3", {"profiles": {"kind", "id", "body", "secrets"}, "state": {"id", "body"}, "tasks": {"id", "body"}},
     {"mcp_mail": {"id", "status"}}),
    ("legacy", "state.sqlite3", {"runs": {"status"}}, {"outbox": {"status"}}),
    ("knowledge", "private-knowledge/knowledge.sqlite3", {"documents": {"status"}}, {}),
    ("crawler", "jobs/crawler-jobs.sqlite3", {"jobs": {"state"}}, {}),
)


class Report:
    def __init__(self):
        self.checks = []

    def add(self, component, code, status, message, action=None, **details):
        item = {"component": component, "code": code, "status": status, "message": message, "details": details}
        if action:
            item["action"] = action
        self.checks.append(item)


def _columns(con, table):
    # All SQL identifiers in this module come from fixed source constants.
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def _counts(con, table, column, allowed):
    result = Counter()
    for row in con.execute(f"SELECT {column},COUNT(*) FROM {table} GROUP BY {column}"):
        result[row[0] if row[0] in allowed else "unknown"] += row[1]
    return dict(result)


def _tasks(con):
    counts, size, truncated = Counter(), 0, False
    rows = con.execute("SELECT CASE WHEN length(CAST(body AS BLOB))<=? THEN body ELSE NULL END FROM tasks LIMIT ?",
                       (MAX_JSON_BYTES, MAX_TASKS + 1))
    for index, row in enumerate(rows):
        if index >= MAX_TASKS:
            truncated = True
            break
        raw = row[0]
        if not isinstance(raw, str):
            counts["unknown"] += 1
            continue
        size += len(raw.encode("utf-8"))
        if size > MAX_TOTAL_JSON:
            truncated = True
            break
        try:
            state = json.loads(raw)["status"]["state"]
            if state not in {"submitted", "working", "input-required", "completed", "failed", "canceled", "rejected", "unknown"}:
                state = "unknown"
            counts[state] += 1
        except (ValueError, TypeError, KeyError, RecursionError):
            counts["unknown"] += 1
    return dict(counts), truncated


def _inspect(report, root, component, relative, required, optional):
    path = root / relative
    try:
        contained(root, path)
        if not path.exists():
            report.add(component, "DB_NOT_INITIALIZED", "info", "数据库尚未初始化；诊断没有创建它。")
            return {}
        with database(root, relative) as con:
            if con.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                raise ProbeError("DB_CORRUPT")
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = {name: sorted(columns - _columns(con, name)) for name, columns in required.items()}
            missing.update({name: sorted(columns - _columns(con, name)) for name, columns in optional.items() if name in tables})
            missing = {name: columns for name, columns in missing.items() if columns or name not in tables}
            if missing:
                report.add(component, "DB_SCHEMA_INCOMPATIBLE", "error", "已存在数据库缺少预期表或列。",
                           "核对软件版本与备份，停止写入后单独制定迁移；不要删除数据库。", missing=missing)
                return {}
            result, counts_complete = {}, True
            if component == "mail":
                result["messages"] = _counts(con, "mail", "status", MAIL_STATES)
                if "mail_binding" in tables:
                    unbound = con.execute("SELECT COUNT(*) FROM mail m LEFT JOIN mail_binding b ON b.message_id=m.id "
                                          "WHERE m.attempts>0 AND m.status IN ('pending','retry','sending','uncertain') "
                                          "AND (b.message_id IS NULL OR b.profile IS NULL)").fetchone()[0]
                else:
                    unbound = con.execute("SELECT COUNT(*) FROM mail WHERE attempts>0 AND status IN ('pending','retry','sending','uncertain')").fetchone()[0]
                if unbound:
                    report.add(component, "MAIL_BINDING_REVIEW", "warning", "部分已有尝试的邮件缺少冻结端点。",
                               "按 MailCore 手册执行只读 binding-plan；审阅后显式绑定，不自动重发。", count=unbound)
            elif component in ("control", "development"):
                result["tasks"], truncated = _tasks(con)
                counts_complete = not truncated
                if truncated:
                    report.add(component, "TASK_SCAN_LIMIT", "warning", "任务扫描达到数量或字节上限，计数不完整。",
                               "分批核对历史任务，不能将本次计数当作完整运行清单。", max_tasks=MAX_TASKS)
                if "mcp_mail" in tables:
                    result["receipts"] = _counts(con, "mcp_mail", "status", MAIL_STATES)
            elif component == "legacy":
                result["runs"] = _counts(con, "runs", "status", {"running", "succeeded", "failed", "interrupted"})
                if "outbox" in tables:
                    result["messages"] = _counts(con, "outbox", "status", MAIL_STATES)
            elif component == "knowledge":
                result["documents"] = _counts(con, "documents", "status",
                    {"pending", "processing", "review", "ready", "failed", "rejected", "deleting"})
            else:
                result["jobs"] = _counts(con, "jobs", "state", {"queued", "running", "cancelling", "completed", "partial", "failed", "cancelled", "interrupted"})
            report.add(component, "DB_READABLE", "ok", "数据库只读结构与 quick_check 检查通过。", queues=result, counts_complete=counts_complete)
            if any(counts.get("unknown", 0) for counts in result.values()):
                report.add(component, "QUEUE_STATE_UNKNOWN", "warning", "存在无法识别的任务状态或任务 JSON。",
                           "核对应用版本和原始记录；诊断未改写这些记录。")
            messages = result.get("messages", {})
            if count := messages.get("uncertain", 0) + messages.get("sending", 0):
                report.add(component, "MAIL_OUTCOME_REVIEW", "warning", "有邮件结果待核对，sending 可能仍在发送或已中断。",
                           "先核实发送进程与服务端结果，再人工确认；不要自动重发。", count=count)
            if count := sum(result.get("receipts", {}).values()):
                report.add(component, "MCP_HISTORY_PRESENT", "warning", "存在缺少正文/信封的旧 MCP 回执，切换新队列可能需要历史审阅。",
                           "先执行 mail-history-plan 核对回执及时间界限，不自动重发或确认。", count=count)
            return result
    except ProbeError as exc:
        report.add(component, exc.code, "warning" if exc.code in ("DB_CHECK_LIMIT", "DB_WAL_CHECK_DEFERRED") else "error", "未能完成数据库只读检查。",
                   "WAL 库本批不打开，避免创建协调文件；需另行快照核对，勿删除 WAL/SHM。锁忙可稍后重试；损坏需核对备份，禁止自动修复。")
    except OSError:
        report.add(component, "DB_UNREADABLE", "error", "无法读取数据库路径。", "核对目录权限和存储设备。")
    return {}


def _vault(report, root):
    key = env("MASTER_KEY")
    development = not key
    relative = "control-development.sqlite3" if development else "control.sqlite3"
    mode = "development" if development else "production"
    report.add("vault", "VAULT_MODE", "info", "密钥模式按当前进程环境选择，与控制台启动规则一致。", mode=mode)
    if development and (root / "control.sqlite3").exists():
        report.add("vault", "PRODUCTION_VAULT_NOT_SELECTED", "warning", "存在正式配置库，当前环境将使用独立开发配置库。",
                   "需要正式配置时注入原 MASTER_KEY；两个库不会自动合并。")
    try:
        contained(root, root / relative)
        exists = (root / relative).exists()
        if development:
            path = root / "control-development.key"
            contained(root, path)
            if not path.exists():
                report.add("vault", "VAULT_KEY_MISSING" if exists else "VAULT_NOT_INITIALIZED", "error" if exists else "info",
                           "已有开发库缺少配套密钥。" if exists else "开发密钥尚未初始化，诊断未生成密钥。",
                           "从配套备份恢复原开发密钥；不要为旧库生成新密钥。" if exists else None)
                return
            with path.open("rb") as stream:
                key = stream.read(129)
        cipher = Fernet(key.encode() if isinstance(key, str) else key)
        if not exists:
            report.add("vault", "VAULT_KEY_FORMAT_OK", "info", "密钥格式有效；配置库尚不存在，不能验证匹配。")
            return
        with database(root, relative) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "state" not in tables or not {"id", "body"}.issubset(_columns(con, "state")):
                raise ProbeError("DB_SCHEMA_INCOMPATIBLE")
            marker = con.execute("SELECT CASE WHEN length(CAST(body AS BLOB))<=4096 THEN body ELSE NULL END FROM state WHERE id='vault_check'").fetchone()
        if marker is None:
            report.add("vault", "VAULT_KEY_UNVERIFIED", "warning", "缺少密钥校验标记，无法确认与原配置匹配。",
                       "核对原密钥来源；本次没有读取或解密 profiles.secrets。")
        elif not isinstance(marker[0], str) or cipher.decrypt(marker[0].encode()) != b"stock-control-v1":
            raise InvalidToken()
        else:
            report.add("vault", "VAULT_KEY_MATCH", "ok", "当前密钥与已有 vault_check 匹配；未读取外部服务凭据。")
    except (ValueError, TypeError):
        report.add("vault", "VAULT_KEY_INVALID", "error", "当前密钥格式无效。", "恢复原密钥，勿将密钥值粘贴到诊断输出。")
    except InvalidToken:
        report.add("vault", "VAULT_KEY_MISMATCH", "error", "当前密钥无法验证已有配置库。", "从原秘密存储或配套备份恢复密钥。")
    except ProbeError as exc:
        report.add("vault", "VAULT_CHECK_DEFERRED" if exc.code == "DB_WAL_CHECK_DEFERRED" else "VAULT_UNREADABLE",
                   "warning" if exc.code == "DB_WAL_CHECK_DEFERRED" else "error", "未能只读验证密钥与库的匹配。", "WAL 库须另行快照检查；其余情况核对路径、数据库状态及权限。")
    except OSError:
        report.add("vault", "VAULT_UNREADABLE", "error", "无法只读检查配套密钥或校验标记。", "核对路径、数据库状态及读取权限。")


def _writer(report, component, root, relative, pending, active, registered=None):
    state = lock_state(root, relative)
    registered = registered or {}
    confirmed = registered.get("state") == "verified" and registered.get("phase") in ("running", "idle", "busy")
    report.add(component, "WRITER_LOCK", "info", "锁只表示写入者活动迹象，不能证明特定 Worker 存活。",
               lock=state, process_identity="verified" if registered.get("ownership") == "verified" else "unknown",
               heartbeat="fresh" if confirmed else "stale" if registered.get("state") == "stale" else "not_available")
    if active and state in ("absent", "available"):
        report.add(component, "INTERRUPTION_SUSPECTED", "warning", "有活动状态记录，当前未观察到持锁写入者。",
                   "核对运行进程和任务记录，再按原 Worker 手册显式处理；诊断没有恢复或重试。", count=active)
    elif active and state == "unknown":
        report.add(component, "WRITER_STATE_UNKNOWN", "warning", "有活动任务，但无法判断写锁状态。", "核对读取权限与运行进程。", count=active)
    if pending:
        report.add(component, "WORKER_CONFIRMED" if confirmed else "WORKER_REQUIRED", "info" if confirmed or state == "busy" else "warning",
                   "已确认登记的 Worker 身份及心跳；待处理任务仍需核对进展。" if confirmed else "存在待处理任务，诊断不能确认对应 Worker 的运行状态。",
                   "确认独立 Worker 使用相同工作区；启动 Worker 可能执行真实任务，应单独显式操作。", count=pending)


def _components(report, root, crawler):
    from .components import COMPONENTS, status
    result = {}
    for name in COMPONENTS:
        try:
            view = status(crawler if name == "crawler_worker" else root, name)
            result[name] = view
            state = view["state"]
            report.add(name, "COMPONENT_VERIFIED" if state == "verified" else "COMPONENT_NOT_REGISTERED" if state == "not_registered" else "COMPONENT_STATE_REVIEW",
                       "ok" if state == "verified" else "info" if state in ("not_registered", "stopped") else "warning",
                       "按实例、OS 创建标识、租约锁及心跳检查组件；心跳不等于业务有进展。", runtime=view)
        except (ServiceError, OSError):
            report.add(name, "COMPONENT_RECORD_UNREADABLE", "warning", "无法只读校验组件登记目录。", "核对目录、权限及登记记录；不自动接管进程。")
    return result


def diagnose(cfg, *, crawler_workspace=None, port=8767, check_port=True):
    if type(port) is not int or not 1 <= port <= 65535 or type(check_port) is not bool:
        raise ServiceError("INVALID_INPUT", "诊断端口须为 1 至 65535，check_port 须为布尔值")
    root = Path(cfg["workspace"]).resolve()
    if crawler_workspace is None:
        from mcp_server.paths import workspace
        crawler_workspace = workspace()
    crawler = Path(crawler_workspace).expanduser().resolve()
    report = Report()
    for name, path in (("workspace", root), ("crawler_workspace", crawler)):
        if not path.exists():
            report.add(name, "WORKSPACE_NOT_INITIALIZED", "warning" if name == "workspace" else "info", "工作区尚不存在，诊断没有创建它。")
        elif not path.is_dir():
            report.add(name, "WORKSPACE_NOT_DIRECTORY", "error", "工作区路径不是目录。", "为配置选择独立数据目录。")
        else:
            report.add(name, "WORKSPACE_PRESENT", "ok", "工作区目录存在；未执行写入权限探针。")
    modules = {name: importlib.util.find_spec(name) is not None for name in ("pandas", "requests", "baostock", "numpy", "sklearn")}
    report.add("dependencies", "OPTIONAL_DEPENDENCIES", "info", "可选依赖只检查是否安装，不导入或联网。", installed=modules)
    mail = cfg.get("mail", {})
    if mail.get("transport") == "smtp":
        available = {"user_present": bool(os.environ.get(mail.get("user_env", "SMTP_USER"))),
                     "password_present": bool(os.environ.get(mail.get("password_env", "SMTP_PASSWORD")))}
        report.add("smtp", "SMTP_CREDENTIALS_PRESENT" if all(available.values()) else "SMTP_CREDENTIALS_MISSING",
                   "ok" if all(available.values()) else "warning", "仅检查 CLI TOML 引用的凭据环境变量是否非空；不连接 SMTP。",
                   None if all(available.values()) else "为发送进程注入配置引用的凭据；不要写入 TOML 或日志。", **available)
    stores = {}
    for component, relative, required, optional in SPECS:
        stores[component] = _inspect(report, crawler if component == "crawler" else root, component, relative, required, optional)
    _vault(report, root)
    registered = _components(report, root, crawler)
    knowledge = stores["knowledge"].get("documents", {})
    jobs = stores["crawler"].get("jobs", {})
    messages = stores["mail"].get("messages", {})
    legacy = stores["legacy"]
    _writer(report, "knowledge_worker", root, "private-knowledge/pipeline.lock", knowledge.get("pending", 0), knowledge.get("processing", 0), registered.get("knowledge_worker"))
    _writer(report, "crawler_worker", crawler, "data/.crawler.lock", jobs.get("queued", 0), jobs.get("running", 0) + jobs.get("cancelling", 0), registered.get("crawler_worker"))
    _writer(report, "mail_pipeline", root, "pipeline.lock", 0, messages.get("sending", 0) + legacy.get("messages", {}).get("sending", 0)
            + legacy.get("runs", {}).get("running", 0))
    if jobs.get("queued", 0) and not all(modules[n] for n in ("pandas", "requests", "baostock")):
        report.add("crawler_worker", "CRAWLER_DEPENDENCY_MISSING", "warning", "有排队采集任务，但缺少执行依赖。", "显式安装 crawler 可选依赖后再决定是否启动 Worker。")
    for name in ("control", "development"):
        tasks = stores[name].get("tasks", {})
        if count := sum(tasks.get(s, 0) for s in ("submitted", "working", "input-required")):
            verified_console = registered.get("console", {}).get("state") == "verified"
            report.add(name, "ANALYSIS_PROGRESS_UNVERIFIED" if verified_console else "ANALYSIS_RUNTIME_UNKNOWN", "warning",
                       "组件心跳可验证，但不能证明每个历史分析任务仍有进展。" if verified_console else "持久化分析任务尚未结束，但没有可验证的进程心跳。",
                       "查看对应控制台的进度/进程，确认后再取消或重新提交；不要仅凭旧状态推断仍在运行。", count=count)
    if check_port:
        state = port_state(port)
        console = registered.get("console", {})
        reported = state == "unavailable" and console.get("state") == "verified" and console.get("phase") == "running" and console.get("configuration", {}).get("port") == port
        report.add("console_port", "PORT_REGISTERED_COMPONENT" if reported else "PORT_AVAILABLE" if state == "available" else "PORT_UNAVAILABLE" if state == "unavailable" else "PORT_STATE_UNKNOWN",
                   "info" if reported else "ok" if state == "available" else "warning",
                   "已验证登记的控制台报告使用该端口；未进行 HTTP 业务健康检查。" if reported else "已检查新实例的本机端口可用性；没有识别服务归属或请求 HTTP。",
                   None if state == "available" or reported else "确认已有本机服务或端口保留规则；需要另一个实例时显式选择其他端口。", port=port, state=state)
    else:
        report.add("console_port", "PORT_CHECK_SKIPPED", "info", "已跳过端口检查，未创建网络套接字。", port=port)
    levels = Counter(item["status"] for item in report.checks)
    status = "error" if levels["error"] else "warning" if levels["warning"] else "ok"
    return {"schema_version": "1", "version": version(), "generated_at": utcnow().isoformat(), "mode": "read_only_preflight",
            "workspace": str(root), "crawler_workspace": str(crawler), "status": status, "summary": dict(levels),
            "checks": report.checks, "limitations": ["各数据库分别读取快照，不保证跨库一致。", "端口/锁可用性是瞬时结果，不等于业务健康或进程身份。",
                "SMTP 配置检查仅针对 CLI TOML，未读取控制台中的邮件配置。",
                "WAL 库不打开，检查延期，避免产生协调文件或忽略未 checkpoint 的提交。",
                "未验证外部数据、模型、SMTP/MCP 服务或真实收件。", "未初始化、修复、恢复、启动或停止任何业务组件。"]}
