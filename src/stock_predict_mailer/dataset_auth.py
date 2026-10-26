"""Snapshot ownership and usage authorization records.

A record states what an owner allows for one snapshot. It is a local governance
record, not authentication: the configured principal is a trusted local operator,
so a shared web entry still needs its own identity layer before relying on this.

Three purposes are tracked separately because they fail differently:

* ``personal_training`` - may this owner train a private version on it;
* ``platform_training`` - may the platform recipe consume it at all (defaults to
  denied for anything the owner imported);
* ``replay`` - may historical rows be re-run for drift or backtest diagnostics,
  where a revoked right must take effect immediately.
"""
from __future__ import annotations

from .core import Config, connect, now

PURPOSES = ("personal_training", "platform_training", "replay")


def schema(con) -> None:
    con.executescript("""
      CREATE TABLE IF NOT EXISTS dataset_authorizations (
        snapshot_id TEXT NOT NULL, owner TEXT NOT NULL,
        personal_training INTEGER NOT NULL, platform_training INTEGER NOT NULL,
        note TEXT NOT NULL DEFAULT '', recorded_at TEXT NOT NULL,
        PRIMARY KEY (snapshot_id, owner));
    """)
    # Databases created before replay rights existed gain the column in place; a
    # silent default keeps every existing grant unchanged.
    columns = {row[1] for row in con.execute("PRAGMA table_info(dataset_authorizations)")}
    if "replay_enabled" not in columns:
        con.execute("ALTER TABLE dataset_authorizations ADD COLUMN replay_enabled INTEGER NOT NULL DEFAULT 0")
        con.execute("UPDATE dataset_authorizations SET replay_enabled=1 WHERE platform_training=1")


def record(cfg: Config, snapshot: str, owner: str | None = None) -> dict | None:
    with connect(cfg) as con:
        schema(con)
        row = con.execute("SELECT * FROM dataset_authorizations WHERE snapshot_id=? AND owner=?",
                          (snapshot, owner or cfg.principal)).fetchone()
    return dict(row) if row is not None else None


def record_import(cfg: Config, snapshot: str, *, synthetic: bool) -> dict:
    """Bind a freshly imported snapshot to this identity.

    Platform-generated synthetic snapshots keep the platform-training allowance
    they always had; anything imported as user data is personal-only until the
    owner explicitly grants platform use.
    """
    existing = record(cfg, snapshot)
    if existing is not None:
        return existing
    return set_authorization(cfg, snapshot, personal=True, platform=bool(synthetic),
                             replay=bool(synthetic),
                             note="default recorded when the snapshot was created")


def set_authorization(cfg: Config, snapshot: str, *, personal: bool | None = None,
                      platform: bool | None = None, replay: bool | None = None,
                      note: str = "") -> dict:
    if not isinstance(note, str) or len(note) > 300:
        raise ValueError("authorization note must be text up to 300 characters")
    current = record(cfg, snapshot)
    personal_value = int(bool(personal)) if personal is not None else int(current["personal_training"]) if current else 1
    platform_value = int(bool(platform)) if platform is not None else int(current["platform_training"]) if current else 0
    replay_value = int(bool(replay)) if replay is not None else int(current["replay_enabled"]) if current else 0
    stamp = now()
    with connect(cfg) as con:
        schema(con)
        con.execute("""INSERT INTO dataset_authorizations
            (snapshot_id, owner, personal_training, platform_training, note, recorded_at, replay_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_id, owner) DO UPDATE SET
              personal_training=excluded.personal_training,
              platform_training=excluded.platform_training,
              replay_enabled=excluded.replay_enabled,
              note=excluded.note, recorded_at=excluded.recorded_at""",
                    (snapshot, cfg.principal, personal_value, platform_value, note or "owner recorded decision",
                     stamp, replay_value))
    return {"snapshot_id": snapshot, "owner": cfg.principal, "personal_training": bool(personal_value),
            "platform_training": bool(platform_value), "replay_enabled": bool(replay_value),
            "note": note or "owner recorded decision", "recorded_at": stamp}


def require(cfg: Config, snapshot: str, purpose: str = "personal_training", owner: str | None = None) -> dict:
    if purpose not in PURPOSES:
        raise ValueError("unsupported authorization purpose")
    row = record(cfg, snapshot, owner)
    if row is None:
        raise ValueError("snapshot has no owner authorization record; import or authorize it first")
    column = "replay_enabled" if purpose == "replay" else purpose
    if not row[column]:
        raise ValueError(f"snapshot is not authorized for {purpose} by its owner")
    return row


def platform_denied(cfg: Config, snapshot: str) -> str | None:
    """Return the owner that refused platform training, if any such record exists."""
    with connect(cfg) as con:
        schema(con)
        row = con.execute("""SELECT owner FROM dataset_authorizations
            WHERE snapshot_id=? AND platform_training=0 ORDER BY owner LIMIT 1""", (snapshot,)).fetchone()
    return row["owner"] if row is not None else None


def describe(cfg: Config, snapshot: str) -> dict:
    return {"snapshot_id": snapshot, "owner": cfg.principal, "authorization": record(cfg, snapshot)}
