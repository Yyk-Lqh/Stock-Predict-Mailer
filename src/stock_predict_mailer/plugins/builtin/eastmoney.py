"""Eastmoney quote relay, declared as a plugin that is not in the default chain.

This module is deliberately self-contained: it owns its URLs, its numeric checks
and its own parsers instead of reaching into ``control.market_feed``'s privates.
A plugin that borrows another module's internals is a plugin in name only.

It is *not* enabled by default. ``market.json`` must name it in ``sources``;
that way adding a provider never silently changes which endpoints a process
contacts, and never makes the display wall depend on an optional install.
"""
from __future__ import annotations

import json
import math
import urllib.request
from datetime import datetime, timedelta, timezone

from ..contract import declare

SHANGHAI = timezone(timedelta(hours=8))
MARKET_ID = {"sh": 1, "sz": 0}
QUOTE_URL = ("https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids={secids}"
             "&fields=f12,f13,f14,f2,f3,f124")
KLINE_URL = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
             "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
             "&klt=101&fqt=1&lmt={count}&end=20500101")
BARS_URL = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
            "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
            "&klt=101&fqt=0&beg={beg}&end={end}")
MAX_POINTS = 500  # the console refuses a chart with more points than this
DEFAULT_COUNT = 40


class EastmoneyError(RuntimeError):
    """The provider answered with data that cannot be shown as a real quote."""


def _number(value, field, low=None, high=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise EastmoneyError(f"{field}不是数值") from None
    if not math.isfinite(number):
        raise EastmoneyError(f"{field}不是有限数值")
    if low is not None and number < low:
        raise EastmoneyError(f"{field}低于下限")
    if high is not None and number > high:
        raise EastmoneyError(f"{field}高于上限")
    return number


def _get(url, timeout):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Stock-Predict-Mailer/1)",
               "Accept": "*/*", "Referer": "https://quote.eastmoney.com/"}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(2 * 1024 * 1024)
    return body.decode("utf-8", "replace")


def _secid(symbol):
    market, code = MARKET_ID.get(symbol[:2]), symbol[2:]
    if market is None or len(code) != 6 or not code.isdigit():
        raise EastmoneyError(f"不支持的标的代码：{symbol}")
    return market, code


def _moment(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise EastmoneyError("行情源时间无效")
    return datetime.fromtimestamp(value, SHANGHAI)


def _body(text, field):
    try:
        body = json.loads(text)
    except ValueError:
        raise EastmoneyError(f"{field}不是 JSON") from None
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise EastmoneyError(f"{field}没有 data")
    return data


def parse_quotes(text, instruments):
    """One quote per configured symbol, in configured order, matched by market+code."""
    rows = _body(text, "东方财富行情").get("diff") or []
    index = {}
    for row in rows:
        if isinstance(row, dict):
            try:
                index[(int(row["f13"]), str(row["f12"]))] = row
            except (KeyError, TypeError, ValueError):
                raise EastmoneyError("行情行缺少市场或代码") from None
    quotes = []
    for symbol, label in instruments:
        market, code = _secid(symbol)
        row = index.get((market, code))
        if row is None:
            raise EastmoneyError(f"行情源未返回 {symbol}")
        name = (str(row.get("f14") or "").strip() or label)[:60]
        quotes.append({"symbol": symbol, "name": name,
                       "last": _number(row.get("f2"), "最新价", 0.0001, 1e9),
                       "change_pct": _number(row.get("f3"), "涨跌幅", -100, 100),
                       "at": _moment(row.get("f124"))})
    return quotes


def _bar_rows(rows):
    """Shared row validation: ``date,open,close,high,low,volume,...`` in that order."""
    bars = []
    for item in rows:
        fields = str(item).split(",")
        if len(fields) < 6:
            raise EastmoneyError("日线行格式无效")
        day = fields[0][:10]
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            raise EastmoneyError("日线日期无效") from None
        open_, close = _number(fields[1], "开盘", 0, 1e9), _number(fields[2], "收盘", 0, 1e9)
        high, low = _number(fields[3], "最高", 0, 1e9), _number(fields[4], "最低", 0, 1e9)
        if low > min(open_, close) or high < max(open_, close) or low > high:
            raise EastmoneyError("日线高低范围无效")
        bars.append({"at": day, "open": open_, "high": high, "low": low, "close": close,
                     "volume": _number(fields[5], "成交量", 0, 1e18)})
    return bars


def parse_candles(text, symbol):
    """Daily OHLC for the overview chart; never synthesises bars."""
    candles = _bar_rows(_body(text, "日线数据").get("klines") or [])
    if len(candles) < 2:
        raise EastmoneyError("日线数据不足")
    return candles[-MAX_POINTS:]


def parse_bars(text, symbol):
    """Every row in the requested window, or none; the caller decides what is fatal."""
    return _bar_rows(_body(text, "日线数据").get("klines") or [])


class EastmoneySource:
    manifest = declare(id="market_eastmoney", kind="market_source", label="东方财富行情",
                       capabilities=("quotes", "candles", "bars"))

    @staticmethod
    def quotes(instruments, timeout):
        secids = ",".join(f"{market}.{code}" for market, code in (_secid(s) for s, _ in instruments))
        return parse_quotes(_get(QUOTE_URL.format(secids=secids), timeout), instruments)

    @staticmethod
    def candles(symbol, timeout, count=DEFAULT_COUNT):
        market, code = _secid(symbol)
        return parse_candles(_get(KLINE_URL.format(secid=f"{market}.{code}", count=count), timeout), symbol)

    @staticmethod
    def bars(symbol, start, end, timeout):
        """Unadjusted daily bars for the snapshot pipeline.

        ``fqt=0`` on purpose: forward-adjusted history is rewritten on every
        dividend, and the contract applies corporate actions locally from
        ``actions-import``. Fetching adjusted bars here would adjust twice.
        """
        market, code = _secid(symbol)
        url = BARS_URL.format(secid=f"{market}.{code}", beg=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"))
        return parse_bars(_get(url, timeout), symbol)
