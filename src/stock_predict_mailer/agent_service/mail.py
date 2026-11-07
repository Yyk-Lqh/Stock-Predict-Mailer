"""Durable idempotent delivery; ambiguous SMTP outcomes are never retried."""
from __future__ import annotations

import json
import os
import re
import smtplib
import sqlite3
import ssl
from contextlib import contextmanager
from datetime import timedelta
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate

from ..core import Config, atomic_write, digest
from ..delivery import address, process_lock
from .analysis import identity, validate_analysis
from .contracts import ServiceError, instant, utcnow
from .png import chart_png
from .reporting import render


class MailService:
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
            yield con
            con.commit()
        except Exception:
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
        return dict(row)

    @staticmethod
    def public(row):
        return {k: row[k] for k in ("id", "status", "attempts", "next_attempt", "error")}

    def listing(self, limit=20, status=None):
        statuses = ("pending", "retry", "failed", "uncertain", "submitted", "simulated")
        if type(limit) is not int or not 1 <= limit <= 1000 or (status is not None and status not in statuses):
            raise ServiceError("INVALID_INPUT", "limit 须为 1 至 1000，status 须为已知邮件状态")
        query = "SELECT id,recipient,sender,transport,status,attempts,next_attempt,error FROM mail"
        params = []
        if status is not None:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY rowid DESC LIMIT ?"
        params.append(limit)
        with self.db() as con:
            return [dict(row) for row in con.execute(query, params)]

    def enqueue(self, analysis, recipient):
        validate_analysis(analysis, self.analysis_settings)
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
        chart_delivery = self.settings.get("chart_delivery", "inline")
        message_id = identity([analysis["analysis_id"], recipient, sender, transport])
        with process_lock(self.cfg):
            with self.db() as con:
                existing = con.execute("SELECT * FROM mail WHERE id=?", (message_id,)).fetchone()
                if existing:
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
        return self.public(self.get(message_id))

    def deliver(self, message_id):
        with process_lock(self.cfg):
            row = self.get(message_id)
            if row["status"] == "sending":
                self.update(message_id, "uncertain", row["attempts"], "InterruptedDelivery")
                return self.public(self.get(message_id))
            if row["status"] not in ("pending", "retry"):
                return self.public(row)
            if instant(row["next_attempt"]) > utcnow():
                return {**self.public(row), "status": "not_due"}
            analysis = json.loads(row["analysis"])
            validate_analysis(analysis, self.analysis_settings)
            payload = (self.workspace / "agent-outbox" / f"{message_id}.eml").read_bytes()
            if digest(payload) != row["payload_hash"]:
                raise ServiceError("INVALID_INPUT", "邮件内容完整性校验失败")
            if row["transport"] != self.settings.get("transport", "file"):
                raise ServiceError("MAIL_CONFIG", "不能改变已入队消息的传输方式")
            attempts = row["attempts"] + 1
            if row["transport"] == "file":
                atomic_write(self.workspace / "sent" / f"{message_id}.eml", payload)
                self.update(message_id, "simulated", attempts)
                return self.public(self.get(message_id))
            if analysis["prediction"]["synthetic"] and not self.settings.get("allow_synthetic", False):
                raise ServiceError("MAIL_CONFIG", "SMTP 发送 Mock 报告需要 allow_synthetic=true")
            host = self.settings.get("host", "")
            user = os.environ.get(self.settings.get("user_env", "SMTP_USER"), "")
            password = os.environ.get(self.settings.get("password_env", "SMTP_PASSWORD"), "")
            mode = self.settings.get("tls", "starttls")
            if not host or not user or not password or mode not in ("ssl", "starttls"):
                raise ServiceError("MAIL_CONFIG", "缺少 SMTP 配置或凭据环境变量")
            if row["sender"].endswith(".invalid") or row["recipient"].endswith(".invalid"):
                raise ServiceError("MAIL_CONFIG", "预览邮箱不能用于 SMTP")
            self.update(message_id, "sending", attempts)
            smtp, sending = None, False
            status, error = "submitted", None
            try:
                ctx = ssl.create_default_context()
                args = (host, self.settings.get("port", 465 if mode == "ssl" else 587))
                kwargs = {"timeout": self.settings.get("timeout_seconds", 15)}
                if self.smtp_factory:
                    smtp = self.smtp_factory(*args, **kwargs)
                elif mode == "ssl":
                    smtp = smtplib.SMTP_SSL(*args, **kwargs, context=ctx)
                else:
                    smtp = smtplib.SMTP(*args, **kwargs)
                if mode == "starttls":
                    smtp.ehlo()
                    smtp.starttls(context=ctx)
                    smtp.ehlo()
                smtp.login(user, password)
                sending = True
                refused = smtp.sendmail(row["sender"], [row["recipient"]], payload)
                if refused:
                    raise smtplib.SMTPRecipientsRefused(refused)
            except Exception as exc:
                error = type(exc).__name__
                if isinstance(exc, smtplib.SMTPRecipientsRefused):
                    temporary = all(400 <= code < 500 for code, _ in exc.recipients.values())
                    status = "retry" if temporary else "failed"
                elif isinstance(exc, smtplib.SMTPResponseException):
                    status = "retry" if 400 <= exc.smtp_code < 500 else "failed"
                elif sending:
                    status = "uncertain"
                else:
                    status = "retry"
                if status == "retry" and attempts >= self.settings.get("max_attempts", 3):
                    status = "failed"
            finally:
                if smtp is not None:
                    try:
                        smtp.close()
                    except Exception:
                        pass
            self.update(message_id, status, attempts, error)
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
                WHERE status IN ('pending','retry') ORDER BY next_attempt LIMIT ?""",
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
