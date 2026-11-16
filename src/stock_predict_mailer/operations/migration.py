"""Explicit backed-up, fenced, single-database transactional upgrades."""
import os
import re
import sqlite3
import time
from pathlib import Path

from ..agent_service.analysis import identity
from ..agent_service.contracts import ServiceError, utcnow
from . import backup
from . import backup_inventory as inv
from . import migration_preflight as preflight
from . import schema_planning as schema
from .schema_models import APPLICATION_ID, DATABASE_VERSION, classify


def fail(code, message):
    raise ServiceError(code, message)


def _delete_mode(root, relative):
    paths = schema._paths(root, relative)
    if paths is None:
        fail("MIGRATION_MISSING", "所选库不存在，不创建新库")
    path = root / relative
    if "wal" in paths or os.path.lexists(path.with_name(path.name + "-shm")):
        fail("MIGRATION_WAL_UNSUPPORTED", "首版只支持 DELETE 日志模式，不自动 checkpoint")
    with path.open("rb") as stream:
        header = stream.read(100)
    if len(header) != 100 or header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
        fail("MIGRATION_WAL_UNSUPPORTED", "来源不是可接受的 DELETE 日志数据库")
    info = path.stat()
    return info.st_dev, info.st_ino


def _connect(path):
    con = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=.2)
    try:
        con.execute("PRAGMA trusted_schema=OFF")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA synchronous=FULL")
        deadline = time.monotonic() + 10
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        return con
    except BaseException:
        con.close()
        raise


def _execute(con, operations):
    records = []
    for operation in operations:
        rows = 0
        for statement in operation["statements"]:
            rows += max(0, con.execute(statement).rowcount)
        records.append({"id": operation["id"], "data_rows_changed": rows})
    return records


def _validate(con, family):
    after = classify(con, family)
    if (after["state"] != "current" or con.execute("PRAGMA foreign_key_check").fetchone() is not None
            or con.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok"):
        fail("MIGRATION_TARGET", "事务内目标结构或完整性校验失败")
    return after


def _other_files(source, target):
    # Target pages/journal intentionally change inside its transaction. Never
    # open other databases; cooperative locks cover all existing business writers.
    for item in source["files"]:
        if inv.source_path(source, item) == target:
            continue
        if inv.fingerprint(inv.source_path(source, item)) != {k: item[k] for k in ("size", "sha256")}:
            fail("MIGRATION_SOURCE_CHANGED", "事务期间其他已知来源发生变化")


def apply(cfg, config_path, archive, expected_plan, expected_preflight, *, store,
          crawler_workspace=None, port=8767, key_env=None, accept_authorization_change=False):
    if not isinstance(store, str) or store not in schema.STORES or type(accept_authorization_change) is not bool:
        fail("INVALID_INPUT", "迁移必须选择单个已知库和有效授权确认标志")
    for value in (expected_plan, expected_preflight):
        if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value):
            fail("INVALID_INPUT", "迁移需要已审阅的结构与预检摘要")
    ready = preflight.check(cfg, config_path, archive, expected_plan, crawler_workspace=crawler_workspace, port=port, key_env=key_env)
    if not ready["ready"]:
        fail("MIGRATION_BLOCKED", "预检阻断，请重新运行 db preflight 核对原因")
    if ready["preflight_id"] != expected_preflight:
        fail("MIGRATION_PREFLIGHT_CHANGED", "认证包或预检摘要与已审阅值不同")
    planned = schema.plan(cfg, crawler_workspace=crawler_workspace)
    selected = next(d for d in planned["databases"] if d["store"] == store)
    if selected["state"] == "missing":
        fail("MIGRATION_MISSING", "所选库不存在，不创建新库")
    if any(op["requires_permission_review"] for op in selected["operations"]) and not accept_authorization_change:
        fail("MIGRATION_AUTHORIZATION_REVIEW", "所选升级改变历史回放权限，必须显式确认授权变化")
    root, relative = Path(selected["workspace"]), selected["file"]
    _delete_mode(root, relative)
    source = backup._scan(cfg, config_path, crawler_workspace, port)
    result = {"schema_version": "1", "mode": "single_store_migration", "store": store,
              "schema_plan_id": expected_plan, "preflight_id": expected_preflight, "archive_sha256": ready["archive_sha256"],
              "committed": False, "source_writes": 0, "services_started": 0, "operations": []}
    phase = {"commit_started": False, "committed": False}
    try:
        with inv.barriers(source):
            current = backup._scan(cfg, config_path, crawler_workspace, port)
            if current["plan_id"] != ready["backup_plan_id"]:
                fail("MIGRATION_SOURCE_CHANGED", "取得屏障后来源与预检不同")
            verified = backup.verify(archive, key_env=key_env)
            if (verified["archive_sha256"] != ready["archive_sha256"] or verified["plan_id"] != current["plan_id"]):
                fail("MIGRATION_PREFLIGHT_CHANGED", "加锁后备份发生变化")
            locked = schema.plan(cfg, crawler_workspace=crawler_workspace)
            if locked["plan_id"] != expected_plan:
                fail("MIGRATION_SOURCE_CHANGED", "取得屏障后结构计划变化")
            if backup._scan(cfg, config_path, crawler_workspace, port)["plan_id"] != current["plan_id"]:
                fail("MIGRATION_SOURCE_CHANGED", "验证期间来源发生变化")
            file_identity = _delete_mode(root, relative)
            if selected["version_source"] == "registered_and_structurally_verified":
                return {**result, "state": "already_current"}
            path = root / relative
            con = _connect(path)
            try:
                con.execute("BEGIN IMMEDIATE")
                fingerprint = schema._fingerprints(root, relative)
                before = classify(con, selected["family"])
                if (schema._source_id(root, relative, fingerprint) != selected["source_id"]
                        or before["schema_id"] != selected["schema_id"] or before["operations"] != selected["operations"]
                        or before["state"] not in ("current", "upgrade_available")):
                    fail("MIGRATION_SOURCE_CHANGED", "取得数据库写锁后来源变化")
                result["operations"] = _execute(con, selected["operations"])
                _validate(con, selected["family"])
                con.execute(f"PRAGMA application_id={APPLICATION_ID}")
                con.execute(f"PRAGMA user_version={DATABASE_VERSION}")
                after = _validate(con, selected["family"])
                if inv.linked(path) or (path.stat().st_dev, path.stat().st_ino) != file_identity:
                    fail("MIGRATION_SOURCE_CHANGED", "事务期间数据库路径或文件身份变化")
                _other_files(current, path)
                result.update(schema_before=before["schema_id"], schema_after=after["schema_id"],
                              application_id=APPLICATION_ID, user_version=DATABASE_VERSION)
                phase["commit_started"] = True
                con.commit()
                phase["committed"] = True
                result.update(committed=True, source_writes=1, state="migrated", completed_at=utcnow().isoformat())
                result["receipt_id"] = identity(result)
            finally:
                try:
                    if con.in_transaction:
                        con.rollback()
                finally:
                    con.close()
        return result
    except (ServiceError, OSError, sqlite3.Error) as exc:
        if phase["committed"]:
            fail("MIGRATION_COMMITTED_RECHECK_REQUIRED", "事务已提交但后续处理失败，请核对当前版本，不自动重试")
        if phase["commit_started"]:
            fail("MIGRATION_COMMIT_OUTCOME_UNKNOWN", "提交阶段异常，请核对版本和日志，不假定未修改或自动重试")
        code = exc.code if isinstance(exc, ServiceError) else "MIGRATION_DATABASE"
        fail(code, "迁移未完成，请核对计划与来源；不自动恢复或重试")
