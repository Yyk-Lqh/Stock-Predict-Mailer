import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_predict_mailer import generation
from stock_predict_mailer.contracts import read_contract
from stock_predict_mailer.core import Config
from stock_predict_mailer.data import demo_csv, import_csv, load_snapshot
from stock_predict_mailer.keys import is_revoked, revoke_key
from stock_predict_mailer.model_packages import export_package, generate_key, install_package, key_paths
from stock_predict_mailer.model_registry import (
    evaluate_model,
    predict_snapshot,
    publish_demo,
    select_model,
    train_platform,
)
from stock_predict_mailer.prediction_report import build_prediction_report, load_prediction_report
from stock_predict_mailer.shadow import (
    evaluate_shadow,
    is_stable_available,
    promote_stable,
    record_shadow,
    release_status,
    revoke_stable,
    shadow_records,
    shadow_status,
)


class PredictionFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.cfg = Config(cls.root / "state")
        cls.contract = read_contract(Path("config/task-demo.json"))
        cls.snapshot = import_csv(cls.cfg, demo_csv(cls.root / "bars.csv", 240, 6), synthetic=True)["snapshot_id"]
        _, cls.raw = load_snapshot(cls.cfg, cls.snapshot)
        cls.dates = sorted({row["date"] for row in cls.raw})
        cls.final_cutoff = f"{cls.dates[-1]}T20:00:00+08:00"
        cls.model = train_platform(cls.cfg, cls.snapshot, cls.contract, f"{cls.dates[100]}T20:00:00+08:00",
                                   "ridge", confirm_platform_data=True)
        evaluation = evaluate_model(cls.cfg, cls.model["version"], cls.snapshot, cls.final_cutoff)
        publish_demo(cls.cfg, cls.model["version"], evaluation["evaluation_id"])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def predict(self, index: int = -1, model: str | None = None):
        cutoff = f"{self.dates[index]}T20:00:00+08:00"
        return predict_snapshot(self.cfg, self.snapshot, cutoff, model or self.model["version"], allow_demo=True)

    # ------------------------------------------------------------------- E-2
    def test_prediction_report_freezes_identifiers(self):
        prediction = self.predict()
        report = build_prediction_report(self.cfg, prediction["prediction_id"])
        self.assertEqual(report["kind"], "prediction")
        self.assertEqual(report["model_version"], prediction["model_version"])
        self.assertEqual(report["contract_id"], prediction["contract_id"])
        self.assertEqual(report["snapshot"], prediction["snapshot"])
        self.assertEqual(report["prediction_id"], prediction["prediction_id"])
        self.assertEqual(report["generation_mode"], "deterministic_template_no_llm")
        _, body = load_prediction_report(self.cfg, report["report_id"])
        text = body.decode("utf-8")
        for value in (prediction["model_version"], prediction["contract_id"], prediction["snapshot"]):
            self.assertIn(value, text)
        again = build_prediction_report(self.cfg, prediction["prediction_id"])
        self.assertEqual(again["report_id"], report["report_id"])
        self.assertEqual(again["html_sha256"], report["html_sha256"])

    def test_switching_model_keeps_old_reports_intact(self):
        first = self.predict()
        report = build_prediction_report(self.cfg, first["prediction_id"])
        _, original = load_prediction_report(self.cfg, report["report_id"])
        other = train_platform(self.cfg, self.snapshot, self.contract, f"{self.dates[100]}T20:00:00+08:00",
                               "momentum", confirm_platform_data=True)
        evaluation = evaluate_model(self.cfg, other["version"], self.snapshot, self.final_cutoff)
        publish_demo(self.cfg, other["version"], evaluation["evaluation_id"])
        select_model(self.cfg, other["version"], allow_demo=True)
        rebuilt = build_prediction_report(self.cfg, first["prediction_id"])
        self.assertEqual(rebuilt["report_id"], report["report_id"])
        _, after = load_prediction_report(self.cfg, rebuilt["report_id"])
        self.assertEqual(after, original, "an old report must not change when the selected model changes")
        newer = self.predict(model=other["version"])
        fresh = build_prediction_report(self.cfg, newer["prediction_id"])
        self.assertNotEqual(fresh["report_id"], report["report_id"])
        self.assertEqual(fresh["model_version"], other["version"])

    def test_report_without_evidence_does_not_invent_citations(self):
        prediction = self.predict()
        report = build_prediction_report(self.cfg, prediction["prediction_id"], query="不存在的主题")
        self.assertEqual(report["evidence"], [])
        self.assertEqual(report["inferences"], [])
        _, body = load_prediction_report(self.cfg, report["report_id"])
        self.assertIn("未补造引用", body.decode("utf-8"))

    # ------------------------------------------------------------------- E-1
    def test_generation_is_template_by_default(self):
        prediction = self.predict()
        brief = generation.generate_brief(self.cfg, prediction, [])
        self.assertEqual(brief["mode"], "deterministic_template_no_llm")
        self.assertFalse(brief["degraded"])
        self.assertIn(prediction["predictions"][0]["security_id"], brief["text"])

    def test_unlisted_provider_degrades_to_template(self):
        prediction = self.predict()
        with patch.dict(os.environ, {"SPM_GENERATION_PROVIDER": "vendor-x"}):
            brief = generation.generate_brief(self.cfg, prediction, [], allow_generation=True)
        self.assertTrue(brief["degraded"])
        self.assertIn("允许清单", brief["reason"])
        self.assertTrue(brief["text"])

    def test_allowlisted_provider_receives_no_raw_material(self):
        captured = {}

        def stub(payload):
            captured.update(payload)
            return "排序结果已复核。"

        generation.register_provider("stub", stub)
        prediction = self.predict()
        with patch.object(generation, "ALLOWED_PROVIDERS", ("stub",)), \
                patch.dict(os.environ, {"SPM_GENERATION_PROVIDER": "stub"}):
            brief = generation.generate_brief(self.cfg, prediction, [], allow_generation=True)
        self.assertEqual(brief["mode"], "external:stub")
        self.assertFalse(brief["degraded"])
        self.assertNotIn("content", captured)
        self.assertEqual(captured["model_version"], prediction["model_version"])
        self.assertEqual([item["security_id"] for item in captured["predictions"]],
                         [item["security_id"] for item in prediction["predictions"]][:10])

    def test_provider_failure_degrades(self):
        def boom(payload):
            raise RuntimeError("upstream said no")

        generation.register_provider("boom", boom)
        prediction = self.predict()
        with patch.object(generation, "ALLOWED_PROVIDERS", ("boom",)), \
                patch.dict(os.environ, {"SPM_GENERATION_PROVIDER": "boom"}):
            brief = generation.generate_brief(self.cfg, prediction, [], allow_generation=True)
        self.assertTrue(brief["degraded"])
        self.assertIn("回退", brief["reason"])
        self.assertNotIn("upstream", brief["reason"] + brief["text"])

    # ------------------------------------------------------------------- F-3
    def test_shadow_scores_matured_predictions(self):
        # A label matures after horizon+1 sessions, so the prediction date needs
        # at least that many sessions behind it.
        prediction = self.predict(-8)
        record_shadow(self.cfg, prediction["prediction_id"])
        self.assertEqual(len(shadow_records(self.cfg)), 1)
        outcome = evaluate_shadow(self.cfg, self.final_cutoff)
        self.assertEqual(len(outcome["evaluated"]), 1)
        self.assertGreaterEqual(outcome["evaluated"][0]["securities"], 3)
        self.assertTrue(-1.0 <= outcome["evaluated"][0]["rank_ic"] <= 1.0)
        status = shadow_status(self.cfg, self.model["version"])
        self.assertEqual(status["matured_days"], 1)
        self.assertFalse(status["ready_for_stable"])

    def test_stable_requires_shadow_days_and_explicit_authorisation(self):
        # A model nobody has shadowed yet: no days, so promotion must be refused
        # no matter how the request is phrased.
        fresh = train_platform(self.cfg, self.snapshot, self.contract, f"{self.dates[100]}T20:00:00+08:00",
                              "momentum", confirm_platform_data=True)
        with self.assertRaises(ValueError):
            promote_stable(self.cfg, fresh["version"], authorize=False, note="不该通过")
        with self.assertRaises(ValueError):
            promote_stable(self.cfg, fresh["version"], authorize=True, note="")
        with self.assertRaises(ValueError) as caught:
            promote_stable(self.cfg, fresh["version"], authorize=True, note="作者批准")
        self.assertIn("matured days", str(caught.exception))

    def test_stable_promotion_and_revocation(self):
        for index in range(-22, -10):
            prediction = self.predict(index)
            record_shadow(self.cfg, prediction["prediction_id"])
        evaluate_shadow(self.cfg, self.final_cutoff)
        status = shadow_status(self.cfg, self.model["version"])
        self.assertGreaterEqual(status["matured_days"], 10)
        self.assertTrue(status["ready_for_stable"])
        release = promote_stable(self.cfg, self.model["version"], authorize=True, note="十日影子运行评审通过")
        self.assertTrue(release["authorized"])
        self.assertTrue(is_stable_available(self.cfg, self.model["version"]))
        revoked = revoke_stable(self.cfg, self.model["version"], "影子期后发现数据缺口")
        self.assertTrue(revoked["revoked"])
        self.assertFalse(is_stable_available(self.cfg, self.model["version"]))
        listed = release_status(self.cfg)
        self.assertTrue(any(item["version"] == self.model["version"] and item["revoked_at"] for item in listed))
        with self.assertRaises(ValueError):
            revoke_stable(self.cfg, "f" * 64, "未知版本")

    def test_revoked_publisher_key_cannot_install(self):
        publisher = Config(self.root / "publisher")
        client = Config(self.root / "client")
        import_csv(publisher, self.root / "bars.csv", synthetic=True)
        model = train_platform(publisher, self.snapshot, self.contract, f"{self.dates[100]}T20:00:00+08:00",
                               "ridge", confirm_platform_data=True)
        evaluation = evaluate_model(publisher, model["version"], self.snapshot, self.final_cutoff)
        publish_demo(publisher, model["version"], evaluation["evaluation_id"])
        key = generate_key(publisher)
        package = self.root / "demo.zip"
        export_package(publisher, model["version"], package)
        _, public_key = key_paths(publisher)
        revoke_key(client, key["public_key_sha256"], "私钥可能已泄露")
        self.assertTrue(is_revoked(client, key["public_key_sha256"]))
        with self.assertRaises(ValueError) as caught:
            install_package(client, package, public_key)
        self.assertIn("revoked", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
