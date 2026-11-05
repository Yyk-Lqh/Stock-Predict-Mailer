"""Strict versioned wire contracts; upstream text is data, never instructions."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone


class ServiceError(Exception):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable

    def as_dict(self):
        return {"error": {"code": self.code, "message": self.message, "retryable": self.retryable}}


def fail(message):
    raise ServiceError("INVALID_INPUT", message)


def keys(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        fail("对象字段缺失或包含不支持的字段")


def string(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        fail("字符串须非空且不超过 1000 字符")
    return value.strip()


def number(value):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        fail("数字必须有限且不是布尔值")
    return value


def instant(value):
    try:
        dt = datetime.fromisoformat(string(value))
        if dt.tzinfo is None or dt.utcoffset() is None:
            fail("时间必须含时区")
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        fail("无效时间")


def utcnow():
    return datetime.now(timezone.utc)


def decode(raw):
    if len(raw) > 1024 * 1024:
        fail("输入超过 1 MiB")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail("JSON 字段重复")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: fail("JSON 数字必须有限"))
    except (ValueError, UnicodeError, RecursionError):
        fail("无效 JSON")


def prediction(raw, *, now=None, max_age=86400):
    keys(raw, ("schema_version", "prediction_id", "subject", "generated_at", "valid_until", "horizon", "model_version", "synthetic"),
         ("direction", "value", "value_unit", "confidence", "metrics"))
    p = dict(raw)
    if p["schema_version"] != "1" or type(p["synthetic"]) is not bool:
        fail("版本或 synthetic 无效")
    for field in ("prediction_id", "subject", "model_version"):
        p[field] = string(p[field])
    keys(p["horizon"], ("value", "unit"))
    h = p["horizon"]
    if type(h["value"]) is not int or not 1 <= h["value"] <= 365 or h["unit"] not in ("trading_days", "calendar_days", "hours"):
        fail("无效预测周期")
    if "direction" not in p and "value" not in p:
        fail("至少需要预测方向或数值")
    if "direction" in p and p["direction"] not in ("up", "down", "flat"):
        fail("无效预测方向")
    if "value" in p:
        number(p["value"])
        p["value_unit"] = string(p.get("value_unit"))
    elif "value_unit" in p:
        fail("value_unit 需要 value")
    p.setdefault("confidence", None)
    if p["confidence"] is not None and not 0 <= number(p["confidence"]) <= 1:
        fail("confidence 必须在 0..1")
    p.setdefault("metrics", {})
    if not isinstance(p["metrics"], dict):
        fail("metrics 必须为对象")
    for k, v in p["metrics"].items():
        string(k)
        number(v)
    generated, expiry = instant(p["generated_at"]), instant(p["valid_until"])
    now = now or utcnow()
    if generated > now or expiry <= generated:
        fail("预测时间在未来或有效期无效")
    if now >= expiry or (now - generated).total_seconds() > max_age:
        raise ServiceError("STALE_RESULT", "预测已过期，请上游重新生成")
    p["generated_at"], p["valid_until"] = generated.isoformat(), expiry.isoformat()
    return p


def context(raw, subject, *, now=None, max_age=86400):
    if raw is None:
        return None
    keys(raw, ("schema_version", "context_id", "subject", "facts"))
    if raw["schema_version"] != "1" or string(raw["subject"]) != subject or not isinstance(raw["facts"], list):
        fail("上下文版本、对象或 facts 无效")
    result = {**raw, "context_id": string(raw["context_id"]), "subject": subject, "facts": []}
    ids = set()
    now = now or utcnow()
    for fact in raw["facts"]:
        keys(fact, ("id", "name", "value", "unit", "source", "observed_at", "available_at"))
        f = dict(fact)
        for key in ("id", "name", "unit", "source"):
            f[key] = string(f[key])
        if f["id"] in ids:
            fail("事实 id 重复")
        ids.add(f["id"])
        if isinstance(f["value"], str):
            f["value"] = string(f["value"])
        else:
            number(f["value"])
        observed, available = instant(f["observed_at"]), instant(f["available_at"])
        if observed > available or available > now:
            fail("事实时间顺序无效或尚不可用")
        if (now - observed).total_seconds() > max_age:
            raise ServiceError("STALE_CONTEXT", "上下文事实已过期")
        f["observed_at"], f["available_at"] = observed.isoformat(), available.isoformat()
        result["facts"].append(f)
    return result
