from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import tomllib
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return result


@dataclass(frozen=True)
class Config:
    workspace: Path
    timezone: str = "Asia/Shanghai"
    horizon: int = 5
    top_k: int = 5
    cost_bps: float = 30
    principal: str = "owner"


def load_config(path: Path) -> Config:
    from zoneinfo import ZoneInfo

    path = path.resolve()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown = set(raw) - set(Config.__dataclass_fields__)
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")
    cfg = Config(**{**raw, "workspace": (path.parent / raw["workspace"]).resolve()})
    if type(cfg.horizon) is not int or cfg.horizon < 1:
        raise ValueError("horizon must be a positive integer")
    if type(cfg.top_k) is not int or cfg.top_k < 1:
        raise ValueError("top_k must be a positive integer")
    if not isinstance(cfg.cost_bps, (int, float)) or not 0 <= cfg.cost_bps <= 10000:
        raise ValueError("cost_bps must be between 0 and 10000")
    if not isinstance(cfg.principal, str) or not cfg.principal.strip():
        raise ValueError("principal cannot be empty")
    ZoneInfo(cfg.timezone)
    return cfg


@contextmanager
def connect(cfg: Config):
    cfg.workspace.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(cfg.workspace / "state.sqlite3", timeout=20)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("""CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, task TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, status TEXT NOT NULL, error TEXT)""")
        con.commit()
        with con:
            yield con
    finally:
        con.close()


@contextmanager
def tracked_run(cfg: Config, task: str):
    run_id = uuid.uuid4().hex
    with connect(cfg) as con:
        con.execute("INSERT INTO runs VALUES (?, ?, ?, NULL, 'running', NULL)", (run_id, task, now()))
    try:
        yield run_id
    except BaseException as exc:
        # Never persist exception text: upstream errors may contain credentials.
        with connect(cfg) as con:
            con.execute("UPDATE runs SET status='failed', finished_at=?, error=? WHERE id=?", (now(), type(exc).__name__, run_id))
        raise
    else:
        with connect(cfg) as con:
            con.execute("UPDATE runs SET status='succeeded', finished_at=? WHERE id=?", (now(), run_id))
