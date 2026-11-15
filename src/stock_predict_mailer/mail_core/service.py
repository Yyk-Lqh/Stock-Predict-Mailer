"""Durable idempotent delivery; ambiguous SMTP outcomes are never retried."""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, formatdate

from ..agent_service.analysis import identity, validate_analysis
from ..agent_service.contracts import ServiceError, instant, utcnow
from ..agent_service.input_evidence import persist
from ..agent_service.png import chart_png
from ..agent_service.reporting import render
from ..core import Config, atomic_write, digest
from ..delivery import address, process_lock
from . import bindings
from .transports import FileTransport, SMTPTransport


class MailCore:
    def __init__(self, workspace, settings, timezone="Asia/Shanghai", smtp_factory=None, analysis_settings=None):
        self.workspace, self.settings, self.timezone = workspace, settings, timezone
        self.cfg = Config(workspace)
        self.smtp_factory = smtp_factory
        self.analysis_settings = analysis_settings

    @contextmanager
    def db(self):
        self.workspace.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.workspace / "agent-mail.sqlite3", timeout=10)
        con.row_factory = sqlite3.Row
        try:
            con.execute("""CREATE TABLE IF NOT EXISTS mail (
                id TEXT PRIMARY KEY, recipient TEXT NOT NULL, sender TEXT NOT NULL, transport TEXT NOT NULL,
                status TEXT NOT NULL, attempts INTEGER NOT NULL, next_attempt TEXT NOT NULL,
                error TEXT, payload_hash TEXT NOT NULL, analysis TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS mail_audit (
                id TEXT PRIMARY KEY, message_id TEXT NOT NULL, action TEXT NOT NULL, at TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS mail_binding(
                message_id TEXT PRIMARY KEY,kind TEXT NOT NULL,principal TEXT NOT NULL,source_id TEXT,report_id TEXT,
                source_record TEXT,profile TEXT,request TEXT,binding_hash TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS mail_alias(
                namespace TEXT,source_id TEXT,principal TEXT,message_id TEXT,PRIMARY KEY(namespace,source_id,principal))""")
            con.execute("CREATE TABLE IF NOT EXISTS mail_control(id TEXT PRIMARY KEY,body TEXT NOT NULL)")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def get(self, message_id):
        if not isinstance(message_id, str) or not re.fullmatch("[a-f0-9]{64}", message_id):
            raise ServiceError("INVALID_INPUT", "无效邮件 ID")
        with self.db() as con:
            row = con.execute("SELECT * FROM mail WHERE id=?", (message_id,)).fetchone()
        if row is None:
            raise ServiceError("INVALID_INPUT", "邮件不存在")
        with self.db() as con:
            scope = con.execute("SELECT kind,principal FROM mail_binding WHERE message_id=?", (message_id,)).fetchone()
        if scope and scope["kind"] == "legacy" and scope["principal"] != self.cfg.principal:
            raise ServiceError("PERMISSION_DENIED", "旧版消息属于其他 principal")
        return dict(row)

    @staticmethod
    def public(row):
        return {k: row[k] for k in ("id", "status", "attempts", "next_attempt", "error")}

    def listing(self, limit=20, status=None):
        statuses = ("pending", "retry", "failed", "uncertain", "submitted", "simulated")
        if type(limit) is not int or not 1 <= limit <= 1000 or (status is not None and status not in statuses):
            raise ServiceError("INVALID_INPUT", "limit 须为 1 至 1000，status 须为已知邮件状态")
        query = "SELECT id,recipient,sender,transport,status,attempts,next_attempt,error FROM mail"
        query += " WHERE NOT EXISTS (SELECT 1 FROM mail_binding b WHERE b.message_id=mail.id AND b.kind='legacy' AND b.principal!=?)"
        params = [self.cfg.principal]
        if status is not None:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY rowid DESC LIMIT ?"
        params.append(limit)
        with self.db() as con:
            return [dict(row) for row in con.execute(query, params)]

    def enqueue(self, analysis, recipient, *, mcp_profile=None):
        validate_analysis(analysis, self.analysis_settings)
        if "input_evidence" in analysis:
            persist(self.workspace, analysis["input_evidence"])
        try:
            recipient, sender = address(recipient), address(self.settings["sender"])
        except ValueError:
            raise ServiceError("INVALID_INPUT", "收发件人必须为单一邮箱地址") from None
        sender_name = self.settings.get("sender_name", "")
        if not isinstance(sender_name, str) or "\r" in sender_name or "\n" in sender_name:
            raise ServiceError("INVALID_INPUT", "发件显示名无效")
        allowlist = self.settings.get("recipient_allowlist") or []
        if allowlist and recipient not in allowlist:
            raise ServiceError("PERMISSION_DENIED", "收件人不在 mail.recipient_allowlist 授权名单内")
        transport = self.settings.get("transport", "file")
        if transport not in ("file", "smtp", "mcp") or (transport == "mcp" and mcp_profile is None):
            raise ServiceError("MAIL_CONFIG", "MailCore 当前活跃队列只支持 file/smtp；MCP 仍由已授权控制台调度")
        chart_delivery = self.settings.get("chart_delivery", "inline")
        message_id = identity([analysis["analysis_id"], recipient, sender, transport])
        frozen_profile = mcp_profile if transport == "mcp" else bindings.profile(self.settings, incomplete=True)
        with process_lock(self.cfg):
            with self.db() as con:
                existing = con.execute("SELECT * FROM mail WHERE id=?", (message_id,)).fetchone()
                if existing:
                    metadata = bindings.unpack(con.execute("SELECT * FROM mail_binding WHERE message_id=?", (message_id,)).fetchone())
                    if metadata is not None:
                        self._verify_binding(dict(existing), metadata, frozen_profile)
                    return self.public(dict(existing))
                msg = EmailMessage(policy=policy.SMTP)
                msg["From"], msg["To"], msg["Message-ID"] = formataddr((sender_name, sender)), recipient, f"<{message_id}@stock-predict-mailer.local>"
                msg["Date"] = formatdate(localtime=False)
                msg["Subject"] = "预测分析报告" + (" [MOCK]" if analysis["prediction"]["synthetic"] else "")
                text, html = render(analysis, self.timezone, charts="cid" if chart_delivery == "inline" else "attachment")
                msg.set_content(text)
                msg.add_alternative(html, subtype="html")
                for idx, chart in enumerate(analysis.get("charts", [])):
                    png = chart_png(chart)
                    if chart_delivery == "inline":
                        msg.get_payload()[-1].add_related(png, maintype="image", subtype="png",
                                                         cid=f"<chart-{idx}@stock-predict-mailer.local>", disposition="inline")
                    else:
                        msg.add_attachment(png, maintype="image", subtype="png", filename=f"analysis-chart-{idx + 1}.png")
                payload = msg.as_bytes()
                atomic_write(self.workspace / "agent-outbox" / f"{message_id}.eml", payload)
                con.execute("INSERT INTO mail VALUES (?,?,?,?,'pending',0,?,NULL,?,?)",
                            (message_id, recipient, sender, transport, utcnow().isoformat(), digest(payload),
                             json.dumps(analysis, ensure_ascii=False, allow_nan=False)))
                request = None
                if transport == "mcp":
                    text, html = render(analysis)
                    request = {"recipient": recipient, "subject": "预测分析报告", "text": text, "html": html, "idempotency_key": message_id}
                self._put_binding(con, dict(con.execute("SELECT * FROM mail WHERE id=?", (message_id,)).fetchone()),
                                  {"kind": "mcp" if transport == "mcp" else "analysis", "principal": "", "source_id": None,
                                   "report_id": None, "source_record": None, "profile": frozen_profile, "request": request})
        return self.public(self.get(message_id))

    def binding(self, message_id):
        with self.db() as con:
            return bindings.unpack(con.execute("SELECT * FROM mail_binding WHERE message_id=?", (message_id,)).fetchone())

    def _put_binding(self, con, row, metadata):
        values = [metadata.get(k) for k in ("kind", "principal", "source_id", "report_id")]
        values += [json.dumps(metadata.get(k), ensure_ascii=False, sort_keys=True, allow_nan=False) if metadata.get(k) is not None else None
                   for k in ("source_record", "profile", "request")]
        con.execute("INSERT OR REPLACE INTO mail_binding VALUES (?,?,?,?,?,?,?,?,?)",
                    (row["id"], *values, bindings.binding_hash(row, metadata)))

    def _verify_binding(self, row, metadata, current_profile=None):
        if bindings.binding_hash(row, metadata) != metadata["binding_hash"]:
            raise ServiceError("MAIL_INTEGRITY", "冻结的邮件信封、正文或端点绑定被修改")
        if current_profile is not None and metadata["profile"] is not None and metadata["profile"] != current_profile:
            raise ServiceError("MAIL_ENDPOINT_CHANGED", "投递端点已变化，请先审阅并确认重新绑定")

    def _audit(self, con, message_id, action):
        moment = utcnow().isoformat()
        con.execute("INSERT INTO mail_audit VALUES (?,?,?,?)", (identity([message_id, action, moment]), message_id, action, moment))

    def _ensure_binding(self, row, current_profile):
        metadata = self.binding(row["id"])
        if metadata is not None:
            self._verify_binding(row, metadata, current_profile)
        if metadata is None or metadata["profile"] is None:
            if row["attempts"] != 0:
                raise ServiceError("MAIL_BINDING_REQUIRED", "历史邮件已有投递尝试，需先执行绑定预演与确认")
            metadata = metadata or {"kind": "analysis", "principal": "", "source_id": None, "report_id": None,
                                    "source_record": None, "request": None}
            metadata["profile"] = current_profile
            with self.db() as con:
                self._put_binding(con, row, metadata)
                self._audit(con, row["id"], "initial_endpoint_binding")
        return metadata

    def payload(self, row, metadata=None):
        payload = (self.workspace / "agent-outbox" / (row["id"] + ".eml")).read_bytes()
        if digest(payload) != row["payload_hash"]:
            raise ServiceError("INVALID_INPUT", "邮件内容完整性校验失败")
        try:
            message = BytesParser(policy=policy.default).parsebytes(payload)
            if any(len(message.get_all(key, [])) != 1 for key in ("From", "To", "Message-ID")):
                raise ValueError()
            sender, recipient = message["From"].addresses, message["To"].addresses
            if len(sender) != 1 or len(recipient) != 1 or sender[0].addr_spec != row["sender"] or recipient[0].addr_spec != row["recipient"]:
                raise ValueError()
            original_id = metadata["source_id"] if metadata and metadata["kind"] == "legacy" else row["id"]
            if not str(message["Message-ID"]).startswith("<" + original_id + "@") or not str(message["Message-ID"]).endswith(">"):
                raise ValueError()
        except (ValueError, AttributeError, IndexError, TypeError):
            raise ServiceError("MAIL_INTEGRITY", "冻结信封与 EML 不一致") from None
        return payload

    def binding_plan(self, message_id):
        from .migration import readonly
        if not isinstance(message_id, str) or not re.fullmatch("[a-f0-9]{64}", message_id):
            raise ServiceError("INVALID_INPUT", "无效邮件 ID")
        path = self.workspace / "agent-mail.sqlite3"
        if not path.exists():
            raise ServiceError("INVALID_INPUT", "邮件不存在")
        with readonly(path) as con:
            row = con.execute("SELECT * FROM mail WHERE id=?", (message_id,)).fetchone()
            if row is None:
                raise ServiceError("INVALID_INPUT", "邮件不存在")
            row = dict(row)
            has_binding = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mail_binding'").fetchone()
            metadata = bindings.unpack(con.execute("SELECT * FROM mail_binding WHERE message_id=?", (message_id,)).fetchone()) if has_binding else None
        self.payload(row, metadata)
        if metadata:
            self._verify_binding(row, metadata)
            if metadata["kind"] == "legacy" and metadata["principal"] != self.cfg.principal:
                raise ServiceError("PERMISSION_DENIED", "旧版消息属于其他 principal")
        if row["transport"] == "mcp":
            if not metadata:
                raise ServiceError("MAIL_BINDING_REQUIRED", "缺少 MCP 路由，不能猜测历史端点")
            selected = bindings.refresh_mcp(self.workspace, metadata["profile"])
        elif metadata and metadata["kind"] == "legacy":
            selected = bindings.profile(bindings.legacy_settings())
        else:
            if self.settings.get("transport", "file") != row["transport"]:
                raise ServiceError("MAIL_CONFIG", "配置与历史消息传输方式不一致")
            selected = bindings.profile(self.settings)
        body = {"message_id": message_id, "payload_hash": row["payload_hash"], "status": row["status"],
                "attempts": row["attempts"], "old_profile": metadata["profile"] if metadata else None, "new_profile": selected,
                "binding_hash": metadata["binding_hash"] if metadata else None}
        return dict(body, plan_id=identity(body), sends_mail=False)

    def bind(self, message_id, expected_plan):
        with process_lock(self.cfg):
            plan = self.binding_plan(message_id)
            if plan["plan_id"] != expected_plan:
                raise ServiceError("MAIL_PLAN_CHANGED", "绑定计划已变化")
            row = self.get(message_id)
            if row["status"] in ("submitted", "simulated"):
                raise ServiceError("MAIL_FINAL", "已完成消息不能更换端点重发")
            metadata = self.binding(message_id) or {"kind": "analysis", "principal": "", "source_id": None,
                "report_id": None, "source_record": None, "request": None}
            metadata["profile"] = plan["new_profile"]
            with self.db() as con:
                self._put_binding(con, row, metadata)
                if row["status"] == "sending":
                    con.execute("UPDATE mail SET status='uncertain',error='InterruptedDelivery' WHERE id=?", (message_id,))
                self._audit(con, message_id, "reviewed_endpoint_binding")
            return self.public(self.get(message_id))

    async def deliver_mcp(self, message_id, current_profile, transport, authorize):
        with process_lock(self.cfg):
            row = self.get(message_id)
            metadata = self.binding(message_id)
            if not metadata or metadata["kind"] != "mcp" or not metadata["request"]:
                raise ServiceError("MAIL_BINDING_REQUIRED", "缺少冻结 MCP 正文或端点")
            self._verify_binding(row, metadata, current_profile)
            if row["status"] == "sending":
                self.update(message_id, "uncertain", row["attempts"], "InterruptedDelivery")
                return self.public(self.get(message_id))
            if row["status"] not in ("pending", "retry"):
                return self.public(row)
            if instant(row["next_attempt"]) > utcnow():
                return {**self.public(row), "status": "not_due"}
            validate_analysis(json.loads(row["analysis"]), self.analysis_settings)
            self.payload(row, metadata)
            authorize()
            attempts = row["attempts"] + 1
            self.update(message_id, "sending", attempts)
            try:
                outcome = await transport.send(metadata["request"])
            except asyncio.CancelledError:
                self.update(message_id, "uncertain", attempts, "CancelledDelivery")
                raise
            except Exception:
                self.update(message_id, "uncertain", attempts, "MCPDeliveryUnknown")
                raise ServiceError("MAIL_UNCERTAIN", "MCP 邮件投递结果不确定，禁止自动重发") from None
            status = outcome.status if outcome.status in ("submitted", "simulated") else "uncertain"
            self.update(message_id, status, attempts, outcome.error)
            return self.public(self.get(message_id))

    def deliver(self, message_id):
        with process_lock(self.cfg):
            row = self.get(message_id)
            metadata = self.binding(message_id)
            if metadata and metadata["kind"] != "analysis":
                raise ServiceError("MAIL_CONFIG", "该消息须经原有授权入口执行，不能由通用 send 投递")
            if row["status"] == "sending":
                self.update(message_id, "uncertain", row["attempts"], "InterruptedDelivery")
                return self.public(self.get(message_id))
            if row["status"] not in ("pending", "retry"):
                return self.public(row)
            if instant(row["next_attempt"]) > utcnow():
                return {**self.public(row), "status": "not_due"}
            analysis = json.loads(row["analysis"])
            validate_analysis(analysis, self.analysis_settings)
            payload = self.payload(row, metadata)
            if row["transport"] != self.settings.get("transport", "file"):
                raise ServiceError("MAIL_CONFIG", "不能改变已入队消息的传输方式")
            if row["transport"] not in ("file", "smtp"):
                raise ServiceError("MAIL_CONFIG", "不支持该队列消息的传输方式")
            self._ensure_binding(row, bindings.profile(self.settings))
            allowlist = self.settings.get("recipient_allowlist") or []
            if allowlist and row["recipient"] not in allowlist:
                raise ServiceError("PERMISSION_DENIED", "投递前收件授权已撤销")
            attempts = row["attempts"] + 1
            if row["transport"] == "file":
                outcome = FileTransport(self.workspace).send(row, payload)
            else:
                transport = SMTPTransport(self.settings, analysis, row, self.smtp_factory)
                self.update(message_id, "sending", attempts)
                outcome = transport.send(row, payload)
            status = outcome.status
            if status == "retry" and attempts >= self.settings.get("max_attempts", 3):
                status = "failed"
            self.update(message_id, status, attempts, outcome.error)
            return self.public(self.get(message_id))

    def update(self, message_id, status, attempts, error=None):
        delay = self.settings.get("retry_seconds", 60) * 2 ** max(0, attempts - 1)
        next_attempt = (utcnow() + timedelta(seconds=delay)).isoformat()
        with self.db() as con:
            con.execute("UPDATE mail SET status=?,attempts=?,error=?,next_attempt=? WHERE id=?",
                        (status, attempts, error, next_attempt, message_id))

    def drain(self, limit=20):
        """Deliver messages whose backoff has elapsed; the scheduler calls this repeatedly."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ServiceError("INVALID_INPUT", "单次投递数量须为 1 到 100 的整数")
        moment = utcnow()
        with self.db() as con:
            rows = con.execute("""SELECT id, next_attempt FROM mail
                WHERE status IN ('pending','retry') AND NOT EXISTS
                (SELECT 1 FROM mail_binding b WHERE b.message_id=mail.id AND b.kind!='analysis')
                ORDER BY next_attempt LIMIT ?""",
                               (limit * 4,)).fetchall()
        due = [row["id"] for row in rows if instant(row["next_attempt"]) <= moment][:limit]
        results = []
        for message_id in due:
            try:
                results.append(self.deliver(message_id))
            except ServiceError as exc:
                # One message's configuration or integrity problem must not stop the batch.
                try:
                    results.append({**self.public(self.get(message_id)), "error": exc.code})
                except ServiceError:
                    continue
        return {"due": len(due), "results": results}

    def resolve(self, message_id, delivered=False):
        """Record a human verdict on an ambiguous send; the only way out of `uncertain`."""
        if not isinstance(delivered, bool):
            raise ServiceError("INVALID_INPUT", "确认结果须为布尔值")
        with process_lock(self.cfg):
            row = self.get(message_id)
            if row["status"] != "uncertain":
                raise ServiceError("INVALID_INPUT", "只有 uncertain 状态的邮件等待人工确认")
            action = "confirmed_delivered" if delivered else "confirmed_not_delivered"
            # Never resend on the strength of a guess: the audit row precedes the state change.
            status = "submitted" if delivered else "retry"
            moment = utcnow().isoformat()
            with self.db() as con:
                con.execute("INSERT INTO mail_audit VALUES (?,?,?,?)",
                            (identity([message_id, action, moment]), message_id, action, moment))
                con.execute("UPDATE mail SET status=?,error=?,next_attempt=? WHERE id=?",
                            (status, None if delivered else row["error"], moment, message_id))
            return self.public(self.get(message_id))
