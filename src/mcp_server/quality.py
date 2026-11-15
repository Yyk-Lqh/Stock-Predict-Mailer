"""Standard-library provenance and validation shared by optional data collectors."""
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_CACHE_AGE = 300


class DataQualityError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def utc_now():
    return datetime.now(timezone.utc)


def today():
    return utc_now().astimezone(SHANGHAI).date().isoformat()


def cutoff_date(value=None):
    value = today() if value is None else value
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise DataQualityError("INVALID_ARGUMENT", "日期必须为 YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise DataQualityError("INVALID_ARGUMENT", "无效日期") from exc
    if parsed > date.fromisoformat(today()):
        raise DataQualityError("INVALID_ARGUMENT", "截止日不能晚于上海时区当天")
    return parsed


def previous_quarter(value):
    at = date.fromisoformat(value)
    quarter = (at.month - 1) // 3
    return (at.year, quarter) if quarter else (at.year - 1, 4)


def code_of(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{6}", value):
        raise DataQualityError("INVALID_DATA", "证券代码必须为六位数字字符串")
    return value


def number(value):
    if value is None or (isinstance(value, str) and value.strip() in ("", "-", "--")):
        return None
    try:
        if isinstance(value, bool):
            raise ValueError()
        result = float(value)
        if not math.isfinite(result):
            raise ValueError()
    except (TypeError, ValueError, OverflowError) as exc:
        raise DataQualityError("INVALID_DATA", "数值必须有限，不能将非法数值当成缺失") from exc
    return result


def timestamp(value):
    try:
        at = datetime.fromisoformat(value)
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError()
        return at
    except (TypeError, ValueError) as exc:
        raise DataQualityError("INVALID_DATA", "抓取时间必须包含时区") from exc


def cache_state(metadata, max_age=DEFAULT_CACHE_AGE):
    if isinstance(max_age, bool) or not isinstance(max_age, int) or not 0 <= max_age <= 86400:
        raise DataQualityError("INVALID_ARGUMENT", "缓存有效期须为 0 至 86400 秒整数")
    if not metadata or metadata.get("fetched_at") is None:
        return "unverified", None
    age = (utc_now() - timestamp(metadata["fetched_at"])).total_seconds()
    if age < -5:
        raise DataQualityError("INVALID_DATA", "缓存抓取时间在未来")
    age = max(0, age)
    return ("fresh" if age <= max_age else "stale"), age


def atomic_bytes(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path, value):
    atomic_bytes(path, json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8"))


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"non-finite JSON value: {value}")

    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique, parse_constant=invalid)
    except (OSError, ValueError) as exc:
        raise DataQualityError("INVALID_DATA", "无法读取有效 JSON 数据") from exc


def write_snapshot(path, payload, metadata):
    meta = dict(metadata, csv_sha256=hashlib.sha256(payload).hexdigest())
    atomic_bytes(path, payload)
    atomic_json(str(path) + ".metadata.json", meta)
    return meta


def snapshot_status(path):
    path = Path(path)
    sidecar = Path(str(path) + ".metadata.json")
    if not path.exists():
        return {"integrity": "missing", "completeness": "unknown"}
    if not sidecar.exists():
        return {"integrity": "unverified", "completeness": "unknown"}
    try:
        meta = read_json(sidecar)
        if not isinstance(meta, dict) or meta.get("csv_sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            raise DataQualityError("INVALID_DATA", "CSV 与元数据不匹配")
        state, age = cache_state(meta)
        return dict(meta, integrity="verified", cache_state=state, cache_age_seconds=age)
    except (DataQualityError, OSError):
        return {"integrity": "invalid", "completeness": "unknown"}
