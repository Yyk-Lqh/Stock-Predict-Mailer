"""A2A 0.3 JSON-RPC non-streaming transport; scheduling lives elsewhere."""
from __future__ import annotations

import uuid

from ..agent_service.contracts import ServiceError


def card(base_url, role="main"):
    return {"protocolVersion": "0.3.0", "name": "Stock analysis " + role,
            "description": "Evidence-bounded prediction analysis", "url": base_url + "/a2a/" + role,
            "version": "1.0.0", "preferredTransport": "JSONRPC",
            "capabilities": {"streaming": False, "pushNotifications": False},
            "securitySchemes": {"session": {"type": "apiKey", "in": "cookie", "name": "spm_session"},
                                "bearer": {"type": "http", "scheme": "bearer"}},
            "security": [{"session": []}, {"bearer": []}], "defaultInputModes": ["application/json"], "defaultOutputModes": ["application/json"],
            "skills": [{"id": role, "name": role, "description": "Structured bounded analysis", "tags": ["prediction", role]}]}


def message(data, context_id=None):
    return {"kind": "message", "role": "user", "messageId": uuid.uuid4().hex,
            "contextId": context_id or uuid.uuid4().hex, "parts": [{"kind": "data", "data": data}]}


def data_part(msg):
    if not isinstance(msg, dict) or msg.get("role") != "user" or not isinstance(msg.get("messageId"), str):
        raise ServiceError("INVALID_PARAMS", "A2A message 必须含 user role 与 messageId")
    parts = msg.get("parts")
    if not isinstance(parts, list) or len(parts) != 1 or not isinstance(parts[0], dict) or parts[0].get("kind") != "data" or not isinstance(parts[0].get("data"), dict):
        raise ServiceError("INVALID_PARAMS", "本服务仅接受单个结构化 DataPart")
    return parts[0]["data"]
