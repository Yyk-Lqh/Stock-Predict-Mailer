"""Independent configuration/task database; encrypted write-only credentials."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager

from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError

from ..agent_service.contracts import ServiceError
from .schemas import AgentEndpoint, MCPProfile, ModelProfile, Settings

TYPES = {"models": ModelProfile, "mcp": MCPProfile, "agents": AgentEndpoint}
SECRETS = {"models": {"api_key"}, "mcp": {"auth_token", "env"}, "agents": {"auth_token"}}


class Store:
    def __init__(self, root, master_key=None):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        key = master_key or os.environ.get("SPM_MASTER_KEY", "")
        try:
            self.cipher = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError):
            raise ServiceError("SECRET_CONFIG", "请先配置有效的 SPM_MASTER_KEY；主密钥不保存到工作区") from None
        self.lock = threading.RLock()
        with self.db() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (kind TEXT,id TEXT,body TEXT,secrets BLOB,PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS state (id TEXT PRIMARY KEY,body TEXT);
            CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY,body TEXT);
            CREATE TABLE IF NOT EXISTS task_events (seq INTEGER PRIMARY KEY, task_id TEXT NOT NULL, body TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS task_events_lookup ON task_events(task_id,seq);
            """)
            con.execute("INSERT OR IGNORE INTO state VALUES ('settings',?)", (Settings().model_dump_json(),))
            marker = con.execute("SELECT body FROM state WHERE id='vault_check'").fetchone()
            try:
                if marker:
                    self.cipher.decrypt(marker[0].encode())
                else:
                    existing = con.execute("SELECT secrets FROM profiles LIMIT 1").fetchone()
                    if existing:
                        self.cipher.decrypt(existing[0])
                    con.execute("INSERT INTO state VALUES ('vault_check',?)", (self.cipher.encrypt(b"stock-control-v1").decode(),))
            except InvalidToken:
                raise ServiceError("SECRET_CONFIG", "主密钥无法解密已有工作区，请恢复原主密钥") from None

    @contextmanager
    def db(self):
        with self.lock:
            con = sqlite3.connect(self.root / "control.sqlite3", timeout=10)
            try:
                yield con
                con.commit()
            except Exception:
                con.rollback()
                raise
            finally:
                con.close()

    def _raw(self, kind, pid):
        with self.db() as con:
            row = con.execute("SELECT body,secrets FROM profiles WHERE kind=? AND id=?", (kind, pid)).fetchone()
        if not row:
            raise ServiceError("NOT_FOUND", "配置不存在")
        return row

    def secret(self, kind, pid):
        try:
            return json.loads(self.cipher.decrypt(self._raw(kind, pid)[1]))
        except InvalidToken:
            raise ServiceError("SECRET_CONFIG", "主密钥无法解密现有配置，请恢复原主密钥") from None

    def get(self, kind, pid):
        return json.loads(self._raw(kind, pid)[0])

    def list(self, kind):
        with self.db() as con:
            rows = con.execute("SELECT body FROM profiles WHERE kind=? ORDER BY id", (kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def put(self, kind, raw, pid=None):
        if kind not in TYPES or not isinstance(raw, dict):
            raise ServiceError("INVALID_INPUT", "不支持的配置类型")
        if pid is not None and not re.fullmatch(r"[a-f0-9]{32}", pid):
            raise ServiceError("INVALID_INPUT", "配置 ID 无效")
        with self.lock:
            if pid:
                self.get(kind, pid)
            secrets = self.secret(kind, pid) if pid else {}
            body = dict(raw)
            clear = body.pop("clear_secrets", [])
            if not isinstance(clear, list) or any(k not in SECRETS[kind] for k in clear):
                raise ServiceError("INVALID_INPUT", "无效凭据清除字段")
            for field in SECRETS[kind]:
                value = body.pop(field, None)
                if value not in (None, ""):
                    if field == "env":
                        if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
                            raise ServiceError("INVALID_INPUT", "环境变量须为字符串映射")
                    elif not isinstance(value, str) or len(value) > 10000 or any(c in value for c in "\r\n"):
                        raise ServiceError("INVALID_INPUT", "凭据格式无效")
                    secrets[field] = value
                if field in clear:
                    secrets.pop(field, None)
            for field in ("id", "has_secret", "secret_mask", "env_keys"):
                body.pop(field, None)
            try:
                body = TYPES[kind].model_validate(body).model_dump()
            except ValidationError as exc:
                fields = sorted({".".join(str(v) for v in e["loc"]) or "parameters" for e in exc.errors(include_input=False)})
                raise ServiceError("INVALID_CONFIG", "配置字段或模型参数不兼容，请检查：" + ", ".join(fields)) from None
            pid = pid or uuid.uuid4().hex
            body.update(id=pid, has_secret=bool(secrets.get("api_key") or secrets.get("auth_token")),
                        secret_mask="••••••••" if secrets.get("api_key") or secrets.get("auth_token") else "", env_keys=sorted(secrets.get("env", {})))
            with self.db() as con:
                con.execute("INSERT OR REPLACE INTO profiles VALUES (?,?,?,?)",
                            (kind, pid, json.dumps(body), self.cipher.encrypt(json.dumps(secrets).encode())))
            return body

    def delete(self, kind, pid):
        self.get(kind, pid)
        settings = self.settings()
        if kind == "models" and (settings["default_model_id"] == pid or any(a["model_id"] == pid for a in settings["agents"].values())):
            raise ServiceError("CONFIG_IN_USE", "请先解除默认模型或角色引用")
        if kind == "agents" and any(a["endpoint_id"] == pid for a in settings["agents"].values()):
            raise ServiceError("CONFIG_IN_USE", "请先解除 Agent 引用")
        if kind == "mcp" and (settings["mail"]["mcp_server_id"] == pid or any(
                t.startswith(pid + ":") for a in settings["agents"].values() for t in a["tools"])):
            raise ServiceError("CONFIG_IN_USE", "请先解除工具或邮件引用")
        with self.db() as con:
            con.execute("DELETE FROM profiles WHERE kind=? AND id=?", (kind, pid))

    def settings(self):
        with self.db() as con:
            body = con.execute("SELECT body FROM state WHERE id='settings'").fetchone()[0]
        return Settings.model_validate_json(body).model_dump()

    def save_settings(self, raw):
        try:
            value = Settings.model_validate(raw).model_dump()
        except ValidationError:
            raise ServiceError("INVALID_CONFIG", "设置字段、温度或预算范围无效") from None
        from ..delivery import address
        from .models import effective_temperature
        try:
            for recipient in value["mail"]["recipient_allowlist"]:
                address(recipient)
            address(value["mail"]["sender"])
        except ValueError:
            raise ServiceError("INVALID_CONFIG", "邮件授权须使用单一邮箱地址") from None
        if value["agents"]["main"]["endpoint_id"]:
            raise ServiceError("INVALID_CONFIG", "主 Agent 编排在本机运行，A2A 对端仅用于子 Agent")
        for role, conf in value["agents"].items():
            if role != "main" and conf["tools"]:
                raise ServiceError("PERMISSION_DENIED", "子 Agent 本阶段不开放工具；由主 Agent 获取并校验事实")
            mid = conf["model_id"] or value["default_model_id"]
            if mid:
                effective_temperature(self.get("models", mid), value, role)
            if conf["endpoint_id"]:
                self.get("agents", conf["endpoint_id"])
            for tool in conf["tools"]:
                sid, sep, name = tool.partition(":")
                if not sep or name not in self.get("mcp", sid)["allowed_tools"]:
                    raise ServiceError("PERMISSION_DENIED", "角色工具必须属于服务允许清单")
        if value["mail"]["transport"] == "mcp":
            server = self.get("mcp", value["mail"]["mcp_server_id"])
            tool = value["mail"]["mcp_tool"]
            if tool not in server["allowed_tools"] or server["effects"].get(tool) != "email":
                raise ServiceError("PERMISSION_DENIED", "邮件 MCP 工具必须显式授权为 email")
        with self.db() as con:
            con.execute("UPDATE state SET body=? WHERE id='settings'", (json.dumps(value),))
        return value

    def task(self, tid, value=None):
        with self.db() as con:
            if value is not None:
                con.execute("INSERT OR REPLACE INTO tasks VALUES (?,?)", (tid, json.dumps(value, ensure_ascii=False)))
            row = con.execute("SELECT body FROM tasks WHERE id=?", (tid,)).fetchone()
        if row is None:
            raise ServiceError("NOT_FOUND", "任务不存在")
        return json.loads(row[0])
