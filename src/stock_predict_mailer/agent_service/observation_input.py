"""Bounded explicit observation imports; never infer columns, dates or units."""
import csv
import io

from ..core import digest
from .contracts import decode, fail, keys, number
from .forecast_contracts import observation
from .input_evidence import canonical

MAX_INPUT = 256 * 1024
FIELDS = ("schema_version", "subject", "metric", "unit", "value", "observed_at", "available_at", "source", "synthetic")


def json_bytes(value):
    try:
        return canonical(value)
    except UnicodeError:
        fail("观测包含无法编码的 Unicode 文本")


def csv_observation(raw):
    try:
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        header = next(reader, [])
        if len(header) != len(FIELDS) or set(header) != set(FIELDS):
            fail("CSV 须包含九个完整且不重复的观测字段，不支持自动列映射")
        rows = []
        for row in reader:
            if not row:
                continue
            rows.append(row)
            if len(rows) > 1:
                fail("每次只接受一条观测，不从多行中自动选择")
        if len(rows) != 1 or len(rows[0]) != len(header):
            fail("CSV 需要恰好一条完整观测")
        value = dict(zip(header, rows[0], strict=True))
        value["value"] = number(decode(value["value"].encode("utf-8")))
        if value["synthetic"] not in ("true", "false"):
            fail("CSV synthetic 只能为小写 true 或 false")
        value["synthetic"] = value["synthetic"] == "true"
        return value
    except (UnicodeError, csv.Error):
        fail("CSV 必须为有效 UTF-8 和正确的逗号分隔格式")


def parse(request, record):
    if isinstance(request, dict) and "observation" in request:
        keys(request, ("observation",), ("as_of",))
        kind, value = "object", request["observation"]
        raw = json_bytes(value)
    else:
        keys(request, ("format", "content"), ("as_of",))
        kind = request["format"]
        if kind not in ("json", "csv") or not isinstance(request["content"], str):
            fail("观测导入需要 json/csv 格式和原始文本")
        try:
            raw = request["content"].encode("utf-8")
        except UnicodeError:
            fail("观测文本不是有效 UTF-8")
        value = None
    if len(raw) > MAX_INPUT:
        fail("单次观测导入不得超过 256 KiB")
    if kind != "object":
        value = decode(raw, max_bytes=MAX_INPUT) if kind == "json" else csv_observation(raw)
    actual = observation(value, record)
    return {"observation": actual, "observation_id": digest(json_bytes(actual)),
            "input": {"format": kind, "content_sha256": digest(raw), "bytes": len(raw)}}
