"""Shadow run records and stable release governance.

A prediction is only evidence if somebody wrote it down before the outcome was
known. ``record_shadow`` snapshots a prediction; ``evaluate_shadow`` scores it
once the labels mature; ``promote_stable`` refuses to run until a model has at
least ten matured shadow days, and every promotion is authorised, signed by a
reason, and revocable.

None of this makes a model "validated". It makes the claim auditable.
"""
from __future__ import annotations

import json

import numpy as np
from scipy.stats import rankdata

from . import dataset_auth
from .calendar import market_context
from .contracts import prepare_rows
from .core import Config, connect, now
from .data import load_snapshot
from .model_registry import get_model
from .prediction_report import load_prediction

MIN_SHADOW_DAYS = 10


def schema(con) -> None:
    con.executescript("""
      CREATE TABLE IF NOT EXISTS shadow_records (
        prediction_id TEXT PRIMARY KEY, owner TEXT NOT NULL, model_version TEXT NOT NULL,
        snapshot_id TEXT NOT NULL, prediction_date TEXT NOT NULL, payload TEXT NOT NULL,
        created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS shadow_outcomes (
        prediction_id TEXT PRIMARY KEY, owner TEXT NOT NULL, model_version TEXT NOT NULL,
        prediction_date TEXT NOT NULL, rank_ic REAL NOT NULL, securities INTEGER NOT NULL,
        evaluated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS stable_releases (
        version TEXT PRIMARY KEY, owner TEXT NOT NULL, authorized_at TEXT NOT NULL, note TEXT NOT NULL,
        revoked_at TEXT, revoke_reason TEXT);
    """)


def record_shadow(cfg: Config, prediction_id: str) -> dict:
    prediction = load_prediction(cfg, prediction_id)
    payload = {"predictions": prediction["predictions"], "cutoff": prediction["cutoff"],
               "data_date": prediction["data_date"], "synthetic": prediction["synthetic"]}
    if len(payload["predictions"]) < 3:
        raise ValueError("a shadow record needs at least three ranked securities to score later")
    stamp = now()
    with connect(cfg) as con:
        schema(con)
        con.execute("INSERT OR IGNORE INTO shadow_records VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (prediction_id, cfg.principal, prediction["model_version"], prediction["snapshot"],
                     prediction["data_date"], json.dumps(payload, sort_keys=True), stamp))
        row = con.execute("SELECT * FROM shadow_records WHERE prediction_id=? AND owner=?",
                          (prediction_id, cfg.principal)).fetchone()
    return dict(row)


def shadow_records(cfg: Config) -> list[dict]:
    with connect(cfg) as con:
        schema(con)
        rows = con.execute("""SELECT prediction_id, model_version, snapshot_id, prediction_date, created_at
            FROM shadow_records WHERE owner=? ORDER BY prediction_date""", (cfg.principal,)).fetchall()
    return [dict(row) for row in rows]


def evaluate_shadow(cfg: Config, cutoff: str | None = None) -> dict:
    """Score every matured shadow day; replay requires a current grant."""
    records = shadow_records(cfg)
    if not records:
        return {"evaluated": [], "skipped": [], "note": "no shadow records yet"}
    snapshots = {record["snapshot_id"] for record in records}
    for snapshot in snapshots:
        dataset_auth.require(cfg, snapshot, "replay")
    evaluated, skipped = [], []
    for record in records:
        with connect(cfg) as con:
            schema(con)
            done = con.execute("SELECT 1 FROM shadow_outcomes WHERE prediction_id=?",
                               (record["prediction_id"],)).fetchone()
        if done:
            continue
        model, _, _ = get_model(cfg, record["model_version"])
        data_manifest, raw = load_snapshot(cfg, record["snapshot_id"])
        sessions, actions = market_context(cfg, model["contract"])
        boundary = cutoff or f"{record['prediction_date']}T23:59:59+08:00"
        _, rows = prepare_rows(raw, model["contract"], boundary, sessions=sessions, actions=actions)
        rows = [row for row in rows if row["date"] == record["prediction_date"]]
        with connect(cfg) as con:
            schema(con)
            stored = con.execute("SELECT payload FROM shadow_records WHERE prediction_id=?",
                                 (record["prediction_id"],)).fetchone()
        predictions = json.loads(stored["payload"])["predictions"] if stored else []
        scores = {item["security_id"]: float(item["score"]) for item in predictions}
        pairs = [(scores[row["security_id"]], row["y"]) for row in rows if row["security_id"] in scores]
        if len(pairs) < 3:
            skipped.append({"prediction_id": record["prediction_id"], "reason": "labels are not matured yet"})
            continue
        predicted, target = np.array(pairs).T
        if np.std(predicted) <= 0 or np.std(target) <= 0:
            skipped.append({"prediction_id": record["prediction_id"], "reason": "degenerate cross-section"})
            continue
        ic = float(np.corrcoef(rankdata(predicted), rankdata(target))[0, 1])
        with connect(cfg) as con:
            schema(con)
            con.execute("INSERT OR REPLACE INTO shadow_outcomes VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (record["prediction_id"], cfg.principal, record["model_version"],
                         record["prediction_date"], ic, len(pairs), now()))
        evaluated.append({"prediction_id": record["prediction_id"], "prediction_date": record["prediction_date"],
                          "rank_ic": ic, "securities": len(pairs)})
    return {"evaluated": evaluated, "skipped": skipped}


def shadow_status(cfg: Config, model_version: str | None = None) -> dict:
    with connect(cfg) as con:
        schema(con)
        query = """SELECT prediction_date, rank_ic FROM shadow_outcomes WHERE owner=?"""
        args: tuple = (cfg.principal,)
        if model_version:
            query += " AND model_version=?"
            args = (*args, model_version)
        rows = [dict(row) for row in con.execute(query + " ORDER BY prediction_date", args)]
    if not rows:
        return {"model_version": model_version, "matured_days": 0, "mean_rank_ic": None,
                "ready_for_stable": False, "required_days": MIN_SHADOW_DAYS}
    values = [row["rank_ic"] for row in rows]
    return {"model_version": model_version, "matured_days": len(rows),
            "mean_rank_ic": float(np.mean(values)),
            "hit_rate": float(np.mean([value > 0 for value in values])),
            "start": rows[0]["prediction_date"], "end": rows[-1]["prediction_date"],
            "ready_for_stable": len(rows) >= MIN_SHADOW_DAYS, "required_days": MIN_SHADOW_DAYS,
            "note": "a positive mean Rank IC over a short shadow run is not evidence of profitability"}


def promote_stable(cfg: Config, model_version: str, *, authorize: bool = False, note: str = "") -> dict:
    if not authorize:
        raise ValueError("stable promotion requires an explicit authorisation")
    if not isinstance(note, str) or not note.strip() or len(note) > 300:
        raise ValueError("stable promotion requires a note recording who authorised it and why")
    status = shadow_status(cfg, model_version)
    if not status["ready_for_stable"]:
        raise ValueError(f"shadow run has only {status['matured_days']} matured days; "
                         f"at least {MIN_SHADOW_DAYS} are required before a stable release")
    manifest, _, _ = get_model(cfg, model_version)
    with connect(cfg) as con:
        schema(con)
        con.execute("""INSERT INTO stable_releases VALUES (?, ?, ?, ?, NULL, NULL)
            ON CONFLICT(version) DO UPDATE SET authorized_at=excluded.authorized_at, note=excluded.note,
              revoked_at=NULL, revoke_reason=NULL""",
                    (model_version, cfg.principal, now(), note))
    return {"version": model_version, "channel": "stable", "authorized": True, "note": note,
            "shadow": {"matured_days": status["matured_days"], "mean_rank_ic": status["mean_rank_ic"]},
            "synthetic": manifest.get("synthetic"), "auto_selected": False,
            "warning": "promotion records governance state only; it does not certify profitability"}


def revoke_stable(cfg: Config, model_version: str, reason: str = "") -> dict:
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
        raise ValueError("revocation requires a recorded reason")
    with connect(cfg) as con:
        schema(con)
        changed = con.execute("""UPDATE stable_releases SET revoked_at=?, revoke_reason=?
            WHERE version=? AND owner=? AND revoked_at IS NULL""",
                              (now(), reason, model_version, cfg.principal))
        row = con.execute("SELECT * FROM stable_releases WHERE version=? AND owner=?",
                          (model_version, cfg.principal)).fetchone()
    if row is None:
        raise ValueError("no stable release recorded for this version")
    return {"version": model_version, "revoked": changed.rowcount == 1, "release": dict(row)}


def release_status(cfg: Config) -> list[dict]:
    with connect(cfg) as con:
        schema(con)
        rows = con.execute("""SELECT version, authorized_at, note, revoked_at, revoke_reason
            FROM stable_releases WHERE owner=? ORDER BY authorized_at DESC""", (cfg.principal,)).fetchall()
    return [dict(row) for row in rows]


def is_stable_available(cfg: Config, model_version: str) -> bool:
    with connect(cfg) as con:
        schema(con)
        row = con.execute("""SELECT revoked_at FROM stable_releases WHERE version=? AND owner=?""",
                          (model_version, cfg.principal)).fetchone()
    return row is not None and row["revoked_at"] is None
