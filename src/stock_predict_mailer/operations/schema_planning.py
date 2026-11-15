"""Source-safe schema reports and migration rehearsal on disposable copies only."""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from ..agent_service.analysis import identity
from ..agent_service.contracts import ServiceError, utcnow
from ..naming import version
from . import backup_inventory as inv
from .lifecycle import selected_root
from .probes import ProbeError, contained
from .schema_models import catalogue, classify

STORES = {
    "mail": ("agent-mail.sqlite3", "mail"),
    "control": ("control.sqlite3", "control"),
    "development": ("control-development.sqlite3", "control"),
    "knowledge": ("private-knowledge/knowledge.sqlite3", "knowledge"),
    "legacy": ("state.sqlite3", "legacy"),
    "crawler": ("jobs/crawler-jobs.sqlite3", "crawler"),
}


def fail(code, message):
    raise ServiceError(code, message)


def _paths(root, relative):
    path = root / relative
    try:
        parents = [p for p in path.parents if p != root and p.is_relative_to(root)]
        for item in (*reversed(parents), path):
            if os.path.lexists(item) and inv.linked(item):
                fail("SCHEMA_PATH", "不跟随数据库文件或目录链接")
        contained(root, path)
    except ProbeError:
        fail("SCHEMA_PATH", "数据库路径越界或不可访问")
    if root.exists() and not root.is_dir():
        fail("SCHEMA_PATH", "工作区不是目录")
    if os.path.lexists(path.with_name(path.name + "-journal")):
        fail("SCHEMA_JOURNAL", "发现回滚日志，不猜测或恢复来源状态")
    if not path.exists():
        if os.path.lexists(path.with_name(path.name + "-wal")):
            fail("SCHEMA_WAL", "发现缺少主数据库的 WAL，不猜测或恢复来源状态")
        return None
    return {label: candidate for label, candidate in (("main", path), ("wal", path.with_name(path.name + "-wal"))) if os.path.lexists(candidate)}


def _fingerprints(root, relative):
    paths = _paths(root, relative)
    if paths is None:
        return None
    result = {}
    for label, path in paths.items():
        try:
            contained(root, path)
        except ProbeError:
            fail("SCHEMA_PATH", "数据库旁文件越界")
        try:
            result[label] = inv.fingerprint(path)
        except FileNotFoundError:
            fail("SCHEMA_SOURCE_CHANGED", "来源文件在扫描期间消失")
    if sum(item["size"] for item in result.values()) > inv.MAX_TOTAL:
        fail("SCHEMA_LIMIT", "数据库和 WAL 合计超过 128 MiB")
    return result


def _source_id(root, relative, fingerprints):
    return identity({"root": os.path.normcase(str(root)), "file": relative, "files": fingerprints})


@contextmanager
def snapshot(root, relative):
    before = _fingerprints(root, relative)
    if before is None:
        fail("SCHEMA_SOURCE_CHANGED", "来源数据库已不存在")
    with tempfile.TemporaryDirectory(prefix="stock-schema-") as temporary:
        folder = Path(temporary)
        for label, info in before.items():
            source = root / (relative + ("-wal" if label == "wal" else ""))
            target = folder / ("image.sqlite3" + ("-wal" if label == "wal" else ""))
            shutil.copyfile(source, target)
            if inv.fingerprint(target) != info:
                fail("SCHEMA_SOURCE_CHANGED", "复制期间来源发生变化")
        if _fingerprints(root, relative) != before:
            fail("SCHEMA_SOURCE_CHANGED", "复制期间来源集合或内容发生变化")
        inv.normalize(folder, [{"path": "image.sqlite3", "kind": "database"}])
        con = inv.connect(folder / "image.sqlite3")
        try:
            if con.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                fail("SCHEMA_DATABASE", "隔离副本完整性检查失败")
            yield con, _source_id(root, relative, before)
        finally:
            con.close()
        if _fingerprints(root, relative) != before:
            fail("SCHEMA_SOURCE_CHANGED", "检查或演练期间来源发生变化")


def _error_code(exc):
    if isinstance(exc, ServiceError):
        return {"BACKUP_LIMIT": "SCHEMA_LIMIT", "BACKUP_PATH": "SCHEMA_PATH", "BACKUP_SOURCE_CHANGED": "SCHEMA_SOURCE_CHANGED",
                "BACKUP_DATABASE": "SCHEMA_DATABASE"}.get(exc.code, exc.code)
    return "SCHEMA_DATABASE" if isinstance(exc, sqlite3.Error) else "SCHEMA_IO"


def _inspect(root, name):
    relative, family = STORES[name]
    result = {"store": name, "file": relative, "family": family, "workspace": str(root), "operations": [], "issues": []}
    try:
        if _paths(root, relative) is None:
            return dict(result, state="missing", version_source="not_initialized", source_id=None, schema_id=None)
        with snapshot(root, relative) as (con, source_id):
            result.update(classify(con, family), source_id=source_id)
        return result
    except (ServiceError, OSError, sqlite3.Error) as exc:
        return dict(result, state="blocked", operations=[], issues=[{"code": _error_code(exc)}], version_source="unverified", source_id=None, schema_id=None)


def _roots(cfg, crawler_workspace):
    return Path(cfg["workspace"]).resolve(), selected_root(cfg, "crawler_worker", crawler_workspace)


def report(cfg, *, crawler_workspace=None, store="all"):
    if store != "all" and store not in STORES:
        fail("INVALID_INPUT", "不支持该数据库标识")
    app, crawler = _roots(cfg, crawler_workspace)
    catalog = catalogue()
    names = list(STORES) if store == "all" else [store]
    databases = [_inspect(crawler if name == "crawler" else app, name) for name in names]
    blocked = any(item["state"] == "blocked" for item in databases)
    pending = sum(len(item["operations"]) for item in databases)
    state = "blocked" if blocked else "upgrade_available" if pending else "not_initialized" if all(item["state"] == "missing" for item in databases) else "current"
    return {"schema_version": "1", "app_version": version(), "catalogue_revision": catalog["catalogue_revision"], "catalogue_id": identity(catalog),
            "sqlite_version": sqlite3.sqlite_version, "generated_at": utcnow().isoformat(), "mode": "read_only_schema_report", "state": state,
            "ready": not blocked, "changes": pending, "databases": databases, "source_writes": 0,
            "limitations": ["版本为已知结构推断，未给来源写入版本标记。", "不验证业务正文或解密列；各库分别取副本，不保证跨库同一时点。",
                            "未知对象、约束/索引漂移或未登记版本会阻断；未使用的可选组不强制初始化。", "没有 apply 操作；实际迁移需要独立备份、停写和显式事务方案。"]}


def _plan_id(value):
    return identity({"app_version": value["app_version"], "catalogue_id": value["catalogue_id"], "sqlite_version": value["sqlite_version"],
        "databases": [{k: item.get(k) for k in ("store", "workspace", "file", "source_id", "schema_id", "state", "operations", "issues")}
                      for item in value["databases"]]})


def plan(cfg, *, crawler_workspace=None, store="all", rehearse=False, expected_plan=None):
    if type(rehearse) is not bool or (not rehearse and expected_plan is not None):
        fail("INVALID_INPUT", "expected-plan 仅用于隔离演练")
    value = report(cfg, crawler_workspace=crawler_workspace, store=store)
    value.update(mode="read_only_migration_plan", plan_id=_plan_id(value), ready_for_apply=False)
    value["requires_permission_review"] = any(op["requires_permission_review"] for db in value["databases"] for op in db["operations"])
    if not rehearse:
        return value
    if expected_plan is None:
        fail("INVALID_INPUT", "隔离演练需要已审阅的 expected-plan")
    if value["plan_id"] != expected_plan:
        fail("SCHEMA_PLAN_CHANGED", "来源、目录或引擎与已审阅计划不同")
    if not value["ready"]:
        fail("SCHEMA_BLOCKED", "存在未知或无法验证的数据库，不能演练")
    results = []
    for database in value["databases"]:
        if database["state"] == "missing":
            continue
        try:
            with snapshot(Path(database["workspace"]), database["file"]) as (con, source_id):
                if source_id != database["source_id"]:
                    fail("SCHEMA_PLAN_CHANGED", "进入演练前来源变化")
                con.execute("PRAGMA foreign_keys=ON")
                con.execute("BEGIN IMMEDIATE")
                operations = []
                try:
                    for operation in database["operations"]:
                        rows = 0
                        for sql in operation["statements"]:
                            cursor = con.execute(sql)
                            rows += max(0, cursor.rowcount)
                        operations.append({"id": operation["id"], "statements": len(operation["statements"]), "data_rows_changed": rows})
                    after = classify(con, database["family"])
                    if after["state"] != "current" or con.execute("PRAGMA foreign_key_check").fetchone() is not None or con.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                        fail("SCHEMA_REHEARSAL_FAILED", "副本升级后结构或完整性不符合目标")
                    results.append({"store": database["store"], "schema_before": database["schema_id"], "schema_after": after["schema_id"],
                                    "operations": operations, "committed": False, "target_verified": True})
                finally:
                    con.rollback()
        except (ServiceError, OSError, sqlite3.Error) as exc:
            fail(_error_code(exc), "隔离演练失败，来源未修改；请重新核对计划及数据")
    return {**value, "mode": "isolated_rehearsal", "rehearsal": results, "source_writes": 0, "services_started": 0}
