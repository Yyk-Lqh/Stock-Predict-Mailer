"""Immutable daily-bar snapshots. This adapter is not a data license validator."""
from __future__ import annotations

import csv
import io
import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from .core import Config, atomic_write, digest, now, timestamp, write_json

FIELDS = ("date", "security_id", "open", "high", "low", "close", "volume", "available_at", "source")
NUMERIC = ("open", "high", "low", "close", "volume")


def validate_rows(rows: list[dict]) -> list[dict]:
    if not rows:
        raise ValueError("empty bar dataset")
    seen = set()
    clean = []
    for raw in rows:
        if not set(FIELDS) <= raw.keys():
            raise ValueError("missing required bar fields")
        row = {key: raw[key] for key in FIELDS}
        day = date.fromisoformat(str(row["date"]))
        if day.isoformat() != row["date"]:
            raise ValueError("date must be YYYY-MM-DD")
        if not row["security_id"] or not row["source"]:
            raise ValueError("security_id and source required")
        key = (row["date"], row["security_id"])
        if key in seen:
            raise ValueError(f"duplicate daily bar: {key}")
        seen.add(key)
        for field in NUMERIC:
            row[field] = float(row[field])
            if not math.isfinite(row[field]):
                raise ValueError("nonfinite bar")
        if min(row[k] for k in ("open", "high", "low", "close")) <= 0 or row["volume"] < 0:
            raise ValueError("nonpositive price or negative volume")
        if row["low"] > min(row["open"], row["close"]) or row["high"] < max(row["open"], row["close"]) or row["low"] > row["high"]:
            raise ValueError("inconsistent OHLC")
        available = timestamp(str(row["available_at"]))
        if available.date() < day:
            raise ValueError("bar cannot be available before its trading date")
        row["available_at"] = available.isoformat()
        clean.append(row)
    return sorted(clean, key=lambda row: (row["date"], row["security_id"]))


def asof_rows(rows: list[dict], cutoff: str) -> list[dict]:
    instant = timestamp(cutoff)
    return [row for row in rows if timestamp(row["available_at"]) <= instant and date.fromisoformat(row["date"]) <= instant.date()]


def import_csv(cfg: Config, path: Path, *, synthetic: bool = False, provenance: dict | None = None) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    raw_bytes = path.read_bytes()
    rows = validate_rows(list(csv.DictReader(io.StringIO(raw_bytes.decode("utf-8-sig")))))
    identity = {"synthetic": synthetic, "rows": rows}
    if provenance is not None:
        identity["provenance"] = provenance
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    snapshot = digest(canonical)
    folder = cfg.workspace / "snapshots" / snapshot
    manifest_path = folder / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    atomic_write(folder / "source.csv", raw_bytes)
    stream = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(rows), stream)
    atomic_write(folder / "bars.parquet", stream.getvalue().to_pybytes())
    manifest = {
        "snapshot_id": snapshot, "created_at": now(), "synthetic": synthetic,
        "row_count": len(rows), "security_count": len({r["security_id"] for r in rows}),
        "start": rows[0]["date"], "end": rows[-1]["date"],
        "raw_sha256": digest(raw_bytes), "parquet_sha256": digest((folder / "bars.parquet").read_bytes()),
        "sources": sorted({r["source"] for r in rows}),
        "limitations": ["CSV availability is supplied by importer, not independently verified", "No corporate action or survivorship certification"],
    }
    if provenance is not None:
        manifest["provenance"] = provenance
    write_json(manifest_path, manifest)  # completion marker written last
    return manifest


def load_snapshot(cfg: Config, snapshot: str) -> tuple[dict, list[dict]]:
    import pyarrow.parquet as pq

    if len(snapshot) != 64 or any(c not in "0123456789abcdef" for c in snapshot):
        raise ValueError("invalid snapshot id")
    folder = cfg.workspace / "snapshots" / snapshot
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    parquet = folder / "bars.parquet"
    if digest(parquet.read_bytes()) != manifest["parquet_sha256"]:
        raise ValueError("snapshot integrity check failed")
    return manifest, pq.read_table(parquet).to_pylist()


def snapshot_summary(cfg: Config, snapshot: str) -> dict:
    import duckdb

    manifest, _ = load_snapshot(cfg, snapshot)
    with duckdb.connect() as con:
        count, first, last = con.execute("SELECT count(*), min(date), max(date) FROM read_parquet(?)", [str(cfg.workspace / "snapshots" / snapshot / "bars.parquet")]).fetchone()
    return {**manifest, "duckdb_count": count, "first": first, "last": last}


def demo_csv(path: Path, days: int = 900, stocks: int = 16) -> Path:
    if not 80 <= days <= 3000 or not 6 <= stocks <= 100:
        raise ValueError("demo requires 80..3000 weekdays and 6..100 securities")
    rng = random.Random(20261024)
    prices = [20.0 + i for i in range(stocks)]
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=FIELDS)
    writer.writeheader()
    day = date(2020, 1, 2)
    completed = 0
    while completed < days:
        if day.weekday() < 5:
            common = rng.gauss(0, 0.006)
            for i in range(stocks):
                opening = prices[i] * math.exp(rng.gauss(0, 0.003))
                close = opening * math.exp(common + rng.gauss(0, 0.012))
                writer.writerow({"date": day.isoformat(), "security_id": f"SYN{i:03}",
                    "open": opening, "high": max(opening, close) * 1.01,
                    "low": min(opening, close) * 0.99, "close": close,
                    "volume": rng.randint(10000, 1000000),
                    "available_at": f"{day.isoformat()}T18:00:00+08:00", "source": "synthetic"})
                prices[i] = close
            completed += 1
        day += timedelta(days=1)
    atomic_write(path, text.getvalue().encode("utf-8"))
    return path
