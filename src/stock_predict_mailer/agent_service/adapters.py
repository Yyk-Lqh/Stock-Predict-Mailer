"""Replaceable result adapters. No model binaries are loaded here."""
from __future__ import annotations

import json
import os
from datetime import timedelta
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import ServiceError, decode, utcnow


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_json(url, *, payload=None, timeout=15, token_env=""):
    try:
        parts = urlsplit(url)
    except ValueError:
        raise ServiceError("CONFIG_ERROR", "无效服务 URL") from None
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ServiceError("CONFIG_ERROR", "服务 URL 必须是无内嵌凭据的 HTTP(S) 地址")
    headers = {"Accept": "application/json"}
    if token_env:
        token = os.environ.get(token_env, "")
        if not token:
            raise ServiceError("CONFIG_ERROR", "未设置服务 token 环境变量")
        headers["Authorization"] = "Bearer " + token
    data = None if payload is None else json.dumps(payload, allow_nan=False).encode()
    if data is not None:
        if len(data) > 1024 * 1024:
            raise ServiceError("INVALID_INPUT", "Agent 请求超过 1 MiB")
        headers["Content-Type"] = "application/json"
    try:
        with build_opener(NoRedirect).open(Request(url, data=data, headers=headers), timeout=timeout) as response:
            if response.status != 200:
                raise ServiceError("UPSTREAM_UNAVAILABLE", "服务返回非 200 响应", True)
            return decode(response.read(1024 * 1024 + 1))
    except HTTPError as exc:
        raise ServiceError("UPSTREAM_UNAVAILABLE", "服务拒绝请求", exc.code == 429 or exc.code >= 500) from None
    except (URLError, OSError, ValueError, HTTPException):
        raise ServiceError("UPSTREAM_UNAVAILABLE", "服务调用失败或超时", True) from None


class FileAdapter:
    def __init__(self, path):
        self.path = Path(path)

    def fetch(self):
        try:
            with self.path.open("rb") as stream:
                return decode(stream.read(1024 * 1024 + 1))
        except OSError:
            raise ServiceError("LOCAL_IO", "无法读取输入文件") from None


class HttpAdapter:
    def __init__(self, url, timeout=15, token_env=""):
        self.url, self.timeout, self.token_env = url, timeout, token_env

    def fetch(self):
        return http_json(self.url, timeout=self.timeout, token_env=self.token_env)


class MockPredictionAdapter:
    def fetch(self):
        # Stable within the hour, while remaining fresh for repeated demos.
        now = utcnow().replace(minute=0, second=0, microsecond=0)
        return {"schema_version": "1", "prediction_id": "mock-" + now.isoformat(), "subject": "DEMO.SZ",
                "generated_at": now.isoformat(), "valid_until": (now + timedelta(days=1)).isoformat(),
                "horizon": {"value": 5, "unit": "trading_days"}, "direction": "up", "confidence": None,
                "model_version": "mock-v1", "synthetic": True, "metrics": {}}


class MockContextAdapter:
    def fetch(self):
        now = utcnow().replace(minute=0, second=0, microsecond=0).isoformat()
        return {"schema_version": "1", "context_id": "mock-context", "subject": "DEMO.SZ", "facts": [
            {"id": "f1", "name": "收盘价（合成）", "value": 10.2, "unit": "CNY", "source": "mock",
             "observed_at": now, "available_at": now}]}


def adapter(kind, settings):
    if kind == "mock":
        return MockPredictionAdapter() if settings["role"] == "prediction" else MockContextAdapter()
    if kind == "file":
        return FileAdapter(settings["path"])
    if kind == "http":
        return HttpAdapter(settings["url"], settings.get("timeout_seconds", 15), settings.get("token_env", ""))
    raise ServiceError("CONFIG_ERROR", "不支持的接入适配器")
