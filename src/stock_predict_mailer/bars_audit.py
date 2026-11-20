"""Facts about a collected bars file: what is missing, duplicated or unexplained.

The audit never asserts *why* a bar is absent. A gap can be a suspension, a
holiday the certified calendar does not know, or a failed collection; guessing
here would corrupt training data. It lists the fact and leaves the cause to a
human, and it separates hard errors (a bar known before its session closed, a
duplicate, a date off the calendar) from things worth a look.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, datetime, time
from pathlib import Path

from .calendar import action_map, certified_sessions
from .core import Config, timestamp

CLOSE = time(15, 0)
DEFAULT_THRESHOLD = 0.11
DEFAULT_LIMIT = 20
REQUIRED = {"date", "security_id", "open", "high", "low", "close", "volume", "available_at", "source"}


def _rows(path):
    text = Path(path).read_bytes().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or not REQUIRED <= set(reader.fieldnames):
        raise ValueError("CSV 缺少数据契约要求的字段")
    return list(reader)


def _parse(raw, bad, index):
    try:
        day = date.fromisoformat(str(raw["date"])[:10])
        available = timestamp(str(raw["available_at"]))
        close = float(raw["close"])
        if close <= 0 or not isinstance(raw["security_id"], str) or not raw["security_id"].strip():
            raise ValueError("bad row")
    except (KeyError, TypeError, ValueError):
        bad.append(index)
        return None
    return {"date": day, "security_id": raw["security_id"].strip(), "close": close, "available_at": available}


def audit(cfg: Config, path, *, market=None, threshold=DEFAULT_THRESHOLD, limit=DEFAULT_LIMIT):
    """Return a report; hard problems flip ``ok`` instead of raising."""
    raw_rows = _rows(path)
    bad, rows = [], []
    for index, raw in enumerate(raw_rows):
        parsed = _parse(raw, bad, index)
        if parsed is not None:
            rows.append(parsed)
    if not rows:
        raise ValueError("文件中没有可解析的日线")
    by_symbol = defaultdict(list)
    for row in rows:
        by_symbol[row["security_id"]].append(row)
    for symbol in by_symbol:
        by_symbol[symbol].sort(key=lambda item: item["date"])

    counts = defaultdict(int)
    for row in rows:
        counts[(row["security_id"], row["date"])] += 1
    duplicates = [{"security_id": symbol, "date": day.isoformat(), "count": count}
                  for (symbol, day), count in sorted(counts.items()) if count > 1]

    sessions = certified_sessions(cfg, market) if market else None
    calendar_set = set(sessions or [])
    panel_dates = sorted({row["date"] for row in rows})
    outside = [day.isoformat() for day in panel_dates if calendar_set and day.isoformat() not in calendar_set]

    early = [{"security_id": row["security_id"], "date": row["date"].isoformat(),
              "available_at": row["available_at"].isoformat()}
             for row in rows
             if row["available_at"] < datetime.combine(row["date"], CLOSE, row["available_at"].tzinfo)]

    missing = {}
    for symbol, items in sorted(by_symbol.items()):
        first, last = items[0]["date"], items[-1]["date"]
        expected = ([date.fromisoformat(day) for day in sessions if first.isoformat() <= day <= last.isoformat()]
                    if sessions else [day for day in panel_dates if first <= day <= last])
        absent = [day.isoformat() for day in expected if day not in {item["date"] for item in items}]
        if absent:
            missing[symbol] = absent[:limit]

    actions = action_map(cfg)
    ex_dates = {symbol: {day for day, _ in entries} for symbol, entries in actions.items()}
    moves = []
    for symbol, items in by_symbol.items():
        for previous, current in zip(items, items[1:], strict=False):
            change = current["close"] / previous["close"] - 1
            if abs(change) >= threshold:
                moves.append({"security_id": symbol, "date": current["date"].isoformat(),
                              "change": round(change, 6),
                              "action_registered": current["date"].isoformat() in ex_dates.get(symbol, set())})
    moves.sort(key=lambda item: (-abs(item["change"]), item["security_id"], item["date"]))

    problems = {"bad_rows": bad[:limit], "duplicates": duplicates[:limit], "dates_outside_calendar": outside[:limit],
                "available_at_before_close": early[:limit], "missing_sessions": missing}
    notes = []
    if not sessions:
        notes.append("未使用认证日历：缺失按本文件出现过的日期计算，不代表交易所口径" if market else
                     "未指定 --market，缺失按本文件出现过的日期计算")
    if moves and not actions:
        notes.append("未导入公司行动：跳空无法区分除权与数据错误，请对照 actions-import")
    return {
        "ok": not (bad or duplicates or outside or early),
        "file": str(path), "rows": len(rows), "symbols": sorted(by_symbol),
        "range": [panel_dates[0].isoformat(), panel_dates[-1].isoformat()],
        "calendar": ({"market": market, "certified": True, "sessions": len(sessions)} if sessions else
                     {"market": market, "certified": False}),
        "threshold": threshold,
        "problems": problems, "large_moves": moves[:limit], "notes": notes,
    }
