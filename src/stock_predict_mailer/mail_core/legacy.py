"""Legacy report API backed by core rows; historical outbox is read-only."""
from contextlib import nullcontext
from email import policy
from email.message import EmailMessage

from ..agent_service.analysis import identity
from ..agent_service.contracts import ServiceError, instant, utcnow
from ..core import atomic_write, digest
from ..delivery import address, lock_owned, process_lock
from . import bindings
from .migration import _inspect, readonly
from .service import MailCore
from .transports import SMTPTransport


def _core(cfg):
    core = MailCore(cfg.workspace, bindings.legacy_settings())
    core.cfg = cfg
    return core


def old_rows(cfg):
    path = cfg.workspace / "state.sqlite3"
    if not path.exists():
        return []
    with readonly(path) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='outbox'").fetchone():
            return []
        return [dict(row) for row in con.execute("SELECT * FROM outbox WHERE principal=?", (cfg.principal,))]


def _lookup(core, source_id):
    path = core.workspace / "agent-mail.sqlite3"
    if not path.exists():
        return None
    with readonly(path) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mail_alias'").fetchone():
            return None
        row = con.execute("SELECT message_id FROM mail_alias WHERE namespace='legacy.outbox' AND source_id=? AND principal=?",
                          (source_id, core.cfg.principal)).fetchone()
    return row[0] if row else None


def _public(core, internal_id):
    row, metadata = core.get(internal_id), core.binding(internal_id)
    core._verify_binding(row, metadata)
    return dict(metadata["source_record"], id=metadata["source_id"], status=row["status"], attempts=row["attempts"],
                next_attempt=row["next_attempt"], error=row["error"], core_id=internal_id)


def _insert(core, source, payload, profile):
    internal_id = identity(["legacy.outbox", core.cfg.principal, source["id"]])
    atomic_write(core.workspace / "agent-outbox" / (internal_id + ".eml"), payload)
    metadata = {"kind": "legacy", "principal": core.cfg.principal, "source_id": source["id"], "report_id": source["report_id"],
                "source_record": source, "profile": profile, "request": None}
    with core.db() as con:
        con.execute("INSERT INTO mail VALUES (?,?,?,?,?,?,?,?,?,?)", (internal_id, source["recipient"], source["sender"], "smtp",
                    "uncertain" if source["status"] == "sending" else source["status"], source["attempts"], source["next_attempt"],
                    source["error"], source["eml_sha256"], "null"))
        row = dict(con.execute("SELECT * FROM mail WHERE id=?", (internal_id,)).fetchone())
        core._put_binding(con, row, metadata)
        con.execute("INSERT INTO mail_alias VALUES ('legacy.outbox',?,?,?)", (source["id"], core.cfg.principal, internal_id))
        core._audit(con, internal_id, "legacy_core_binding")
    return _public(core, internal_id)


def enqueue(cfg, report_id, recipient, sender="research@example.invalid"):
    from ..report import load_report
    recipient, sender = address(recipient), address(sender)
    report, body = load_report(cfg, report_id)
    source_id = digest(f"{report_id}\n{recipient}\n{sender}".encode())
    core = _core(cfg)
    with (nullcontext() if lock_owned(cfg) else process_lock(cfg)):
        alias = _lookup(core, source_id)
        if alias:
            return _public(core, alias)
        old = next((row for row in old_rows(cfg) if row["id"] == source_id), None)
        if old:
            return dict(old, legacy_read_only=True)
        message = EmailMessage(policy=policy.SMTP)
        message_id = f"<{source_id}@stock-predict-mailer.local>"
        message["From"], message["To"], message["Message-ID"] = sender, recipient, message_id
        label = "SYNTHETIC DEMO" if report["synthetic"] else "UNVERIFIED RESEARCH"
        message["Subject"] = f"[{label}] Stock research {report['latest_data_date']}"
        message.set_content(f"{label}: not investment advice. Data cutoff: {report['cutoff']}. See HTML version.")
        message.add_alternative(body.decode("utf-8"), subtype="html")
        payload, stamp = message.as_bytes(), utcnow().isoformat()
        source = {"id": source_id, "report_id": report_id, "principal": cfg.principal, "recipient": recipient, "sender": sender,
                  "status": "pending", "attempts": 0, "next_attempt": stamp, "updated_at": stamp,
                  "message_id": message_id, "eml_sha256": digest(payload), "error": None}
        atomic_write(cfg.workspace / "outbox" / (source_id + ".eml"), payload)
        return _insert(core, source, payload, bindings.profile(core.settings, incomplete=True))


def listing(cfg):
    core = _core(cfg)
    combined = {row["id"]: dict(row, legacy_read_only=True) for row in old_rows(cfg)}
    path = cfg.workspace / "agent-mail.sqlite3"
    if path.exists():
        with readonly(path) as con:
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mail_alias'").fetchone():
                ids = [row[0] for row in con.execute("SELECT message_id FROM mail_alias WHERE namespace='legacy.outbox' AND principal=?", (cfg.principal,))]
            else:
                ids = []
        combined.update({row["id"]: row for row in (_public(core, mid) for mid in ids)})
    return list(combined.values())


def deliver(cfg, source_id, allow_synthetic=False, allow_stale=False, factory=None):
    core = _core(cfg)
    with process_lock(cfg):
        alias = _lookup(core, source_id)
        if not alias:
            old = next((row for row in old_rows(cfg) if row["id"] == source_id), None)
            if not old:
                raise ServiceError("INVALID_INPUT", "unknown or unauthorized outbox message")
            if old["status"] in ("submitted", "simulated", "failed", "uncertain", "sending"):
                return "uncertain" if old["status"] == "sending" else old["status"]
            raise ServiceError("MAIL_BINDING_REQUIRED", "历史旧队列须先预演并显式绑定，不能自动迁移发送")
        row, metadata = core.get(alias), core.binding(alias)
        core._verify_binding(row, metadata)
        if row["status"] == "sending":
            core.update(alias, "uncertain", row["attempts"], "InterruptedDelivery")
            return "uncertain"
        if row["status"] not in ("pending", "retry"):
            return row["status"]
        if instant(row["next_attempt"]) > utcnow():
            return "not_due"
        from ..report import load_report
        report, _ = load_report(cfg, metadata["report_id"])
        if report["synthetic"] and not allow_synthetic:
            raise ServiceError("PERMISSION_DENIED", "synthetic delivery requires explicit allow_synthetic")
        if (utcnow().date() - instant(report["latest_data_date"] + "T00:00:00+00:00").date()).days > 4 and not allow_stale:
            raise ServiceError("PERMISSION_DENIED", "stale report requires explicit allow_stale")
        payload = core.payload(row, metadata)
        if digest((cfg.workspace / "outbox" / (source_id + ".eml")).read_bytes()) != row["payload_hash"]:
            raise ServiceError("MAIL_INTEGRITY", "legacy EML compatibility copy was modified")
        settings = dict(core.settings, allow_synthetic=allow_synthetic)
        transport = SMTPTransport(settings, None, row, factory, synthetic=report["synthetic"])
        core._ensure_binding(row, bindings.profile(settings))
        attempts = row["attempts"] + 1
        core.update(alias, "sending", attempts)
        outcome = transport.send(row, payload)
        status = "failed" if outcome.error in ("SMTPRecipientsRefused", "SMTPAuthenticationError") or (outcome.status == "retry" and attempts >= 3) else outcome.status
        core.update(alias, status, attempts, outcome.error)
        return status


def binding_plan(cfg, source_id):
    source = next((row for row in old_rows(cfg) if row["id"] == source_id), None)
    if source is None:
        raise ServiceError("INVALID_INPUT", "该 principal 下没有历史旧邮件")
    entry = _inspect(cfg.workspace, "legacy.outbox", source)["entry"]
    if entry["blockers"]:
        raise ServiceError("MAIL_INTEGRITY", "历史邮件不完整，不能激活")
    body = {"source": source, "payload_hash": entry["payload_hash"], "profile": bindings.profile(bindings.legacy_settings())}
    return dict(body, plan_id=identity(body), sends_mail=False)


def bind_old(cfg, source_id, expected_plan):
    core = _core(cfg)
    with process_lock(cfg):
        plan = binding_plan(cfg, source_id)
        if plan["plan_id"] != expected_plan:
            raise ServiceError("MAIL_PLAN_CHANGED", "历史绑定计划已变化")
        alias = _lookup(core, source_id)
        if alias:
            return _public(core, alias)
        source = plan["source"]
        if source["status"] in ("submitted", "simulated", "failed"):
            raise ServiceError("MAIL_FINAL", "已完成或终止的历史邮件不能激活重发")
        payload = (cfg.workspace / "outbox" / (source_id + ".eml")).read_bytes()
        if digest(payload) != plan["payload_hash"]:
            raise ServiceError("MAIL_PLAN_CHANGED", "历史正文已变化")
        return _insert(core, source, payload, plan["profile"])
