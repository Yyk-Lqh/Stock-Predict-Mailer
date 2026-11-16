"""Read-only migration prerequisites, binding a verified backup to current sources."""
import re

from ..agent_service.analysis import identity
from ..agent_service.contracts import ServiceError, utcnow
from . import backup
from . import backup_inventory as inv
from . import schema_planning as schema


def check(cfg, config_path, archive, expected_plan, *, crawler_workspace=None, port=8767, key_env=None):
    if not isinstance(expected_plan, str) or not re.fullmatch("[a-f0-9]{64}", expected_plan):
        raise ServiceError("INVALID_INPUT", "迁移检查需要已审阅的结构 expected-plan")
    result = {"schema_version": "1", "generated_at": utcnow().isoformat(), "mode": "read_only_migration_preflight",
              "ready": False, "ready_for_apply": False, "state": "blocked", "backup_verified": False,
              "blockers": [], "source_writes": 0, "services_started": 0,
              "limitations": ["检查不持有停写屏障，成功仅代表检查时点；实际迁移必须重新加锁和重验。",
                              "本检查不执行迁移或写版本；db migrate 须重新取得屏障并校验，不保证跨库原子恢复。"]}
    try:
        source = backup._scan(cfg, config_path, crawler_workspace, port)
        planned = schema.plan(cfg, crawler_workspace=crawler_workspace)
        result.update(schema_plan_id=planned["plan_id"], backup_plan_id=source["plan_id"], changes=planned["changes"],
                      requires_permission_review=planned["requires_permission_review"])
        if planned["plan_id"] != expected_plan:
            result["blockers"].append({"code": "SCHEMA_PLAN_CHANGED"})
        if not planned["ready"]:
            result["blockers"].append({"code": "SCHEMA_BLOCKED"})
        result["blockers"].extend(inv.quiescence(source))
        # Avoid decrypting user data when cheap prerequisites already block.
        if result["blockers"]:
            return result
        verified = backup.verify(archive, key_env=key_env)
        result.update(archive_sha256=verified["archive_sha256"], backup_verified=True)
        if verified["plan_id"] != source["plan_id"]:
            result["blockers"].append({"code": "MIGRATION_BACKUP_MISMATCH"})
        after = backup._scan(cfg, config_path, crawler_workspace, port)
        if after["plan_id"] != source["plan_id"]:
            result["blockers"].append({"code": "MIGRATION_SOURCE_CHANGED"})
        result["blockers"].extend(inv.quiescence(after))
        if not result["blockers"]:
            result.update(ready=True, state="upgrade_preconditions_met" if planned["changes"] else "no_changes")
            result["preflight_id"] = identity({"schema_plan_id": planned["plan_id"], "backup_plan_id": source["plan_id"],
                                               "archive_sha256": verified["archive_sha256"]})
    except (ServiceError, OSError) as exc:
        result["blockers"].append({"code": exc.code if isinstance(exc, ServiceError) else "MIGRATION_IO"})
    return result
