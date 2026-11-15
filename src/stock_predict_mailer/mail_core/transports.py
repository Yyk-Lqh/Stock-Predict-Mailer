"""One-attempt delivery adapters; queue state and retry policy belong to MailCore."""
from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from typing import Protocol

from ..agent_service.contracts import ServiceError
from ..core import atomic_write


@dataclass(frozen=True)
class Outcome:
    status: str
    error: str | None = None


class Transport(Protocol):
    def send(self, envelope: dict, payload: bytes) -> Outcome: ...


class AsyncTransport(Protocol):
    async def send(self, arguments: dict) -> Outcome: ...


class FileTransport:
    def __init__(self, workspace):
        self.workspace = workspace

    def send(self, envelope, payload):
        atomic_write(self.workspace / "sent" / f"{envelope['id']}.eml", payload)
        return Outcome("simulated")


class SMTPTransport:
    def __init__(self, settings, analysis, envelope, factory=None, *, synthetic=None):
        self.settings = dict(settings)
        self.factory = factory
        is_synthetic = analysis["prediction"]["synthetic"] if synthetic is None else synthetic
        if is_synthetic and not settings.get("allow_synthetic", False):
            raise ServiceError("MAIL_CONFIG", "SMTP 发送 Mock 报告需要 allow_synthetic=true")
        self.host = settings.get("host", "")
        self.user = os.environ.get(settings.get("user_env", "SMTP_USER"), "")
        self.password = os.environ.get(settings.get("password_env", "SMTP_PASSWORD"), "")
        self.mode = settings.get("tls", "starttls")
        if not self.host or not self.user or not self.password or self.mode not in ("ssl", "starttls"):
            raise ServiceError("MAIL_CONFIG", "缺少 SMTP 配置或凭据环境变量")
        if envelope["sender"].endswith(".invalid") or envelope["recipient"].endswith(".invalid"):
            raise ServiceError("MAIL_CONFIG", "预览邮箱不能用于 SMTP")

    def send(self, envelope, payload):
        smtp, sending = None, False
        try:
            ctx = ssl.create_default_context()
            args = (self.host, self.settings.get("port", 465 if self.mode == "ssl" else 587))
            kwargs = {"timeout": self.settings.get("timeout_seconds", 15)}
            if self.factory:
                smtp = self.factory(*args, **kwargs)
            elif self.mode == "ssl":
                smtp = smtplib.SMTP_SSL(*args, **kwargs, context=ctx)
            else:
                smtp = smtplib.SMTP(*args, **kwargs)
            if self.mode == "starttls":
                smtp.ehlo()
                smtp.starttls(context=ctx)
                smtp.ehlo()
            smtp.login(self.user, self.password)
            sending = True
            refused = smtp.sendmail(envelope["sender"], [envelope["recipient"]], payload)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
            return Outcome("submitted")
        except Exception as exc:
            if isinstance(exc, smtplib.SMTPRecipientsRefused):
                temporary = all(400 <= code < 500 for code, _ in exc.recipients.values())
                status = "retry" if temporary else "failed"
            elif isinstance(exc, smtplib.SMTPResponseException):
                status = "retry" if 400 <= exc.smtp_code < 500 else "failed"
            else:
                status = "uncertain" if sending else "retry"
            return Outcome(status, type(exc).__name__)
        finally:
            if smtp is not None:
                try:
                    smtp.close()
                except Exception:
                    pass


class MCPTransport:
    def __init__(self, call, server_id, tool):
        self.call, self.server_id, self.tool = call, server_id, tool

    async def send(self, arguments):
        # Authorization, budget and cancellation handling stay with the caller/MCPLayer.
        result = await self.call(self.server_id, self.tool, arguments, effect="email")
        status = result.get("status") if isinstance(result, dict) else None
        return Outcome("submitted" if status in ("submitted", "sent") else "simulated" if status == "simulated" else "uncertain")
