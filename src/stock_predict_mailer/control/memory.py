"""Owner-scoped conversation checkpoints and a local SQLite vector index."""
from __future__ import annotations

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
