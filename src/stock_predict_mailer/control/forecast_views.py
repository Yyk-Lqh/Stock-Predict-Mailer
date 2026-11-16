"""Bounded, read-only archive views reached only through accessible tasks."""
from ..agent_service.contracts import ServiceError, decode, utcnow
from ..agent_service.forecast_archive import KEY, MAX_READ, ForecastArchive
from ..agent_service.input_evidence import canonical

MAX_BODY = 2 * 1024 * 1024
MAX_RESPONSE = 2 * 1024 * 1024


def fail(code, message):
    raise ServiceError(code, message)


class Reader:
    def __init__(self, store):
        self.store, self.bytes = store, 0
        self.archive = ForecastArchive(store.root)
        self.now = utcnow()

    def body(self, raw):
        if not isinstance(raw, bytes):
            fail("FORECAST_CORRUPT", "关联任务记录无法解析")
        self.consume(len(raw))
        if len(raw) > MAX_BODY:
            fail("FORECAST_LIMIT", "任务记录超过预测列表读取上限")
        try:
            value = decode(raw, max_bytes=MAX_BODY)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ServiceError, ValueError):
            fail("FORECAST_CORRUPT", "关联任务记录无法解析")

    def consume(self, size):
        self.bytes += size
        if self.bytes > MAX_READ:
            fail("FORECAST_LIMIT", "预测任务查询超过读取预算，请缩小分页")

    def key(self, con, tid):
        row = con.execute("SELECT substr(CAST(body AS BLOB),1,?) FROM tasks WHERE id=?", (MAX_BODY + 1, tid)).fetchone()
        if row is None:
            fail("NOT_FOUND", "任务不存在")
        task = self.body(row[0])
        try:
            artifacts = task.get("artifacts", [])
            key = artifacts[0]["parts"][0]["data"]["analysis"]["forecast_evidence"]["forecast_id"] if artifacts else None
        except (KeyError, IndexError, TypeError):
            key = None
        if key is None:
            # Registration is near the beginning of execution. Preserve access
            # to receipts from failed/canceled tasks without scanning all events.
            for raw, in con.execute("SELECT substr(CAST(body AS BLOB),1,?) FROM task_events WHERE task_id=? ORDER BY seq LIMIT 100",
                                    (MAX_BODY + 1, tid)):
                event = self.body(raw)
                if event.get("kind") == "forecast":
                    key = event.get("forecast_id")
                    if key is None:
                        fail("FORECAST_CORRUPT", "关联任务缺少预测标识")
                    break
        if key is not None and (not isinstance(key, str) or not KEY.fullmatch(key)):
            fail("FORECAST_CORRUPT", "关联任务的预测标识无效")
        return key

    def view(self, key):
        result = self.archive.show(key, now=self.now)
        self.consume(self.archive.read_bytes)
        return result


def bounded(value):
    if len(canonical(value)) > MAX_RESPONSE:
        fail("FORECAST_LIMIT", "预测查询响应超过 2 MiB，请缩小分页")
    return value


def listing(store, owner=None, *, before=2**63 - 1, limit=20, state="all"):
    if (type(before) is not int or not 0 <= before <= 2**63 - 1 or type(limit) is not int or not 1 <= limit <= 50
            or state not in ("all", "pending", "due", "evaluated")):
        fail("INVALID_INPUT", "预测列表分页或状态无效")
    reader, items, seen = Reader(store), [], set()
    with store.db() as con:
        rows = con.execute("SELECT t.rowid,t.id FROM tasks t LEFT JOIN memory_tasks m ON m.task=t.id "
                           "WHERE t.rowid<? AND (m.owner IS NULL OR m.owner=?) ORDER BY t.rowid DESC LIMIT ?",
                           (before, owner, limit + 1)).fetchall()
        for _, tid in rows[:limit]:
            key = reader.key(con, tid)
            if key is None or key in seen:
                continue
            seen.add(key)
            view = reader.view(key)
            if state != "all" and view["state"] != state:
                continue
            record = view["record"]
            latest = view["evaluations"][-1] if view["evaluations"] else None
            items.append({"task_id": tid, "forecast_id": key, "state": view["state"], "subject": record["prediction"]["subject"],
                          "synthetic": record["prediction"]["synthetic"], "target_at": record["definition"]["target_at"],
                          "metric": record["definition"]["metric"], "unit": record["definition"]["unit"],
                          "registered_at": record["registered_at"], "evaluation_count": len(view["evaluations"]),
                          "latest_metrics": latest["metrics"] if latest else None})
    return bounded({"items": items, "as_of": reader.now.isoformat(), "scanned_tasks": min(limit, len(rows)),
                    "next_before": rows[limit - 1][0] if len(rows) > limit else None})


def detail(store, tid):
    """Caller must apply the existing task-owner guard before invoking this."""
    reader = Reader(store)
    with store.db() as con:
        key = reader.key(con, tid)
    if key is None:
        fail("NOT_FOUND", "此任务没有关联的预测归档")
    return bounded({"task_id": tid, **reader.view(key)})
