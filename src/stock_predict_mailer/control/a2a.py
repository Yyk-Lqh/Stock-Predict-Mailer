"""A2A 0.3 JSON-RPC non-streaming transport; scheduling lives elsewhere."""
from __future__ import annotations

import asyncio
import time
import uuid

from ..agent_service.contracts import ServiceError
from .models import request_json


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


class A2AClient:
    def __init__(self, store):
        self.store = store

    async def delegate(self, endpoint_id, data, budget):
        profile = self.store.get("agents", endpoint_id)
        if not profile["enabled"]:
            raise ServiceError("SERVICE_DISABLED", "对端 Agent 已停用")
        # A remote peer is allocated the remaining task envelope, no credentials.
        budget.reserve(profile["cost_ceiling_usd"])
        data = {**data, "cost_ceiling_usd": profile["cost_ceiling_usd"]}
        token = self.store.secret("agents", endpoint_id).get("auth_token", "")
        async def rpc(method, params):
            mid = uuid.uuid4().hex
            response = await request_json(profile["url"], {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}, token=token,
                                          timeout=min(profile["timeout_seconds"], max(0.1, budget.deadline - time.monotonic())))
            if not isinstance(response, dict) or response.get("id") != mid or response.get("jsonrpc") != "2.0" or "error" in response:
                raise ServiceError("A2A_FAILED", "A2A 对端响应不合规或执行失败")
            result = response.get("result", {})
            if not isinstance(result, dict):
                raise ServiceError("A2A_FAILED", "A2A 结果必须为结构化对象")
            return result
        task = await rpc("message/send", {"message": message(data)})
        try:
            while task.get("kind") == "task" and task.get("status", {}).get("state") in ("submitted", "working"):
                if not isinstance(task.get("id"), str):
                    raise ServiceError("A2A_FAILED", "异步子任务缺少 ID")
                await asyncio.sleep(.25)
                budget.reserve()
                task = await rpc("tasks/get", {"id": task["id"]})
        except (ServiceError, asyncio.CancelledError):
            if task.get("id"):
                try:
                    # One bounded lifecycle cleanup, independent of exhausted inference quota.
                    await asyncio.wait_for(rpc("tasks/cancel", {"id": task["id"]}), timeout=1)
                except (ServiceError, TimeoutError, asyncio.CancelledError):
                    pass
            raise
        if task.get("kind") != "task" or task.get("status", {}).get("state") != "completed":
            raise ServiceError("A2A_FAILED", "A2A 子任务未完成")
        try:
            result = task["artifacts"][0]["parts"][0]
            if result["kind"] != "data":
                raise ValueError()
            return result["data"]
        except (KeyError, IndexError, TypeError, ValueError):
            raise ServiceError("A2A_FAILED", "A2A 子任务缺少结构化产物") from None
