import csv
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path

from stock_predict_mailer.bars_fetch import SHANGHAI, FetchError, collect, parse_symbols, parse_window, run
from stock_predict_mailer.cli import main
from stock_predict_mailer.data import FIELDS, validate_rows


def bar(day, open_=10.0, high=11.0, low=9.0, close=10.5, volume=1000):
    return {"at": day, "open": open_, "high": high, "low": low, "close": close, "volume": volume}


def clock_at(day=19, hour=18, minute=30):
    return lambda: datetime(2026, 11, day, hour, minute, tzinfo=SHANGHAI)


def source(*bars):
    return lambda symbol, first, last, timeout: list(bars)


class SymbolTests(unittest.TestCase):
    def test_symbols_are_normalised_and_deduplicated(self):
        self.assertEqual(parse_symbols(" SH.600519 , sz.000001 "), ("sh.600519", "sz.000001"))
        with self.assertRaises(FetchError):
            parse_symbols("sh.600519,sh.600519")
        for bad in ("600519", "sh600519", "sh.6005190", ""):
            with self.assertRaises(FetchError):
                parse_symbols(bad)

    def test_window_is_ordered_and_bounded(self):
        self.assertEqual(parse_window("2026-11-01", "2026-11-19"), (date(2026, 11, 1), date(2026, 11, 19)))
        with self.assertRaises(FetchError):
            parse_window("2026-11-19", "2026-11-01")
        with self.assertRaises(FetchError):
            parse_window("2026-11-01", "2040-01-01")


class CollectTests(unittest.TestCase):
    def test_rows_carry_the_source_and_the_fetch_time(self):
        rows, provenance = collect(("sh.600519",), date(2026, 11, 18), date(2026, 11, 19),
                                   clock=clock_at(), fetch=source(bar("2026-11-19")))
        self.assertEqual(rows[0]["security_id"], "sh.600519")
        self.assertEqual(rows[0]["date"], "2026-11-19")
        self.assertEqual(rows[0]["available_at"], "2026-11-19T18:30:00+08:00")
        self.assertEqual(provenance["source"]["id"], "market_eastmoney")
        self.assertEqual(len(provenance["source"]["module_digest"]), 64)
        self.assertEqual((provenance["rows"], provenance["first_date"], provenance["last_date"]),
                         (1, "2026-11-19", "2026-11-19"))
        self.assertEqual(provenance["available_at"], "fetched")
        self.assertEqual(provenance["price_basis"], "unadjusted")

    def test_assume_session_close_records_the_settlement_convention(self):
        rows, provenance = collect(("sh.600519",), date(2026, 11, 18), date(2026, 11, 19),
                                   assume_session_close=True, clock=clock_at(), fetch=source(bar("2026-11-19")))
        self.assertEqual(rows[0]["available_at"], "2026-11-19T18:00:00+08:00")
        self.assertEqual(provenance["available_at"], "session_close")

    def test_empty_result_stops_the_write(self):
        with self.assertRaises(FetchError) as caught:
            collect(("sh.600519",), date(2026, 11, 18), date(2026, 11, 19), clock=clock_at(), fetch=source())
        self.assertIn("没有返回任何日线", str(caught.exception))

    def test_a_date_outside_the_window_is_rejected(self):
        with self.assertRaises(FetchError):
            collect(("sh.600519",), date(2026, 11, 18), date(2026, 11, 19),
                    clock=clock_at(), fetch=source(bar("2026-11-02")))

    def test_an_unclosed_session_is_rejected(self):
        with self.assertRaises(FetchError) as caught:
            collect(("sh.600519",), date(2026, 11, 19), date(2026, 11, 19),
                    clock=clock_at(hour=10), fetch=source(bar("2026-11-19")))
        self.assertIn("尚未收盘", str(caught.exception))

    def test_inconsistent_ohlc_and_duplicate_days_are_rejected(self):
        with self.assertRaises(FetchError):
            collect(("sh.600519",), date(2026, 11, 18), date(2026, 11, 19), clock=clock_at(),
                    fetch=source(bar("2026-11-19", high=9.5)))
        with self.assertRaises(FetchError) as caught:
            collect(("sh.600519",), date(2026, 11, 18), date(2026, 11, 19), clock=clock_at(),
                    fetch=source(bar("2026-11-19"), bar("2026-11-19")))
        self.assertIn("重复", str(caught.exception))

    def test_a_source_failure_is_reported_as_a_fetch_failure(self):
        def broken(symbol, first, last, timeout):
            raise RuntimeError("upstream down")

        with self.assertRaises(FetchError) as caught:
            collect(("sh.600519",), date(2026, 11, 18), date(2026, 11, 19), clock=clock_at(), fetch=broken)
        self.assertIn("upstream down", str(caught.exception))

    def test_a_source_without_the_bars_capability_is_refused(self):
        with self.assertRaises(FetchError) as caught:
            collect(("sh.600519",), date(2026, 11, 18), date(2026, 11, 19), source="market_sina")
        self.assertIn("bars", str(caught.exception))


class WriteTests(unittest.TestCase):
    def test_csv_matches_the_data_contract_and_has_a_sidecar(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder, "bars.csv")
            result = run("sh.600519", "2026-11-18", "2026-11-19", output,
                         clock=clock_at(), fetch=source(bar("2026-11-19")))
            text = output.read_text(encoding="utf-8")
            record = json.loads(Path(str(output) + ".provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(text.splitlines()[0], ",".join(FIELDS))
        rows = validate_rows(list(csv.DictReader(io.StringIO(text))))
        self.assertEqual([(row["security_id"], row["date"], row["source"]) for row in rows],
                         [("sh.600519", "2026-11-19", "market_eastmoney")])
        self.assertEqual(record["source"]["id"], "market_eastmoney")
        self.assertEqual(record["rows"], 1)
        self.assertEqual(result["output"], str(output))

    def test_rows_are_sorted_by_symbol_then_date(self):
        payload = [bar("2026-11-19"), bar("2026-11-18")]
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder, "bars.csv")
            run("sh.600519,sz.000001", "2026-11-18", "2026-11-19", output,
                clock=clock_at(), fetch=source(*payload))
            rows = list(csv.DictReader(io.StringIO(output.read_text(encoding="utf-8"))))
        self.assertEqual([row["date"] for row in rows], ["2026-11-18", "2026-11-19", "2026-11-18", "2026-11-19"])


    def test_a_backfill_without_the_flag_warns_about_available_at(self):
        _, provenance = collect(("sh.600519",), date(2026, 11, 2), date(2026, 11, 6),
                                clock=clock_at(day=20), fetch=source(bar("2026-11-06")))
        self.assertEqual(len(provenance["warnings"]), 1)
        self.assertIn("--assume-session-close", provenance["warnings"][0])

    def test_a_daily_fetch_right_after_the_close_does_not_warn(self):
        _, provenance = collect(("sh.600519",), date(2026, 11, 18), date(2026, 11, 19),
                                clock=clock_at(day=20), fetch=source(bar("2026-11-19")))
        self.assertEqual(provenance["warnings"], [])


@unittest.skipUnless(importlib.util.find_spec("pyarrow"), "需要 research 额外依赖（pyarrow）")
class SnapshotSeamTests(unittest.TestCase):
    def test_a_collected_csv_becomes_a_snapshot_unchanged(self):
        from stock_predict_mailer.core import Config
        from stock_predict_mailer.data import import_csv

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "bars.csv"
            run("sh.600519", "2026-11-18", "2026-11-19", output,
                clock=clock_at(), fetch=source(bar("2026-11-19")))
            summary = import_csv(Config(root), output)
            self.assertTrue((root / "snapshots" / summary["snapshot_id"]).is_dir())
        self.assertEqual(summary["row_count"], 1)
        self.assertEqual(summary["security_count"], 1)
        self.assertEqual(summary["sources"], ["market_eastmoney"])


class CliTests(unittest.TestCase):
    def test_unknown_source_exits_as_a_plugin_error(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()) as out:
            code = main(["bars-fetch", "--symbols", "sh.600519", "--start", "2026-11-18", "--end", "2026-11-19",
                         "--output", str(Path(folder, "bars.csv")), "--source", "market_wind"])
        self.assertEqual(code, 2)
        self.assertIn("PLUGIN_NOT_FOUND", out.getvalue())

    def test_a_source_without_bars_exits_as_a_fetch_error(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()) as out:
            code = main(["bars-fetch", "--symbols", "sh.600519", "--start", "2026-11-18", "--end", "2026-11-19",
                         "--output", str(Path(folder, "bars.csv")), "--source", "market_sina"])
        self.assertEqual(code, 2)
        self.assertIn("FETCH_FAILED", out.getvalue())


if __name__ == "__main__":
    unittest.main()
