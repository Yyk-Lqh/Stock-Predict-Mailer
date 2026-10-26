"""Retention policy for local model artifacts.

Deleting a model is the one irreversible operation in this project, so the policy
is deliberately conservative:

* a version the owner currently selected is never removed;
* a published version is never removed;
* a version another version was trained from (``parent_version``) or built on
  (``residual_of``) is never removed;
* the newest ``keep`` personal versions are kept regardless of the above;
* every removal is written to an audit table *before* the files disappear, and
  the default is a dry run.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .core import Config, connect, digest, now
from .model_registry import model_folder, personal_model_folder, selected_model

DEFAULT_KEEP = 5
MAX_KEEP = 200


def schema(con) -> None:
    con.executescript("""
      CREATE TABLE IF NOT EXISTS retention_actions (
        action_id TEXT PRIMARY KEY, owner TEXT NOT NULL, model_version TEXT NOT NULL,
        action TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
    """)


def _registry_rows(cfg: Config) -> list[dict]:
    with connect(cfg) as con:
        from .model_registry import schema as registry_schema

        registry_schema(con)
        return [dict(row) for row in con.execute(
            "SELECT version, owner, created_by, scope, origin, status, channel FROM registry_models")]


def _folder(cfg: Config, row: dict) -> Path:
    return model_folder(cfg, row["version"]) if row["scope"] == "platform" else personal_model_folder(cfg, row["owner"], row["version"])


def _manifest(cfg: Config, row: dict) -> dict | None:
    path = _folder(cfg, row) / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _dependencies(cfg: Config, rows: list[dict]) -> dict[str, list[str]]:
    """version -> owners that depend on it (as parent or residual base)."""
    depends: dict[str, list[str]] = {}
    for row in rows:
        manifest = _manifest(cfg, row)
        if not manifest:
            continue
        for key in ("parent_version", "residual_of"):
            base = manifest.get(key)
            if base and base != row["version"]:
                depends.setdefault(base, []).append(row["version"])
    return depends


def plan_retention(cfg: Config, keep: int = DEFAULT_KEEP) -> dict:
    if type(keep) is not int or not 0 <= keep <= MAX_KEEP:
        raise ValueError(f"keep must be an integer in 0..{MAX_KEEP}")
    rows = _registry_rows(cfg)
    depends = _dependencies(cfg, rows)
    selected = selected_model(cfg)
    protected, candidates = [], []
    for row in rows:
        if row["owner"] != cfg.principal and not row["created_by"] == cfg.principal:
            continue
        if row["scope"] == "platform" and row["status"] == "published":
            protected.append({"version": row["version"], "reason": "published versions are immutable"})
            continue
        if row["scope"] == "platform" and row["channel"]:
            protected.append({"version": row["version"], "reason": "channel versions are not collected"})
            continue
        if row["version"] == selected:
            protected.append({"version": row["version"], "reason": "currently selected by this owner"})
            continue
        if row["version"] in depends:
            protected.append({"version": row["version"], "reason": "required by " + ", ".join(sorted(depends[row["version"]]))})
            continue
        manifest = _manifest(cfg, row) or {}
        size = sum(path.stat().st_size for path in _folder(cfg, row).rglob("*") if path.is_file())
        candidates.append({"version": row["version"], "scope": row["scope"], "status": row["status"],
                           "created_at": manifest.get("created_at", ""), "bytes": size,
                           "algorithm": manifest.get("algorithm")})
    candidates.sort(key=lambda item: item["created_at"], reverse=True)
    retained = candidates[:keep]
    removable = candidates[keep:]
    return {"owner": cfg.principal, "keep": keep,
            "personal_versions": sum(1 for row in rows if row["scope"] == "personal" and row["owner"] == cfg.principal),
            "protected": protected, "retained_recent": [item["version"] for item in retained],
            "delete": removable, "reclaim_bytes": sum(item["bytes"] for item in removable),
            "dry_run": True,
            "note": "run with apply to delete; every removal is recorded in retention_actions first"}


def apply_retention(cfg: Config, plan: dict) -> dict:
    """Delete exactly the versions the plan listed, recording each removal first."""
    removable = plan.get("delete") or []
    if not removable:
        return {"deleted": [], "note": "nothing to delete"}
    stamp = now()
    deleted = []
    with connect(cfg) as con:
        schema(con)
        from .model_registry import schema as registry_schema

        registry_schema(con)
        con.execute("BEGIN IMMEDIATE")
        for item in removable:
            action_id = digest(f"{item['version']}|{stamp}".encode())
            con.execute("INSERT INTO retention_actions VALUES (?, ?, ?, 'delete', ?, ?)",
                        (action_id, cfg.principal, item["version"],
                         f"beyond keep={plan['keep']} and not selected, published or depended on", stamp))
        for item in removable:
            con.execute("DELETE FROM registry_models WHERE version=?", (item["version"],))
            deleted.append(item)
    for item in deleted:
        folder = (model_folder(cfg, item["version"]) if item["scope"] == "platform"
                  else personal_model_folder(cfg, cfg.principal, item["version"]))
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
    return {"deleted": [item["version"] for item in deleted], "keep": plan["keep"],
            "reclaimed_bytes": sum(item["bytes"] for item in deleted)}


def retention_log(cfg: Config) -> list[dict]:
    with connect(cfg) as con:
        schema(con)
        return [dict(row) for row in con.execute(
            "SELECT action_id, model_version, action, reason, created_at FROM retention_actions "
            "WHERE owner=? ORDER BY created_at DESC", (cfg.principal,))]
