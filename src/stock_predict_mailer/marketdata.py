"""Incremental self-collected market data: append-only merge plus a freshness gate.

The owner collects daily files; this module merges them into a **new** snapshot
instead of overwriting the previous one, so every training run keeps pointing at
the exact bytes it used. Three refusals are deliberate:

* a conflicting re-statement of a bar already in the base snapshot is rejected
  (silently preferring one version would rewrite history);
* a file that stops short of the cutoff by more than the allowed staleness is
  rejected unless the caller explicitly accepts a stale update;
* nothing here grants training rights - the snapshot still needs its own
  authorization record before any model may consume it.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from . import dataset_auth
from .core import Config, atomic_write, connect, digest, now, timestamp, write_json
from .data import FIELDS, load_snapshot, validate_rows

DEFAULT_MAX_STALENESS_DAYS = 5


def schema(con) -> None:
    con.executescript("""
      CREATE TABLE IF NOT EXISTS data_updates (
        update_id TEXT PRIMARY KEY, owner TEXT NOT NULL, base_snapshot TEXT,
        result_snapshot TEXT NOT NULL, files TEXT NOT NULL, latest_session TEXT NOT NULL,
        cutoff TEXT NOT NULL, stale_days INTEGER NOT NULL, verdict TEXT NOT NULL,
        created_at TEXT NOT NULL);
    """)


def _read_bars(path: Path) -> list[dict]:
    text = path.read_bytes().decode("utf-8-sig")
    return validate_rows(list(csv.DictReader(io.StringIO(text))))


def latest_snapshot(cfg: Config) -> str | None:
    root = cfg.workspace / "snapshots"
    if not root.is_dir():
        return None
    candidates = []
    for folder in root.iterdir():
        manifest = folder / "manifest.json"
        if not manifest.is_file():
            continue
        try:
            record = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        candidates.append((record.get("created_at", ""), folder.name))
    return max(candidates)[1] if candidates else None


def _bar_key(row: dict) -> tuple[str, str]:
    return (row["date"], row["security_id"])


def _same_bar(left: dict, right: dict) -> bool:
    return all(abs(float(left[field]) - float(right[field])) < 1e-9
               for field in ("open", "high", "low", "close", "volume"))


def freshness(cfg: Config, snapshot: str, cutoff: str, max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS) -> dict:
    """How far the newest bar sits behind the cutoff, in calendar days."""
    manifest, rows = load_snapshot(cfg, snapshot)
    if not rows:
        raise ValueError("snapshot has no bars")
    latest = max(row["date"] for row in rows)
    cutoff_date = timestamp(cutoff).astimezone(ZoneInfo(cfg.timezone)).date()
    stale_days = (cutoff_date - date.fromisoformat(latest)).days
    return {"snapshot_id": snapshot, "latest_session": latest, "data_start": manifest["start"],
            "cutoff_date": cutoff_date.isoformat(), "stale_days": stale_days,
            "max_staleness_days": max_staleness_days,
            "status": "fresh" if stale_days <= max_staleness_days else "stale"}


def _write_snapshot(cfg: Config, rows: list[dict], *, synthetic: bool, provenance: dict) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    identity = {"synthetic": synthetic, "rows": rows, "provenance": provenance}
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    snapshot = digest(canonical)
    folder = cfg.workspace / "snapshots" / snapshot
    manifest_path = folder / "manifest.json"
    exists = manifest_path.exists()
    if not exists:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        raw_bytes = stream.getvalue().encode("utf-8")
        atomic_write(folder / "source.csv", raw_bytes)
        buffer = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_pylist(rows), buffer)
        atomic_write(folder / "bars.parquet", buffer.getvalue().to_pybytes())
        manifest = {
            "snapshot_id": snapshot, "created_at": now(), "synthetic": synthetic,
            "row_count": len(rows), "security_count": len({row["security_id"] for row in rows}),
            "start": rows[0]["date"], "end": rows[-1]["date"],
            "raw_sha256": digest(raw_bytes),
            "parquet_sha256": digest((folder / "bars.parquet").read_bytes()),
            "sources": sorted({row["source"] for row in rows}),
            "provenance": provenance,
            "limitations": ["Incremental merge is append-only; corrections need a new snapshot",
                            "Availability stamps come from the owner's collector, not an exchange feed",
                            "No survivorship or universe certification"],
        }
        write_json(manifest_path, manifest)
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_auth.record_import(cfg, snapshot, synthetic=synthetic)
    return {**manifest, "reused": exists}


def update_bars(cfg: Config, paths: list[Path], *, base: str | None = None, cutoff: str,
                max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS, allow_stale: bool = False,
                synthetic: bool = False, market: str = "unknown") -> dict:
    if type(max_staleness_days) is not int or not 0 <= max_staleness_days <= 60:
        raise ValueError("max-staleness-days must be an integer in 0..60")
    timestamp(cutoff)
    base_snapshot = base or latest_snapshot(cfg)
    base_rows: list[dict] = []
    if base_snapshot:
        if not (cfg.workspace / "snapshots" / base_snapshot / "manifest.json").is_file():
            raise ValueError("base snapshot does not exist in this workspace")
        _, base_rows = load_snapshot(cfg, base_snapshot)
    incoming: dict[tuple[str, str], dict] = {}
    files = []
    for path in paths:
        rows = _read_bars(path)
        if incoming:
            collisions = {_bar_key(row) for row in rows} & set(incoming)
            if collisions:
                raise ValueError(f"the same update repeats a bar in more than one file: {sorted(collisions)[:3]}")
        for row in rows:
            incoming[_bar_key(row)] = row
        files.append({"name": path.name, "sha256": digest(path.read_bytes()), "rows": len(rows),
                      "start": rows[0]["date"], "end": rows[-1]["date"]})
    base_lookup = {_bar_key(row): row for row in base_rows}
    conflicts = [key for key, row in incoming.items()
                 if key in base_lookup and not _same_bar(base_lookup[key], row)]
    if conflicts:
        raise ValueError("incoming bars conflict with the base snapshot; a correction needs its own "
                         f"snapshot instead of a silent overwrite: {sorted(conflicts)[:3]}")
    added = [row for key, row in incoming.items() if key not in base_lookup]
    merged = sorted(base_rows + added, key=_bar_key)
    if not added:
        return {"status": "no_change", "base_snapshot": base_snapshot, "snapshot_id": base_snapshot,
                "added_rows": 0, "files": files,
                "message": "every incoming bar was already present with identical values"}
    latest = max(row["date"] for row in merged)
    cutoff_date = timestamp(cutoff).astimezone(ZoneInfo(cfg.timezone)).date()
    stale_days = (cutoff_date - date.fromisoformat(latest)).days
    if stale_days > max_staleness_days and not allow_stale:
        raise ValueError(f"collected data stops at {latest}, which is {stale_days} days before the cutoff; "
                         f"refresh the files or pass --allow-stale to record a knowingly stale update")
    verdict = "fresh" if stale_days <= max_staleness_days else "stale_accepted"
    provenance = {"update": {"base_snapshot": base_snapshot, "files": files, "market": market,
                             "cutoff": cutoff, "latest_session": latest, "stale_days": stale_days,
                             "verdict": verdict, "collector": cfg.principal},
                  "market": market, "price_basis": "unknown", "volume_unit": "shares"}
    manifest = _write_snapshot(cfg, merged, synthetic=synthetic, provenance=provenance)
    update_id = digest(json.dumps({"base": base_snapshot, "result": manifest["snapshot_id"],
                                   "files": [f["sha256"] for f in files]}, sort_keys=True).encode())
    stamp = now()
    with connect(cfg) as con:
        schema(con)
        con.execute("""INSERT OR REPLACE INTO data_updates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (update_id, cfg.principal, base_snapshot, manifest["snapshot_id"],
                     json.dumps(files, ensure_ascii=False), latest, cutoff, stale_days, verdict, stamp))
    return {"status": "created", "update_id": update_id, "base_snapshot": base_snapshot,
            "snapshot_id": manifest["snapshot_id"], "reused": manifest["reused"],
            "added_rows": len(added), "total_rows": len(merged), "latest_session": latest,
            "stale_days": stale_days, "verdict": verdict, "files": files,
            "authorization": dataset_auth.record(cfg, manifest["snapshot_id"]),
            "note": "the new snapshot is personal-training-only until its owner grants platform use"}


def update_history(cfg: Config) -> list[dict]:
    with connect(cfg) as con:
        schema(con)
        rows = con.execute("""SELECT update_id, base_snapshot, result_snapshot, latest_session, cutoff,
            stale_days, verdict, created_at FROM data_updates WHERE owner=? ORDER BY created_at DESC""",
                           (cfg.principal,)).fetchall()
    return [dict(row) for row in rows]
