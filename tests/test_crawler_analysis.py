"""Synthetic crawler CSV -> v1 prediction -> report -> file mail, no external calls."""
import copy
import io
import json
import tempfile
import unittest
from calendar import monthrange
from contextlib import redirect_stdout
from datetime import date, timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path
from zoneinfo import ZoneInfo

from mcp_server.fundamental_snapshot import write_cutoff_view
from mcp_server.quality import atomic_json, read_json, write_snapshot
from stock_predict_mailer.agent_service.analysis import AnalysisAgent, identity, validate_analysis
from stock_predict_mailer.agent_service.config import load
from stock_predict_mailer.agent_service.contracts import ServiceError, instant, prediction, utcnow
from stock_predict_mailer.agent_service.crawler_context import CrawlerContextAdapter
from stock_predict_mailer.agent_service.input_evidence import fingerprint, freeze
from stock_predict_mailer.agent_service.mail import MailService
from stock_predict_mailer.agent_service.reporting import render, save_report
from stock_predict_mailer.cli import main

SETTINGS = {"max_context_age_seconds": 31536000}
NAMES = {"pubDate": "pub_date", "roeAvg": "ROE", "npMargin": "net_margin"}


class CrawlerAnalysisTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = utcnow().replace(microsecond=0) - timedelta(seconds=1)
        today = self.now.astimezone(ZoneInfo("Asia/Shanghai")).date()
        quarter = (today.month - 1) // 3
        year, month = (today.year, quarter * 3) if quarter else (today.year - 1, 12)
        self.report = date(year, month, monthrange(year, month)[1])
        self.p = {"schema_version": "1", "prediction_id": "synthetic-upstream-001", "subject": "000001.SZ",
                  "generated_at": (self.now - timedelta(minutes=1)).isoformat(),
                  "valid_until": (self.now + timedelta(days=1)).isoformat(),
                  "horizon": {"value": 5, "unit": "trading_days"}, "direction": "up",
                  "confidence": None, "model_version": "synthetic-upstream-model-v1", "synthetic": True}
        self.path = self.root / "view.csv"
        self.rows = [{"code": "000001", "report_date": self.report.isoformat(), "pubDate": self.report.isoformat(),
                      "roeAvg": 0.12, "npMargin": 0.2, "publication_verified": True,
                      "collected_at": self.now.isoformat(), "provider_symbol": "sz.000001"}]
        self.meta = {"completeness": "complete", "run_complete": True, "scope_limited": False,
                     "selected_count": 1, "processed_count": 1, "dataset_completeness": "unknown"}
        self.write_view()

    def write_view(self):
        return write_cutoff_view(self.path, self.rows, self.now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(),
                                 NAMES, self.meta)

    def collect(self):
        return CrawlerContextAdapter(self.path, self.p).fetch()

    def analyze(self):
        return AnalysisAgent(SETTINGS).analyze(self.p, self.collect())

    def update_metadata(self, **changes):
        path = Path(str(self.path) + ".metadata.json")
        value = read_json(path)
        atomic_json(path, dict(value, **changes))

    def config(self, *, extra=""):
        self.config_path = self.root / "config.toml"
        self.config_path.write_text('workspace="work"\n[prediction]\nadapter="file"\npath="prediction.json"\n'
                                    '[context]\nadapter="crawler"\npath="view.csv"\n'
                                    '[agent]\nmax_context_age_seconds=31536000\n'
                                    '[mail]\ntransport="file"\nallow_synthetic=true\n' + extra, encoding="utf-8")
        (self.root / "prediction.json").write_text(json.dumps(self.p), encoding="utf-8")
        return self.config_path

    def cli(self):
        with redirect_stdout(io.StringIO()) as stream:
            code = main(["--config", str(self.config_path), "run", "--send"])
        return code, json.loads(stream.getvalue())

    def test_standard_context_preserves_period_units_and_acquisition(self):
        collected = self.collect()
        self.assertEqual(len(collected["facts"]), 2)
        fact = collected["facts"][0]
        self.assertEqual(fact["unit"], "source_native:ROE")
        self.assertEqual(instant(fact["observed_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date(), self.report)
        self.assertEqual(instant(fact["available_at"]), instant(self.now.isoformat()))
        analysis = self.analyze()
        self.assertIsNone(analysis["prediction"]["confidence"])
        self.assertEqual(analysis["prediction"]["model_version"], self.p["model_version"])
        validate_analysis(analysis, SETTINGS)

    def test_old_quarter_does_not_become_fresh_when_read(self):
        if (self.now.date() - self.report).days <= 1:
            self.skipTest("quarter boundary fixture may be fresh for a day")
        with self.assertRaises(ServiceError) as caught:
            AnalysisAgent().analyze(self.p, self.collect())
        self.assertEqual(caught.exception.code, "STALE_CONTEXT")

    def test_csv_and_metadata_tampering_is_rejected(self):
        self.path.write_bytes(self.path.read_bytes().replace(b"0.12", b"0.99"))
        with self.assertRaises(ServiceError):
            self.collect()

    def test_missing_sidecar_and_missing_target_are_explicit_errors(self):
        self.p["subject"] = "000002.SZ"
        with self.assertRaises(ServiceError) as caught:
            self.collect()
        self.assertEqual(caught.exception.code, "CONTEXT_UNAVAILABLE")
        Path(str(self.path) + ".metadata.json").unlink()
        with self.assertRaises(ServiceError) as caught:
            self.collect()
        self.assertEqual(caught.exception.code, "LOCAL_IO")

    def test_missing_or_invalid_prediction_does_not_create_reports(self):
        self.config()
        (self.root / "prediction.json").unlink()
        code, result = self.cli()
        self.assertEqual(code, 2)
        self.assertEqual(result["error"]["code"], "LOCAL_IO")
        self.assertFalse((self.root / "work").exists())

    def test_invalid_subject_and_expired_prediction_are_rejected(self):
        self.p["subject"] = "000001"
        with self.assertRaises(ServiceError):
            self.collect()
        self.p["subject"] = "000001.SZ"
        self.p["valid_until"] = self.now.isoformat()
        with self.assertRaises(ServiceError) as caught:
            self.collect()
        self.assertEqual(caught.exception.code, "STALE_RESULT")

    def test_partial_or_old_unverified_view_is_rejected(self):
        for changes in ({"run_complete": False}, {"run_complete": None}, {"completeness": "partial"}):
            self.write_view()
            self.update_metadata(**changes)
            with self.subTest(changes=changes), self.assertRaises(ServiceError):
                self.collect()

    def test_complete_single_symbol_from_limited_pool_remains_labelled(self):
        self.meta.update(completeness="partial", scope_limited=True)
        self.write_view()
        analysis = self.analyze()
        self.assertTrue(any("限量" in note for note in analysis["limitations"]))
        self.assertFalse(analysis["input_evidence"]["snapshot"]["source"]["metadata"]["point_in_time_verified"])

    def test_false_disclosure_and_future_acquisition_are_rejected(self):
        for changes in ({"publication_verified": False}, {"collected_at": (self.now + timedelta(days=1)).isoformat()}):
            self.rows[0].update(changes)
            self.write_view()
            with self.subTest(changes=changes), self.assertRaises(ServiceError):
                self.collect()
            self.rows[0]["publication_verified"] = True

    def test_latest_available_period_selected_without_other_subjects(self):
        previous = self.report.replace(day=1) - timedelta(days=1)
        previous = date(previous.year, ((previous.month - 1) // 3 + 1) * 3, 1)
        previous = previous.replace(day=monthrange(previous.year, previous.month)[1])
        self.rows += [dict(self.rows[0], report_date=previous.isoformat(), pubDate=previous.isoformat(), roeAvg=0.01),
                      dict(self.rows[0], code="000002", roeAvg=99)]
        self.write_view()
        selected = self.collect()["input_evidence"]["snapshot"]["source"]["record"]
        self.assertEqual(selected["code"], "000001")
        self.assertEqual(selected["report_date"], self.report.isoformat())

    def test_forged_context_or_prediction_binding_is_rejected(self):
        collected = self.collect()
        collected["facts"][0]["value"] = 999
        with self.assertRaises(ServiceError):
            AnalysisAgent(SETTINGS).analyze(self.p, collected)
        collected = self.collect()
        with self.assertRaises(ServiceError):
            AnalysisAgent(SETTINGS).analyze(dict(self.p, prediction_id="different-id"), collected)

    def test_rehashed_forged_field_mapping_is_rejected(self):
        collected = self.collect()
        evidence = collected["input_evidence"]
        key = next(iter(evidence["snapshot"]["source"]["fact_fields"]))
        evidence["snapshot"]["source"]["fact_fields"][key] = "wrong_field"
        evidence["snapshot_id"] = fingerprint(evidence["snapshot"])
        with self.assertRaises(ServiceError):
            AnalysisAgent(SETTINGS).analyze(self.p, collected)

    def test_missing_source_warnings_are_rejected_by_mail_validation(self):
        analysis = self.analyze()
        analysis["limitations"] = []
        analysis["analysis_id"] = identity({k: v for k, v in analysis.items() if k != "analysis_id"})
        with self.assertRaises(ServiceError):
            validate_analysis(analysis, SETTINGS)

    def test_snapshot_is_stable_and_corruption_is_not_overwritten(self):
        analysis = self.analyze()
        folder = save_report(self.root / "work", analysis)
        snapshot = self.root / "work" / "input-snapshots" / (analysis["input_evidence"]["snapshot_id"] + ".json")
        original = snapshot.read_bytes()
        self.assertEqual(self.analyze()["analysis_id"], analysis["analysis_id"])
        save_report(self.root / "work", analysis)
        self.assertEqual(snapshot.read_bytes(), original)
        self.assertTrue((folder / "report.html").exists())
        snapshot.write_bytes(b"corrupted")
        with self.assertRaises(ServiceError):
            save_report(self.root / "work", analysis)
        self.assertEqual(snapshot.read_bytes(), b"corrupted")

    def test_source_change_produces_distinct_snapshot(self):
        first = self.analyze()
        self.rows[0]["roeAvg"] = 0.13
        self.write_view()
        second = self.analyze()
        self.assertNotEqual(first["input_evidence"]["snapshot_id"], second["input_evidence"]["snapshot_id"])

    def test_render_escapes_source_filename_and_preserves_citations(self):
        collected = self.collect()
        source = copy.deepcopy(collected["input_evidence"]["snapshot"]["source"])
        source["filename"] = "<img src=x onerror=alert(1)>.csv"
        base = {k: v for k, v in collected.items() if k != "input_evidence"}
        collected["input_evidence"] = freeze(prediction(self.p), base, source)
        analysis = AnalysisAgent(SETTINGS).analyze(self.p, collected)
        text, html = render(analysis)
        self.assertIn(analysis["input_evidence"]["snapshot_id"], text)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;img src=x", html)
        self.assertIn(analysis["facts"][0]["id"], html)

    def test_direct_mail_enqueue_also_archives_evidence(self):
        analysis = self.analyze()
        workspace = self.root / "mail-only"
        mail = MailService(workspace, {"sender": "source@example.invalid", "transport": "file", "allow_synthetic": True},
                           analysis_settings=SETTINGS)
        result = mail.enqueue(analysis, "preview@example.invalid")
        self.assertEqual(result["status"], "pending")
        self.assertTrue((workspace / "input-snapshots" / (analysis["input_evidence"]["snapshot_id"] + ".json")).exists())

    def test_actual_cli_report_snapshot_file_mail_and_dedup(self):
        self.config()
        code, result = self.cli()
        self.assertEqual(code, 0, result)
        code, repeated = self.cli()
        self.assertEqual(code, 0, repeated)
        self.assertEqual(result["analysis_id"], repeated["analysis_id"])
        self.assertEqual(result["mail"]["id"], repeated["mail"]["id"])
        self.assertEqual(result["mail"]["status"], "simulated")
        report = Path(result["report"])
        analysis = json.loads((report.parent / "analysis.json").read_text(encoding="utf-8"))
        snapshot = json.loads(Path(result["input_snapshot"]).read_text(encoding="utf-8"))
        self.assertEqual(snapshot, analysis["input_evidence"])
        emls = list((self.root / "work" / "sent").glob("*.eml"))
        self.assertEqual(len(emls), 1)
        message = BytesParser(policy=policy.default).parsebytes(emls[0].read_bytes())
        snapshot_id = snapshot["snapshot_id"]
        for kind in ("plain", "html"):
            body = message.get_body(preferencelist=(kind,)).get_content()
            self.assertIn(snapshot_id, body)
            self.assertIn(analysis["facts"][0]["id"], body)
        self.assertIn(snapshot_id, report.read_text(encoding="utf-8"))

    def test_config_expands_only_context_age_and_resolves_crawler_path(self):
        cfg = load(self.config())
        self.assertEqual(cfg["context"]["path"], self.path)
        self.assertEqual(cfg["agent"]["max_context_age_seconds"], 31536000)
        original = self.config_path.read_text()
        self.config_path.write_text(original.replace("max_context_age_seconds=31536000", "timeout_seconds=31536000"))
        with self.assertRaises(ServiceError):
            load(self.config_path)

    def test_duplicate_headers_and_illegal_numbers_are_rejected(self):
        metadata = read_json(Path(str(self.path) + ".metadata.json"))
        write_snapshot(self.path, b"code,code,report_date,pub_date,collected_at\n000001,000001,x,x,x\n", metadata)
        with self.assertRaises(ServiceError):
            self.collect()
        self.write_view()
        raw = self.path.read_bytes().replace(b"0.12", b"NaN")
        write_snapshot(self.path, raw, metadata)
        with self.assertRaises(ServiceError):
            self.collect()

    def test_config_never_substitutes_mock_for_missing_upstream(self):
        self.config()
        self.config_path.write_text('workspace="work"\n[context]\nadapter="crawler"\npath="view.csv"\n')
        with self.assertRaises(ServiceError) as caught:
            load(self.config_path)
        self.assertEqual(caught.exception.code, "CONFIG_ERROR")

    def test_inconsistent_completed_counts_are_rejected(self):
        self.update_metadata(selected_count=2, processed_count=1)
        with self.assertRaises(ServiceError):
            self.collect()

    def test_capture_before_disclosure_is_not_accepted(self):
        self.rows[0]["collected_at"] = (self.report - timedelta(days=1)).isoformat() + "T12:00:00+08:00"
        self.write_view()
        with self.assertRaises(ServiceError):
            self.collect()

    def test_same_code_in_different_market_is_rejected(self):
        self.p["subject"] = "000001.SH"
        with self.assertRaises(ServiceError) as caught:
            self.collect()
        self.assertEqual(caught.exception.code, "UNVERIFIED_CONTEXT")

    def test_missing_provider_route_is_not_inferred(self):
        self.rows[0].pop("provider_symbol")
        self.write_view()
        with self.assertRaises(ServiceError) as caught:
            self.collect()
        self.assertEqual(caught.exception.code, "UNVERIFIED_CONTEXT")
