"""Bounded source inventory and isolated SQLite/WAL normalization."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import stat
import tempfile
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath

from cryptography.fernet import Fernet, InvalidToken

from ..agent_service.analysis import identity
from ..agent_service.contracts import ServiceError
from ..core import Config
from ..delivery import process_lock
from ..naming import env
from .components import directory, status
from .probes import ProbeError, contained, lock_state, port_state

MAX_FILES = 10000
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
DB_SUFFIXES = {".sqlite3", ".sqlite", ".db"}
EXCLUDED_DIRS = {".runtime", "logs", "backups", ".git", ".venv", ".uv-cache", "__pycache__"}


def fail(code, message):
    raise ServiceError(code, message)


def safe_name(value):
    if not isinstance(value, str) or len(value) > 500 or "\\" in value or ":" in value or "\x00" in value:
        fail("BACKUP_PATH", "备份包含不安全的文件名")
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) < 2 or len(path.parts) > 32 or path.parts[0] not in ("app", "crawler", "reference") or path.as_posix() != value:
        fail("BACKUP_PATH", "备份路径不在允许范围内")
    reserved = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}
    if any(p in (".", "..") or p.endswith((".", " ")) or p.split(".")[0].upper() in reserved or any(ord(c) < 32 for c in p) for p in path.parts):
        fail("BACKUP_PATH", "备份文件名不适合安全恢复")
    return path


def linked(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def fingerprint(path):
    if linked(path) or not path.is_file():
        fail("BACKUP_PATH", "备份不跟随符号链接、重解析点或特殊文件")
    before = path.stat()
    if before.st_size > MAX_FILE:
        fail("BACKUP_LIMIT", "文件超过 64 MiB 上限")
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            if count > MAX_FILE:
                fail("BACKUP_LIMIT", "读取文件时超过大小上限")
            digest.update(chunk)
    after = path.stat()
    if count != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        fail("BACKUP_SOURCE_CHANGED", "扫描期间来源文件发生变化")
    return {"size": count, "sha256": digest.hexdigest()}


def excluded(name):
    name = name.casefold()
    return (name in ("pipeline.lock", ".crawler.lock") or name.startswith((".pending-", ".backup-", ".restore-"))
            or name.endswith(("-shm", ".log", ".pyc", ".spmbak")))


def inventory(app, crawler, config, port):
    app, crawler, config = Path(app).resolve(), Path(crawler).resolve(), Path(config).resolve()
    if any(str(root).startswith(("\\\\", "//")) or any(ord(c) < 32 for c in str(root)) for root in (app, crawler)):
        fail("BACKUP_SCOPE", "本批仅支持本机正常路径，不跟随网络共享")
    if app == crawler or app.is_relative_to(crawler) or crawler.is_relative_to(app):
        fail("BACKUP_SCOPE", "应用与采集工作区必须分离且不能互相包含")
    if not app.is_dir() or (crawler.exists() and not crawler.is_dir()):
        fail("BACKUP_SOURCE", "应用工作区必须存在，采集工作区若存在必须为目录")
    if type(port) is not int or not 1 <= port <= 65535:
        fail("INVALID_INPUT", "控制台端口须为 1 至 65535")
    entries = []
    for scope, root in (("app", app), ("crawler", crawler)):
        if not root.exists():
            continue
        for parent, dirs, files in os.walk(root, followlinks=False):
            parent = Path(parent)
            dirs[:] = sorted(d for d in dirs if d.casefold() not in EXCLUDED_DIRS and not d.casefold().startswith((".backup-", ".restore-")))
            for name in dirs:
                if linked(parent / name):
                    fail("BACKUP_PATH", "工作区目录包含链接或重解析点")
            for name in sorted(files):
                if excluded(name):
                    continue
                path = parent / name
                relative = scope + "/" + path.relative_to(root).as_posix()
                safe_name(relative)
                kind = "database" if path.suffix.lower() in DB_SUFFIXES else "wal" if name.endswith("-wal") else "file"
                if name.endswith("-journal"):
                    fail("BACKUP_JOURNAL", "发现回滚日志，先单独核对写入者和数据库状态")
                entries.append({"path": relative, "kind": kind, **fingerprint(path)})
                if len(entries) > MAX_FILES:
                    fail("BACKUP_LIMIT", "文件数量超过 10000 上限")
    entries.append({"path": "reference/original-agent.toml", "kind": "file", **fingerprint(config)})
    entries.sort(key=lambda item: item["path"])
    names = {item["path"] for item in entries}
    if len({name.casefold() for name in names}) != len(entries):
        fail("BACKUP_PATH", "备份文件名发生大小写冲突")
    if len(entries) > MAX_FILES or sum(item["size"] for item in entries) > MAX_TOTAL:
        fail("BACKUP_LIMIT", "备份总量超过 128 MiB 或文件数量上限")
    databases = {item["path"] for item in entries if item["kind"] == "database"}
    if any(item["kind"] == "wal" and item["path"][:-4] not in databases for item in entries):
        fail("BACKUP_WAL", "发现缺少主数据库的 WAL 文件")
    body = {"schema_version": "1", "origins": {"app": str(app), "crawler": str(crawler)}, "crawler_exists": crawler.exists(),
            "config_path": str(config), "console_port": port, "files": entries}
    return dict(body, plan_id=identity(body))


def source_path(plan, item):
    if item["path"].startswith("reference/"):
        return Path(plan["config_path"])
    scope, relative = item["path"].split("/", 1)
    root = Path(plan["origins"][scope])
    path = root / relative
    try:
        contained(root, path)
    except ProbeError:
        fail("BACKUP_PATH", "来源路径已变化或越界")
    return path


def quiescence(plan):
    app, crawler = (Path(plan["origins"][name]) for name in ("app", "crawler"))
    blockers = []
    for component, root in (("console", app), ("knowledge_worker", app), ("crawler_worker", crawler)):
        view = status(root, component)
        if view["state"] not in ("not_registered", "stopped", "failed", "dead") or view["lock"] not in ("absent", "available"):
            blockers.append({"code": "BACKUP_COMPONENT_ACTIVE", "component": component, "state": view["state"]})
    for root, relative in ((app, "pipeline.lock"), (app, "private-knowledge/pipeline.lock"), (crawler, "data/.crawler.lock")):
        if lock_state(root, relative) not in ("absent", "available"):
            blockers.append({"code": "BACKUP_WRITER_BUSY"})
    if port_state(plan["console_port"]) != "available":
        blockers.append({"code": "BACKUP_PORT_UNAVAILABLE"})
    return blockers


@contextmanager
def barriers(plan):
    from mcp_server.quality import DataQualityError
    from mcp_server.runtime import workspace_lock
    app, crawler = (Path(plan["origins"][name]) for name in ("app", "crawler"))
    with ExitStack() as stack:
        try:
            for component, root in (("console", app), ("knowledge_worker", app), ("crawler_worker", crawler)):
                if not root.exists():
                    continue
                folder = directory(root, component)
                stack.enter_context(process_lock(Config(folder / "launch")))
                stack.enter_context(process_lock(Config(folder)))
            for root in (app, app / "private-knowledge"):
                contained(app, root / "pipeline.lock")
                stack.enter_context(process_lock(Config(root)))
            if crawler.exists():
                contained(crawler, crawler / "data" / ".crawler.lock")
                stack.enter_context(workspace_lock(crawler / "data"))
            if port_state(plan["console_port"]) != "available":
                fail("BACKUP_WRITER_BUSY", "控制台端口在加锁后不可用")
            yield
        except (RuntimeError, DataQualityError):
            fail("BACKUP_WRITER_BUSY", "来源存在运行者或另一个备份操作")


def copy_sources(plan, target):
    for item in plan["files"]:
        source = source_path(plan, item)
        if fingerprint(source) != {k: item[k] for k in ("size", "sha256")}:
            fail("BACKUP_SOURCE_CHANGED", "来源内容与审阅清单不同")
        path = target / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
        if fingerprint(path) != {k: item[k] for k in ("size", "sha256")}:
            fail("BACKUP_SOURCE_CHANGED", "复制期间来源内容发生变化")


def connect(path, readonly=False):
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.2) if readonly else sqlite3.connect(path, timeout=.2)
    try:
        con.execute("PRAGMA trusted_schema=OFF")
        deadline = time.monotonic() + 10
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        return con
    except BaseException:
        con.close()
        raise


def normalize(root, files):
    with tempfile.TemporaryDirectory(prefix=".normalize-", dir=root) as folder:
        _normalize(root, files, Path(folder))


def _normalize(root, files, scratch):
    for item in files:
        if item["kind"] != "database":
            continue
        path = root / item["path"]
        output = scratch / "snapshot.sqlite3"
        source, target = None, None
        try:
            source = connect(path, True)
            target = connect(output)
            deadline = time.monotonic() + 10
            def progress(*args, deadline=deadline):
                if time.monotonic() > deadline:
                    fail("BACKUP_LIMIT", "数据库快照超过查询预算")
            source.backup(target, pages=128, progress=progress, sleep=.05)
            target.execute("PRAGMA journal_mode=DELETE")
            if target.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                fail("BACKUP_DATABASE", "数据库快照完整性检查失败")
        except sqlite3.Error:
            fail("BACKUP_DATABASE", "无法在隔离目录完成数据库/WAL 快照")
        finally:
            if source is not None:
                source.close()
            if target is not None:
                target.close()
        for suffix in ("-wal", "-shm"):
            path.with_name(path.name + suffix).unlink(missing_ok=True)
        os.replace(output, path)


def validate_vaults(root):
    result = {}
    for filename, development in (("control.sqlite3", False), ("control-development.sqlite3", True)):
        path = root / "app" / filename
        if not path.exists():
            continue
        con = None
        try:
            key = (root / "app" / "control-development.key").read_bytes() if development else env("MASTER_KEY").encode()
            if len(key) > 128:
                raise ValueError()
            cipher = Fernet(key)
            con = connect(path, True)
            marker = con.execute("SELECT body FROM state WHERE id='vault_check'").fetchone()
            if not marker or not isinstance(marker[0], str) or len(marker[0]) > 4096 or cipher.decrypt(marker[0].encode()) != b"stock-control-v1":
                raise InvalidToken()
        except (OSError, ValueError, TypeError, InvalidToken, sqlite3.Error):
            fail("BACKUP_VAULT_KEY", "缺少或无法验证配套密钥；外部主密钥不会导出")
        finally:
            if con is not None:
                con.close()
        result["development" if development else "production"] = "paired_file" if development else "external_master_key_required"
    return result
