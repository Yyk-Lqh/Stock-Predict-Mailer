"""HTTP nodes call exact endpoints registered by the console operator."""
from __future__ import annotations

import asyncio
import json
import os
import re
from urllib.parse import urlsplit

import httpx

from ..agent_service.analysis import identity
from ..agent_service.contracts import ServiceError, decode
from ..naming import ENV_PREFIX, LEGACY_ENV_PREFIX, env, env_key

TARGETS_KEY = "WORKFLOW_HTTP_TARGETS"
TARGETS_ENV = env_key(TARGETS_KEY)
TOKEN_ENV_PATTERN = re.compile(rf"(?:{ENV_PREFIX}|{LEGACY_ENV_PREFIX})_WORKFLOW_HTTP_TOKEN_[A-Z0-9_]{{1,48}}")


def targets():
    try:
        entries = json.loads(env(TARGETS_KEY, "{}"))
    except ValueError:
        return {}
    approved = {}
    for key, target in (entries.items() if isinstance(entries, dict) else ()):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key) or not isinstance(target, dict):
            continue
        url, method, secret = (target.get(name) for name in ("url", "method", "token_env"))
        if (not isinstance(url, str) or len(url) > 1000 or method not in ("GET", "POST") or
                (secret is not None and (not isinstance(secret, str) or
                 not TOKEN_ENV_PATTERN.fullmatch(secret)))):
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.fragment:
                continue
            checked = httpx.URL(url)
        except (ValueError, httpx.InvalidURL):
            continue
        if checked.is_absolute_url:
            approved[key] = {"url": str(checked), "method": method, "token_env": secret}
    return approved


def options():
    return {key: {"method": item["method"]} for key, item in targets().items()}


def binding(config, node):
    target = targets().get(config.get("target"))
    if not target:
        raise ServiceError("PERMISSION_DENIED", f"{node} · 请选择已授权的 HTTP 目标")
    if target["token_env"] and not os.environ.get(target["token_env"]):
        raise ServiceError("PERMISSION_DENIED", f"{node} · HTTP 目标未配置凭据")
    return target


async def request(config, parameters, frozen, budget, node):
    target = binding(config, node)
    if not frozen or identity(target) != frozen:
        raise ServiceError("WORKFLOW_PROFILE_CHANGED", f"{node} · HTTP 目标授权已更改，请重新提交")
    if not isinstance(parameters, dict):
        raise ServiceError("WORKFLOW_VALUE", f"{node} · HTTP 参数需要对象")
    if len(json.dumps(parameters, ensure_ascii=False, allow_nan=False).encode()) > 8_000:
        raise ServiceError("WORKFLOW_VALUE", f"{node} · HTTP 参数超过 8 KB")
    method = target["method"]
    if method == "GET" and any(type(value) not in (str, int, float, bool) for value in parameters.values()):
        raise ServiceError("WORKFLOW_VALUE", f"{node} · GET 参数需要文本、数值或布尔值")
    arguments = ({"params": httpx.QueryParams(parameters).merge(httpx.URL(target["url"]).params)} if method == "GET" and parameters
                 else {"json": parameters} if method == "POST" else {})
    token = os.environ.get(target["token_env"], "") if target["token_env"] else ""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    budget.progress.tool_attempt()
    try:
        async with (asyncio.timeout(config["timeout"]),
                    httpx.AsyncClient(timeout=config["timeout"], follow_redirects=False, trust_env=False) as client,
                    client.stream(method, target["url"], headers=headers, **arguments) as response):
            if not response.is_success:
                raise ServiceError("WORKFLOW_HTTP_STATUS", f"{node} · HTTP 响应状态 {response.status_code}",
                                   response.status_code >= 500 or response.status_code == 429)
            data = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=4096):
                budget.check()
                data.extend(chunk)
                if len(data) > 10_000:
                    raise ServiceError("WORKFLOW_HTTP_RESPONSE", f"{node} · HTTP 响应超过 10 KB")
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            try:
                if data and (mime == "application/json" or mime.endswith("+json")):
                    content = decode(bytes(data), max_bytes=10_000)
                    json.dumps(content, allow_nan=False)
                else:
                    content = data.decode("utf-8")
            except (ServiceError, ValueError, RecursionError):
                raise ServiceError("WORKFLOW_HTTP_RESPONSE", f"{node} · HTTP 响应需为有效 JSON 或 UTF-8 文本") from None
            return {"status": response.status_code, "value": content}
    except (httpx.TimeoutException, TimeoutError):
        raise ServiceError("WORKFLOW_HTTP_TIMEOUT", f"{node} · HTTP 请求超时", True) from None
    except httpx.HTTPError:
        raise ServiceError("WORKFLOW_HTTP_CONNECTION", f"{node} · HTTP 目标连接失败", True) from None
