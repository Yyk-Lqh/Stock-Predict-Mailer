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
