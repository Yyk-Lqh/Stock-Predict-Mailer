"""Ownership of console conversations, runs and derived memory."""
import json

from ..agent_service.contracts import ServiceError

STANDARD = "standard"
PROFESSIONAL = "professional"
LEGACY = "legacy"
MODES = (STANDARD, PROFESSIONAL)
TASK_MODE_SQL = """COALESCE(json_extract(t.body,'$.metadata.mode'), CASE
    WHEN json_extract(t.body,'$.metadata.workflow') IS NOT NULL THEN 'professional'
    WHEN json_extract(t.body,'$.metadata.request') IS NOT NULL THEN 'standard'
    ELSE 'legacy' END)"""


def require_mode(actual, expected):
    if expected is not None and actual != expected:
        raise ServiceError("FORBIDDEN", "资源属于其他模式")


def task_mode(task):
    meta = task.get("metadata", {})
    return meta.get("mode") or (
        PROFESSIONAL if meta.get("workflow") else STANDARD if meta.get("request") else LEGACY
    )


def with_task_mode(task):
    return {**task, "metadata": {**task.get("metadata", {}), "mode": task_mode(task)}}


def migrate(con, open_memory):
    """Only assign old conversations when their recorded runs agree."""
    con.execute("BEGIN IMMEDIATE")
    for table in ("conversations", "memory_pending", "memory_vectors"):
        if "mode" not in {column[1] for column in con.execute(f"PRAGMA table_info({table})")}:
            con.execute(f"ALTER TABLE {table} ADD COLUMN mode TEXT")
    old_tasks = {}
    for tid, raw in con.execute("SELECT id,body FROM tasks WHERE json_valid(body) AND json_extract(body,'$.metadata.mode') IS NULL"):
        old_tasks[tid] = json.loads(raw)
    for tid, task in old_tasks.items():
        parent = task.get("contextId")
        if parent and parent != tid and task_mode(task) == LEGACY:
            source = old_tasks.get(parent)
            if source is None:
                row = con.execute("SELECT body FROM tasks WHERE id=? AND json_valid(body)", (parent,)).fetchone()
                source = json.loads(row[0]) if row else {}
            task.setdefault("metadata", {})["mode"] = task_mode(source)
        con.execute("UPDATE tasks SET body=? WHERE id=?", (json.dumps(with_task_mode(task), ensure_ascii=False), tid))
    for (cid,) in con.execute("SELECT id FROM conversations WHERE mode IS NULL").fetchall():
        modes = {row[0] for row in con.execute("""
            SELECT DISTINCT json_extract(t.body,'$.metadata.mode')
            FROM memory_tasks m JOIN tasks t ON t.id=m.task
            WHERE m.conversation=? AND json_valid(t.body) AND json_extract(t.body,'$.contextId')=t.id
            AND json_extract(t.body,'$.metadata.workflow.debug') IS NULL
        """, (cid,))}
        mode = modes.pop() if len(modes) == 1 else LEGACY
        con.execute("UPDATE conversations SET mode=? WHERE id=?", (mode or LEGACY, cid))
    def source_mode(cid, seq):
        if seq is not None:
            turn = con.execute("SELECT body FROM conversation_turns WHERE seq=? AND conversation=?", (seq, cid)).fetchone()
            if turn:
                row = con.execute("SELECT body FROM tasks WHERE id=? AND json_valid(body)",
                                  (open_memory(turn[0]).get("task"),)).fetchone()
                if row:
                    return task_mode(json.loads(row[0]))
        row = con.execute("SELECT mode FROM conversations WHERE id=?", (cid,)).fetchone()
        return row[0] if row else LEGACY

    for mid, cid, seq in con.execute("SELECT id,conversation,turn FROM memory_pending WHERE mode IS NULL").fetchall():
        con.execute("UPDATE memory_pending SET mode=? WHERE id=?", (source_mode(cid, seq), mid))
    for mid, dedup, body in con.execute("SELECT id,dedup,body FROM memory_vectors WHERE mode IS NULL").fetchall():
        entry = open_memory(body)
        mode = source_mode(entry.get("source_conversation"), entry.get("source_message"))
        con.execute("UPDATE memory_vectors SET mode=?,dedup=? WHERE id=?", (mode, f"{mode}:{dedup}", mid))
