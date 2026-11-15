"""Non-secret delivery profiles and immutable envelope/payload bindings."""
import json
import os
import re
import sqlite3
from pathlib import Path

from ..agent_service.analysis import identity
from ..agent_service.contracts import ServiceError, decode
from ..core import digest


def smtp_profile(settings, incomplete=False):
    if not settings.get("host"):
        if incomplete:
            return None
        raise ServiceError("MAIL_CONFIG", "请先配置 SMTP 主机再审阅绑定")
    mode = settings.get("tls", "starttls")
    result = {"transport": "smtp", "host": settings["host"], "port": settings.get("port", 465 if mode == "ssl" else 587),
              "tls": mode, "user_env": settings.get("user_env", "SMTP_USER"),
              "password_env": settings.get("password_env", "SMTP_PASSWORD"), "timeout_seconds": settings.get("timeout_seconds", 15)}
    if (not isinstance(result["host"], str) or any(c in result["host"] for c in "\r\n")
            or mode not in ("ssl", "starttls") or type(result["port"]) is not int or not 1 <= result["port"] <= 65535
            or type(result["timeout_seconds"]) is not int or not 1 <= result["timeout_seconds"] <= 604800
            or any(not isinstance(result[k], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", result[k]) for k in ("user_env", "password_env"))):
        raise ServiceError("MAIL_CONFIG", "SMTP 公开端点参数无效")
    return result


def profile(settings, incomplete=False):
    mode = settings.get("transport", "file")
    if mode == "file":
        return {"transport": "file"}
    if mode == "smtp":
        return smtp_profile(settings, incomplete)
    raise ServiceError("MAIL_CONFIG", "MCP 绑定需要控制台路由快照")


def legacy_settings():
    mode = os.environ.get("SMTP_MODE", "starttls")
    try:
        port = int(os.environ.get("SMTP_PORT", "465" if mode == "ssl" else "587"))
    except ValueError:
        raise ServiceError("MAIL_CONFIG", "SMTP_PORT 无效") from None
    return {"transport": "smtp", "host": os.environ.get("SMTP_HOST", ""), "port": port, "retry_seconds": 300,
            "tls": mode, "user_env": "SMTP_USER", "password_env": "SMTP_PASSWORD", "timeout_seconds": 30}


def endpoint_snapshot(store, sid):
    with store.lock:
        body, encrypted = store._raw("mcp", sid)
    return endpoint(decode(body.encode()), encrypted, store.db_path.name)


def endpoint(body, encrypted, filename):
    return {"database": filename, "server_id": body["id"], "transport": body["transport"], "url": body["url"],
            "command": body["command"], "args": body["args"], "timeout_seconds": body["timeout_seconds"],
            "secret_revision": digest(encrypted)}


def mcp_profile(store, policy):
    sid, tool = policy["mcp_server_id"], policy["mcp_tool"]
    if not sid or not tool:
        raise ServiceError("MAIL_CONFIG", "未选择 MCP 邮件服务和工具")
    return {"transport": "mcp", "server_id": sid, "tool": tool, "endpoint": endpoint_snapshot(store, sid)}


def refresh_mcp(root, frozen):
    filename = frozen["endpoint"]["database"]
    if filename not in ("control.sqlite3", "control-development.sqlite3"):
        raise ServiceError("MAIL_CONFIG", "无效 MCP 配置库引用")
    path = Path(root) / filename
    if not path.exists():
        raise ServiceError("MAIL_CONFIG", "绑定引用的 MCP 配置库不存在")
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = con.execute("SELECT body,secrets FROM profiles WHERE kind='mcp' AND id=?", (frozen["server_id"],)).fetchone()
        if row is None:
            raise ServiceError("MAIL_CONFIG", "绑定引用的 MCP 服务已删除")
        return dict(frozen, endpoint=endpoint(decode(row[0].encode()), row[1], filename))
    finally:
        con.close()


def binding_hash(row, metadata):
    return identity({"message": {k: row[k] for k in ("id", "recipient", "sender", "transport", "payload_hash", "analysis")},
                     "metadata": {k: metadata.get(k) for k in ("kind", "principal", "source_id", "report_id", "source_record", "profile", "request")}})


def unpack(row):
    if row is None:
        return None
    result = dict(row)
    try:
        for key in ("profile", "request", "source_record"):
            result[key] = json.loads(result[key]) if result[key] is not None else None
    except (TypeError, ValueError, RecursionError):
        raise ServiceError("MAIL_INTEGRITY", "冻结邮件绑定资料损坏") from None
    return result
