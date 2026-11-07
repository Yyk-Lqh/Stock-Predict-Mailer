"""Explicitly authorized embedding adapters with strict vector validation."""
from __future__ import annotations

import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..agent_service.contracts import ServiceError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def configuration(raw, *, require_consent=True):
    allowed = {"provider", "base_url", "model", "version", "api_key", "timeout_seconds", "allow_external"}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise ServiceError("INVALID_CONFIG", "Embedding 配置字段无效")
    cfg = {"provider": "none", "base_url": "", "model": "", "version": "1", "timeout_seconds": 30,
           "allow_external": False, **raw}
    if cfg["provider"] not in ("none", "openai_compatible", "ollama"):
        raise ServiceError("INVALID_CONFIG", "不支持的 Embedding 类型")
    if type(cfg["timeout_seconds"]) is not int or not 1 <= cfg["timeout_seconds"] <= 120 or type(cfg["allow_external"]) is not bool:
        raise ServiceError("INVALID_CONFIG", "连接参数无效")
    for key in ("base_url", "model", "version", "api_key"):
        value = cfg.get(key, "")
        if not isinstance(value, str) or len(value) > 4000 or any(c in value for c in "\r\n"):
            raise ServiceError("INVALID_CONFIG", "模型字符串参数无效")
    if cfg["provider"] != "none":
        try:
            url = urlsplit(cfg["base_url"])
            _ = url.port  # Validate malformed or out-of-range ports.
        except ValueError:
            raise ServiceError("INVALID_CONFIG", "Embedding 服务 URL 无效") from None
        local = url.hostname in ("localhost", "127.0.0.1", "::1")
        if (url.scheme not in ("https", "http") or not url.hostname or url.username or url.password or url.query or url.fragment
                or (url.scheme == "http" and not local) or not cfg["model"].strip() or not cfg["version"].strip()):
            raise ServiceError("INVALID_CONFIG", "需要有效服务地址、模型与版本；远程服务须 HTTPS")
        if require_consent and not local and not cfg["allow_external"]:
            raise ServiceError("EXTERNAL_CONSENT", "请先允许向此服务发送资料及查询")
    return cfg


class EmbeddingAdapter:
    def embed(self, cfg, texts):
        cfg = configuration(cfg)
        if cfg["provider"] == "none":
            return []
        suffix = "/api/embed" if cfg["provider"] == "ollama" else "/embeddings"
        payload = {"model": cfg["model"], "input": texts}
        if cfg["provider"] == "ollama":
            payload["truncate"] = False
        headers = {"Content-Type": "application/json"}
        if cfg.get("api_key"):
            headers["Authorization"] = "Bearer " + cfg["api_key"]
        request = Request(cfg["base_url"].rstrip("/") + suffix, json.dumps(payload).encode(), headers)
        try:
            with build_opener(NoRedirect).open(request, timeout=cfg["timeout_seconds"]) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError()
            result = json.loads(raw)
            if cfg["provider"] == "ollama":
                vectors = result["embeddings"]
            else:
                rows = sorted(result["data"], key=lambda r: r["index"])
                if [r["index"] for r in rows] != list(range(len(texts))):
                    raise ValueError()
                vectors = [row["embedding"] for row in rows]
            if not isinstance(vectors, list) or len(vectors) != len(texts):
                raise ValueError()
            dimension = None
            normalized = []
            for vector in vectors:
                if not isinstance(vector, list) or not 1 <= len(vector) <= 16384:
                    raise ValueError()
                if any(type(v) not in (float, int) or not math.isfinite(v) for v in vector):
                    raise ValueError()
                norm = math.hypot(*vector)
                if not norm or not math.isfinite(norm) or (dimension is not None and len(vector) != dimension):
                    raise ValueError()
                dimension = len(vector)
                normalized.append([v / norm for v in vector])
            return normalized
        except (HTTPError, URLError, TimeoutError, OSError):
            raise ServiceError("EMBEDDING_UNAVAILABLE", "向量服务连接失败，原索引保留", True) from None
        except (ValueError, KeyError, TypeError, OverflowError):
            raise ServiceError("EMBEDDING_INVALID", "向量数量、维度或数值无效") from None
