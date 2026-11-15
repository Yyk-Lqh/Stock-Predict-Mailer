"""Non-secret TOML settings; credentials are environment references only."""
from __future__ import annotations

import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import ServiceError


def load(path):
    path = Path(path).resolve()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        allowed = {
            "prediction": {"adapter", "path", "url", "token_env", "timeout_seconds"},
            "context": {"adapter", "path", "url", "token_env", "timeout_seconds"},
            "agent": {"provider", "url", "token_env", "timeout_seconds", "max_age_seconds", "max_context_age_seconds"},
            "mail": {"transport", "sender", "sender_name", "recipient", "recipient_allowlist", "chart_delivery", "host", "port", "tls",
                     "user_env", "password_env", "allow_synthetic", "timeout_seconds", "max_attempts", "retry_seconds"},
        }
        if set(raw) - {"workspace", "timezone", *allowed}:
            raise ValueError()
        if not isinstance(raw.get("workspace"), str) or not raw["workspace"].strip():
            raise ValueError()
        raw["workspace"] = (path.parent / raw["workspace"]).resolve()
        ZoneInfo(raw.setdefault("timezone", "Asia/Shanghai"))
        for name, fields in allowed.items():
            section = raw.setdefault(name, {})
            if not isinstance(section, dict) or set(section) - fields:
                raise ValueError()
            for key, value in section.items():
                if key in ("timeout_seconds", "max_age_seconds", "max_context_age_seconds", "retry_seconds", "max_attempts", "port"):
                    maximum = 315360000 if key == "max_context_age_seconds" else 65535 if key == "port" else 604800
                    if type(value) is not int or not 1 <= value <= maximum:
                        raise ValueError()
                elif key == "allow_synthetic":
                    if type(value) is not bool:
                        raise ValueError()
                elif key == "recipient_allowlist":
                    from ..delivery import address
                    if not isinstance(value, list) or len(value) > 20:
                        raise ValueError()
                    for item in value:
                        address(item)
                elif not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
                    raise ValueError()
        for name in ("prediction", "context"):
            section = raw[name]
            kind = section.setdefault("adapter", "mock" if name == "prediction" else "none")
            if kind not in (("mock", "file", "http") if name == "prediction" else ("none", "mock", "file", "http", "crawler")):
                raise ValueError()
            if kind in ("file", "crawler"):
                section["path"] = path.parent / section["path"]
            if kind == "http" and not section.get("url"):
                raise ValueError()
        if raw["context"]["adapter"] == "crawler" and raw["prediction"]["adapter"] == "mock":
            raise ServiceError("CONFIG_ERROR", "采集上下文须显式配置 file/http 上游预测，不能回退为默认 Mock")
        if raw["agent"].setdefault("provider", "deterministic") not in ("deterministic", "http"):
            raise ValueError()
        if raw["agent"]["provider"] == "http" and not raw["agent"].get("url"):
            raise ValueError()
        if raw["mail"].setdefault("transport", "file") not in ("file", "smtp"):
            raise ValueError()
        if raw["mail"].get("chart_delivery", "inline") not in ("inline", "attachment"):
            raise ValueError()
        if raw["mail"].get("tls", "starttls") not in ("ssl", "starttls"):
            raise ValueError()
        raw["mail"].setdefault("sender", "research@example.invalid")
        raw["mail"].setdefault("recipient", "preview@example.invalid")
        if raw["mail"].get("max_attempts", 3) > 10:
            raise ValueError()
        return raw
    except (OSError, ValueError, KeyError, TypeError, ZoneInfoNotFoundError):
        raise ServiceError("CONFIG_ERROR", "配置缺失、字段不支持或参数无效") from None
