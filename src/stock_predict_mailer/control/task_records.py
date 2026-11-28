"""Owner-scoped search and updated-time pagination for the task records page."""
import json
import re

from ..agent_service.contracts import ServiceError
from .modes import LEGACY, MODES, TASK_MODE_SQL, with_task_mode

ACTIVE = ("submitted", "working")
STATES = (*ACTIVE, "completed", "failed", "canceled")
CURSOR = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z)?\|(\d{1,19})")
STATE = "json_extract(t.body,'$.status.state')"
UPDATED = "COALESCE(strftime('%Y-%m-%dT%H:%M:%fZ',json_extract(t.body,'$.status.timestamp')), '')"
MAIL = "json_extract(t.body,'$.artifacts[0].parts[0].data.mail.status')"
SEARCH = (
    "t.id",
    "json_extract(t.body,'$.metadata.request.subject')",
    "json_extract(t.body,'$.artifacts[0].parts[0].data.analysis.prediction.subject')",
    "json_extract(t.body,'$.metadata.request.name')",
    "json_extract(t.body,'$.metadata.workflow.flow.name')",
    "json_extract(t.body,'$.metadata.error.code')",
    f"""CASE {STATE} WHEN 'submitted' THEN '已提交' WHEN 'working' THEN '运行中'
    WHEN 'completed' THEN '已完成' WHEN 'failed' THEN '失败' WHEN 'canceled' THEN '已取消' END""",
    f"""CASE {MAIL} WHEN 'not_requested' THEN '未请求通知' WHEN 'simulated' THEN '模拟投递'
    WHEN 'submitted' THEN '已提交服务器' WHEN 'retry' THEN '等待重试' WHEN 'not_due' THEN '等待到期'
    WHEN 'failed' THEN '投递失败' WHEN 'uncertain' THEN '结果未知' WHEN 'pending' THEN '待发送'
    WHEN 'sending' THEN '发送中' WHEN 'partial' THEN '部分投递完成，查看逐邮箱结果' END""",
)
ELIGIBLE = f"""
    FROM tasks t LEFT JOIN memory_tasks m ON m.task=t.id
    WHERE (m.owner IS NULL OR m.owner=:owner)
      AND (:header IS NULL OR {TASK_MODE_SQL}=:header)
      AND (:mode='all' OR {TASK_MODE_SQL}=:mode)
      AND json_extract(t.body,'$.metadata.workflow.debug') IS NULL
      AND coalesce(nullif(json_extract(t.body,'$.contextId'), ''), t.id)=t.id
      AND (:q='' OR ({" OR ".join(f"instr(record_fold({field}), :q)>0" for field in SEARCH)}))
"""


def listing(store, owner, header_mode, query):
    if set(query) - {"mode", "state", "q", "before", "limit"} or any(len(values) != 1 for values in query.values()):
        raise ServiceError("INVALID_INPUT", "任务记录仅接受单个模式、状态、搜索词、游标及分页大小")
    filters = {key: values[0] for key, values in query.items()}
    mode, state = filters.get("mode", "all"), filters.get("state", "all")
    term = filters.get("q", "").strip()
    if mode not in ("all", *MODES, LEGACY) or state not in ("all", "active", *STATES):
        raise ServiceError("INVALID_INPUT", "任务记录模式或状态无效")
    if len(term) > 128 or any(ord(char) < 32 for char in term):
        raise ServiceError("INVALID_INPUT", "搜索词应为 128 字以内的单行文字")
    try:
        limit = int(filters.get("limit", "30"))
        if not 1 <= limit <= 100:
            raise ValueError()
        if "before" in filters:
            match = CURSOR.fullmatch(filters["before"])
            if match is None or not 1 <= int(match[2]) < 2**63:
                raise ValueError()
            updated, rowid = match[1] or "", int(match[2])
        else:
            updated, rowid = None, None
    except ValueError:
        raise ServiceError("INVALID_INPUT", "任务记录分页大小或游标无效") from None

    params = {"owner": owner, "header": header_mode, "mode": mode, "state": state,
              "q": term.casefold(), "updated": updated, "rowid": rowid, "limit": limit + 1}
    with store.db() as con:
        con.create_function("record_fold", 1, lambda value: "" if value is None else str(value).casefold(),
                            deterministic=True)
        con.execute("BEGIN")
        counts = dict(con.execute(f"SELECT {STATE}, count(*) {ELIGIBLE} GROUP BY {STATE}", params))
        rows = con.execute(f"""
            WITH page AS (
                SELECT t.rowid AS position, {UPDATED} AS updated {ELIGIBLE}
                  AND (:state='all' OR {STATE}=:state OR (:state='active' AND {STATE} IN ('submitted','working')))
                  AND (:updated IS NULL OR ({UPDATED}, t.rowid)<(:updated,:rowid))
                ORDER BY updated DESC, position DESC LIMIT :limit
            )
            SELECT p.position, p.updated, t.body FROM page p JOIN tasks t ON t.rowid=p.position
            ORDER BY p.updated DESC, p.position DESC
        """, params).fetchall()
    groups = {"all": sum(counts.values()), "active": sum(counts.get(status, 0) for status in ACTIVE),
              **{status: counts.get(status, 0) for status in STATES}}
    return {"items": [with_task_mode(json.loads(body)) for _, _, body in rows[:limit]], "counts": groups,
            "next_before": f"{rows[limit - 1][1]}|{rows[limit - 1][0]}" if len(rows) > limit else None}
