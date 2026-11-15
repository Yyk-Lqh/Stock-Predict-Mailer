"""Synthetic provider responses and temporary files; no external collection."""
import csv
import hashlib
import importlib.util
import json
import socket
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from mcp_server import quality, server
from mcp_server.fundamental_snapshot import normalize_row, write_cutoff_view

NOW = datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc)
HAS_CRAWLER = all(importlib.util.find_spec(n) for n in ("requests", "pandas", "baostock"))


def row(code="000001", **updates):
    return dict({"f12": code, "f14": "SYNTHETIC", "f2": 1234, "f15": 1300,
                 "f16": 1100, "f17": 1200, "f18": 1190, "f5": 42}, **updates)


def fundamental(pub="2026-10-25", **updates):
    return dict({"code": "000001", "report_date": "2026-09-30", "pubDate": pub,
                 "roeAvg": 0.1, "publication_verified": True, "collected_at": NOW.isoformat()}, **updates)


class QualityTests(unittest.TestCase):
    def test_shanghai_midnight_and_previous_quarter(self):
        with patch.object(quality, "utc_now", return_value=NOW.replace(hour=16)):
            self.assertEqual(quality.today(), "2026-11-16")
        for value, expected in (("2026-01-01", (2025, 4)), ("2026-09-30", (2026, 2)),
                                ("2026-10-01", (2026, 3))):
            self.assertEqual(quality.previous_quarter(value), expected)

    def test_cutoff_is_explicit_iso_and_cannot_be_future(self):
        with patch.object(quality, "utc_now", return_value=NOW):
            self.assertEqual(quality.cutoff_date().isoformat(), "2026-11-15")
            for value in ("", "20261115", "2026-02-30", "2026-11-16"):
                with self.subTest(value=value), self.assertRaises(quality.DataQualityError):
                    quality.cutoff_date(value)

    def test_cache_age_boundaries_and_unknown_time(self):
        with patch.object(quality, "utc_now", return_value=NOW):
            for age, expected in ((300, "fresh"), (301, "stale")):
                value = {"fetched_at": (NOW - timedelta(seconds=age)).isoformat()}
                self.assertEqual(quality.cache_state(value)[0], expected)
            self.assertEqual(quality.cache_state(None), ("unverified", None))
            for at in ("2026-11-15T08:00:00", (NOW + timedelta(minutes=1)).isoformat()):
                with self.assertRaises(quality.DataQualityError):
                    quality.cache_state({"fetched_at": at})

    def test_invalid_cache_limits_and_numbers(self):
        for value in (-1, 86401, True, 1.5):
            with self.assertRaises(quality.DataQualityError):
                quality.cache_state(None, value)
        for value in (True, "nan", float("inf"), "broken"):
            with self.assertRaises(quality.DataQualityError):
                quality.number(value)
        for value in (None, "", "--"):
            self.assertIsNone(quality.number(value))
        self.assertEqual(quality.number("-1.5"), -1.5)

    def test_strict_json_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "data.json"
            for raw in ('{"key":1,"key":2}', '{"value":NaN}'):
                path.write_text(raw)
                with self.assertRaises(quality.DataQualityError):
                    quality.read_json(path)
            path.write_bytes(b"previous")
            with patch.object(quality.os, "replace", side_effect=OSError("synthetic failure")), self.assertRaises(OSError):
                quality.atomic_bytes(path, b"new")
            self.assertEqual(path.read_bytes(), b"previous")
            self.assertEqual(list(Path(temporary).iterdir()), [path])

    def test_sidecar_detects_tampered_or_interrupted_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "data.csv"
            quality.write_snapshot(path, b"original", {"fetched_at": NOW.isoformat()})
            with patch.object(quality, "utc_now", return_value=NOW):
                self.assertEqual(quality.snapshot_status(path)["integrity"], "verified")
            path.write_bytes(b"modified")
            self.assertEqual(quality.snapshot_status(path)["integrity"], "invalid")

    def test_cutoff_view_excludes_late_or_unknown_disclosure_without_touching_master(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(quality, "utc_now", return_value=NOW):
            master = Path(temporary) / "master.csv"
            master.write_bytes(b"retained future records")
            output = Path(temporary) / "view.csv"
            rows = [fundamental(), fundamental("2026-11-16", code="000002"),
                    fundamental("", code="000003"), fundamental(code="000004", publication_verified=False)]
            meta = write_cutoff_view(output, rows, "2026-11-15", {"pubDate": "pub_date", "roeAvg": "ROE"}, {})
            with output.open(encoding="utf-8-sig", newline="") as stream:
                values = list(csv.DictReader(stream))
            self.assertEqual([r["code"] for r in values], ["000001"])
            self.assertEqual(meta["excluded"], {"missing_disclosure": 2, "after_cutoff": 1})
            self.assertFalse(meta["point_in_time_verified"])
            self.assertIsNone(meta["fetched_at"])
            self.assertEqual(master.read_bytes(), b"retained future records")

    def test_quarter_cutoff_and_bad_fundamental_records(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(quality, "utc_now", return_value=NOW):
            meta = write_cutoff_view(Path(temporary) / "v.csv", [fundamental("2026-09-30")],
                                     "2026-09-30", {"pubDate": "pub_date", "roeAvg": "ROE"}, {})
            self.assertEqual(meta["row_count"], 0)
        for value in (fundamental(code="1"), fundamental(report_date="2026-09-29"),
                      fundamental("2026-09-01"), fundamental(roeAvg="not a number")):
            with self.subTest(value=value), self.assertRaises(quality.DataQualityError):
                normalize_row(value, ["roeAvg"])

    def test_mcp_preserves_quality_error_code(self):
        result = json.loads(server._error(quality.DataQualityError("CACHE_STALE", "expired", age=301)))
        self.assertEqual(result["error"]["code"], "CACHE_STALE")
        self.assertEqual(result["details"], {"age": 301})


@unittest.skipUnless(HAS_CRAWLER, "requires crawler extra")
class CatalogTests(unittest.TestCase):
    def setUp(self):
        from mcp_server import catalog_crawler
        self.catalog = catalog_crawler
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache, self.output = self.root / "cache.json", self.root / "stocks.csv"
        for target, value in (("CACHE_FILE", str(self.cache)), ("OUTPUT_FILE", str(self.output))):
            context = patch.object(self.catalog, target, value)
            context.start()
            self.addCleanup(context.stop)
        context = patch.object(quality, "utc_now", return_value=NOW)
        context.start()
        self.addCleanup(context.stop)
        context = patch.object(self.catalog, "utc_now", return_value=NOW)
        context.start()
        self.addCleanup(context.stop)

    def snapshot(self, age=0):
        return {"cache_version": 1, "metadata": {"source": "eastmoney", "source_url": self.catalog.URL,
                "fetched_at": (NOW - timedelta(seconds=age)).isoformat(), "source_as_of": None,
                "completeness": "complete", "row_count": 1, "expected_count": 1},
                "data": {"total": 1, "diff": [row()]}}

    def api(self, responses):
        session = Mock()
        session.get.side_effect = responses
        context = patch.object(self.catalog.requests, "Session")
        factory = context.start()
        factory.return_value.__enter__.return_value = session
        self.addCleanup(context.stop)
        context = patch.object(self.catalog.time, "sleep")
        context.start()
        self.addCleanup(context.stop)
        return session

    def response(self, total, rows):
        result = Mock()
        result.json.return_value = {"data": {"total": total, "diff": rows}}
        return result

    def test_fresh_cache_preserves_actual_fetch_time_and_unknown_source_time(self):
        quality.atomic_json(self.cache, self.snapshot(100))
        with patch.object(self.catalog, "_fetch_from_api", side_effect=AssertionError("must not fetch")):
            result = self.catalog.crawl_catalog()
        self.assertTrue(result["ok"])
        self.assertEqual(result["cache_age_seconds"], 100)
        self.assertIsNone(result["metadata"]["source_as_of"])
        self.assertEqual(result["metadata"]["csv_sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())

    def test_expired_cache_requires_explicit_override_without_network(self):
        quality.atomic_json(self.cache, self.snapshot(301))
        self.output.write_bytes(b"previous")
        with self.assertRaises(quality.DataQualityError) as caught:
            self.catalog.crawl_catalog()
        self.assertEqual(caught.exception.code, "CACHE_STALE")
        self.assertEqual(self.output.read_bytes(), b"previous")
        result = self.catalog.crawl_catalog(allow_stale=True)
        self.assertEqual(result["cache_state"], "stale")
        self.assertFalse(result["analysis_eligible"])

    def test_legacy_cache_is_explicitly_unverified(self):
        quality.atomic_json(self.cache, {"data": {"diff": [row()]}})
        with self.assertRaises(quality.DataQualityError) as caught:
            self.catalog.crawl_catalog()
        self.assertEqual(caught.exception.code, "CACHE_UNVERIFIED")
        result = self.catalog.crawl_catalog(allow_stale=True)
        self.assertEqual(result["completeness"], "unknown")
        self.assertFalse(result["analysis_eligible"])

    def test_fresh_network_snapshot_writes_cache_and_manifest(self):
        self.api([self.response(1, [row()])])
        result = self.catalog.crawl_catalog()
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "网络快照")
        self.assertEqual(quality.read_json(self.cache)["cache_version"], 1)
        self.assertEqual(quality.snapshot_status(self.output)["completeness"], "complete")

    def test_later_page_failure_preserves_previous_cache_and_csv(self):
        quality.atomic_json(self.cache, self.snapshot())
        old_cache = self.cache.read_bytes()
        self.output.write_bytes(b"previous csv")
        self.api([self.response(2, [row()]), self.catalog.requests.ConnectionError("synthetic")])
        result = self.catalog.crawl_catalog(force_refresh=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "PARTIAL_DATA")
        self.assertEqual(self.cache.read_bytes(), old_cache)
        self.assertEqual(self.output.read_bytes(), b"previous csv")

    def test_duplicate_pages_or_total_changes_do_not_become_complete(self):
        for response in (self.response(2, [row()]), self.response(3, [row("000002")]), self.response(2, [])):
            self.api([self.response(2, [row()]), response])
            result = self.catalog.crawl_catalog(force_refresh=True)
            self.assertEqual(result["completeness"], "partial")
            self.assertFalse(self.output.exists())

    def test_invalid_values_do_not_overwrite_existing_snapshot(self):
        for value in (row("123"), row(f2=float("nan")), row(f5=-1), row(f15=1000), row(f14="")):
            self.output.write_bytes(b"previous")
            self.api([self.response(1, [value])])
            with self.subTest(value=value), self.assertRaises(quality.DataQualityError):
                self.catalog.crawl_catalog(force_refresh=True)
            self.assertEqual(self.output.read_bytes(), b"previous")

    def test_valid_multiple_pages_reach_unique_total(self):
        self.api([self.response(2, [row()]), self.response(2, [row("000002")])])
        result = self.catalog.crawl_catalog()
        self.assertEqual(result["completeness"], "complete")
        self.assertEqual(result["stock_count"], 2)
        self.assertEqual(result["metadata"]["pages"], 2)

    def test_empty_first_response_and_forged_counts_are_rejected(self):
        self.api([self.response(0, [])])
        with self.assertRaises(quality.DataQualityError):
            self.catalog.crawl_catalog()
        snapshot = self.snapshot()
        snapshot["metadata"]["expected_count"] = 2
        quality.atomic_json(self.cache, snapshot)
        with self.assertRaises(quality.DataQualityError):
            self.catalog.crawl_catalog()
        self.assertFalse(self.output.exists())


@unittest.skipUnless(HAS_CRAWLER, "requires crawler extra")
class FundamentalTests(unittest.TestCase):
    def setUp(self):
        previous_timeout = socket.getdefaulttimeout()
        self.addCleanup(socket.setdefaulttimeout, previous_timeout)
        from mcp_server import fundamental_crawler
        self.fund = fundamental_crawler
        context = patch.object(self.fund, "_reconnect")
        context.start()
        self.addCleanup(context.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for target, value in (("DATA_DIR", str(self.root)), ("POOL_FILE", str(self.root / "pool.csv")),
                              ("OUTPUT_FILE", str(self.root / "master.csv")), ("LOG_FILE", str(self.root / "log.txt"))):
            context = patch.object(self.fund, target, value)
            context.start()
            self.addCleanup(context.stop)
        context = patch.object(quality, "utc_now", return_value=NOW)
        context.start()
        self.addCleanup(context.stop)
        Path(self.fund.POOL_FILE).write_text("股票代码\n000001\n000002\n", encoding="utf-8-sig")

    def test_unverified_pool_requires_explicit_override(self):
        with self.assertRaises(quality.DataQualityError) as caught:
            self.fund.collect_fundamental()
        self.assertEqual(caught.exception.code, "POOL_UNVERIFIED")

    def test_corrupt_baseline_is_not_silently_discarded(self):
        master = Path(self.fund.OUTPUT_FILE)
        master.write_text("bad,data\n1,2\n")
        with self.assertRaises(quality.DataQualityError):
            self.fund.collect_fundamental(allow_unverified_pool=True)
        self.assertEqual(master.read_text(), "bad,data\n1,2\n")

    def test_default_cutoff_uses_today_and_marks_limited_scope(self):
        with (patch.object(self.fund, "_preflight", return_value=True),
              patch.object(self.fund, "_fetch_stock", return_value=[fundamental()]),
              patch.object(self.fund.bs, "logout")):
            result = self.fund.collect_fundamental(max_stocks=1, allow_unverified_pool=True)
        self.assertEqual(result["crawl_date"], "2026-11-15")
        self.assertEqual(result["end_quarter"], "2026Q3")
        self.assertEqual(result["completeness"], "partial")
        self.assertTrue(result["scope_limited"])
        self.assertEqual(result["view_metadata"]["row_count"], 1)

    def test_failure_after_one_success_is_partial(self):
        with (patch.object(self.fund, "_preflight", return_value=True),
              patch.object(self.fund, "_fetch_stock", side_effect=[[fundamental()], RuntimeError("synthetic failure")]),
              patch.object(self.fund.bs, "logout")):
            result = self.fund.collect_fundamental(allow_unverified_pool=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], ["000002"])
        self.assertEqual(result["completeness"], "partial")

    def test_joined_fact_with_missing_disclosure_stays_unverified(self):
        values = [{"2026-09-30": {"pubDate": "2026-10-25", "roeAvg": "0.1"}},
                  {"2026-09-30": {"liabilityToAsset": "0.5"}}, {}, {}]
        with patch.object(self.fund, "_query", side_effect=values):
            result = self.fund._fetch_stock("000001", quarters=[(2026, 3)])
        self.assertFalse(result[0]["publication_verified"])

    def test_historical_cutoff_view_preserves_later_master_records(self):
        earlier = fundamental("2026-07-20", report_date="2026-06-30")
        later = fundamental(code="000002")
        self.fund._save([earlier, later])
        before = Path(self.fund.OUTPUT_FILE).read_bytes()
        with patch.object(self.fund, "_preflight", side_effect=AssertionError("must not fetch")):
            result = self.fund.collect_fundamental(end_date="2026-09-01", allow_unverified_pool=True)
        self.assertEqual(result["crawl_date"], "2026-09-01")
        self.assertEqual(result["view_metadata"]["row_count"], 1)
        self.assertEqual(Path(self.fund.OUTPUT_FILE).read_bytes(), before)
        self.assertFalse(result["view_metadata"]["point_in_time_verified"])

    def test_invalid_pool_sidecar_cannot_be_bypassed(self):
        Path(self.fund.POOL_FILE + ".metadata.json").write_text('{"csv_sha256":"wrong"}')
        with self.assertRaises(quality.DataQualityError):
            self.fund.collect_fundamental(allow_unverified_pool=True)

    def test_valid_looking_but_tampered_baseline_is_rejected(self):
        self.fund._save([fundamental()])
        master = Path(self.fund.OUTPUT_FILE)
        master.write_bytes(master.read_bytes().replace(b"000001", b"000003"))
        with self.assertRaises(quality.DataQualityError):
            self.fund._load_existing()
