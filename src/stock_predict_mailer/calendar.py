"""Certified exchange calendars and corporate actions for self-collected data.

Two separate governance objects, both owner-recorded:

* a *calendar* replaces the benchmark-observed session list, so a missing
  benchmark day is skipped instead of being compressed into a false adjacency;
* *corporate actions* adjust historical prices for splits and cash events, so a
  labelled open-to-open return is not silently broken by an ex-date.

Nothing here is authentication: ``principal`` stays a trusted local operator.
Certification is a local statement of provenance ("I imported this from X"), and
the record keeps the source string so a reviewer can re-check it.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date
from pathlib import Path

from .core import Config, connect, now

CALENDAR_FIELDS = ("date",)
ACTION_FIELDS = ("security_id", "ex_date", "kind", "price_factor")
ACTION_KINDS = ("split", "reverse_split", "cash_dividend", "spin_off")
BASES = ("unadjusted", "forward_adjusted", "backward_adjusted")
EPSILON = 1e-9


def schema(con) -> None:
    con.executescript("""
      CREATE TABLE IF NOT EXISTS exchange_calendars (
        market TEXT NOT NULL, session TEXT NOT NULL, source TEXT NOT NULL,
        certified_at TEXT NOT NULL, PRIMARY KEY (market, session));
      CREATE TABLE IF NOT EXISTS corporate_actions (
        security_id TEXT NOT NULL, ex_date TEXT NOT NULL, kind TEXT NOT NULL,
        price_factor REAL NOT NULL, source TEXT NOT NULL, recorded_at TEXT NOT NULL,
        PRIMARY KEY (security_id, ex_date, kind));
    """)


def _rows(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if reader.fieldnames is None:
        raise ValueError("empty CSV")
    return [dict(row) for row in reader]


def import_calendar(cfg: Config, path: Path, market: str, source: str = "owner-import") -> dict:
    """Record one certified trading-session list for a market.

    The import is additive and idempotent: re-importing the same file adds no
    duplicate sessions. A later import may extend the list but never silently
    removes sessions, because a shrinking calendar would rewrite history.
    """
    if not isinstance(market, str) or not market.strip() or len(market) > 100:
        raise ValueError("market must be a short nonempty string")
    if not isinstance(source, str) or not source.strip() or len(source) > 200:
        raise ValueError("calendar source is required so the certification can be re-checked")
    text = path.read_bytes().decode("utf-8-sig")
    records = _rows(text)
    if not records:
        raise ValueError("empty calendar file")
    header = set(records[0])
    field = "date" if "date" in header else "session" if "session" in header else None
    if field is None:
        raise ValueError("calendar needs a date or session column")
    sessions = []
    for record in records:
        value = (record.get(field) or "").strip()
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("calendar sessions must be YYYY-MM-DD")
        sessions.append(value)
    unique = sorted(set(sessions))
    stamp = now()
    with connect(cfg) as con:
        schema(con)
        before = {row["session"] for row in con.execute(
            "SELECT session FROM exchange_calendars WHERE market=?", (market,))}
        con.executemany("INSERT OR IGNORE INTO exchange_calendars VALUES (?, ?, ?, ?)",
                        [(market, session, source, stamp) for session in unique])
        after = {row["session"] for row in con.execute(
            "SELECT session FROM exchange_calendars WHERE market=?", (market,))}
    return {"market": market, "imported": len(unique), "added": len(after - before),
            "total_sessions": len(after), "start": min(after), "end": max(after),
            "source": source, "removed_by_this_import": sorted(before - after)}


def certified_sessions(cfg: Config, market: str) -> list[str] | None:
    """Certified sessions for a market, or None when the owner never imported one."""
    with connect(cfg) as con:
        schema(con)
        rows = con.execute("SELECT session FROM exchange_calendars WHERE market=? ORDER BY session",
                           (market,)).fetchall()
    return [row["session"] for row in rows] if rows else None


def calendar_status(cfg: Config, market: str) -> dict:
    sessions = certified_sessions(cfg, market)
    if sessions is None:
        return {"market": market, "certified": False,
                "note": "no certified calendar; the benchmark-observed session list is used instead"}
    return {"market": market, "certified": True, "sessions": len(sessions),
            "start": sessions[0], "end": sessions[-1]}


def import_actions(cfg: Config, path: Path, source: str = "owner-import") -> dict:
    """Record corporate actions as price factors applied to bars before the ex-date.

    ``price_factor`` multiplies historical prices; 2-for-1 split = 0.5, reverse
    split 1-for-2 = 2.0. Volume uses the inverse, so a volume ratio across the
    ex-date stays comparable.
    """
    text = path.read_bytes().decode("utf-8-sig")
    records = _rows(text)
    if not records:
        raise ValueError("empty corporate action file")
    if not set(ACTION_FIELDS) <= set(records[0]):
        raise ValueError(f"corporate actions need columns {', '.join(ACTION_FIELDS)}")
    stamp = now()
    clean = []
    for record in records:
        security = (record["security_id"] or "").strip()
        ex_date = (record["ex_date"] or "").strip()
        kind = (record["kind"] or "").strip()
        if not security:
            raise ValueError("corporate action needs a security_id")
        if date.fromisoformat(ex_date).isoformat() != ex_date:
            raise ValueError("ex_date must be YYYY-MM-DD")
        if kind not in ACTION_KINDS:
            raise ValueError(f"unsupported corporate action kind: {kind}")
        try:
            factor = float(record["price_factor"])
        except (TypeError, ValueError):
            raise ValueError("price_factor must be numeric") from None
        if not 0.001 <= factor <= 1000:
            raise ValueError("price_factor must be in 0.001..1000")
        clean.append((security, ex_date, kind, factor, source, stamp))
    with connect(cfg) as con:
        schema(con)
        con.executemany("INSERT OR REPLACE INTO corporate_actions VALUES (?, ?, ?, ?, ?, ?)", clean)
    return {"imported": len(clean), "securities": len({row[0] for row in clean}),
            "start": min(row[1] for row in clean), "end": max(row[1] for row in clean), "source": source}


def action_map(cfg: Config) -> dict[str, list[tuple[str, float]]]:
    """security -> [(ex_date, price_factor)] sorted by ex_date."""
    with connect(cfg) as con:
        schema(con)
        rows = con.execute("""SELECT security_id, ex_date, price_factor FROM corporate_actions
            ORDER BY security_id, ex_date""").fetchall()
    grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in rows:
        grouped[row["security_id"]].append((row["ex_date"], float(row["price_factor"])))
    return dict(grouped)


def adjust_rows(rows: list[dict], actions: dict[str, list[tuple[str, float]]], price_basis: str = "backward_adjusted") -> tuple[list[dict], dict]:
    """Apply cumulative corporate actions to a copy of the bars.

    Backward adjustment multiplies bars strictly before every ex-date, which keeps
    the most recent price untouched. Forward adjustment would instead divide the
    later bars; only ``unadjusted`` and the backward form are applied here, and an
    unsupported basis is rejected rather than silently approximated.
    """
    if price_basis not in BASES:
        raise ValueError("unsupported price basis")
    if price_basis == "unadjusted" or not actions:
        return rows, {"adjusted": False, "basis": price_basis, "actions_applied": 0}
    if price_basis == "forward_adjusted":
        raise ValueError("forward-adjusted prices are not produced locally; import backward-adjusted data or a factor file")
    adjusted, applied = [], 0
    for row in rows:
        events = actions.get(row["security_id"])
        factor = 1.0
        for ex_date, value in events or ():
            if row["date"] < ex_date:
                factor *= value
        if abs(factor - 1.0) < EPSILON:
            adjusted.append(row)
            continue
        copy = dict(row)
        for field in ("open", "high", "low", "close"):
            copy[field] = row[field] * factor
        copy["volume"] = row["volume"] / factor
        adjusted.append(copy)
        applied += 1
    return adjusted, {"adjusted": applied > 0, "basis": price_basis, "actions_applied": applied,
                      "securities_with_actions": len(actions)}


def market_context(cfg: Config, contract: dict) -> tuple[list[str] | None, dict | None]:
    """Certified sessions and corporate actions that apply to this contract.

    Returns ``(None, None)`` when the owner has imported neither, which keeps the
    synthetic/demo path exactly as it was before this module existed.
    """
    sessions = certified_sessions(cfg, contract["market"])
    actions = None
    if contract["price_basis"] != "unadjusted":
        actions = action_map(cfg) or None
    return sessions, actions
