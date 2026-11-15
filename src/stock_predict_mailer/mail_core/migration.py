"""Read-only migration planning and explicit, non-deliverable archival import."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from pathlib import Path

from ..agent_service.analysis import identity
from ..agent_service.contracts import ServiceError, decode, instant, utcnow
from ..core import Config, digest
from ..delivery import address, process_lock

STATUSES = {"pending", "retry", "sending", "failed", "uncertain", "submitted", "simulated"}
MAX_EML = 32 * 1024 * 1024
MAX_BATCH_BYTES = 128 * 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024 * 1024
SOURCES = (
    ("agent.mail", "agent-mail.sqlite3", "mail", ("id", "recipient", "sender", "transport", "status", "attempts", "next_attempt", "error", "payload_hash", "analysis")),
    ("legacy.outbox", "state.sqlite3", "outbox", ("id", "report_id", "principal", "recipient", "sender", "status", "attempts", "next_attempt", "updated_at", "message_id", "eml_sha256", "error")),
    ("control.mcp_mail", "control.sqlite3", "mcp_mail", ("id", "status")),
    ("control-development.mcp_mail", "control-development.sqlite3", "mcp_mail", ("id", "status")),
)


@contextmanager
def readonly(path):
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
        con.execute("BEGIN")
        yield con
    finally:
        con.close()


def _read_payload(path):
    with path.open("rb") as stream:
        payload = stream.read(MAX_EML + 1)
    if len(payload) > MAX_EML:
        raise ValueError("EML_TOO_LARGE")
    return payload


def _inspect(root, namespace, row):
    receipt = namespace.startswith("control")
    try:
        row_digest = identity(row)
    except (ValueError, TypeError, RecursionError):
        raise ServiceError("MIGRATION_SOURCE", "来源邮件列包含无法归档的数据类型") from None
    entry = {"namespace": namespace, "source_id": row["id"], "source_digest": row_digest,
             "kind": "receipt" if receipt else "message", "original_status": row["status"],
             "planned_status": "uncertain" if row["status"] == "sending" else row["status"],
             "principal": row.get("principal"), "report_id": row.get("report_id"), "analysis_id": None,
             "recipient": row.get("recipient"), "sender": row.get("sender"), "message_id": None,
             "payload_hash": None, "payload_bytes": 0, "delivery_disabled": True, "blockers": []}
    record = {"entry": entry, "row": row, "payload_path": None}
    if not isinstance(row["id"], str) or not re.fullmatch("[a-f0-9]{64}", row["id"]):
        entry["blockers"].append("INVALID_SOURCE_ID")
    if row["status"] not in STATUSES:
        entry["blockers"].append("UNKNOWN_STATUS")
    if receipt:
        entry["missing_fields"] = ["payload", "recipient", "sender", "analysis_id", "endpoint"]
        return record
    if entry["blockers"]:
        return record
    try:
        address(row["recipient"])
        address(row["sender"])
        if type(row["attempts"]) is not int or row["attempts"] < 0:
            raise ValueError()
        instant(row["next_attempt"])
    except (ServiceError, TypeError, ValueError):
        entry["blockers"].append("INVALID_ENVELOPE_OR_RETRY_METADATA")
    if namespace == "agent.mail":
        try:
            binding = row.get("binding")
            if binding:
                from .bindings import binding_hash, unpack
                binding = unpack(binding)
                if binding_hash(row, binding) != binding["binding_hash"]:
                    raise ValueError()
            if binding and binding.get("kind") == "legacy":
                entry["principal"], entry["report_id"] = binding["principal"], binding["report_id"]
                analysis_id = None
                if identity(["legacy.outbox", binding["principal"], binding["source_id"]]) != row["id"]:
                    raise ValueError()
            else:
                analysis = decode(row["analysis"].encode("utf-8"))
                analysis_id = analysis["analysis_id"]
                if identity({k: v for k, v in analysis.items() if k != "analysis_id"}) != analysis_id:
                    raise ValueError()
                if row["transport"] not in ("file", "smtp", "mcp") or identity([analysis_id, row["recipient"], row["sender"], row["transport"]]) != row["id"]:
                    raise ValueError()
            entry["analysis_id"] = analysis_id
        except (AttributeError, KeyError, TypeError, ValueError, ServiceError):
            entry["blockers"].append("INVALID_ANALYSIS_BINDING")
    relative = ("agent-outbox" if namespace == "agent.mail" else "outbox") + "/" + row["id"] + ".eml"
    record["payload_path"] = root / relative
    try:
        payload = _read_payload(record["payload_path"])
        expected = row.get("payload_hash", row.get("eml_sha256"))
        if digest(payload) != expected:
            entry["blockers"].append("PAYLOAD_HASH_MISMATCH")
        entry["payload_hash"], entry["payload_bytes"] = digest(payload), len(payload)
        message = BytesParser(policy=policy.default).parsebytes(payload)
        if any(len(message.get_all(name, [])) != 1 for name in ("From", "To", "Message-ID")):
            raise ValueError()
        senders, recipients = message["From"].addresses, message["To"].addresses
        if len(senders) != 1 or len(recipients) != 1 or senders[0].addr_spec != row["sender"] or recipients[0].addr_spec != row["recipient"]:
            raise ValueError()
        message_id = str(message["Message-ID"])
        if namespace == "legacy.outbox":
            if message_id != row["message_id"]:
                raise ValueError()
        else:
            bound = row.get("binding") or {}
            original_id = bound["source_id"] if bound.get("kind") == "legacy" else row["id"]
            if not message_id.startswith("<" + original_id + "@") or not message_id.endswith(">"):
                raise ValueError()
        entry["message_id"] = message_id
    except FileNotFoundError:
        entry["blockers"].append("PAYLOAD_MISSING")
    except OSError:
        entry["blockers"].append("PAYLOAD_UNREADABLE")
    except (AttributeError, IndexError, TypeError, ValueError):
        entry["blockers"].append("INVALID_OR_OVERSIZED_EML")
    return record


def _scan(root, principal="owner", limit=1000):
    root = Path(root).resolve()
    if not root.is_dir() or not isinstance(principal, str) or not principal.strip() or len(principal) > 1000:
        raise ServiceError("MIGRATION_SOURCE", "来源工作区或 principal 无效")
    if type(limit) is not int or not 1 <= limit <= 10000:
        raise ServiceError("INVALID_INPUT", "迁移 limit 须为 1 至 10000")
    records, summaries = [], []
    payload_bytes, metadata_bytes = 0, 0
    try:
        for namespace, filename, table, columns in SOURCES:
            path = root / filename
            summary = {"namespace": namespace, "file": filename, "rows": 0, "status": "missing"}
            summaries.append(summary)
            if not path.exists():
                continue
            with readonly(path) as con:
                if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    summary["status"] = "no_mail_table"
                    continue
                available = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
                if not set(columns).issubset(available):
                    raise ServiceError("MIGRATION_SCHEMA", "来源邮件表字段不兼容")
                where, args = (" WHERE principal=?", (principal,)) if table == "outbox" else ("", ())
                has_binding = namespace == "agent.mail" and con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mail_binding'").fetchone()
                if has_binding:
                    where = " WHERE NOT EXISTS (SELECT 1 FROM mail_binding b WHERE b.message_id=mail.id AND b.kind='legacy' AND b.principal!=?)"
                    args = (principal,)
                count = con.execute(f"SELECT COUNT(*) FROM {table}" + where, args).fetchone()[0]
                if len(records) + count > limit:
                    raise ServiceError("MIGRATION_LIMIT", "来源记录超过 limit；请提高上限或按 principal 分批")
                summary.update(rows=count, status="scanned")
                for row in con.execute(f"SELECT {','.join(columns)} FROM {table}" + where + " ORDER BY id", args):
                    original = dict(row)
                    if has_binding:
                        bound = con.execute("SELECT * FROM mail_binding WHERE message_id=?", (original["id"],)).fetchone()
                        if bound:
                            original["binding"] = dict(bound)
                    record = _inspect(root, namespace, original)
                    payload_bytes += record["entry"]["payload_bytes"]
                    metadata_bytes += len(json.dumps(record["row"], ensure_ascii=False).encode("utf-8"))
                    if payload_bytes > MAX_BATCH_BYTES or metadata_bytes > MAX_METADATA_BYTES:
                        raise ServiceError("MIGRATION_LIMIT", "批次 EML 超过 128 MiB 或邮件元数据超过 16 MiB，须分批处理")
                    records.append(record)
    except (sqlite3.Error, OSError):
        raise ServiceError("MIGRATION_SOURCE", "无法只读扫描来源数据库") from None
    entries = [record["entry"] for record in records]
    origin = digest(os.path.normcase(str(root)).encode("utf-8"))
    # Empty tables are not material input; adding an empty source cannot create duplicate records.
    plan_id = identity({"version": "1", "origin": origin, "principal": principal, "entries": entries})
    plan = {"schema_version": "1", "plan_id": plan_id, "origin": origin, "source_workspace": str(root),
            "principal_scope": principal, "sources": summaries, "entries": entries,
            "ready": not any(entry["blockers"] for entry in entries),
            "counts": {"messages": sum(entry["kind"] == "message" for entry in entries),
                       "receipts": sum(entry["kind"] == "receipt" for entry in entries),
                       "blocked": sum(bool(entry["blockers"]) for entry in entries)},
            "warnings": ["本计划不发送邮件，也不切换活跃写入口。", "各库分别只读取快照；切换前须停止旧写入者并重新核对。",
                         "principal 筛选旧 outbox 及 Core legacy 绑定；原有 agent/MCP 没有 principal，保留为未知。",
                         "submitted 不等于已进入收件箱；MCP 缺少的正文、收发信息与端点不会被补造。"]}
    return plan, records


def plan_migration(root, principal="owner", limit=1000):
    return _scan(root, principal, limit)[0]


def _archive_schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS mail_archive(
        id TEXT PRIMARY KEY, origin TEXT NOT NULL, namespace TEXT NOT NULL, source_id TEXT NOT NULL,
        kind TEXT NOT NULL, principal TEXT, report_id TEXT, analysis_id TEXT, status TEXT NOT NULL,
        original_status TEXT NOT NULL, recipient TEXT, sender TEXT, message_id TEXT,
        payload_hash TEXT, payload BLOB, source_metadata TEXT NOT NULL,
        delivery_disabled INTEGER NOT NULL CHECK(delivery_disabled=1), UNIQUE(origin,namespace,source_id))""")
    con.execute("""CREATE TABLE IF NOT EXISTS mail_migration_ledger(
        origin TEXT NOT NULL, namespace TEXT NOT NULL, source_id TEXT NOT NULL,
        record_id TEXT NOT NULL, source_digest TEXT NOT NULL, plan_id TEXT NOT NULL, imported_at TEXT NOT NULL,
        PRIMARY KEY(origin,namespace,source_id))""")


def _insert_archive(con, origin, record, plan_id):
    entry = record["entry"]
    existing = con.execute("SELECT record_id,source_digest FROM mail_migration_ledger WHERE origin=? AND namespace=? AND source_id=?",
                           (origin, entry["namespace"], entry["source_id"])).fetchone()
    source_digest = identity(entry)
    if existing:
        if existing["source_digest"] != source_digest:
            raise ServiceError("MIGRATION_CONFLICT", "来源记录与已导入映射不同，拒绝覆盖")
        archive = con.execute("SELECT * FROM mail_archive WHERE id=?", (existing["record_id"],)).fetchone()
        if archive is None or archive["source_metadata"] != json.dumps(record["row"], ensure_ascii=False, sort_keys=True, allow_nan=False):
            raise ServiceError("MIGRATION_CONFLICT", "已导入归档或映射不完整")
        expected = {"id": identity([origin, entry["namespace"], entry["source_id"]]), "origin": origin,
                    "namespace": entry["namespace"], "source_id": entry["source_id"], "kind": entry["kind"],
                    "principal": entry["principal"], "report_id": entry["report_id"], "analysis_id": entry["analysis_id"],
                    "status": entry["planned_status"], "original_status": entry["original_status"],
                    "recipient": entry["recipient"], "sender": entry["sender"], "message_id": entry["message_id"],
                    "payload_hash": entry["payload_hash"], "delivery_disabled": 1}
        if any(archive[key] != value for key, value in expected.items()):
            raise ServiceError("MIGRATION_CONFLICT", "已归档状态或来源映射被修改")
        if (archive["payload"] is None) != (entry["kind"] == "receipt") or (
                archive["payload"] is not None and digest(archive["payload"]) != entry["payload_hash"]):
            raise ServiceError("MIGRATION_CONFLICT", "已导入 EML 损坏")
        return False
    payload = _read_payload(record["payload_path"]) if record["payload_path"] else None
    if payload is not None and digest(payload) != entry["payload_hash"]:
        raise ServiceError("MIGRATION_PLAN_CHANGED", "来源 EML 在核对后变化，未导入")
    record_id = identity([origin, entry["namespace"], entry["source_id"]])
    con.execute("INSERT INTO mail_archive VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)", (
        record_id, origin, entry["namespace"], entry["source_id"], entry["kind"], entry["principal"], entry["report_id"],
        entry["analysis_id"], entry["planned_status"], entry["original_status"], entry["recipient"], entry["sender"],
        entry["message_id"], entry["payload_hash"], payload, json.dumps(record["row"], ensure_ascii=False, sort_keys=True, allow_nan=False)))
    con.execute("INSERT INTO mail_migration_ledger VALUES (?,?,?,?,?,?,?)",
                (origin, entry["namespace"], entry["source_id"], record_id, source_digest, plan_id, utcnow().isoformat()))
    return True


def import_archive(source, target, expected_plan, principal="owner", limit=1000):
    if not isinstance(expected_plan, str) or not re.fullmatch("[a-f0-9]{64}", expected_plan):
        raise ServiceError("INVALID_INPUT", "显式导入需要有效 expected-plan")
    if Path(source).resolve() == Path(target).resolve():
        raise ServiceError("MIGRATION_TARGET", "归档目标须为独立工作区，来源库保持只读")
    plan, records = _scan(source, principal, limit)
    if plan["plan_id"] != expected_plan:
        raise ServiceError("MIGRATION_PLAN_CHANGED", "来源内容与已审阅计划不同")
    if not plan["ready"]:
        raise ServiceError("MIGRATION_BLOCKED", "计划包含缺失或损坏资料，不能导入")
    if not records:
        return {"plan_id": expected_plan, "imported": 0, "existing": 0, "delivery_disabled": True}
    target = Path(target).resolve()
    from .service import MailCore

    with process_lock(Config(target)):
        plan, records = _scan(source, principal, limit)
        if plan["plan_id"] != expected_plan or not plan["ready"]:
            raise ServiceError("MIGRATION_PLAN_CHANGED", "加锁复验后来源内容变化")
        imported = 0
        with MailCore(target, {}).db() as con:
            _archive_schema(con)
            for record in records:
                imported += _insert_archive(con, plan["origin"], record, expected_plan)
    return {"plan_id": expected_plan, "imported": imported, "existing": len(records) - imported, "delivery_disabled": True}


def list_archive(target, principal="owner", limit=20):
    if type(limit) is not int or not 1 <= limit <= 1000 or not isinstance(principal, str) or not principal.strip():
        raise ServiceError("INVALID_INPUT", "归档查询参数无效")
    path = Path(target) / "agent-mail.sqlite3"
    if not path.exists():
        return []
    with readonly(path) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mail_archive'").fetchone():
            return []
        columns = "id,namespace,source_id,kind,principal,report_id,analysis_id,status,original_status,recipient,sender,message_id,payload_hash,delivery_disabled"
        return [dict(row) for row in con.execute(f"SELECT {columns} FROM mail_archive WHERE principal=? OR principal IS NULL ORDER BY rowid DESC LIMIT ?", (principal, limit))]
