"""Durable local collection queue; reads never create a database or collect data."""
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .paths import workspace
from .quality import DataQualityError, cutoff_date, utc_now
from .runtime import JobStopped, lock_held

ACTIVE = ("running", "cancelling")
TERMINAL = ("completed", "partial", "failed", "cancelled", "interrupted")


def encoded(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(raw.encode("utf-8")) > 1024 * 1024:
        raise DataQualityError("INVALID_ARGUMENT", "任务数据超过 1 MiB")
    return raw


def parameters(kind, values):
    if not isinstance(values, dict):
        raise DataQualityError("INVALID_ARGUMENT", "任务参数须为对象")
    defaults = ({"force_refresh": False, "max_cache_age_seconds": 300, "allow_stale": False} if kind == "catalog" else
                {"max_stocks": 0, "end_date": None, "allow_unverified_pool": False} if kind == "fundamental" else None)
    if defaults is None or set(values) - set(defaults):
        raise DataQualityError("INVALID_ARGUMENT", "任务类型或参数无效")
    result = dict(defaults, **values)
    for field in ("force_refresh", "allow_stale", "allow_unverified_pool"):
        if field in result and type(result[field]) is not bool:
            raise DataQualityError("INVALID_ARGUMENT", "布尔任务参数无效")
    if kind == "catalog":
        value = result["max_cache_age_seconds"]
        if type(value) is not int or not 0 <= value <= 86400:
            raise DataQualityError("INVALID_ARGUMENT", "缓存有效期须为 0 至 86400 秒")
    else:
        value = result["max_stocks"]
        if type(value) is not int or not 0 <= value <= 100000:
            raise DataQualityError("INVALID_ARGUMENT", "股票数量须为非负整数且不超过 100000")
        result["end_date"] = cutoff_date(result["end_date"]).isoformat()
    return result


class JobStore:
    def __init__(self, root=None):
        self.root = (Path(root) if root is not None else workspace()).resolve()
        self.path = self.root / "jobs" / "crawler-jobs.sqlite3"
        self.data = self.root / "data"

    @contextmanager
    def db(self, write=False):
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(self.path, timeout=10)
            con.executescript("""
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, parameters TEXT NOT NULL,
                    request_key TEXT UNIQUE, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    owner TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
                    progress TEXT NOT NULL DEFAULT '{}', checkpoint TEXT NOT NULL DEFAULT '{}',
                    result TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    at TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_job_seq ON events(job_id,seq);
            """)
            con.execute("BEGIN IMMEDIATE")
        else:
            con = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            yield con
            if write:
                con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def _event(self, con, job_id, kind, body):
        con.execute("INSERT INTO events(job_id,at,kind,body) VALUES(?,?,?,?)",
                    (job_id, utc_now().isoformat(), kind, encoded(body)))

    def _id(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise DataQualityError("INVALID_ARGUMENT", "无效任务 ID")

    def _get(self, con, job_id):
        self._id(job_id)
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise DataQualityError("JOB_NOT_FOUND", "采集任务不存在")
        return dict(row)

    @staticmethod
    def public(row):
        result = {k: v for k, v in row.items() if k != "owner"}
        for field in ("parameters", "progress", "checkpoint", "result", "error"):
            result[field] = json.loads(result[field]) if result.get(field) is not None else None
        result["cancel_requested"] = bool(result["cancel_requested"])
        return result

    def submit(self, kind, values=None, request_key=None):
        params = parameters(kind, {} if values is None else values)
        if request_key is not None and (not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128):
            raise DataQualityError("INVALID_ARGUMENT", "request_key 须为非空且不超过 128 字符")
        with self.db(True) as con:
            if request_key is not None:
                old = con.execute("SELECT * FROM jobs WHERE request_key=?", (request_key,)).fetchone()
                if old:
                    if old["kind"] != kind or old["parameters"] != encoded(params):
                        raise DataQualityError("JOB_KEY_CONFLICT", "同一 request_key 不能提交不同参数")
                    return self.public(dict(old))
            job_id, stamp = uuid.uuid4().hex, utc_now().isoformat()
            con.execute("INSERT INTO jobs(id,kind,parameters,request_key,state,created_at,updated_at) VALUES(?,?,?,?,'queued',?,?)",
                        (job_id, kind, encoded(params), request_key, stamp, stamp))
            self._event(con, job_id, "queued", {"kind": kind, "parameters": params})
            return self.public(self._get(con, job_id))

    def get(self, job_id):
        self._id(job_id)
        if not self.path.exists():
            raise DataQualityError("JOB_NOT_FOUND", "采集任务不存在")
        with self.db() as con:
            return self.public(self._get(con, job_id))

    def listing(self, limit=20):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise DataQualityError("INVALID_ARGUMENT", "limit 须为 1 至 100")
        if not self.path.exists():
            return []
        with self.db() as con:
            return [self.public(dict(row)) for row in con.execute("SELECT * FROM jobs ORDER BY rowid DESC LIMIT ?", (limit,))]

    def events(self, job_id, after=0, limit=100):
        self.get(job_id)
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise DataQualityError("INVALID_ARGUMENT", "事件游标或数量无效")
        with self.db() as con:
            return [dict(row, body=json.loads(row["body"])) for row in con.execute(
                "SELECT seq,at,kind,body FROM events WHERE job_id=? AND seq>? ORDER BY seq LIMIT ?", (job_id, after, limit))]

    def cancel(self, job_id):
        self.get(job_id)
        with self.db(True) as con:
            row = self._get(con, job_id)
            state = "cancelled" if row["state"] == "queued" else "cancelling" if row["state"] in ACTIVE else row["state"]
            if state != row["state"]:
                con.execute("UPDATE jobs SET state=?,cancel_requested=1,updated_at=? WHERE id=?",
                            (state, utc_now().isoformat(), job_id))
                self._event(con, job_id, state, {})
            return self.public(self._get(con, job_id))

    def resume(self, job_id):
        self.get(job_id)
        with self.db(True) as con:
            row = self._get(con, job_id)
            if row["state"] not in ("cancelled", "interrupted", "failed", "partial"):
                raise DataQualityError("JOB_NOT_RESUMABLE", "仅失败、部分完成、已取消或已中断任务可恢复")
            con.execute("UPDATE jobs SET state='queued',owner=NULL,cancel_requested=0,error=NULL,updated_at=? WHERE id=?",
                        (utc_now().isoformat(), job_id))
            self._event(con, job_id, "resumed", {"previous_state": row["state"], "previous_result": json.loads(row["result"]) if row["result"] else None})
            return self.public(self._get(con, job_id))

    def claim(self):
        if not lock_held(self.data):
            raise DataQualityError("LOCK_REQUIRED", "恢复和领取任务前必须取得工作区写锁")
        if not self.path.exists():
            return None
        with self.db(True) as con:
            stranded = con.execute("SELECT id,cancel_requested FROM jobs WHERE state IN ('running','cancelling')").fetchall()
            for row in stranded:
                state = "cancelled" if row["cancel_requested"] else "interrupted"
                con.execute("UPDATE jobs SET state=?,owner=NULL,updated_at=? WHERE id=?", (state, utc_now().isoformat(), row["id"]))
                self._event(con, row["id"], state, {"reason": "previous_worker_released_lock"})
            row = con.execute("SELECT id FROM jobs WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
            if row is None:
                return None
            owner = uuid.uuid4().hex
            con.execute("UPDATE jobs SET state='running',owner=?,attempts=attempts+1,result=NULL,error=NULL,updated_at=? WHERE id=?",
                        (owner, utc_now().isoformat(), row["id"]))
            self._event(con, row["id"], "running", {})
            return self._get(con, row["id"])

    def owned(self, job_id, owner):
        with self.db() as con:
            row = self._get(con, job_id)
        if row["owner"] != owner or row["state"] not in ACTIVE:
            raise JobStopped("job ownership lost")
        return row

    def update(self, job_id, owner, field, value, event):
        if field not in ("progress", "checkpoint"):
            raise ValueError("unsupported job field")
        with self.db(True) as con:
            row = self._get(con, job_id)
            if row["owner"] != owner or row["state"] not in ACTIVE:
                raise JobStopped("job ownership lost")
            con.execute(f"UPDATE jobs SET {field}=?,updated_at=? WHERE id=?", (encoded(value), utc_now().isoformat(), job_id))
            body = value if field != "checkpoint" else {
                "completed_count": len(value.get("completed_codes", ())), "output_sha256": value.get("output_sha256"),
                "selected_count": len(value.get("plan", {}).get("selected_codes", ())) }
            self._event(con, job_id, event, body)

    def touch(self, job_id, owner):
        with self.db(True) as con:
            con.execute("UPDATE jobs SET updated_at=? WHERE id=? AND owner=? AND state IN ('running','cancelling')",
                        (utc_now().isoformat(), job_id, owner))

    def finish(self, job_id, owner, state, result=None, error=None):
        if state not in TERMINAL:
            raise ValueError("unsupported terminal state")
        with self.db(True) as con:
            row = self._get(con, job_id)
            if row["owner"] != owner or row["state"] not in ACTIVE:
                raise JobStopped("job ownership lost")
            state = "cancelled" if row["cancel_requested"] else state
            con.execute("UPDATE jobs SET state=?,owner=NULL,result=?,error=?,updated_at=? WHERE id=?",
                        (state, encoded(result) if result is not None else None, encoded(error) if error else None,
                         utc_now().isoformat(), job_id))
            self._event(con, job_id, state, {"error": error})
        return self.get(job_id)


class JobControl:
    def __init__(self, store, row, stop_event=None):
        self.store, self.job_id, self.owner = store, row["id"], row["owner"]
        self.checkpoint = json.loads(row["checkpoint"])
        self._progress = json.loads(row["progress"])
        self._last_heartbeat = time.monotonic()
        self.stop_event = stop_event

    def check(self):
        if self.stop_event is not None and self.stop_event.is_set():
            raise JobStopped("worker stop requested")
        if self.store.owned(self.job_id, self.owner)["cancel_requested"]:
            raise JobStopped("cancellation requested")
        if time.monotonic() - self._last_heartbeat >= 5:
            self.store.touch(self.job_id, self.owner)
            self._last_heartbeat = time.monotonic()

    def progress(self, values):
        self._progress.update(values)
        self.store.update(self.job_id, self.owner, "progress", self._progress, "progress")

    def prepare(self, plan, output_sha256):
        previous = self.checkpoint.get("plan")
        if previous:
            if previous["pool_sha256"] != plan["pool_sha256"] or previous["as_of"] != plan["as_of"]:
                raise DataQualityError("INPUT_CHANGED", "恢复任务的股票池或截止日已改变")
            if self.checkpoint.get("output_sha256") != output_sha256:
                raise DataQualityError("CHECKPOINT_CONFLICT", "输出已改变，不能直接跳过检查点股票")
            return previous
        self.checkpoint = {"plan": plan, "completed_codes": [], "output_sha256": output_sha256}
        self._save()
        return plan

    def output_written(self, output_sha256):
        self.checkpoint["output_sha256"] = output_sha256
        self._save()

    def complete_stock(self, code, output_sha256):
        self.checkpoint["completed_codes"] = sorted(set(self.checkpoint.get("completed_codes", ())) | {code})
        self.checkpoint["output_sha256"] = output_sha256
        self._save()

    def _save(self):
        self.store.update(self.job_id, self.owner, "checkpoint", self.checkpoint, "checkpoint")
