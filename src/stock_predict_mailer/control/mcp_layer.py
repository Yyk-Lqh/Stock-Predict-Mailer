"""Official MCP SDK sessions, discovery and deny-by-default execution."""
from __future__ import annotations

import json
import logging

from jsonschema import Draft202012Validator, ValidationError

from ..agent_service.contracts import ServiceError

# SDK diagnostics can contain raw provider messages. Export sanitized codes only.
_sdk_log = logging.getLogger("mcp")
_sdk_log.addHandler(logging.NullHandler())
_sdk_log.propagate = False


def bounded(value):
    try:
        raw = json.dumps(value, allow_nan=False, ensure_ascii=False)
        if len(raw.encode()) > 1024 * 1024:
            raise ValueError()
    except (ValueError, TypeError, RecursionError):
        raise ServiceError("INVALID_TOOL_DATA", "外部数据不是有限 JSON 或超过 1 MiB") from None
    return value


def schema_check(schema):
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("$ref", "$dynamicRef") and (not isinstance(item, str) or not item.startswith("#")):
                    raise ServiceError("INVALID_TOOL_SCHEMA", "不接受会触发外部取数的 Schema 引用")
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    bounded(schema)
    walk(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception:
        raise ServiceError("INVALID_TOOL_SCHEMA", "工具 Schema 不合法") from None


def validate_data(schema, data):
    schema_check(schema)
    try:
        Draft202012Validator(schema).validate(bounded(data))
    except (ValidationError, TypeError, ValueError):
        raise ServiceError("INVALID_TOOL_DATA", "工具输入或返回数据不符合 Schema") from None


def exception_code(exc):
    # SDK task groups wrap transport failures. Never expose provider messages.
    children = getattr(exc, "exceptions", ())
    if children:
        codes = [exception_code(e) for e in children]
        return "AUTH_FAILED" if "AUTH_FAILED" in codes else "CALL_TIMEOUT" if "CALL_TIMEOUT" in codes else "MCP_UNAVAILABLE"
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) in (401, 403):
        return "AUTH_FAILED"
    return "CALL_TIMEOUT" if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower() else "MCP_UNAVAILABLE"


def service_error(exc):
    if isinstance(exc, ServiceError):
        return exc
    for child in getattr(exc, "exceptions", ()):
        result = service_error(child)
        if result:
            return result
    return None
