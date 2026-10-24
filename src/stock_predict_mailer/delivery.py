"""Explicit SMTP delivery with conservative handling of ambiguous outcomes."""
from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage
from pathlib import Path

from .core import Config, atomic_write, connect, digest, now, timestamp
from .report import load_report


def outbox_schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS outbox (
        id TEXT PRIMARY KEY, report_id TEXT NOT NULL, principal TEXT NOT NULL,
        recipient TEXT NOT NULL, sender TEXT NOT NULL, status TEXT NOT NULL,
        attempts INTEGER NOT NULL, next_attempt TEXT NOT NULL, updated_at TEXT NOT NULL,
        message_id TEXT NOT NULL, eml_sha256 TEXT NOT NULL, error TEXT)""")


def address(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value):
        raise ValueError("single plain email address required")
    return value


@contextmanager
def process_lock(cfg: Config):
    """OS releases advisory byte-range lock automatically on process death."""
    cfg.workspace.mkdir(parents=True, exist_ok=True)
    path = cfg.workspace / "pipeline.lock"
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("another pipeline or sender is running") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)


def enqueue(cfg: Config, report_id: str, recipient: str, sender: str = "research@example.invalid") -> dict:
    recipient, sender = address(recipient), address(sender)
    report, body = load_report(cfg, report_id)
    identity = digest(f"{report_id}\n{recipient}\n{sender}".encode())
    with connect(cfg) as con:
        outbox_schema(con)
        existing = con.execute("SELECT * FROM outbox WHERE id=?", (identity,)).fetchone()
        if existing:
            return dict(existing)
        message_id = f"<{identity}@stock-predict-mailer.local>"
        msg = EmailMessage(policy=policy.SMTP)
        msg["From"], msg["To"], msg["Message-ID"] = sender, recipient, message_id
        label = "SYNTHETIC DEMO" if report["synthetic"] else "UNVERIFIED RESEARCH"
        msg["Subject"] = f"[{label}] Stock research {report['latest_data_date']}"
        msg.set_content(f"{label}: not investment advice. Data cutoff: {report['cutoff']}. See HTML version.")
        msg.add_alternative(body.decode("utf-8"), subtype="html")
        payload = msg.as_bytes()
        atomic_write(cfg.workspace / "outbox" / f"{identity}.eml", payload)
        con.execute("INSERT INTO outbox VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?, NULL)",
                    (identity, report_id, cfg.principal, recipient, sender, now(), now(), message_id, digest(payload)))
        return dict(con.execute("SELECT * FROM outbox WHERE id=?", (identity,)).fetchone())


def outbox(cfg: Config) -> list[dict]:
    with connect(cfg) as con:
        outbox_schema(con)
        return [dict(row) for row in con.execute("SELECT * FROM outbox WHERE principal=? ORDER BY updated_at DESC", (cfg.principal,))]


def deliver(cfg: Config, outbox_id: str, *, allow_synthetic: bool = False, allow_stale: bool = False, factory=None) -> str:
    with process_lock(cfg):
        with connect(cfg) as con:
            outbox_schema(con)
            row = con.execute("SELECT * FROM outbox WHERE id=? AND principal=?", (outbox_id, cfg.principal)).fetchone()
            if row is None:
                raise ValueError("unknown or unauthorized outbox message")
            row = dict(row)
            if row["status"] == "sending":
                con.execute("UPDATE outbox SET status='uncertain',error='InterruptedDelivery' WHERE id=?", (outbox_id,))
                return "uncertain"
            if row["status"] not in ("pending", "retry"):
                return row["status"]
            if timestamp(row["next_attempt"]) > datetime.now(timezone.utc):
                return "not_due"
        report, _ = load_report(cfg, row["report_id"])
        if report["synthetic"] and not allow_synthetic:
            raise ValueError("synthetic delivery requires explicit allow_synthetic")
        age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(report["latest_data_date"]).date()).days
        if age > 4 and not allow_stale:
            raise ValueError("stale report requires explicit allow_stale")
        payload = (cfg.workspace / "outbox" / f"{outbox_id}.eml").read_bytes()
        if digest(payload) != row["eml_sha256"]:
            raise ValueError("outbox integrity check failed")
        host, user, password = (os.environ.get(k, "") for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))
        mode = os.environ.get("SMTP_MODE", "starttls")
        if not all((host, user, password)) or mode not in ("ssl", "starttls"):
            raise ValueError("SMTP_HOST, SMTP_USER, SMTP_PASSWORD and TLS mode required")
        if row["sender"].endswith(".invalid") or row["recipient"].endswith(".invalid"):
            raise ValueError("preview addresses cannot be delivered")
        port = int(os.environ.get("SMTP_PORT", "465" if mode == "ssl" else "587"))
        attempts = row["attempts"] + 1
        with connect(cfg) as con:
            con.execute("UPDATE outbox SET status='sending',attempts=?,updated_at=? WHERE id=?", (attempts, now(), outbox_id))
        sending = False
        smtp = None
        try:
            context = ssl.create_default_context()
            if factory is not None:
                smtp = factory(host, port, timeout=30)
            elif mode == "ssl":
                smtp = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
            else:
                smtp = smtplib.SMTP(host, port, timeout=30)
            if mode == "starttls":
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(user, password)
            sending = True
            refused = smtp.sendmail(row["sender"], [row["recipient"]], payload)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
            status, error = "submitted", None
        except Exception as exc:
            error = type(exc).__name__
            if isinstance(exc, (smtplib.SMTPRecipientsRefused, smtplib.SMTPAuthenticationError)):
                status = "failed"
            elif isinstance(exc, (smtplib.SMTPDataError, smtplib.SMTPSenderRefused)):
                status = "retry" if 400 <= exc.smtp_code < 500 and attempts < 3 else "failed"
            elif sending:
                status = "uncertain"
            else:
                status = "retry" if attempts < 3 else "failed"
        finally:
            if smtp is not None:
                try:
                    smtp.close()
                except Exception:
                    pass
        with connect(cfg) as con:
            next_attempt = (datetime.now(timezone.utc) + timedelta(minutes=5 * attempts)).isoformat()
            con.execute("UPDATE outbox SET status=?,error=?,next_attempt=?,updated_at=? WHERE id=?",
                        (status, error, next_attempt, now(), outbox_id))
        return status
