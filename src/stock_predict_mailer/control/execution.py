"""Execution envelopes and persisted, user-facing operation events."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Literal

from ..agent_service.contracts import ServiceError, utcnow

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


class Progress:
    def __init__(self, store, tid, budget):
        self.store, self.tid, self.budget = store, tid, budget
        self.steps = 0
        self.tools = 0

    def tool_attempt(self):
        if self.tools >= self.budget.limits["max_tool_calls"]:
            raise ServiceError("TOOL_LIMIT", "工具调用额度已用完")
        self.budget.reserve()
        self.tools += 1

    def emit(self, kind, **data):
        self.store.append_event(self.tid, {"kind": kind, "timestamp": utcnow().isoformat(), **data})

    @contextmanager
    def step(self, key, label, **details):
        self.budget.check()
        if self.steps >= self.budget.limits["max_steps"]:
            raise ServiceError("STEP_LIMIT", "执行步骤额度已用完")
        self.steps += 1
        self.emit("step", step=key, status="running", label=label, **details)
        try:
            yield
        except BaseException as exc:
            code = exc.code if isinstance(exc, ServiceError) else type(exc).__name__
            self.emit("step", step=key, status="failed", label=label, code=code)
            raise
        else:
            self.emit("step", step=key, status="completed", label=label)
