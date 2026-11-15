"""Independent import service with an OS lock and durable checkpoints."""
from __future__ import annotations

import math
import os
import socket
import time

from ..agent_service.contracts import ServiceError, utcnow
from ..core import Config
from ..delivery import process_lock
from .service import Knowledge

# Idle beats are throttled to this interval. The console treats WORKER_STALE (90s) as
# gone, so six misses in a row would be needed before a healthy worker looks dead.
BEAT_EVERY = 10.0


def run(root, *, once=False, poll=2):
    from ..control.memory import Memory
    from ..control.store import Store

    if not math.isfinite(poll) or not .1 <= poll <= 60:
        raise ServiceError("INVALID_INPUT", "poll 须为 .1 至 60 秒")
    store = Store(root)
    Memory(store)
    kb = Knowledge(store)
    host, pid, started = socket.gethostname(), os.getpid(), utcnow().isoformat()
    counter, last = {"processed": 0}, {"at": 0.0, "state": None, "current": None}

    def beat(now_state, current=None, force=False):
        # Losing sight of the worker is a display problem; a killed import is not. So a
        # failed beat is swallowed rather than raised, and repeats are throttled because
        # the idle loop wakes every couple of seconds and each beat is a write transaction.
        moment = time.monotonic()
        if not force and now_state == last["state"] and current == last["current"] and moment - last["at"] < BEAT_EVERY:
            return
        last.update(at=moment, state=now_state, current=current)
        try:
            kb.heartbeat(host, pid, state=now_state, current=current,
                         processed=counter["processed"], started=started)
        except Exception:
            # 心跳写失败说明控制台看不到进度，不影响本次导入；下一次心跳会再次尝试。
            pass

    with process_lock(Config(kb.root)):
        kb.recover()
        beat("idle", force=True)
        try:
            failed = False
            while True:
                result = kb.process_one(on_start=lambda did: beat("busy", did))
                if result is None:
                    if once:
                        return 2 if failed else 0
                    beat("idle")
                    time.sleep(poll)
                elif result["status"] == "failed":
                    failed = True
                    counter["processed"] += 1
                    beat("idle")
                else:
                    counter["processed"] += 1
                    beat("idle")
        finally:
            # Normal exit and Ctrl+C both leave an honest "stopped" row: an idle worker
            # that vanished must not keep looking online for ninety seconds.
            beat("stopped", force=True)
