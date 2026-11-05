"""Official MCP SDK sessions, discovery and deny-by-default execution."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta

import httpx
from jsonschema import Draft202012Validator, ValidationError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from ..agent_service.contracts import ServiceError, decode

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


class MCPLayer:
    def __init__(self, store):
        self.store = store

    @asynccontextmanager
    async def session(self, sid):
        profile = self.store.get("mcp", sid)
        if not profile["enabled"]:
            raise ServiceError("SERVICE_DISABLED", "MCP 服务已停用")
        secrets = self.store.secret("mcp", sid)
        try:
            async with asyncio.timeout(profile["timeout_seconds"]), AsyncExitStack() as stack:
                if profile["transport"] == "stdio":
                    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "COMSPEC", "PATHEXT", "USERPROFILE") if k in os.environ}
                    env.update(secrets.get("env", {}))
                    errlog = stack.enter_context(open(os.devnull, "w"))
                    streams = await stack.enter_async_context(stdio_client(
                        StdioServerParameters(command=profile["command"], args=profile["args"], env=env), errlog=errlog))
                else:
                    headers = {"Authorization": "Bearer " + secrets["auth_token"]} if secrets.get("auth_token") else {}
                    http = await stack.enter_async_context(httpx.AsyncClient(headers=headers, timeout=profile["timeout_seconds"],
                                                                            follow_redirects=False, trust_env=False))
                    streams = await stack.enter_async_context(streamable_http_client(profile["url"], http_client=http))
                client = await stack.enter_async_context(ClientSession(streams[0], streams[1],
                                                                     read_timeout_seconds=timedelta(seconds=profile["timeout_seconds"])))
                info = await client.initialize()
                yield client, info, profile
        except ServiceError:
            raise
        except Exception as exc:
            nested = service_error(exc)
            if nested:
                raise nested from None
            code = exception_code(exc)
            raise ServiceError(code, {"AUTH_FAILED": "MCP 认证失败", "CALL_TIMEOUT": "MCP 调用超时"}.get(code, "MCP 连接或调用失败"), code != "AUTH_FAILED") from None

    async def pages(self, method):
        cursor, result = None, []
        for _ in range(10):
            page = await method(cursor=cursor)
            data = page.model_dump(mode="json", by_alias=True)
            result.extend(data.get("tools", data.get("resources", [])))
            cursor = data.get("nextCursor")
            if not cursor:
                return result
        raise ServiceError("MCP_LIMIT", "发现结果超过 10 页上限")

    async def discover(self, sid):
        async with self.session(sid) as (client, info, _):
            tools = await self.pages(client.list_tools) if info.capabilities.tools else []
            resources = await self.pages(client.list_resources) if info.capabilities.resources else []
            for tool in tools:
                schema_check(tool["inputSchema"])
                if tool.get("outputSchema"):
                    schema_check(tool["outputSchema"])
            return bounded({"status": "ok", "tools": tools, "resources": resources,
                            "protocol_version": info.protocolVersion, "server": info.serverInfo.model_dump(mode="json")})

    async def call(self, sid, name, arguments, *, effect="read", role_tools=None):
        profile = self.store.get("mcp", sid)
        if name not in profile["allowed_tools"] or profile["effects"].get(name, "deny") != effect:
            raise ServiceError("PERMISSION_DENIED", "工具未授权或副作用类型不匹配")
        if role_tools is not None and sid + ":" + name not in role_tools:
            raise ServiceError("PERMISSION_DENIED", "此 Agent 未获该工具权限")
        if effect == "email":
            policy = self.store.settings()["mail"]
            if policy["transport"] != "mcp" or policy["mcp_server_id"] != sid or policy["mcp_tool"] != name:
                raise ServiceError("PERMISSION_DENIED", "不在邮件授权服务范围内")
            if arguments.get("recipient") not in policy["recipient_allowlist"]:
                raise ServiceError("PERMISSION_DENIED", "收件人未授权")
        async with self.session(sid) as (client, _, _):
            tools = await self.pages(client.list_tools)
            tool = next((t for t in tools if t["name"] == name), None)
            if tool is None:
                raise ServiceError("TOOL_NOT_FOUND", "服务未提供此工具")
            validate_data(tool["inputSchema"], arguments)
            response = await client.call_tool(name, arguments)
            if response.isError:
                raise ServiceError("TOOL_FAILED", "外部工具执行失败")
            result = response.structuredContent
            if result is None and len(response.content) == 1 and response.content[0].type == "text":
                result = decode(response.content[0].text.encode())
            if not isinstance(result, dict):
                raise ServiceError("INVALID_TOOL_DATA", "工具须提供结构化内容或单个 JSON text 对象")
            if tool.get("outputSchema"):
                validate_data(tool["outputSchema"], result)
            return bounded(result)

    async def read(self, sid, uri):
        profile = self.store.get("mcp", sid)
        if uri not in profile["allowed_resources"]:
            raise ServiceError("PERMISSION_DENIED", "资源 URI 未授权")
        async with self.session(sid) as (client, _, _):
            result = await client.read_resource(uri)
            return bounded(result.model_dump(mode="json", by_alias=True))
