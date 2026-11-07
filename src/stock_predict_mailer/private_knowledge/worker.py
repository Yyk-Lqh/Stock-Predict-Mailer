"""Independent import service with an OS lock and durable checkpoints."""
from __future__ import annotations

import math
import time

from ..agent_service.contracts import ServiceError
from ..core import Config
from ..delivery import process_lock
from .service import Knowledge


def run(root, *, once=False, poll=2):
    from ..control.memory import Memory
    from ..control.store import Store

    if not math.isfinite(poll) or not .1 <= poll <= 60:
        raise ServiceError("INVALID_INPUT", "poll 须为 .1 至 60 秒")
    store = Store(root)
    Memory(store)
    kb = Knowledge(store)
    with process_lock(Config(kb.root)):
        kb.recover()
        failed = False
        while True:
            result = kb.process_one()
            if result is None:
                if once:
                    return 2 if failed else 0
                time.sleep(poll)
            elif result["status"] == "failed":
                failed = True
