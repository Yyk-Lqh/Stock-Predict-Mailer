import base64
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from stock_predict_mailer import __version__
from stock_predict_mailer.agent_service.charts import chart_svg
from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.agent_service.png import chart_png
from stock_predict_mailer.agent_service.reporting import render, save_report
from stock_predict_mailer.cli import main
from stock_predict_mailer.control.market_feed import MarketFeed
from stock_predict_mailer.plugins import github, registry
from stock_predict_mailer.plugins.builtin import market as market_module
from stock_predict_mailer.plugins.builtin import report as report_module
from stock_predict_mailer.plugins.builtin.eastmoney import EastmoneyError, EastmoneySource
from stock_predict_mailer.plugins.builtin.eastmoney import parse_candles as eastmoney_candles
from stock_predict_mailer.plugins.builtin.eastmoney import parse_quotes as eastmoney_quotes
from stock_predict_mailer.plugins.builtin.market import TencentSource
from stock_predict_mailer.plugins.contract import API_VERSION, PluginManifest, declare
from stock_predict_mailer.plugins.doctor import check
from stock_predict_mailer.plugins.errors import (
    PluginError,
    PluginIncompatible,
    PluginKindMismatch,
    PluginMissingDependency,
    PluginNotFound,
)
from stock_predict_mailer.plugins.registry import Registry


def prediction(**overrides):
    base = {"generated_at": "2026-11-19T10:00:00+08:00", "synthetic": True, "subject": "SYN000",
            "model_version": "demo", "horizon": {"value": 5, "unit": "d"}, "confidence": None, "metrics": {}}
    return {**base, **overrides}


def analysis(**overrides):
    base = {"analysis_id": "A-demo", "status": "ok", "mode": "deterministic", "prediction": prediction(),
            "facts": [], "inferences": [], "limitations": [], "risks": [], "recommendations": [], "charts": []}
    return {**base, **overrides}


def fake_source(plugin_id="market_fake", **declaration):
    class Fake:
        manifest = declare(id=plugin_id, kind="market_source", label="假行情", capabilities=("quotes",), **declaration)

        @staticmethod
        def quotes(instruments, timeout):
            return []

    return Fake()


class DeclarationTests(unittest.TestCase):
    def test_manifest_defaults_to_the_current_api_version(self):
        self.assertEqual(declare(id="market_a", kind="market_source", label="甲", capabilities=("quotes",)).api_version, API_VERSION)

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(PluginIncompatible):
            declare(id="market_a", kind="chat_bot", label="甲", capabilities=("quotes",))

    def test_capability_must_belong_to_the_declared_kind(self):
        with self.assertRaises(PluginIncompatible):
            declare(id="mail_a", kind="notifier", label="甲", capabilities=("quotes",))

    def test_duplicate_capability_is_rejected(self):
        with self.assertRaises(PluginIncompatible):
            declare(id="market_a", kind="market_source", label="甲", capabilities=("quotes", "quotes"))

    def test_optional_dependency_without_extra_name_is_rejected(self):
        with self.assertRaises(PluginIncompatible):
            declare(id="market_a", kind="market_source", label="甲", capabilities=("quotes",), requires=("akshare",))

    def test_malformed_id_is_rejected(self):
        with self.assertRaises(PluginIncompatible):
            declare(id="Market-A", kind="market_source", label="甲", capabilities=("quotes",))


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()

    def test_builtin_market_sources_keep_display_priority(self):
        declared = [adapter.manifest.label for adapter in registry.select("market_source")]
        self.assertEqual(declared, ["腾讯行情", "新浪行情", "东方财富行情"])
        self.assertEqual([label for label, _ in registry.market_fetchers()], ["腾讯行情", "新浪行情"])

    def test_undeclared_id_is_refused_rather_than_guessed(self):
        with self.assertRaises(PluginNotFound):
            registry.resolve("market_akshare")

    def test_wrong_kind_is_refused(self):
        with self.assertRaises(PluginKindMismatch):
            registry.resolve("market_tencent", kind="notifier")

    def test_unknown_kind_argument_is_refused(self):
        with self.assertRaises(PluginIncompatible):
            self.registry.select("something_else")

    def test_duplicate_id_is_refused(self):
        with self.assertRaises(PluginError) as caught:
            Registry((fake_source(), fake_source()))
        self.assertIn("重复", str(caught.exception))

    def test_another_api_version_is_refused(self):
        class Future:
            manifest = PluginManifest(id="market_future", kind="market_source", label="未来源",
                                      capabilities=("quotes",), api_version=API_VERSION + 1)

            @staticmethod
            def quotes(instruments, timeout):
                return []

        with self.assertRaises(PluginIncompatible):
            Registry((Future(),))

    def test_declaring_candles_without_implementing_them_is_refused(self):
        class Half:
            manifest = declare(id="market_half", kind="market_source", label="半个源",
                               capabilities=("quotes", "candles"))

            @staticmethod
            def quotes(instruments, timeout):
                return []

        with self.assertRaises(PluginIncompatible):
            Registry((Half(),))

    def test_missing_optional_dependency_names_the_extra(self):
        registry_with_extra = Registry((fake_source(requires=("definitely_absent_module",), extra="crawler"),))
        self.assertFalse(registry_with_extra.available("market_fake"))
        with self.assertRaises(PluginMissingDependency) as caught:
            registry_with_extra.resolve("market_fake")
        self.assertIn("definitely_absent_module", str(caught.exception))
        self.assertIn(".[crawler]", str(caught.exception))

    def test_resolve_many_refuses_to_skip_an_unavailable_plugin(self):
        registry_with_extra = Registry((fake_source(requires=("definitely_absent_module",), extra="crawler"),))
        with self.assertRaises(PluginMissingDependency):
            registry_with_extra.resolve_many("market_source", ("market_fake",))

    def test_notifier_table_stays_empty_until_the_mail_transports_change_shape(self):
        self.assertEqual(registry.select("notifier"), ())

    def test_describe_reports_every_declared_plugin(self):
        described = registry.describe()
        self.assertEqual(described["api_version"], API_VERSION)
        self.assertEqual([item["id"] for item in described["plugins"]],
                         ["market_tencent", "market_sina", "market_eastmoney", "export_csv", "export_jsonl",
                          "export_parquet", "report_text", "report_html", "chart_line", "chart_bar",
                          "report_dashboard", "report_evidence"])
        self.assertTrue(all(item["available"] for item in described["plugins"]))

    def test_error_payload_matches_the_cli_envelope(self):
        payload = PluginMissingDependency("缺依赖").as_dict()
        self.assertEqual(payload, {"error": {"code": "PLUGIN_MISSING_DEPENDENCY", "message": "缺依赖", "retryable": False}})


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.analysis = analysis()
        self.view = {"analysis": self.analysis, "timezone": "Asia/Shanghai", "charts": "inline"}

    def test_builtin_reporters_declare_one_format_each(self):
        declared = {adapter.manifest.id: adapter.manifest.capabilities for adapter in registry.select("report_renderer")}
        self.assertEqual(declared, {"report_text": ("text",), "report_html": ("html",),
                                    "report_dashboard": ("html",), "report_evidence": ("html",)})

    def test_public_render_routes_through_the_declared_reporters(self):
        text, html = render(self.analysis)
        self.assertEqual(text, registry.resolve("report_text").render(self.view).decode("utf-8"))
        self.assertEqual(html, registry.resolve("report_html").render(self.view).decode("utf-8"))

    def test_html_reporter_escapes_upstream_text(self):
        script = "<script>alert(1)</script>"
        _, html = render(analysis(prediction=prediction(subject=script)))
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn(script, html)

    def test_text_reporter_keeps_upstream_text_unmodified(self):
        script = "<script>alert(1)</script>"
        text, _ = render(analysis(prediction=prediction(subject=script)))
        self.assertIn(script, text)

    def test_chart_mode_switches_between_inline_svg_and_cid_reference(self):
        chart = {"title": "走势", "caption": "说明", "unit": "元",
                 "series": {"observed": {"source": "本地", "points": [{"at": "2026-11-18T00:00:00+08:00", "value": 1.0}]}}}
        body = analysis(charts=[chart])
        _, inline = render(body)
        _, cid = render(body, charts="cid")
        self.assertIn("<svg", inline)
        self.assertIn("cid:chart-0@stock-predict-mailer.local", cid)
        self.assertNotIn("<svg", cid)

    def test_chart_plugins_render_the_same_series_as_lines_or_grouped_bars(self):
        first, second = "2026-11-18T00:00:00+08:00", "2026-11-19T00:00:00+08:00"
        chart = {"title": "走势", "caption": "说明", "unit": "元", "series": {
            "observed": {"source": "本地观测", "points": [{"at": first, "value": -2}, {"at": second, "value": 3}]},
            "forecast": {"source": "本地模型", "points": [{"at": second, "value": 5, "lower": 4, "upper": 6}]},
        }}
        bars = {**chart, "renderer": "chart_bar"}
        line, bar = chart_svg(chart), chart_svg(bars)
        self.assertIn("<polyline", line)
        self.assertNotIn("<polyline", bar)
        self.assertRegex(bar, r'<rect [^>]*fill="#17634d"')
        self.assertRegex(bar, r'<rect [^>]*fill="#2356a3"')
        line_png, bar_png = chart_png(chart), chart_png(bars)
        self.assertTrue(bar_png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertNotEqual(line_png, bar_png)

    def test_selected_page_renders_escaped_evidence_and_records_its_provenance(self):
        source = '<script>alert(1)</script>'
        fact = {"id": "fact-1", "name": "收盘价", "value": 10, "unit": "元", "source": source,
                "observed_at": "2026-11-18T00:00:00+08:00", "available_at": "2026-11-18T01:00:00+08:00"}
        body = analysis(facts=[fact], report_renderer="report_evidence")
        with tempfile.TemporaryDirectory() as folder:
            path = save_report(Path(folder), body)
            page = (path / "report.html").read_text(encoding="utf-8")
            provenance = json.loads((path / "renderers.json").read_text(encoding="utf-8"))
        self.assertIn("<td>&lt;script&gt;alert(1)&lt;/script&gt;</td>", page)
        self.assertNotIn(source, page)
        self.assertEqual(provenance["renderers"][1]["id"], "report_evidence")
        self.assertIn("分析概览", render({**body, "report_renderer": "report_dashboard"})[1])
        self.assertNotIn("客观事实来源</h2>", render(body, charts="cid")[1])


class WiringTests(unittest.TestCase):
    def test_market_feed_defaults_come_from_the_registry(self):
        feed = MarketFeed()
        self.assertEqual([label for label, _ in feed.fetchers], ["腾讯行情", "新浪行情"])
        self.assertIs(feed.candles, TencentSource.candles)

    def test_candles_come_from_the_source_declaring_the_capability(self):
        self.assertIs(registry.market_candles(), TencentSource.candles)

    def test_explicit_fetchers_still_override_the_table(self):
        feed = MarketFeed(fetchers=[("自建源", lambda instruments, timeout: [])], candles=lambda symbol, timeout: [])
        self.assertEqual([label for label, _ in feed.fetchers], ["自建源"])


def eastmoney_body(rows=None, klines=None):
    data = {"rc": 0, "data": {"diff": rows} if rows is not None else {"klines": klines}}
    return json.dumps(data, ensure_ascii=False)


def eastmoney_row(code, market, name, last, change, stamp=1794553200):
    return {"f12": code, "f13": market, "f14": name, "f2": last, "f3": change, "f124": stamp}


class EastmoneyTests(unittest.TestCase):
    def test_quotes_follow_configured_order_and_fields(self):
        body = eastmoney_body(rows=[eastmoney_row("399001", 0, "深证成指", 10583.2, -0.71),
                                    eastmoney_row("000001", 1, "上证指数", 3577.62, -0.28)])
        rows = eastmoney_quotes(body, (("sh000001", "上证指数"), ("sz399001", "深证成指")))
        self.assertEqual([row["symbol"] for row in rows], ["sh000001", "sz399001"])
        self.assertEqual(rows[0]["name"], "上证指数")
        self.assertEqual(rows[0]["last"], 3577.62)
        self.assertEqual(rows[0]["change_pct"], -0.28)
        self.assertEqual(rows[0]["at"].isoformat(), "2026-11-13T15:00:00+08:00")

    def test_missing_symbol_and_suspended_price_are_rejected(self):
        body = eastmoney_body(rows=[eastmoney_row("000001", 1, "上证指数", 3577.62, -0.28)])
        with self.assertRaises(EastmoneyError):
            eastmoney_quotes(body, (("sz399001", "深证成指"),))
        halted = eastmoney_body(rows=[eastmoney_row("000001", 1, "上证指数", "-", -0.28)])
        with self.assertRaises(EastmoneyError):
            eastmoney_quotes(halted, (("sh000001", "上证指数"),))

    def test_implausible_change_and_timestamp_are_rejected(self):
        with self.assertRaises(EastmoneyError):
            eastmoney_quotes(eastmoney_body(rows=[eastmoney_row("000001", 1, "上证指数", 3577.62, 139)]),
                             (("sh000001", ""),))
        with self.assertRaises(EastmoneyError):
            eastmoney_quotes(eastmoney_body(rows=[eastmoney_row("000001", 1, "上证指数", 3577.62, -0.28, stamp=0)]),
                             (("sh000001", ""),))

    def test_non_json_and_missing_data_are_rejected(self):
        for body in ("not json", json.dumps({"rc": 0, "data": None})):
            with self.assertRaises(EastmoneyError):
                eastmoney_quotes(body, (("sh000001", ""),))

    def test_candles_keep_ohlc_and_reject_inverted_ranges(self):
        good = eastmoney_body(klines=["2026-11-18,3596.55,3587.83,3596.55,3560.45,423934832,650231688071.30,1.01",
                                      "2026-11-19,3583.12,3577.62,3584.28,3547.94,412912755,636909057689.00,1.01"])
        rows = eastmoney_candles(good, "sh000001")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["close"], 3577.62)
        self.assertEqual(rows[-1]["volume"], 412912755.0)
        bad = good.replace("3584.28,3547.94", "3570.00,3547.94")
        with self.assertRaises(EastmoneyError):
            eastmoney_candles(bad, "sh000001")

    def test_too_few_or_short_candles_are_rejected(self):
        with self.assertRaises(EastmoneyError):
            eastmoney_candles(eastmoney_body(klines=["2026-11-19,3583.12,3577.62,3584.28,3547.94,412912755"]), "sh000001")
        with self.assertRaises(EastmoneyError):
            eastmoney_candles(eastmoney_body(klines=["2026-11-19,3583.12"]), "sh000001")


class TencentBarsTests(unittest.TestCase):
    @staticmethod
    def body(rows, symbol="sh600519"):
        return json.dumps({"code": 0, "data": {symbol: {"day": rows}}})

    def test_field_order_is_date_open_close_high_low_volume(self):
        rows = market_module.parse_bars(
            self.body([["2026-11-19", "1442.000", "1460.210", "1464.990", "1432.100", "42692.000"]]), "sh600519")
        self.assertEqual((rows[0]["open"], rows[0]["close"], rows[0]["high"], rows[0]["low"], rows[0]["volume"]),
                         (1442.0, 1460.21, 1464.99, 1432.1, 42692.0))

    def test_bad_payloads_are_refused(self):
        for text in ("not json", json.dumps({"code": 0, "data": {}}),
                     self.body([["2026-11-19", "1442.0", "1460.2", "1432.0", "1435.0", "1"]]),
                     self.body([["2026-11-19", "1442.0", "-1", "1464.9", "1432.1", "1"]]),
                     self.body([["2026-11-19", "1442.0", "1460.2"]])):
            with self.assertRaises(market_module.TencentError):
                market_module.parse_bars(text, "sh600519")

    def test_long_windows_are_split_into_yearly_chunks(self):
        calls = []

        def fake(url, timeout):
            calls.append(url)
            return self.body([["2026-11-19", "1", "2", "3", "0.5", "7"]])

        with mock.patch.object(market_module, "_get", fake):
            rows = market_module.TencentSource.bars("sh600519", date(2024, 1, 1), date(2026, 11, 20), 5)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all("param=sh600519,day," in url for url in calls))
        self.assertEqual(len(rows), 3)


class ExporterTests(unittest.TestCase):
    ROWS = [{"date": "2026-11-18", "security_id": "sh.600519", "open": 1.0, "high": 2.0, "low": 0.5,
             "close": 1.5, "volume": 100.0, "available_at": "2026-11-18T18:00:00+08:00", "source": "test"},
            {"date": "2026-11-19", "security_id": "sz.000001", "open": 2.0, "high": 3.0, "low": 1.5,
             "close": 2.5, "volume": 200.0, "available_at": "2026-11-19T18:00:00+08:00", "source": "test"}]

    def test_each_format_is_declared_by_exactly_one_exporter(self):
        declared = {adapter.manifest.id: adapter.manifest.capabilities for adapter in registry.select("exporter")}
        self.assertEqual(declared, {"export_csv": ("csv",), "export_jsonl": ("json",), "export_parquet": ("parquet",)})
        self.assertIn("exporter", registry.describe()["kinds"])

    def test_csv_keeps_the_contract_column_order(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bars.csv"
            result = registry.exporter("csv").export(self.ROWS, path)
            lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "date,security_id,open,high,low,close,volume,available_at,source")
        self.assertEqual(len(lines), 3)
        self.assertEqual((result["format"], result["rows"]), ("csv", 2))

    def test_json_lines_export_writes_one_object_per_row(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bars.jsonl"
            registry.exporter("json").export(self.ROWS, path)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["security_id"] for row in rows], ["sh.600519", "sz.000001"])
        self.assertEqual(rows[0]["close"], 1.5)

    def test_an_undeclared_format_is_refused(self):
        with self.assertRaises(PluginNotFound):
            registry.exporter("xlsx")

    @unittest.skipUnless(importlib.util.find_spec("pyarrow"), "需要 research 额外依赖（pyarrow）")
    def test_the_command_resolves_the_declared_exporter(self):
        import csv as csv_module

        from stock_predict_mailer.core import Config
        from stock_predict_mailer.data import FIELDS, import_csv

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "ws"
            root.mkdir()
            config = Path(folder) / "config.toml"
            config.write_text('workspace = "./ws"\ntimezone = "Asia/Shanghai"\n', encoding="utf-8")
            raw = Path(folder) / "bars.csv"
            buffer = io.StringIO()
            writer = csv_module.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(self.ROWS)
            raw.write_text(buffer.getvalue(), encoding="utf-8")
            snapshot = import_csv(Config(root), raw)["snapshot_id"]
            output = Path(folder) / "out.csv"
            with redirect_stdout(io.StringIO()):
                code = main(["legacy", "--config", str(config), "dataset-export", snapshot,
                             "--format", "csv", "--output", str(output)])
            self.assertEqual(code, 0)
            self.assertEqual(len(output.read_text(encoding="utf-8").splitlines()), 3)

            plugin_root = Path(folder) / "console"
            plugin_root.mkdir()
            raw_manifest = json.dumps({"id": "export_array", "kind": "exporter", "label": "数组",
                                       "api_version": 1, "export": {"format": "json", "indent": 2}}).encode()
            with mock.patch.object(github, "_download", return_value=raw_manifest):
                github.install(plugin_root, "https://github.com/example/exporter")
            output = Path(folder) / "out.json"
            with redirect_stdout(io.StringIO()) as stdout:
                code = main(["legacy", "--config", str(config), "dataset-export", snapshot, "--plugin", "export_array",
                             "--plugin-workspace", str(plugin_root), "--output", str(output)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), self.ROWS)
            self.assertEqual(json.loads(stdout.getvalue())["manifest_sha256"], hashlib.sha256(raw_manifest).hexdigest())

    @unittest.skipUnless(importlib.util.find_spec("pyarrow"), "需要 research 额外依赖（pyarrow）")
    def test_parquet_export_round_trips(self):
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bars.parquet"
            registry.exporter("parquet").export(self.ROWS, path)
            table = pq.read_table(path)
        self.assertEqual(table.num_rows, 2)
        self.assertEqual(table.column_names, ["date", "security_id", "open", "high", "low", "close", "volume",
                                              "available_at", "source"])


class SourceSelectionTests(unittest.TestCase):
    def test_eastmoney_is_declared_but_absent_from_the_default_chain(self):
        declared = [adapter.manifest.id for adapter in registry.select("market_source")]
        self.assertIn("market_eastmoney", declared)
        self.assertEqual([label for label, _ in registry.market_fetchers()], ["腾讯行情", "新浪行情"])

    def test_selecting_eastmoney_replaces_the_whole_chain(self):
        self.assertEqual([label for label, _ in registry.market_fetchers(("market_eastmoney",))], ["东方财富行情"])
        self.assertIs(registry.market_candles(("market_eastmoney",)), EastmoneySource.candles)

    def test_undeclared_source_id_is_refused(self):
        with self.assertRaises(PluginNotFound):
            registry.market_fetchers(("market_wind",))

    def test_config_can_select_a_chain(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "market.json").write_text(json.dumps({"sources": ["market_eastmoney"]}), encoding="utf-8")
            feed = MarketFeed(root=Path(folder))
        self.assertEqual(feed.sources, ("market_eastmoney",))
        self.assertEqual([label for label, _ in feed.fetchers], ["东方财富行情"])
        self.assertIs(feed.candles, EastmoneySource.candles)

    def test_unknown_configured_source_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "market.json").write_text(json.dumps({"sources": ["market_wind"]}), encoding="utf-8")
            with self.assertRaises(PluginNotFound):
                MarketFeed(root=Path(folder))

    def test_duplicate_or_malformed_source_lists_are_refused(self):
        for value in (["market_tencent", "market_tencent"], "market_tencent", [], [1], ["  "]):
            with tempfile.TemporaryDirectory() as folder:
                Path(folder, "market.json").write_text(json.dumps({"sources": value}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    MarketFeed(root=Path(folder))


class CheckTests(unittest.TestCase):
    def test_default_chain_is_ready(self):
        report = check()
        self.assertTrue(report["ok"])
        self.assertIsNone(report["market_file"])
        self.assertEqual(report["source_chain"], ["market_tencent", "market_sina"])
        self.assertEqual(report["candles_from"], "market_tencent")
        self.assertEqual(report["problems"], [])
        self.assertTrue(all(row["available"] for row in report["plugins"]))

    def test_check_follows_the_workspace_config(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "market.json").write_text(json.dumps({"sources": ["market_eastmoney"]}), encoding="utf-8")
            report = check(Path(folder))
        self.assertTrue(report["ok"])
        self.assertEqual(report["source_chain"], ["market_eastmoney"])
        self.assertEqual(report["candles_from"], "market_eastmoney")

    def test_undeclared_source_is_reported_before_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "market.json").write_text(json.dumps({"sources": ["market_wind"]}), encoding="utf-8")
            report = check(Path(folder))
        self.assertFalse(report["ok"])
        self.assertEqual(report["source_chain"], [])
        self.assertEqual(len(report["problems"]), 1)
        self.assertIn("market_wind", report["problems"][0])

    def test_chain_without_a_candle_source_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "market.json").write_text(json.dumps({"sources": ["market_sina"]}), encoding="utf-8")
            report = check(Path(folder))
        self.assertFalse(report["ok"])
        self.assertEqual(report["source_chain"], ["market_sina"])
        self.assertIsNone(report["candles_from"])
        self.assertIn("candles", report["problems"][0])

    def test_duplicate_sources_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "market.json").write_text(json.dumps({"sources": ["market_tencent", "market_tencent"]}),
                                                   encoding="utf-8")
            report = check(Path(folder))
        self.assertFalse(report["ok"])
        self.assertIn("重复", report["problems"][0])

    def test_list_marks_declared_versus_enabled(self):
        described = registry.describe()
        self.assertEqual(described["default_chain"], ["market_tencent", "market_sina"])
        defaults = {entry["id"]: entry["default"] for entry in described["plugins"] if entry["kind"] == "market_source"}
        self.assertEqual(defaults, {"market_tencent": True, "market_sina": True, "market_eastmoney": False})
        self.assertFalse(any("default" in entry for entry in described["plugins"] if entry["kind"] != "market_source"))


class ProvenanceTests(unittest.TestCase):
    def test_digest_hashes_the_module_bytes(self):
        expected = hashlib.sha256(Path(report_module.__file__).read_bytes()).hexdigest()
        self.assertEqual(registry.identity("report_html")["module_digest"], expected)
        self.assertEqual(registry.identity("report_html")["module"], "stock_predict_mailer.plugins.builtin.report")

    def test_plugins_declared_in_one_module_share_a_digest(self):
        tencent, sina, html = registry.identity("market_tencent"), registry.identity("market_sina"), registry.identity("report_html")
        self.assertEqual(tencent["module"], sina["module"])
        self.assertEqual(tencent["module_digest"], sina["module_digest"])
        self.assertNotEqual(tencent["module_digest"], html["module_digest"])

    def test_unknown_plugin_has_no_identity(self):
        with self.assertRaises(PluginNotFound):
            registry.identity("market_wind")

    def test_list_reports_the_module_and_digest(self):
        for entry in registry.describe()["plugins"]:
            self.assertRegex(entry["module_digest"], r"^[0-9a-f]{64}$")
            self.assertTrue(entry["module"].startswith("stock_predict_mailer.plugins.builtin."))

    def test_report_folder_records_the_renderers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = save_report(Path(folder), analysis())
            record = json.loads((path / "renderers.json").read_text(encoding="utf-8"))
            self.assertTrue((path / "report.html").is_file())
        self.assertEqual(record["plugin_api_version"], 1)
        self.assertEqual(record["release"], __version__)
        self.assertEqual([item["format"] for item in record["renderers"]], ["text", "html"])
        self.assertEqual([item["id"] for item in record["renderers"]], ["report_text", "report_html"])
        self.assertEqual(record["renderers"][1]["module_digest"], registry.identity("report_html")["module_digest"])


class GitHubPluginTests(unittest.TestCase):
    def test_import_is_workspace_local_and_rejects_collisions(self):
        raw = b'{"id":"export_tabs","kind":"exporter","label":"TSV","api_version":1,"export":{"format":"csv","delimiter":"\\t","bom":true}}'
        body = json.dumps({"type": "file", "encoding": "base64", "size": len(raw), "content": base64.b64encode(raw).decode()})
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(github, "build_opener") as opener:
            root = Path(folder)
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = body.encode()
            url = "https://github.com/Owner/Repo/"
            entry = github.install(root, url)
            self.assertEqual(github.install(root, url), entry)
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, f"https://api.github.com/repos/owner/repo/contents/{github.MANIFEST_NAME}")
            self.assertEqual(check(root)["plugins"][-1], entry)
            self.assertEqual(github.describe(root / "other"), [])
            with self.assertRaises(PluginError):
                github.install(root, "https://github.com/other/repo")
            target = root / "output.tsv"
            github.export(root, "export_tabs", ExporterTests.ROWS, target)
            self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbfdate\tsecurity_id\t"))
            github.remove(root, "export_tabs")
            self.assertEqual(github.describe(root), [])
            with self.assertRaises(PluginNotFound):
                github.remove(root, "export_tabs")

    def test_rejects_unsupported_urls_and_manifests_without_persisting(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(github, "_download") as download:
            root = Path(folder)
            for url in ("http://github.com/o/r", "https://github.com@localhost/o/r",
                        "https://github.com/o/..", "https://github.com/o/r?ref=test"):
                with self.subTest(url=url), self.assertRaises(ServiceError):
                    github.install(root, url)
            download.assert_not_called()
            declaration = {"id": "export_custom", "kind": "exporter", "label": "Example",
                           "api_version": 1, "export": {"format": "json"}}
            for change in ({"id": "export_csv"}, {"api_version": 2}, {"kind": "notifier"}, {"python": "plugin.py"},
                           {"export": {"format": "json", "indent": True}}):
                download.return_value = json.dumps(declaration | change).encode()
                with self.subTest(change=change), self.assertRaises(PluginIncompatible):
                    github.install(root, "https://github.com/o/r")
            self.assertEqual(list(root.iterdir()), [])


class ReloadTests(unittest.TestCase):
    @staticmethod
    def write(folder, body, tick=0):
        path = Path(folder, "market.json")
        path.write_text(json.dumps(body), encoding="utf-8")
        stamp = 1_700_000_000 + tick
        os.utime(path, (stamp, stamp))

    def test_editing_sources_takes_effect_without_a_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            self.write(folder, {"sources": ["market_tencent"]})
            feed = MarketFeed(root=Path(folder))
            self.assertEqual([label for label, _ in feed.fetchers], ["腾讯行情"])
            self.write(folder, {"sources": ["market_eastmoney"]}, tick=10)
            self.assertTrue(feed.sync_config())
            self.assertEqual([label for label, _ in feed.fetchers], ["东方财富行情"])
            self.assertEqual(feed.reload_problem, "")

    def test_a_successful_reload_drops_the_cached_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            self.write(folder, {"sources": ["market_tencent"]})
            feed = MarketFeed(root=Path(folder))
            feed._retrieved, feed._candles = 123.0, ({"at": "2026-11-19"},)
            self.write(folder, {"sources": ["market_eastmoney"]}, tick=10)
            self.assertTrue(feed.sync_config())
        self.assertEqual(feed._retrieved, 0.0)
        self.assertEqual(feed._candles, ())

    def test_a_rejected_config_keeps_the_previous_chain(self):
        with tempfile.TemporaryDirectory() as folder:
            self.write(folder, {"sources": ["market_tencent"]})
            feed = MarketFeed(root=Path(folder))
            self.write(folder, {"sources": ["market_wind"]}, tick=10)
            self.assertFalse(feed.sync_config())
            self.assertEqual([label for label, _ in feed.fetchers], ["腾讯行情"])
            self.assertIn("market_wind", feed.reload_problem)
            self.assertIn("继续使用上一组行情源", feed.reload_problem)

    def test_an_unchanged_file_is_not_reapplied(self):
        with tempfile.TemporaryDirectory() as folder:
            self.write(folder, {"sources": ["market_tencent"]})
            feed = MarketFeed(root=Path(folder))
            self.assertFalse(feed.sync_config())

    def test_explicit_fetchers_are_never_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            self.write(folder, {"sources": ["market_eastmoney"]})
            feed = MarketFeed(root=Path(folder), fetchers=[("自建源", lambda instruments, timeout: [])],
                              candles=lambda symbol, timeout: [])
            self.write(folder, {"sources": ["market_sina"]}, tick=10)
            self.assertFalse(feed.sync_config())
            self.assertEqual([label for label, _ in feed.fetchers], ["自建源"])

    def test_disabling_the_relay_drops_the_cached_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            self.write(folder, {"sources": ["market_tencent"]})
            feed = MarketFeed(root=Path(folder))
            feed._snapshot = {"as_of": "2026-11-20T10:00:00+08:00", "demo": False, "source": "腾讯行情",
                              "timezone": "Asia/Shanghai", "quotes": [], "history": [], "candles": []}
            self.write(folder, {"enabled": False, "sources": ["market_tencent"]}, tick=10)
            body = feed.payload()
        self.assertEqual(body["status"], "unavailable")
        self.assertIsNone(body["snapshot"])

    def test_a_rejected_config_is_reported_in_the_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            self.write(folder, {"enabled": False, "sources": ["market_tencent"]})
            feed = MarketFeed(root=Path(folder))
            self.write(folder, {"enabled": False, "sources": ["market_wind"]}, tick=10)
            body = feed.payload()
        self.assertEqual(body["status"], "unavailable")
        self.assertIn("market_wind", body["detail"])


class CliTests(unittest.TestCase):
    def test_exit_code_reflects_the_report(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["plugins-check"]), 0)
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "market.json").write_text(json.dumps({"sources": ["market_wind"]}), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["plugins-check", "--market", folder]), 2)


if __name__ == "__main__":
    unittest.main()
