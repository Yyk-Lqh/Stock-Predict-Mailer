"""Bounded editor-only details saved with a private workflow revision."""
from __future__ import annotations

import re

from ..agent_service.contracts import ServiceError


def canvas_details(graph):
    if "canvas" not in graph:
        return {}
    raw = graph["canvas"]
    if not isinstance(raw, dict) or set(raw) - {"notes", "comments"}:
        raise ServiceError("INVALID_WORKFLOW", "画布说明格式无效")
    result, seen = {}, set()
    for kind in ("notes", "comments"):
        items = raw.get(kind, [])
        if not isinstance(items, list) or len(items) > 24:
            raise ServiceError("INVALID_WORKFLOW", "每条流程最多保存 24 张注释和 24 条评论")
        result[kind] = []
        for item in items:
            if not isinstance(item, dict):
                raise ServiceError("INVALID_WORKFLOW", "画布说明格式无效")
            key, body = item.get("id"), item.get("body")
            if (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key) or key in seen
                    or not isinstance(body, str) or len(body) > 1500
                    or any(type(item.get(axis)) not in (int, float) or not -20000 <= item[axis] <= 20000 for axis in ("x", "y"))):
                raise ServiceError("INVALID_WORKFLOW", "画布说明标识、正文或位置无效")
            seen.add(key)
            clean = {field: item[field] for field in ("id", "x", "y", "body")}
            if kind == "comments" and not body.strip():
                raise ServiceError("INVALID_WORKFLOW", "请先输入评论")
            if kind == "notes":
                if (item.get("color") not in ("blue", "yellow", "green", "purple", "neutral")
                        or item.get("font") not in (14, 16, 20)
                        or any(type(item.get(axis)) not in (int, float) or not low <= item[axis] <= high
                               for axis, low, high in (("width", 160, 1000), ("height", 92, 800)))):
                    raise ServiceError("INVALID_WORKFLOW", "注释颜色、字号或大小无效")
                clean.update({field: item[field] for field in ("color", "font", "width", "height")})
            result[kind].append(clean)
    return result if any(result.values()) else {}
