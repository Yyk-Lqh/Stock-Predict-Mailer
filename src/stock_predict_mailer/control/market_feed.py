"""Loopback relay for display-only market quotes.

Quotes decorate the hall wall and nothing else: they never become task input,
prediction input or model input. A failed fetch keeps the last validated snapshot
and says so; a first failure returns no snapshot at all rather than inventing one.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SHANGHAI = timezone(timedelta(hours=8))
SYMBOL = re.compile(r"^(sh|sz)\d{6}$")
TENCENT_QUOTE = "https://qt.gtimg.cn/q={symbols}"
TENCENT_KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{count},qfq"
SINA_QUOTE = "https://hq.sinajs.cn/list={symbols}"
SINA_REFERER = "https://finance.sina.com.cn"
DEFAULT_INSTRUMENTS = (
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
    ("sh000300", "沪深300"),
)
MAX_INSTRUMENTS = 4
MAX_POINTS = 500
KLINE_COUNT = 40
LIVE_SECONDS = 180
CANDLE_SECONDS = 600
ACTIVE_TTL = 5
IDLE_TTL = 300
TIMEOUT_SECONDS = 6.0


class MarketError(RuntimeError):
    """The provider answered with data that cannot be shown as a real quote."""


def _number(value, field, low=None, high=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise MarketError(f"{field}不是数值") from None
    if not math.isfinite(number):
        raise MarketError(f"{field}不是有限数值")
    if low is not None and number < low:
        raise MarketError(f"{field}低于下限")
    if high is not None and number > high:
        raise MarketError(f"{field}高于上限")
    return number


def _http(url, timeout, encoding, referer=None):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Stock-Predict-Mailer/1)", "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(2 * 1024 * 1024)
    return body.decode(encoding, "replace")


def _tencent_time(value):
    text = str(value).strip()
    try:
        return datetime.strptime(text[:14], "%Y%m%d%H%M%S").replace(tzinfo=SHANGHAI)
    except ValueError:
        raise MarketError("行情源时间无效") from None


def _sina_time(day, clock):
    try:
        return datetime.strptime(f"{str(day).strip()} {str(clock).strip()}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=SHANGHAI)
    except ValueError:
        raise MarketError("行情源时间无效") from None


def _rows(text, prefix, separator):
    rows = {}
    for line in text.split(";"):
        line = line.strip()
        if not line.startswith(prefix) or "=" not in line:
            continue
        head, body = line.split("=", 1)
        rows[head[len(prefix):].strip().lower()] = body.strip().strip('"').split(separator)
    return rows


def parse_tencent(text, instruments):
    """Return one quote per configured symbol, in configured order."""
    rows = _rows(text, "v_", "~")
    quotes = []
    for symbol, label in instruments:
        fields = rows.get(symbol)
        if not fields or len(fields) < 33:
            raise MarketError(f"行情源未返回 {symbol}")
        name = (fields[1].strip() or label)[:60]
        quotes.append({"symbol": symbol, "name": name, "last": _number(fields[3], "最新价", 0.0001, 1e9),
                       "change_pct": _number(fields[32], "涨跌幅", -100, 100), "at": _tencent_time(fields[30])})
    return quotes


def parse_sina(text, instruments):
    """Same contract as :func:`parse_tencent` for the fallback provider."""
    rows = _rows(text, "var hq_str_", ",")
    quotes = []
    for symbol, label in instruments:
        fields = rows.get(symbol)
        if not fields or len(fields) < 32:
            raise MarketError(f"行情源未返回 {symbol}")
        name = (fields[0].strip() or label)[:60]
        last, previous = _number(fields[3], "最新价", 0.0001, 1e9), _number(fields[2], "昨收", 0.0001, 1e9)
        change = (last / previous - 1) * 100
        if not -100 <= change <= 100:
            raise MarketError("涨跌幅超出范围")
        quotes.append({"symbol": symbol, "name": name, "last": last, "change_pct": round(change, 4),
                       "at": _sina_time(fields[30], fields[31])})
    return quotes


def tencent_quotes(instruments, timeout):
    return parse_tencent(_http(TENCENT_QUOTE.format(symbols=",".join(s for s, _ in instruments)), timeout, "gbk"), instruments)


def sina_quotes(instruments, timeout):
    return parse_sina(_http(SINA_QUOTE.format(symbols=",".join(s for s, _ in instruments)), timeout, "gbk", SINA_REFERER), instruments)


def parse_candles(text, symbol):
    """Daily OHLC for the overview chart; raises instead of synthesising bars."""
    try:
        body = json.loads(text)
    except ValueError:
        raise MarketError("日线数据不是 JSON") from None
    node = (body.get("data") or {}).get(symbol) or {}
    rows = node.get("day") or node.get("qfqday") or []
    candles = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            raise MarketError("日线行格式无效")
        day = str(row[0])[:10]
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            raise MarketError("日线日期无效") from None
        open_, close = _number(row[1], "开盘", 0, 1e9), _number(row[2], "收盘", 0, 1e9)
        high, low = _number(row[3], "最高", 0, 1e9), _number(row[4], "最低", 0, 1e9)
        if low > min(open_, close) or high < max(open_, close) or low > high:
            raise MarketError("日线高低范围无效")
        candles.append({"at": day, "open": open_, "high": high, "low": low, "close": close,
                        "volume": _number(row[5], "成交量", 0, 1e18)})
    if len(candles) < 2:
        raise MarketError("日线数据不足")
    return candles[-MAX_POINTS:]


def tencent_candles(symbol, timeout, count=KLINE_COUNT):
    return parse_candles(_http(TENCENT_KLINE.format(symbol=symbol, count=count), timeout, "utf-8"), symbol)


def _settings(root):
    """Read ``market.json`` from the workspace; invalid files fall back to the four indices."""
    fallback = (DEFAULT_INSTRUMENTS, 10, True)
    if not root:
        return fallback
    try:
        raw = json.loads((Path(root) / "market.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback
    if not isinstance(raw, dict):
        return fallback
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        enabled = True
    refresh = raw.get("refresh_seconds", 10)
    if isinstance(refresh, bool) or not isinstance(refresh, int) or not 5 <= refresh <= 60:
        refresh = 10
    items = raw.get("instruments")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_INSTRUMENTS:
        return (DEFAULT_INSTRUMENTS, refresh, enabled)
    instruments, seen = [], set()
    for item in items:
        symbol = item.get("symbol") if isinstance(item, dict) else item
        label = item.get("name") if isinstance(item, dict) else None
        symbol = symbol.strip().lower() if isinstance(symbol, str) else ""
        if not SYMBOL.match(symbol) or symbol in seen:
            return (DEFAULT_INSTRUMENTS, refresh, enabled)
        seen.add(symbol)
        instruments.append((symbol, label.strip()[:60] if isinstance(label, str) and label.strip() else ""))
    return (tuple(instruments), refresh, enabled)


class MarketFeed:
    """One validated snapshot shared by every browser tab, refreshed on demand."""

    def __init__(self, root=None, fetchers=None, candles=None, timeout=TIMEOUT_SECONDS, clock=time.time):
        self.instruments, self.refresh_seconds, self.enabled = _settings(root)
        default = (("腾讯行情", tencent_quotes), ("新浪行情", sina_quotes))
        self.fetchers = tuple(default if fetchers is None else fetchers) if self.enabled else ()
        self.candles = candles or tencent_candles
        self.timeout = timeout
        self.clock = clock
        self._lock = threading.Lock()
        self._snapshot = None
        self._retrieved = 0.0
        self._candles = ()
        self._candles_symbol = ""
        self._candles_at = 0.0
        self._candles_failed_at = 0.0

    def _ttl(self, now):
        local = datetime.fromtimestamp(now, SHANGHAI)
        minutes = local.hour * 60 + local.minute
        return ACTIVE_TTL if local.weekday() < 5 and 9 * 60 + 10 <= minutes < 15 * 60 + 10 else IDLE_TTL

    def _series(self, symbol, now):
        if self._candles and self._candles_symbol == symbol and now - self._candles_at < CANDLE_SECONDS:
            return list(self._candles)
        if now - self._candles_failed_at < 60:
            return list(self._candles) if self._candles_symbol == symbol else []
        try:
            candles = self.candles(symbol, self.timeout)
        except Exception:
            self._candles_failed_at = now
            return list(self._candles) if self._candles_symbol == symbol else []
        self._candles, self._candles_symbol, self._candles_at = tuple(candles), symbol, now
        return candles

    def _fetch(self, now):
        quotes, source = None, ""
        for name, fetcher in self.fetchers:
            try:
                candidate = fetcher(self.instruments, self.timeout)
                if len(candidate) != len(self.instruments):
                    raise MarketError("行情标的数量与配置不符")
                quotes, source = candidate, name
                break
            except Exception:
                quotes = None
        if not quotes:
            raise MarketError("所有行情源均不可用")
        candles = self._series(quotes[0]["symbol"], now)
        as_of = max(quote["at"] for quote in quotes)
        return {"demo": False, "source": source, "as_of": as_of.isoformat(), "timezone": "Asia/Shanghai",
                "quotes": [{key: value for key, value in quote.items() if key != "at"} for quote in quotes],
                "history": [{"at": candle["at"], "value": candle["close"]} for candle in candles],
                "candles": candles}

    def _decorate(self, now, status=None, detail=""):
        snapshot = dict(self._snapshot)
        age = now - datetime.fromisoformat(snapshot["as_of"]).timestamp()
        snapshot["session"] = "live" if age <= LIVE_SECONDS else "delayed"
        body = {"status": status or snapshot["session"], "snapshot": snapshot, "refresh_seconds": self.refresh_seconds}
        if detail:
            body["detail"] = detail
        return body

    def payload(self, force=False):
        """Return ``{status, snapshot, refresh_seconds}``; never raises for provider failures."""
        with self._lock:
            now = self.clock()
            if self._snapshot is not None and not force and now - self._retrieved < self._ttl(now):
                return self._decorate(now)
            try:
                self._snapshot, self._retrieved = self._fetch(now), now
            except Exception:
                if self._snapshot is None:
                    return {"status": "unavailable", "snapshot": None, "refresh_seconds": self.refresh_seconds,
                            "detail": "行情源不可用，尚未取得实时报价"}
                return self._decorate(now, "stale", "行情源暂时不可用，保留上一份快照")
            return self._decorate(now)
