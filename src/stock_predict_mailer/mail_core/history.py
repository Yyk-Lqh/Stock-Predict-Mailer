"""Read-only legacy MCP receipts and explicit new-prediction cutover fence."""
from ..agent_service.analysis import identity
from ..agent_service.contracts import ServiceError, instant, utcnow
from .migration import readonly


def markers(root):
    result = []
    for filename in ("control.sqlite3", "control-development.sqlite3"):
        path = root / filename
        if not path.exists():
            continue
        with readonly(path) as con:
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mcp_mail'").fetchone():
                result.extend({"database": filename, "id": row[0], "status": row[1]}
                              for row in con.execute("SELECT id,status FROM mcp_mail ORDER BY id"))
    return result


def historical_result(root, key):
    found = [row for row in markers(root) if row["id"] == key]
    if not found:
        return None
    statuses = {row["status"] for row in found}
    status = next(iter(statuses)) if len(statuses) == 1 else "uncertain"
    if status not in ("submitted", "simulated", "failed"):
        status = "uncertain"
    return {"id": key, "status": status, "legacy_read_only": True}


def review(root):
    receipts = markers(root)
    return {"plan_id": identity(receipts), "receipts": receipts, "sends_mail": False}


def acknowledge(core, expected_plan, not_before):
    from ..delivery import process_lock
    cutoff = instant(not_before)
    if cutoff > utcnow():
        raise ServiceError("INVALID_INPUT", "历史切换界限不能在未来")
    with process_lock(core.cfg):
        plan = review(core.workspace)
        if plan["plan_id"] != expected_plan:
            raise ServiceError("MAIL_PLAN_CHANGED", "旧 MCP 回执已变化，请重新审阅")
        import json
        with core.db() as con:
            con.execute("INSERT OR REPLACE INTO mail_control VALUES ('mcp_history',?)",
                        (json.dumps({"plan_id": expected_plan, "not_before": cutoff.isoformat()}),))
            core._audit(con, "mcp_history", "reviewed_history_cutover")
    return {"not_before": cutoff.isoformat(), "sends_mail": False}


def require_new_prediction(core, analysis):
    receipts = markers(core.workspace)
    if not receipts:
        return
    import json
    path = core.workspace / "agent-mail.sqlite3"
    ack = None
    if path.exists():
        with readonly(path) as con:
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mail_control'").fetchone():
                row = con.execute("SELECT body FROM mail_control WHERE id='mcp_history'").fetchone()
                ack = json.loads(row[0]) if row else None
    if (not ack or ack["plan_id"] != identity(receipts)
            or instant(analysis["prediction"]["generated_at"]) < instant(ack["not_before"])):
        raise ServiceError("MAIL_HISTORY_REVIEW_REQUIRED", "存在无法关联的旧 MCP 回执，须审阅切换界限，禁止自动重放旧预测")
