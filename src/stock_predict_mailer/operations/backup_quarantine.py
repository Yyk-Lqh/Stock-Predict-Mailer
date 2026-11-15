"""Schema checks and restored-queue quarantine, only on isolated copies."""
import json
import sqlite3
import uuid

from ..agent_service.contracts import ServiceError, decode, utcnow
from ..core import digest
from .backup_inventory import connect, fail
from .diagnostics import SPECS

REVIEW = "RESTORED_REVIEW_REQUIRED"


def schema(con, required, optional=None):
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, columns in {**required, **{k: v for k, v in (optional or {}).items() if k in tables}}.items():
        if table not in tables or not columns.issubset({r[1] for r in con.execute(f"PRAGMA table_info({table})")}):
            fail("BACKUP_SCHEMA", "数据库结构与当前版本不兼容")
    return tables


def task_rows(con):
    total = 0
    for index, (tid, raw) in enumerate(con.execute("SELECT id,body FROM tasks")):
        if index >= 10000 or not isinstance(raw, str):
            fail("BACKUP_LIMIT", "分析任务数量或格式超过可验证范围")
        total += len(raw.encode("utf-8"))
        if total > 16 * 1024 * 1024:
            fail("BACKUP_LIMIT", "分析任务 JSON 合计超过 16 MiB")
        try:
            body = decode(raw.encode("utf-8"))
            if not isinstance(body.get("status"), dict) or not isinstance(body["status"].get("state"), str):
                raise ValueError()
            if "metadata" in body and not isinstance(body["metadata"], dict):
                raise ValueError()
        except (ValueError, TypeError, AttributeError, ServiceError):
            fail("BACKUP_SCHEMA", "分析任务 JSON 无法验证")
        yield tid, body


def validate_databases(root):
    for component, relative, required, optional in SPECS:
        path = root / ("crawler" if component == "crawler" else "app") / relative
        if not path.exists():
            continue
        con = None
        try:
            con = connect(path, True)
            schema(con, required, optional)
            if component in ("control", "development"):
                for _ in task_rows(con):
                    pass
            if component == "mail":
                schema(con, {}, {"mail_audit": {"id", "message_id", "action", "at"}})
            if component == "knowledge":
                schema(con, {"documents": {"id", "status", "error"}})
                schema(con, {}, {"workers": {"state", "current", "beat"}})
            if component == "crawler":
                schema(con, {"jobs": {"id", "state", "owner", "cancel_requested", "updated_at"}})
            if component == "legacy":
                schema(con, {}, {"outbox": {"id", "status", "error", "updated_at"}})
                schema(con, {}, {"training_jobs": {"job_id", "status", "stage", "worker_pid", "heartbeat_at", "finished_at", "cancel_requested", "error_category", "error_message"}})
        except sqlite3.Error:
            fail("BACKUP_DATABASE", "数据库结构验证失败")
        finally:
            if con is not None:
                con.close()


def quarantine(root):
    counts = {}
    for component, relative, _, _ in SPECS:
        path = root / ("crawler" if component == "crawler" else "app") / relative
        if not path.exists():
            continue
        con = connect(path)
        try:
            con.execute("BEGIN IMMEDIATE")
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            changed = 0
            stamp = utcnow().isoformat()
            if component == "mail":
                ids = [r[0] for r in con.execute("SELECT id FROM mail WHERE status IN ('pending','retry','sending')")]
                changed += con.execute("UPDATE mail SET status='uncertain',error=? WHERE status IN ('pending','retry','sending')", (REVIEW,)).rowcount
                if "mail_audit" in tables:
                    con.executemany("INSERT INTO mail_audit(id,message_id,action,at) VALUES (?,?,?,?)", [(digest((str(tid) + stamp + uuid.uuid4().hex).encode()), tid, "restored_quarantine", stamp) for tid in ids])
            elif component == "legacy":
                if "outbox" in tables:
                    changed += con.execute("UPDATE outbox SET status='uncertain',error=?,updated_at=? WHERE status IN ('pending','retry','sending')", (REVIEW, stamp)).rowcount
                changed += con.execute("UPDATE runs SET status='interrupted' WHERE status='running'").rowcount
                if "training_jobs" in tables:
                    counts["training_jobs"] = con.execute("""UPDATE training_jobs SET
                        status=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'interrupted' END,
                        stage=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'interrupted' END,
                        worker_pid=NULL,heartbeat_at=NULL,finished_at=?,error_category=?,error_message=?
                        WHERE status IN ('queued','preparing','training','cancelling')""", (stamp, REVIEW, "Restored training requires review")).rowcount
            elif component == "knowledge":
                changed += con.execute("UPDATE documents SET status='failed',error=? WHERE status IN ('pending','processing')", (REVIEW,)).rowcount
                if "workers" in tables:
                    counts["knowledge_workers"] = con.execute("UPDATE workers SET state='stopped',current=NULL,beat=?", (stamp,)).rowcount
            elif component == "crawler":
                changed += con.execute("UPDATE jobs SET state=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'interrupted' END,owner=NULL,updated_at=? WHERE state IN ('queued','running','cancelling')", (stamp,)).rowcount
            else:
                for tid, body in list(task_rows(con)):
                    if body["status"]["state"] in ("submitted", "working", "input-required"):
                        body["status"].update(state="failed", timestamp=stamp)
                        body.setdefault("metadata", {})["error"] = {"code": REVIEW, "message": "恢复的历史任务等待人工核对", "retryable": False}
                        con.execute("UPDATE tasks SET body=? WHERE id=?", (json.dumps(body, ensure_ascii=False), tid))
                        changed += 1
                if "mcp_mail" in tables:
                    changed += con.execute("UPDATE mcp_mail SET status='uncertain' WHERE status IN ('pending','retry','sending')").rowcount
            con.commit()
            if con.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                fail("BACKUP_DATABASE", "恢复后的数据库校验失败")
            counts[component] = changed
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()
    return counts
