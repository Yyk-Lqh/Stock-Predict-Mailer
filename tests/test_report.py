import tempfile
import unittest
from pathlib import Path

from stock_predict_mailer.core import Config
from stock_predict_mailer.data import demo_csv, import_csv
from stock_predict_mailer.knowledge import ingest_document, revoke
from stock_predict_mailer.report import build_report, load_report
from stock_predict_mailer.research import experiment


class ReportTests(unittest.TestCase):
    def test_escaped_report_citations_and_revocation(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Config(Path(folder) / "state")
            document = Path(folder) / "note.md"
            document.write_text('策略风险<script>alert("upload")</script>', encoding="utf-8")
            doc = ingest_document(cfg, document, "2019-01-01T00:00:00Z", "2019-01-01T00:00:00Z", ["owner"])
            snap = import_csv(cfg, demo_csv(Path(folder) / "a.csv", 160, 6), synthetic=True)
            research = experiment(cfg, snap["snapshot_id"], "2021-01-01T20:00:00+08:00")
            built = build_report(cfg, research["experiment_id"], "策略风险")
            report, body = load_report(cfg, built["report_id"])
            self.assertEqual(report["generation_mode"], "deterministic_template_no_llm")
            self.assertNotIn(b"<script>", body)
            self.assertIn(b"&lt;script&gt;", body)
            self.assertEqual(len(report["evidence"]), 1)
            revoke(cfg, doc["document_id"])
            with self.assertRaises(ValueError):
                load_report(cfg, built["report_id"])


if __name__ == "__main__":
    unittest.main()
