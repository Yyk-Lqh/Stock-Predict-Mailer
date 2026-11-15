"""Independent import service with an OS lock and durable checkpoints."""
from __future__ import annotations

import math
import os
import socket
import time

from ..agent_service.contracts import ServiceError, utcnow
from ..core import Config
from ..delivery import process_lock
from ..naming import env
from ..operations.components import Component
from .service import Knowledge

# Idle beats are throttled to this interval. The console treats WORKER_STALE (90s) as
# gone, so six misses in a row would be needed before a healthy worker looks dead.
BEAT_EVERY = 10.0


def run(root, *, once=False, poll=2, runtime_id=None):
    from ..control.memory import Memory
    from ..control.store import Store

    if not math.isfinite(poll) or not .1 <= poll <= 60:
        raise ServiceError("INVALID_INPUT", "poll 须为 .1 至 60 秒")
    config = {"poll_seconds": poll, "once": once, "vault_mode": "production" if env("MASTER_KEY") else "development"}
    with Component(root, "knowledge_worker", config, instance=runtime_id) as component:
        with process_lock(Config(root / "private-knowledge")):
            if component.should_stop():
                return 0
            store = Store(root)
            Memory(store)
            kb = Knowledge(store)
            if component.should_stop():
                return 0
            host, pid, started = socket.gethostname(), os.getpid(), utcnow().isoformat()
            counter, last = {"processed": 0}, {"at": 0.0, "state": None, "current": None}

            def beat(state, current=None, force=False):
                moment = time.monotonic()
                if not force and state == last["state"] and current == last["current"] and moment - last["at"] < BEAT_EVERY:
                    return
                last.update(at=moment, state=state, current=current)
                try:
                    kb.heartbeat(host, pid, state=state, current=current, processed=counter["processed"], started=started)
                except Exception:
                    # Display beats do not invalidate completed work. Component
                    # retains the authoritative identity and cooperative stop fence.
                    pass

            try:
                kb.recover()
                failed = False
                beat("idle", force=True)
                component.phase("idle")
                while not component.should_stop():
                    component.phase("busy")
                    if component.should_stop():
                        break
                    result = kb.process_one(on_start=lambda did: beat("busy", did))
                    component.phase("idle")
                    if result is not None:
                        counter["processed"] += 1
                        failed = failed or result["status"] == "failed"
                    beat("idle")
                    if result is None:
                        if once:
                            return 2 if failed else 0
                        component.wait(poll)
                return 2 if failed else 0
            finally:
                beat("stopped", force=True)
