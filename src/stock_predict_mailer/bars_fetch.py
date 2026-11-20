"""Fetch daily bars from a declared source into the nine-field data contract.

Fetching is dependency-free and writes a plain CSV; turning that CSV into an
immutable snapshot stays in the research path (``legacy update-bars``), which
needs the research extra. Nothing here invents a bar: a symbol with no rows, a
date outside the window, or a session that has not closed yet stops the write.

``available_at`` is the moment this machine actually received the rows. Backfill
can declare the exchange convention instead (``--assume-session-close``), and the
provenance file records which of the two was used.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from .core import atomic_write, write_json
from .data import FIELDS
from .plugins import registry

SHANGHAI = timezone(timedelta(hours=8))
SECURITY = re.compile(r"^(sh|sz)\.(\d{6})$")
SESSION_CLOSE = time(15, 5)
SETTLED_AT = time(18, 0)
MAX_SPAN_DAYS = 3660
MAX_ROWS = 200_000


class FetchError(Exception):
    """Rows that cannot enter a snapshot; never downgraded to a warning."""

    code = "FETCH_FAILED"

    def __init__(self, message):
        super().__init__(message)
        self.message = message
        self.retryable = False

    def as_dict(self):
        return {"error": {"code": self.code, "message": self.message, "retryable": self.retryable}}


def parse_symbols(value):
    """``sh.600519,sz.000001`` → validated, ordered, de-duplicated tuple."""
    items = [item.strip().lower() for item in str(value).split(",") if item.strip()]
    if not items:
        raise FetchError("至少需要一个证券代码，例如 sh.600519,sz.000001")
    seen = []
    for item in items:
        if not SECURITY.match(item):
            raise FetchError(f"证券代码须形如 sh.600519 或 sz.000001：{item}")
        if item in seen:
            raise FetchError(f"证券代码重复：{item}")
        seen.append(item)
    return tuple(seen)


def parse_window(start, end):
    try:
        first, last = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    except ValueError:
        raise FetchError("起止日期须形如 YYYY-MM-DD") from None
    if first > last:
        raise FetchError("起始日期不能晚于结束日期")
    if (last - first).days > MAX_SPAN_DAYS:
        raise FetchError(f"单次最多取 {MAX_SPAN_DAYS} 天，请分段采集")
    return first, last


def _row(symbol_id, bar, available):
    day = bar["at"]
    open_, high, low, close = bar["open"], bar["high"], bar["low"], bar["close"]
    if low > min(open_, close) or high < max(open_, close) or low > high:
        raise FetchError(f"{symbol_id} {day} 的开高低收不自洽")
    return {"date": day, "security_id": symbol_id, "open": open_, "high": high, "low": low,
            "close": close, "volume": bar["volume"], "available_at": available, "source": ""}


def collect(symbol_ids, first, last, *, source="market_eastmoney", timeout=8.0,
            assume_session_close=False, clock=None, fetch=None):
    """Fetch and validate; returns ``(rows, provenance)`` and never writes a partial file."""
    adapter = _adapter(source)
    fetched_at = (clock or (lambda: datetime.now(SHANGHAI)))()
    if fetched_at.tzinfo is None:
        raise FetchError("取数时间必须带时区")
    rows, seen = [], set()
    warnings = []
    if not assume_session_close and last < fetched_at.date() - timedelta(days=1):
        warnings.append(f"区间止于 {last}，但 available_at 记为取数时间 {fetched_at.date()}：这批数据只能用于"
                        f"晚于该时间的截止点；若要回溯历史，请加 --assume-session-close 并接受其假设")
    for symbol_id in symbol_ids:
        market, code = SECURITY.match(symbol_id).groups()
        try:
            bars = (fetch or adapter.bars)(f"{market}{code}", first, last, timeout)
        except FetchError:
            raise
        except Exception as exc:
            # A plugin failure must read as a fetch failure, not as a generic
            # runtime error the CLI would report as "another delivery is running".
            raise FetchError(f"{symbol_id} 取数失败：{exc}") from exc
        if not bars:
            raise FetchError(f"{symbol_id} 在 {first}..{last} 没有返回任何日线，已停止写入")
        for bar in bars:
            day = date.fromisoformat(str(bar["at"])[:10])
            if not first <= day <= last:
                raise FetchError(f"{symbol_id} 返回了区间外的日期 {day}")
            if day == fetched_at.date() and fetched_at.time() < SESSION_CLOSE:
                raise FetchError(f"{symbol_id} 的 {day} 尚未收盘，请把 --end 设为上一交易日，或收盘后再取")
            available = (datetime.combine(day, SETTLED_AT, SHANGHAI) if assume_session_close
                         else fetched_at).isoformat()
            row = _row(symbol_id, {**bar, "at": day.isoformat()}, available)
            key = (symbol_id, day)
            if key in seen:
                raise FetchError(f"{symbol_id} 的 {day} 重复出现")
            seen.add(key)
            rows.append(row)
    if len(rows) > MAX_ROWS:
        raise FetchError(f"本次 {len(rows)} 行超过 {MAX_ROWS} 行上限，请分段采集")
    rows.sort(key=lambda item: (item["security_id"], item["date"]))
    provenance = {
        "fetched_at": fetched_at.isoformat(),
        "source": registry.identity(source) | {"label": adapter.manifest.label},
        "symbols": list(symbol_ids), "start": first.isoformat(), "end": last.isoformat(),
        "rows": len(rows), "first_date": rows[0]["date"], "last_date": rows[-1]["date"],
        "available_at": "session_close" if assume_session_close else "fetched",
        "price_basis": "unadjusted",
        "warnings": warnings,
        "timeout_seconds": timeout,
    }
    return rows, provenance


def _adapter(source_id):
    adapter = registry.resolve(source_id, "market_source")
    if "bars" not in adapter.manifest.capabilities:
        raise FetchError(f"行情源 {source_id} 没有声明 bars 能力，无法用于采集")
    return adapter


def write(output, rows, provenance):
    """Write the CSV and its provenance sidecar atomically."""
    source_id = provenance["source"]["id"]
    for row in rows:
        row["source"] = source_id
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path = Path(output)
    atomic_write(path, buffer.getvalue().encode("utf-8"))
    sidecar = Path(str(path) + ".provenance.json")
    write_json(sidecar, provenance)
    return path, sidecar


def run(symbols_value, start, end, output, *, source="market_eastmoney", timeout=8.0,
        assume_session_close=False, clock=None, fetch=None):
    symbol_ids = parse_symbols(symbols_value)
    first, last = parse_window(start, end)
    rows, provenance = collect(symbol_ids, first, last, source=source, timeout=timeout,
                               assume_session_close=assume_session_close, clock=clock, fetch=fetch)
    path, sidecar = write(output, rows, provenance)
    return {**provenance, "output": str(path), "provenance": str(sidecar)}
