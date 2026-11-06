"""Owner-scoped conversation checkpoints and a local SQLite vector index."""
from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import uuid
from collections import Counter
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from ..agent_service.contracts import ServiceError, instant, utcnow
from .schemas import Closed

Kind = Literal["user_statement", "preference", "watchlist", "constraint", "prediction", "inference"]
ReportFormat = Literal["brief", "standard"]


class MemoryEntry(Closed):
    content: str = Field(min_length=1, max_length=800)
    kind: Kind
    tags: list[str] = Field(min_length=1, max_length=8)
    importance: int = Field(default=3, ge=1, le=5)
    subject: str | None = Field(default=None, max_length=60)
    applies_at: str | None = None
    expires_at: str | None = None
    data_version: str | None = Field(default=None, max_length=100)
    confirmed: bool = True
    report_format: ReportFormat | None = None

    @model_validator(mode="after")
    def provenance(self):
        if any(not tag or len(tag) > 40 for tag in self.tags):
            raise ValueError("主题标签无效")
        if self.kind in ("prediction", "inference") and not (self.subject and self.applies_at and self.data_version):
            raise ValueError("历史预测和推断需要标的、时间及数据版本")
        if self.report_format and self.kind != "preference":
            raise ValueError("报告格式属于偏好")
        for field in ("applies_at", "expires_at"):
            value = getattr(self, field)
            if value:
                try:
                    setattr(self, field, instant(value).isoformat())
                except ServiceError as exc:
                    raise ValueError(exc.message) from None
        return self


class MemorySettings(Closed):
    enabled: bool = True
    context_bytes: int = Field(default=10000, ge=1024, le=15000)
    recent_turns: int = Field(default=2, ge=1, le=6)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def vector(text):
    """Sparse normalized feature vector with multilingual domain-topic expansion."""
    text = text.casefold()
    aliases = {
        "report-format": ("报告", "简版", "简洁", "格式", "brief", "report", "summary"),
        "risk": ("风险", "波动", "回撤", "risk", "volatility"),
        "forecast": ("预测", "走势", "股价", "forecast", "prediction"),
    }
    terms = re.findall(r"[a-z0-9.]+|[\u3400-\u9fff]+", text)
    features = [term for term in terms if not re.fullmatch(r"[\u3400-\u9fff]{2,}", term)]
    for term in terms:
        if re.fullmatch(r"[\u3400-\u9fff]+", term):
            features.extend(term[i:i + 2] for i in range(len(term) - 1))
    for topic, words in aliases.items():
        if any(word in text for word in words):
            features.extend([topic] * 3)
    counts = Counter(hashlib.blake2s(feature.encode(), digest_size=4).hexdigest() for feature in features)
    norm = math.sqrt(sum(count * count for count in counts.values())) or 1
    return {key: count / norm for key, count in counts.items()}


def entry_identity(value):
    topic = "report-format" if value["report_format"] else ",".join(sorted(set(value["tags"])))
    if value["kind"] in ("preference", "constraint", "watchlist"):
        identity = [value["kind"], topic, value["subject"]]
    else:
        identity = [value["kind"], value["subject"], value["applies_at"], value["data_version"], value["content"]]
    return hashlib.sha256(encoded(identity)).hexdigest(), topic


def explicit_memory(message, subject):
    """Extract an explicit remember request without interpreting arbitrary prose."""
    match = re.fullmatch(r"(?:请)?记住[：:，,\s]*([^。！？\n]{1,800})[。！？]?", message.strip())
    if not match:
        return None
    content = match[1].strip()
    if not content or re.search(r"密钥|密码|令牌|api.?key|secret|password|bearer", content, re.I):
        return None
    if re.fullmatch(r"(?:我)?(?:偏好|喜欢|默认使用)(?:简版|标准版)报告", content):
        return MemoryEntry(content=content, kind="preference", tags=["报告格式"],
                           report_format="brief" if "简版" in content else "standard").model_dump()
    if re.fullmatch(r"(?:持续)?关注(?:这只股票|" + re.escape(subject) + r")", content, re.I) and len(subject) <= 60:
        return MemoryEntry(content=content, kind="watchlist", tags=["关注标的"], subject=subject).model_dump()
    return MemoryEntry(content=content, kind="user_statement", tags=["用户明确要求"]).model_dump()


class Memory:
    def __init__(self, store):
        self.store = store
        with store.db() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS memory_owners (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, settings TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, owner TEXT NOT NULL, state BLOB NOT NULL, updated TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS conversation_owner ON conversations(owner,updated);
                CREATE TABLE IF NOT EXISTS conversation_turns (seq INTEGER PRIMARY KEY, conversation TEXT NOT NULL, body BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS conversation_turn_index ON conversation_turns(conversation,seq);
                CREATE TABLE IF NOT EXISTS memory_tasks (task TEXT PRIMARY KEY, owner TEXT NOT NULL, conversation TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS memory_pending (id TEXT PRIMARY KEY, owner TEXT NOT NULL, conversation TEXT NOT NULL, turn INTEGER NOT NULL, body BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS memory_pending_owner ON memory_pending(owner,conversation);
                CREATE TABLE IF NOT EXISTS memory_vectors (id TEXT PRIMARY KEY, owner TEXT NOT NULL, dedup TEXT NOT NULL,
                    kind TEXT NOT NULL, expires TEXT, body BLOB NOT NULL, vector BLOB NOT NULL, UNIQUE(owner,dedup));
                CREATE INDEX IF NOT EXISTS memory_filter ON memory_vectors(owner,kind,expires);
            """)

    def seal(self, value):
        return self.store.cipher.encrypt(encoded(value))

    def open(self, value):
        return json.loads(self.store.cipher.decrypt(value))

    def create_owner(self):
        token, owner = secrets.token_urlsafe(32), uuid.uuid4().hex
        with self.store.db() as con:
            con.execute("INSERT INTO memory_owners VALUES (?,?,?)",
                        (owner, hashlib.sha256(token.encode()).hexdigest(), MemorySettings().model_dump_json()))
        return {"key": token, "owner": owner}

    def owner(self, token):
        with self.store.db() as con:
            row = con.execute("SELECT id FROM memory_owners WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None:
            raise ServiceError("FORBIDDEN", "需要有效的记忆访问密钥")
        return row[0]

    def settings(self, owner, value=None):
        with self.store.db() as con:
            if value is not None:
                try:
                    config = MemorySettings.model_validate(value)
                except ValidationError:
                    raise ServiceError("INVALID_CONFIG", "记忆阈值或保留轮数无效") from None
                con.execute("UPDATE memory_owners SET settings=? WHERE id=?", (config.model_dump_json(), owner))
            return json.loads(con.execute("SELECT settings FROM memory_owners WHERE id=?", (owner,)).fetchone()[0])

    def new(self, owner):
        cid = uuid.uuid4().hex
        self.save(owner, cid, {}, create=True)
        return {"id": cid}

    def conversations(self, owner):
        with self.store.db() as con:
            return [{"id": cid, "updated": updated, "subject": self.open(body).get("request", {}).get("prediction", {}).get("subject")}
                    for cid, body, updated in con.execute("SELECT id,state,updated FROM conversations WHERE owner=? ORDER BY updated DESC LIMIT 100", (owner,))]

    def state(self, owner, cid):
        with self.store.db() as con:
            row = con.execute("SELECT state FROM conversations WHERE owner=? AND id=?", (owner, cid)).fetchone()
        if row is None:
            raise ServiceError("NOT_FOUND", "会话不存在")
        return self.open(row[0])

    def save(self, owner, cid, state, *, create=False):
        with self.store.db() as con:
            if create:
                con.execute("INSERT INTO conversations VALUES (?,?,?,?)", (cid, owner, self.seal(state), utcnow().isoformat()))
            else:
                con.execute("UPDATE conversations SET state=?,updated=? WHERE owner=? AND id=?",
                            (self.seal(state), utcnow().isoformat(), owner, cid))

    def task_owner(self, tid):
        with self.store.db() as con:
            row = con.execute("SELECT owner FROM memory_tasks WHERE task=?", (tid,)).fetchone()
        return row[0] if row else None

    def begin(self, owner, cid, tid, request, task):
        state = self.state(owner, cid)
        if state.get("task"):
            status = self.store.task(state["task"])["status"]["state"]
            if status in ("working", "submitted"):
                raise ServiceError("BUSY", "该会话已有任务正在执行", True)
        p = request["prediction"]
        previous = state.get("request", {})
        if previous.get("prediction") != p or request.get("fresh_context"):
            state.pop("checkpoint", None)
        state.update(task=tid, request=request)
        turn = {"message": request.get("message", ""), "constraints": request.get("constraints", []),
                "goal": request["goal"], "task": tid, "prediction": p}
        with self.store.db() as con:
            con.execute("INSERT INTO tasks VALUES (?,?)", (tid, json.dumps(task)))
            seq = con.execute("INSERT INTO conversation_turns(conversation,body) VALUES (?,?)", (cid, self.seal(turn))).lastrowid
            con.execute("INSERT INTO memory_tasks VALUES (?,?,?)", (tid, owner, cid))
            for item in request.get("remember", []):
                con.execute("INSERT INTO memory_pending VALUES (?,?,?,?,?)", (uuid.uuid4().hex, owner, cid, seq, self.seal(item)))
            con.execute("UPDATE conversations SET state=?,updated=? WHERE owner=? AND id=?",
                        (self.seal(state), utcnow().isoformat(), owner, cid))

    def checkpoint(self, owner, cid, **values):
        state = self.state(owner, cid)
        state["checkpoint"] = {**state.get("checkpoint", {}), **values}
        self.save(owner, cid, state)

    def bind_child(self, owner, cid, tid):
        with self.store.db() as con:
            con.execute("INSERT INTO memory_tasks VALUES (?,?,?)", (tid, owner, cid))

    def _write_vector(self, con, owner, value, *, mid=None):
        dedup, topic = entry_identity(value)
        old = con.execute("SELECT id FROM memory_vectors WHERE owner=? AND dedup=?", (owner, dedup)).fetchone()
        if mid and old and old[0] != mid:
            con.execute("DELETE FROM memory_vectors WHERE owner=? AND id=?", (owner, old[0]))
        mid = mid or (old[0] if old else uuid.uuid4().hex)
        item = {**value, "id": mid, "owner": owner, "recorded_at": utcnow().isoformat()}
        features = vector(" ".join([item["content"], *item["tags"], item["subject"] or "", topic]))
        con.execute("INSERT OR REPLACE INTO memory_vectors VALUES (?,?,?,?,?,?,?)",
                    (mid, owner, dedup, item["kind"], item["expires_at"], self.seal(item), self.seal(features)))
        return item

    def entries(self, owner):
        with self.store.db() as con:
            return [self.open(row[0]) for row in con.execute("SELECT body FROM memory_vectors WHERE owner=? ORDER BY rowid DESC LIMIT 100", (owner,))]

    def pending(self, owner):
        with self.store.db() as con:
            rows = con.execute("SELECT id,conversation,turn,body FROM memory_pending WHERE owner=? ORDER BY rowid LIMIT 100", (owner,)).fetchall()
        return [{"id": pid, "source_conversation": cid, "source_message": seq, **self.open(body)} for pid, cid, seq, body in rows]

    def conversation(self, owner, cid):
        state = self.state(owner, cid)
        with self.store.db() as con:
            rows = con.execute("SELECT seq,body FROM conversation_turns WHERE conversation=? ORDER BY seq DESC LIMIT 20", (cid,)).fetchall()
        return {"id": cid, "task": state.get("task"), "summary": state.get("summary", []),
                "completed_step": state.get("checkpoint", {}).get("completed_step"),
                "messages": [{"seq": seq, **self.open(body)} for seq, body in reversed(rows)]}

    def update(self, owner, mid, raw):
        try:
            value = MemoryEntry.model_validate(raw).model_dump()
        except ValidationError:
            raise ServiceError("INVALID_INPUT", "记忆字段无效") from None
        with self.store.db() as con:
            row = con.execute("SELECT body FROM memory_vectors WHERE owner=? AND id=?", (owner, mid)).fetchone()
            if not row:
                raise ServiceError("NOT_FOUND", "记忆不存在")
            old = self.open(row[0])
            self._discard_replaced_pending(con, owner, entry_identity(old)[0], entry_identity(value)[0])
            return self._write_vector(con, owner, {**old, **value}, mid=mid)

    def delete(self, owner, mid):
        with self.store.db() as con:
            row = con.execute("SELECT dedup FROM memory_vectors WHERE owner=? AND id=?", (owner, mid)).fetchone()
            if not row:
                raise ServiceError("NOT_FOUND", "记忆不存在")
            self._discard_replaced_pending(con, owner, row[0])
            con.execute("DELETE FROM memory_vectors WHERE owner=? AND id=?", (owner, mid))

    def _discard_replaced_pending(self, con, owner, *identities):
        rows = con.execute("SELECT id,body FROM memory_pending WHERE owner=?", (owner,)).fetchall()
        for pid, body in rows:
            if entry_identity(self.open(body))[0] in identities:
                con.execute("DELETE FROM memory_pending WHERE id=?", (pid,))

    def flush(self, owner, cid):
        with self.store.db() as con:
            pending = con.execute("SELECT id,turn,body FROM memory_pending WHERE owner=? AND conversation=? ORDER BY rowid", (owner, cid)).fetchall()
            for pid, seq, body in pending:
                self._write_vector(con, owner, {**self.open(body), "source_conversation": cid, "source_message": seq})
                con.execute("DELETE FROM memory_pending WHERE id=?", (pid,))
            return len(pending)
