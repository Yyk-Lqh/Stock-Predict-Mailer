"""Owner-scoped conversation checkpoints and a local SQLite vector index."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from typing import Literal

from pydantic import Field, model_validator

from ..agent_service.contracts import ServiceError, instant
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
