import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from stock_predict_mailer.control.market_feed import (
    DEFAULT_INSTRUMENTS,
    SHANGHAI,
    MarketError,
    MarketFeed,
    parse_candles,
    parse_sina,
    parse_tencent,
)


# Shape fixtures copied from the two public endpoints; no network in these tests.
def tencent_row(symbol, name, last, change_pct, stamp, size=36):
    fields = ["0"] * size
    fields[0], fields[1], fields[2] = "1", name, symbol[2:]
    fields[3], fields[30], fields[32] = last, stamp, change_pct
    return "v_" + symbol + '="' + "~".join(fields) + '";'


def sina_row(symbol, name, previous, last, day="2026-11-13", clock="15:00:00"):
    fields = ["0"] * 32
    fields[0], fields[1], fields[2], fields[3] = name, "0", previous, last
    fields[30], fields[31] = day, clock
    return "var hq_str_" + symbol + '="' + ",".join(fields) + '";'


def quotes(clock, shift=0, change=-0.59):
    def fetch(instruments, timeout):
        at = datetime.fromtimestamp(clock() + shift, SHANGHAI)
        return [{"symbol": symbol, "name": label or symbol, "last": 3000.0 + index, "change_pct": change, "at": at}
                for index, (symbol, label) in enumerate(instruments)]
    return fetch


class ParserTests(unittest.TestCase):
    def test_tencent_group_keeps_configured_order_and_fields(self):
        text = tencent_row("sh000001", "上证指数", "3634.35", "-0.59", "20261113161427")
        rows = parse_tencent(text, (("sh000001", "上证指数"),))
        self.assertEqual(rows[0]["name"], "上证指数")
        self.assertEqual(rows[0]["last"], 3634.35)
        self.assertEqual(rows[0]["change_pct"], -0.59)
        self.assertEqual(rows[0]["at"].isoformat(), "2026-11-13T16:14:27+08:00")

    def test_missing_symbol_and_zero_price_are_rejected(self):
        text = tencent_row("sh000001", "上证指数", "3634.35", "-0.59", "20261113161427")
        with self.assertRaises(MarketError):
            parse_tencent(text, (("sz399001", "深证成指"),))
        zero = tencent_row("sh000001", "上证指数", "0", "-0.59", "20261113161427")
        with self.assertRaises(MarketError):
            parse_tencent(zero, (("sh000001", "上证指数"),))

    def test_implausible_change_and_timestamp_are_rejected(self):
        with self.assertRaises(MarketError):
            parse_tencent(tencent_row("sh000001", "上证指数", "3634", "139", "20261113161427"), (("sh000001", ""),))
        with self.assertRaises(MarketError):
            parse_tencent(tencent_row("sh000001", "上证指数", "3634", "1", "yesterday"), (("sh000001", ""),))

    def test_sina_computes_change_from_previous_close(self):
        rows = parse_sina(sina_row("sh000001", "上证指数", "3655.83", "3634.35"), (("sh000001", "上证指数"),))
        self.assertAlmostEqual(rows[0]["change_pct"], -0.588, places=3)
        self.assertEqual(rows[0]["at"].isoformat(), "2026-11-13T15:00:00+08:00")

    def test_candles_keep_ohlc_and_reject_inverted_ranges(self):
        good = {"data": {"sh000001": {"day": [["2026-11-12", "3900", "3910", "3920", "3890", "123"],
                                              ["2026-11-13", "3910", "3888", "3912", "3852", "456"]]}}}
        rows = parse_candles(json.dumps(good), "sh000001")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["close"], 3888.0)
        self.assertEqual(rows[-1]["volume"], 456.0)
        bad = {"data": {"sh000001": {"day": [["2026-11-12", "3900", "3910", "3920", "3890", "123"],
                                              ["2026-11-13", "3910", "3888", "3870", "3852", "456"]]}}}
        with self.assertRaises(MarketError):
            parse_candles(json.dumps(bad), "sh000001")


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 13, 10, 0, tzinfo=SHANGHAI).timestamp()
        self.clock = lambda: self.now

    def feed(self, fetchers):
        return MarketFeed(fetchers=fetchers, candles=lambda symbol, timeout: [], clock=self.clock)

    def test_live_snapshot_reports_source_time_and_session(self):
        body = self.feed([("腾讯行情", quotes(self.clock))]).payload()
        snapshot = body["snapshot"]
        self.assertEqual(body["status"], "live")
        self.assertEqual(snapshot["session"], "live")
        self.assertFalse(snapshot["demo"])
        self.assertEqual(snapshot["source"], "腾讯行情")
        self.assertEqual(snapshot["timezone"], "Asia/Shanghai")
        self.assertEqual(snapshot["as_of"], datetime.fromtimestamp(self.now, SHANGHAI).isoformat())
        self.assertNotIn("at", snapshot["quotes"][0])
        self.assertEqual(body["refresh_seconds"], 10)

    def test_quote_older_than_three_minutes_is_delayed(self):
        body = self.feed([("腾讯行情", quotes(self.clock, shift=-600))]).payload()
        self.assertEqual(body["status"], "delayed")
        self.assertEqual(body["snapshot"]["session"], "delayed")

    def test_active_session_cache_holds_for_five_seconds(self):
        calls = []

        def fetch(instruments, timeout):
            calls.append(1)
            return quotes(self.clock)(instruments, timeout)

        feed = self.feed([("腾讯行情", fetch)])
        feed.payload()
        feed.payload()
        self.assertEqual(len(calls), 1)
        self.now += 6
        feed.payload()
        self.assertEqual(len(calls), 2)

    def test_closed_session_cache_holds_for_five_minutes(self):
        self.now = datetime(2026, 11, 13, 20, 0, tzinfo=SHANGHAI).timestamp()
        calls = []

        def fetch(instruments, timeout):
            calls.append(1)
            return quotes(self.clock)(instruments, timeout)

        feed = self.feed([("腾讯行情", fetch)])
        feed.payload()
        self.now += 60
        feed.payload()
        self.assertEqual(len(calls), 1)

    def test_failure_keeps_the_last_snapshot_and_says_it_is_stale(self):
        state = {"fail": False}

        def fetch(instruments, timeout):
            if state["fail"]:
                raise OSError("down")
            return quotes(self.clock)(instruments, timeout)

        feed = self.feed([("腾讯行情", fetch)])
        first = feed.payload()["snapshot"]
        state["fail"] = True
        self.now += 6
        body = feed.payload()
        self.assertEqual(body["status"], "stale")
        self.assertEqual(body["snapshot"], first)
        self.assertIn("保留上一份快照", body["detail"])

    def test_first_failure_reports_unavailable_without_inventing_quotes(self):
        def broken(instruments, timeout):
            raise OSError("down")

        body = self.feed([("腾讯行情", broken), ("新浪行情", broken)]).payload()
        self.assertEqual(body["status"], "unavailable")
        self.assertIsNone(body["snapshot"])
        self.assertIn("尚未取得", body["detail"])

    def test_second_provider_covers_the_first(self):
        def broken(instruments, timeout):
            raise OSError("down")

        body = self.feed([("腾讯行情", broken), ("新浪行情", quotes(self.clock))]).payload()
        self.assertEqual(body["status"], "live")
        self.assertEqual(body["snapshot"]["source"], "新浪行情")

    def test_provider_with_the_wrong_symbol_count_is_rejected(self):
        feed = self.feed([("腾讯行情", lambda instruments, timeout: [])])
        self.assertEqual(feed.payload()["status"], "unavailable")

    def test_candle_failure_is_not_retried_on_every_quote_refresh(self):
        calls = []

        def broken(symbol, timeout):
            calls.append(1)
            raise OSError("down")

        feed = MarketFeed(fetchers=[("腾讯行情", quotes(self.clock))], candles=broken, clock=self.clock)
        feed.payload()
        self.now += 6
        feed.payload()
        self.assertEqual(len(calls), 1)

    def test_history_and_candles_level_out(self):
        candles = [{"at": "2026-11-12", "open": 3900.0, "high": 3920.0, "low": 3890.0, "close": 3910.0, "volume": 1.0},
                   {"at": "2026-11-13", "open": 3910.0, "high": 3912.0, "low": 3852.0, "close": 3888.0, "volume": 2.0}]
        feed = MarketFeed(fetchers=[("腾讯行情", quotes(self.clock))], candles=lambda symbol, timeout: candles, clock=self.clock)
        body = feed.payload()
        self.assertEqual([point["value"] for point in body["snapshot"]["history"]], [3910.0, 3888.0])
        self.assertEqual(len(body["snapshot"]["candles"]), 2)


class SettingsTests(unittest.TestCase):
    def test_invalid_config_falls_back_to_the_four_indices(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "market.json").write_text('{"instruments":[{"symbol":"bad"}]}', encoding="utf-8")
            self.assertEqual(tuple(MarketFeed(root=Path(folder)).instruments), DEFAULT_INSTRUMENTS)

    def test_missing_config_keeps_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            feed = MarketFeed(root=Path(folder))
            self.assertEqual(tuple(feed.instruments), DEFAULT_INSTRUMENTS)
            self.assertEqual(feed.refresh_seconds, 10)

    def test_config_selects_symbols_and_clamps_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "market.json").write_text(
                json.dumps({"refresh_seconds": 1, "instruments": [{"symbol": "sh600519", "name": "贵州茅台"}]}), encoding="utf-8")
            feed = MarketFeed(root=Path(folder))
            self.assertEqual(feed.instruments, (("sh600519", "贵州茅台"),))
            self.assertEqual(feed.refresh_seconds, 10)

    def test_disabled_config_keeps_the_demo_wall(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "market.json").write_text('{"enabled": false}', encoding="utf-8")
            feed = MarketFeed(root=Path(folder), fetchers=[("腾讯行情", quotes(lambda: 0))])
            self.assertEqual(feed.fetchers, ())
            self.assertEqual(feed.payload()["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
