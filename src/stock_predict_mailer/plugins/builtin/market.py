"""Built-in quote relays, registered as data-source plugins.

These are seams, not relocations: HTTP, decoding and the "reject an implausible
quote" checks stay in ``control.market_feed``, which remains the single owner of
the display contract. A provider with its own parsing (AKShare, Tushare) would
implement ``quotes`` from scratch behind the same declaration.
"""
from __future__ import annotations

import json
import math
import urllib.request
from datetime import datetime, timedelta

from ...control import market_feed
from ..contract import declare

BARS_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,{beg},{end},640,"
CHUNK_DAYS = 365
USER_AGENT = "Mozilla/5.0 (compatible; Stock-Predict-Mailer/1)"


class TencentError(RuntimeError):
    """The quote relay returned rows that cannot enter a snapshot."""


def _get(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Referer": "https://gu.qq.com/"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def parse_bars(text, symbol):
    """``data[symbol].day`` rows are ``[date, open, close, high, low, volume]``."""
    try:
        payload = (json.loads(text).get("data") or {})
    except ValueError:
        raise TencentError("日线接口返回的不是 JSON") from None
    rows = (payload.get(symbol) or {}).get("day")
    if rows is None:
        raise TencentError(f"{symbol} 没有返回日线")
    bars = []
    for item in rows:
        if not isinstance(item, list) or len(item) < 6:
            raise TencentError("日线行格式无效")
        day = str(item[0])[:10]
        try:
            datetime.strptime(day, "%Y-%m-%d")
            open_, close, high, low, volume = (float(item[index]) for index in (1, 2, 3, 4, 5))
        except (TypeError, ValueError):
            raise TencentError("日线数值无效") from None
        if not all(math.isfinite(value) and value > 0 for value in (open_, close, high, low)):
            raise TencentError("日线数值无效")
        if not math.isfinite(volume) or volume < 0:
            raise TencentError("日线成交量无效")
        if low > min(open_, close) or high < max(open_, close) or low > high:
            raise TencentError("日线高低范围无效")
        bars.append({"at": day, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
    return bars


class TencentSource:
    manifest = declare(id="market_tencent", kind="market_source", label="腾讯行情",
                       capabilities=("quotes", "candles", "bars"))

    @staticmethod
    def quotes(instruments, timeout):
        return market_feed.tencent_quotes(instruments, timeout)

    @staticmethod
    def candles(symbol, timeout):
        return market_feed.tencent_candles(symbol, timeout)

    @staticmethod
    def bars(symbol, start, end, timeout):
        """Unadjusted daily bars, requested in yearly chunks.

        The endpoint caps a response at 640 rows and would silently drop the
        older part of a longer window, so the window is split rather than
        trusting the server to return everything asked for.
        """
        rows, cursor = [], start
        while cursor <= end:
            chunk = min(cursor + timedelta(days=CHUNK_DAYS - 1), end)
            url = BARS_URL.format(symbol=symbol, beg=cursor.isoformat(), end=chunk.isoformat())
            rows.extend(parse_bars(_get(url, timeout), symbol))
            cursor = chunk + timedelta(days=1)
        return rows


class SinaSource:
    manifest = declare(id="market_sina", kind="market_source", label="新浪行情",
                       capabilities=("quotes",))

    @staticmethod
    def quotes(instruments, timeout):
        return market_feed.sina_quotes(instruments, timeout)
