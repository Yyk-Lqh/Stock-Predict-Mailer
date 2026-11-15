"""Explicit SMTP delivery with conservative handling of ambiguous outcomes."""
from __future__ import annotations

import asyncio
import os
import re
import threading
from contextlib import contextmanager

from .core import Config

_owned_locks = set()


def _lock_owner(cfg):
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return os.getpid(), threading.get_ident(), id(task) if task else None, str(cfg.workspace.resolve()).casefold() if os.name == "nt" else str(cfg.workspace.resolve())


def lock_owned(cfg):
    return _lock_owner(cfg) in _owned_locks


def outbox_schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS outbox (
        id TEXT PRIMARY KEY, report_id TEXT NOT NULL, principal TEXT NOT NULL,
        recipient TEXT NOT NULL, sender TEXT NOT NULL, status TEXT NOT NULL,
        attempts INTEGER NOT NULL, next_attempt TEXT NOT NULL, updated_at TEXT NOT NULL,
        message_id TEXT NOT NULL, eml_sha256 TEXT NOT NULL, error TEXT)""")


def address(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value):
        raise ValueError("single plain email address required")
    return value


@contextmanager
def process_lock(cfg: Config):
    """OS releases advisory byte-range lock automatically on process death."""
    cfg.workspace.mkdir(parents=True, exist_ok=True)
    path = cfg.workspace / "pipeline.lock"
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("another pipeline or sender is running") from exc
        try:
            _owned_locks.add(_lock_owner(cfg))
            yield
        finally:
            _owned_locks.discard(_lock_owner(cfg))
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)


def enqueue(cfg: Config, report_id: str, recipient: str, sender: str = "research@example.invalid") -> dict:
    from .agent_service.contracts import ServiceError
    from .mail_core.legacy import enqueue as core_enqueue
    try:
        return core_enqueue(cfg, report_id, recipient, sender)
    except ServiceError as exc:
        raise ValueError(exc.message) from None


def outbox(cfg: Config) -> list[dict]:
    from .mail_core.legacy import listing
    return listing(cfg)


def deliver(cfg: Config, outbox_id: str, *, allow_synthetic: bool = False, allow_stale: bool = False, factory=None) -> str:
    from .agent_service.contracts import ServiceError
    from .mail_core.legacy import deliver as core_deliver
    try:
        return core_deliver(cfg, outbox_id, allow_synthetic, allow_stale, factory)
    except ServiceError as exc:
        raise ValueError(exc.message) from None
