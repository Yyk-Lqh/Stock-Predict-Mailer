"""Execution envelopes and persisted, user-facing operation events."""
from __future__ import annotations

from typing import Literal

Effort = Literal["light", "medium", "high", "extreme", "ultra"]
DEFAULT_EFFORT = "extreme"
PRESETS = {
    "light": (7, 1, 3, 20, 0),
    "medium": (8, 2, 5, 45, 0),
    "high": (10, 3, 8, 75, 0),
    "extreme": (14, 5, 12, 120, 3),
    "ultra": (18, 8, 24, 240, 3),
}
LABELS = dict(zip(PRESETS, ("轻度", "中", "高", "极高", "Ultra"), strict=True))


def envelope(level, limits):
    steps, tools, calls, seconds, children = PRESETS[level]
    return {**limits, "max_steps": steps, "max_tool_calls": tools,
            "max_calls": min(calls, limits["max_calls"]), "timeout_seconds": min(seconds, limits["timeout_seconds"]),
            "max_subagents": min(children, limits["max_subagents"])}
