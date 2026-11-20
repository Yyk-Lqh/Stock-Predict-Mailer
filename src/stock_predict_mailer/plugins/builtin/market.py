"""Built-in quote relays, registered as data-source plugins.

These are seams, not relocations: HTTP, decoding and the "reject an implausible
quote" checks stay in ``control.market_feed``, which remains the single owner of
the display contract. A provider with its own parsing (AKShare, Tushare) would
implement ``quotes`` from scratch behind the same declaration.
"""
from __future__ import annotations

from ...control import market_feed
from ..contract import declare


class TencentSource:
    manifest = declare(id="market_tencent", kind="market_source", label="腾讯行情",
                       capabilities=("quotes", "candles"))

    @staticmethod
    def quotes(instruments, timeout):
        return market_feed.tencent_quotes(instruments, timeout)

    @staticmethod
    def candles(symbol, timeout):
        return market_feed.tencent_candles(symbol, timeout)


class SinaSource:
    manifest = declare(id="market_sina", kind="market_source", label="新浪行情",
                       capabilities=("quotes",))

    @staticmethod
    def quotes(instruments, timeout):
        return market_feed.sina_quotes(instruments, timeout)
