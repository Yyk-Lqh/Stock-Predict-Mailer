"""Bounded, read-only queries for workflow database nodes."""

import os
import sqlite3
import stat
from collections import deque
from contextlib import closing, contextmanager
from pathlib import Path
from time import monotonic

from ..agent_service.contracts import ServiceError, utcnow

SOURCES = {"tasks": "项目任务库", "sqlite": "本机 SQLite 文件"}
QUERIES = {"completed": "已完成分析", "archived": "已归档预测的分析"}
SCOPES = {"subject": "当前预测标的", "accessible": "全部可访问标的"}
DEFAULTS = {"query": "completed", "scope": "subject", "limit": 10, "include_fact": False}
MAX_RESULTS = 30
FIELDS = {*DEFAULTS, "source", "path", "table", "symbol_column"}
_SUFFIXES = {".db", ".db3", ".sqlite", ".sqlite3", ".s3db", ".sl3", ".sql"}
_VAULTS = {"control.sqlite3", "control-development.sqlite3"}
_SKIP_DIRS = {"node_modules", "__pycache__", "private-knowledge"}
_DISK_SYSTEM_DIRS = {"windows", "program files", "program files (x86)", "programdata", "system volume information", "$recycle.bin"}
_MAX_FILES = 100


def options():
    return {"sources": SOURCES, "queries": QUERIES, "scopes": SCOPES, "defaults": DEFAULTS, "max_results": MAX_RESULTS}


def _name(value):
    return isinstance(value, str) and 1 <= len(value) <= 128 and all(ord(c) >= 32 and ord(c) != 127 for c in value)


def config_for(config, store, *, enabled):
    source = config.get("source", "tasks")
    limit = config.get("limit", DEFAULTS["limit"])
    include_fact = config.get("include_fact", False)
    if (source not in tuple(SOURCES) or type(limit) is not int or not 1 <= limit <= MAX_RESULTS
            or type(include_fact) is not bool):
        raise ServiceError("INVALID_WORKFLOW", "请选择有效的数据库来源和 1 至 30 条返回上限")
    if source == "tasks":
        values = {**DEFAULTS, **config}
        if (set(config) - {*DEFAULTS, "source"} or values["query"] not in tuple(QUERIES)
                or values["scope"] not in tuple(SCOPES)):
            raise ServiceError("INVALID_WORKFLOW", "请选择项目任务库支持的查询和标的范围")
        return values
    if set(config) - {"source", "path", "table", "symbol_column", "limit", "include_fact"}:
        raise ServiceError("INVALID_WORKFLOW", "本机 SQLite 配置含有不适用的选项")
    path, table, column = (config.get(key, "") for key in ("path", "table", "symbol_column"))
    if not enabled and not path and not table and not column:
        return {"source": source, "limit": limit, "include_fact": include_fact}
    if not _name(table) or (column != "" and not _name(column)):
        raise ServiceError("INVALID_WORKFLOW", "请填写有效的数据表和可选的标的列")
    database = _path(store, path)
    if enabled:
        with _connect(database) as con:
            _check_table(con, table, column)
    return {"source": source, "path": str(database), "table": table, "symbol_column": column,
            "limit": limit, "include_fact": include_fact}


def _path(store, raw):
    if not isinstance(raw, str) or not 1 <= len(raw) <= 1024 or any(ord(c) < 32 for c in raw):
        raise ServiceError("WORKFLOW_DATABASE", "请输入本机 SQLite 文件的绝对路径")
    candidate = Path(raw)
    if not candidate.is_absolute() or candidate.anchor.startswith(("//", "\\\\")):
        raise ServiceError("WORKFLOW_DATABASE", "请输入本机文件的绝对路径")
    try:
        path = candidate.resolve(strict=True)
        if path.anchor.startswith(("//", "\\\\")) or not path.is_file():
            raise OSError()
        for name in _VAULTS:
            vault = store.root / name
            if vault.is_file() and path.samefile(vault):
                raise ServiceError("PERMISSION_DENIED", "请选择业务数据库文件；项目任务请通过任务库选项查询")
        return path
    except (OSError, RuntimeError, ValueError):
        raise ServiceError("WORKFLOW_DATABASE", "找不到或无法访问该 SQLite 文件") from None


@contextmanager
def _connect(path):
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("PRAGMA trusted_schema=OFF")
            deadline = monotonic() + 2
            con.set_progress_handler(lambda: monotonic() > deadline, 10_000)
            yield con
    except sqlite3.Error:
        raise ServiceError("WORKFLOW_DATABASE", "无法读取 SQLite 数据库，请检查文件格式、访问权限及占用情况") from None


def _check_table(con, table, column):
    row = con.execute("SELECT 1 FROM pragma_table_list WHERE schema='main' AND type='table' "
                      "AND name=? AND substr(lower(name),1,7)<>'sqlite_'", (table,)).fetchone()
    if row is None:
        raise ServiceError("WORKFLOW_DATABASE", "找不到所选数据表")
    if column and not con.execute("SELECT 1 FROM pragma_table_xinfo(?, 'main') WHERE name=? AND hidden=0",
                                  (table, column)).fetchone():
        raise ServiceError("WORKFLOW_DATABASE", "所选表中找不到标的列")


def inspect(store, raw_path):
    with _connect(_path(store, raw_path)) as con:
        rows = con.execute("SELECT name FROM pragma_table_list WHERE schema='main' AND type='table' "
                           "AND substr(lower(name),1,7)<>'sqlite_' ORDER BY name LIMIT 201").fetchall()
    return {"tables": [name for (name,) in rows[:200] if _name(name)], "has_more": len(rows) > 200}


def _search_roots(store):
    home = Path.home()
    folders = {"Desktop": home / "Desktop", "Personal": home / "Documents",
               "{374DE290-123F-4565-9164-39C4925E467B}": home / "Downloads"}
    if os.name == "nt":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                for name in folders:
                    try:
                        raw, _ = winreg.QueryValueEx(key, name)
                        if isinstance(raw, str):
                            folders[name] = Path(os.path.expandvars(raw))
                    except OSError:
                        continue
        except OSError:
            pass
    return (store.root, Path.cwd(), *folders.values())


def _disk_roots():
    if os.name != "nt":
        return (Path.home(),)
    from ctypes import windll

    api = windll.kernel32
    mask = api.GetLogicalDrives()
    roots = [f"{chr(65 + index)}:\\" for index in range(26) if mask & (1 << index)]
    return tuple(Path(root) for root in roots if api.GetDriveTypeW(root) == 3)


def _scan_directory(raw):
    if not isinstance(raw, str) or not 1 <= len(raw) <= 1024 or any(ord(c) < 32 for c in raw):
        raise ServiceError("WORKFLOW_DATABASE", "请输入本机目录的绝对路径")
    path = Path(raw)
    if not path.is_absolute() or path.anchor.startswith(("//", "\\\\")):
        raise ServiceError("WORKFLOW_DATABASE", "请输入本机目录的绝对路径")
    try:
        if path.is_dir():
            resolved = path.resolve(strict=True)
            if not resolved.anchor.startswith(("//", "\\\\")):
                return resolved
    except (OSError, RuntimeError, ValueError):
        pass
    raise ServiceError("WORKFLOW_DATABASE", "找不到或无法访问该目录")


def discover(store, *, scope="common", directory=None):
    """Find candidates without opening SQLite connections or reading table data."""
    if scope == "common":
        roots, max_depth, seconds, max_entries = _search_roots(store), 3, 2, 12_000
    elif scope == "directory":
        roots, max_depth, seconds, max_entries = (_scan_directory(directory),), None, 6, 80_000
    elif scope == "disks":
        roots, max_depth, seconds, max_entries = _disk_roots(), None, 8, 100_000
    else:
        raise ServiceError("INVALID_INPUT", "无效的扫描范围")
    queue = deque((path, 0) for path in roots)
    visited, matches = set(), set()
    deadline, scanned = monotonic() + seconds, 0
    def at_limit():
        return monotonic() >= deadline or scanned >= max_entries or len(matches) >= _MAX_FILES

    while queue:
        folder, depth = queue.popleft()
        if at_limit():
            return _discovery_result(matches, True)
        try:
            if not folder.is_absolute() or folder.anchor.startswith(("//", "\\\\")) or (scope == "common" and folder == Path(folder.anchor)):
                continue
            info = folder.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                continue
            folder = folder.resolve(strict=True)
            if folder in visited or folder.anchor.startswith(("//", "\\\\")):
                continue
            visited.add(folder)
            with os.scandir(folder) as entries:
                for entry in entries:
                    if at_limit():
                        return _discovery_result(matches, True)
                    scanned += 1
                    if entry.name.startswith("."):
                        continue
                    candidate = Path(entry.path)
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                        if getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                            continue
                        skip = entry.name.casefold() in _SKIP_DIRS or (
                            scope == "disks" and depth == 0 and entry.name.casefold() in _DISK_SYSTEM_DIRS
                        )
                        if (max_depth is None or depth < max_depth) and stat.S_ISDIR(metadata.st_mode) and not skip:
                            queue.append((candidate, depth + 1))
                        elif (stat.S_ISREG(metadata.st_mode) and candidate.suffix.casefold() in _SUFFIXES
                              and entry.name.casefold() not in _VAULTS):
                            with candidate.open("rb") as stream:
                                if stream.read(16) == b"SQLite format 3\x00":
                                    matches.add(_path(store, str(candidate)))
                    except (OSError, ServiceError):
                        continue
        except (OSError, RuntimeError, ValueError):
            continue
    return _discovery_result(matches, False)


def _discovery_result(matches, truncated):
    paths = sorted(matches, key=lambda path: (path.name.casefold(), str(path).casefold()))
    return {"files": [{"name": path.name, "path": str(path)} for path in paths], "truncated": truncated}


def _identifier(name):
    return '"' + name.replace('"', '""') + '"'


def _local_query(store, request, config):
    table, column = config["table"], config["symbol_column"]
    subject = request["prediction"]["subject"] if column else None
    predicate = f" WHERE {_identifier(column)}=? COLLATE NOCASE" if column else ""
    args = (subject, config["limit"] + 1) if column else (config["limit"] + 1,)
    with _connect(_path(store, config["path"])) as con:
        _check_table(con, table, column)
        size = len(con.execute(f"SELECT 1 FROM main.{_identifier(table)}{predicate} LIMIT ?", args).fetchall())
    return {"source": "本机 SQLite 文件", "table": table, "symbol_column": column or None, "subject": subject,
            "queried_at": utcnow().isoformat(), "has_more": size > config["limit"], "row_count": min(size, config["limit"])}


def query(store, request, config):
    """Use the same owner boundary as the console task list."""
    if config.get("source") == "sqlite":
        return _local_query(store, request, config)
    subject = request["prediction"]["subject"] if config["scope"] == "subject" else None
    with store.db() as con:
        rows = con.execute(
            """
            SELECT t.id, json_extract(t.body,'$.metadata.request.subject'),
                   json_extract(t.body,'$.status.timestamp'),
                   json_extract(t.body,'$.metadata.request.synthetic'),
                   json_extract(t.body,'$.artifacts[0].parts[0].data.analysis.forecast_evidence.forecast_id')
            FROM tasks t LEFT JOIN memory_tasks m ON m.task=t.id
            WHERE (m.owner IS NULL OR m.owner=?)
              AND json_extract(t.body,'$.status.state')='completed'
              AND json_type(t.body,'$.artifacts[0].parts[0].data.analysis')='object'
              AND (? IS NULL OR json_extract(t.body,'$.metadata.request.subject')=? COLLATE NOCASE)
              AND (?=0 OR json_extract(t.body,'$.artifacts[0].parts[0].data.analysis.forecast_evidence.forecast_id') IS NOT NULL)
            ORDER BY t.rowid DESC LIMIT ?
            """,
            (request.get("_owner"), subject, subject, config["query"] == "archived", config["limit"] + 1),
        ).fetchall()
    return {
        "source": "本地 SQLite · 任务记录", "query": config["query"], "scope": config["scope"], "subject": subject,
        "queried_at": utcnow().isoformat(), "has_more": len(rows) > config["limit"], "row_count": min(len(rows), config["limit"]),
        "rows": [{"task_id": tid, "subject": symbol, "completed_at": finished,
                  "synthetic": bool(synthetic) if synthetic is not None else None, "forecast_id": forecast}
                 for tid, symbol, finished, synthetic, forecast in rows[:config["limit"]]],
    }
