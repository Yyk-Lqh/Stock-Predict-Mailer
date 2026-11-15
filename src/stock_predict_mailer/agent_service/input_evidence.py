"""Content-addressed input evidence, shared by reports and mail validation."""
from __future__ import annotations

import json
import re

from ..core import atomic_write, digest
from .contracts import context, fail, keys


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        fail("输入证据必须为有限 JSON")


def fingerprint(value):
    return digest(canonical(value))


def freeze(predicted, collected, source):
    snapshot = {"schema_version": "1", "prediction": predicted, "context": collected, "source": source}
    return {"schema_version": "1", "snapshot_id": fingerprint(snapshot), "snapshot": snapshot}


def validate(evidence, predicted, facts, settings=None, *, full_context=None):
    from .crawler_context import context_from_source

    settings = settings or {}
    if len(canonical(evidence)) > 256 * 1024:
        fail("输入证据超过 256 KiB")
    keys(evidence, ("schema_version", "snapshot_id", "snapshot"))
    snapshot = evidence["snapshot"]
    keys(snapshot, ("schema_version", "prediction", "context", "source"))
    if (evidence["schema_version"] != "1" or snapshot["schema_version"] != "1"
            or not isinstance(evidence["snapshot_id"], str) or not re.fullmatch("[a-f0-9]{64}", evidence["snapshot_id"])
            or fingerprint(snapshot) != evidence["snapshot_id"] or snapshot["prediction"] != predicted):
        fail("输入快照摘要或预测绑定不匹配")
    original = context(snapshot["context"], predicted["subject"], max_age=settings.get("max_context_age_seconds", 86400))
    rebuilt = context_from_source(snapshot["source"], predicted["subject"])
    if original != rebuilt or (full_context is not None and original != full_context):
        fail("输入证据与上下文或来源字段不匹配")
    originals = {fact["id"]: fact for fact in original["facts"]}
    if any(originals.get(fact["id"]) != fact for fact in facts):
        fail("分析事实未绑定冻结输入")
    return evidence


def persist(workspace, evidence):
    payload = canonical(evidence)
    if fingerprint(evidence["snapshot"]) != evidence["snapshot_id"]:
        fail("输入快照摘要不匹配")
    target = workspace / "input-snapshots" / (evidence["snapshot_id"] + ".json")
    if target.exists():
        if target.read_bytes() != payload:
            fail("已归档的输入快照损坏，拒绝覆盖")
    else:
        atomic_write(target, payload)
    return target
