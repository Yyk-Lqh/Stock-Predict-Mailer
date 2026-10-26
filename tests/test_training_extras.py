import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_predict_mailer.contracts import read_contract
from stock_predict_mailer.core import Config
from stock_predict_mailer.data import demo_csv, import_csv, load_snapshot
from stock_predict_mailer.model_registry import (
    evaluate_model,
    get_model,
    publish_demo,
    select_model,
    train_platform,
)
from stock_predict_mailer.model_training import (
    compare_models,
    run_worker,
    submit_training,
    train_list,
    train_status,
)
from stock_predict_mailer.retention import apply_retention, plan_retention, retention_log


class TrainingExtrasTests(unittest.TestCase):
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
        cls.ridge = train_platform(cls.cfg, cls.snapshot, cls.contract, f"{cls.dates[100]}T20:00:00+08:00",
                                   "ridge", confirm_platform_data=True)
        evaluation = evaluate_model(cls.cfg, cls.ridge["version"], cls.snapshot, cls.final_cutoff)
        publish_demo(cls.cfg, cls.ridge["version"], evaluation["evaluation_id"])
        cls.trees = train_platform(cls.cfg, cls.snapshot, cls.contract, f"{cls.dates[100]}T20:00:00+08:00",
                                   "lightgbm", confirm_platform_data=True)
        evaluation = evaluate_model(cls.cfg, cls.trees["version"], cls.snapshot, cls.final_cutoff)
        publish_demo(cls.cfg, cls.trees["version"], evaluation["evaluation_id"])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def cutoff(self, index: int) -> str:
        return f"{self.dates[index]}T20:00:00+08:00"

    def drain(self, **kwargs):
        return run_worker(self.cfg, once=True, poll=0.05, **kwargs)

    # ---------------------------------------------------------- D-1 capabilities
    def test_continue_training_is_refused_for_algorithms_without_partial_state(self):
        with self.assertRaises(ValueError) as caught:
            submit_training(self.cfg, self.ridge["version"], self.snapshot, self.cutoff(160), method="continue_train")
        self.assertIn("cannot continue training", str(caught.exception))

    def test_continue_training_records_the_frozen_parent(self):
        queued = submit_training(self.cfg, self.trees["version"], self.snapshot, self.cutoff(160),
                                 method="continue_train", additional_rounds=10)
        self.assertEqual(queued["method"], "continue_train")
        self.assertEqual(queued["additional_rounds"], 10)
        self.assertTrue(queued["capability"]["supports_continue"])
        result = self.drain()
        self.assertEqual(result["executed"][0]["status"], "succeeded")
        version = result["executed"][0]["model_version"]
        manifest, payload, state = get_model(self.cfg, version)
        self.assertEqual(manifest["method"], "continue_train")
        self.assertEqual(manifest["continued_from"], self.trees["version"])
        self.assertEqual(manifest["additional_rounds"], 10)
        self.assertEqual(state["status"], "ready")
        self.assertNotEqual(version, self.trees["version"])
        self.assertTrue(payload)
        spec = train_status(self.cfg, queued["job_id"])["spec"]
        self.assertEqual(spec["additional_rounds"], 10)

    def test_additional_rounds_are_bounded(self):
        for rounds in (0, 1000):
            with self.assertRaises(ValueError):
                submit_training(self.cfg, self.trees["version"], self.snapshot, self.cutoff(161),
                                method="continue_train", additional_rounds=rounds)
        with self.assertRaises(ValueError):
            submit_training(self.cfg, self.ridge["version"], self.snapshot, self.cutoff(161),
                            method="continue_train", additional_rounds=1)

    # ------------------------------------------------------- C-2 workers/priority
    def test_priority_decides_claim_order_only(self):
        low = submit_training(self.cfg, self.ridge["version"], self.snapshot, self.cutoff(150), priority=1)
        high = submit_training(self.cfg, self.ridge["version"], self.snapshot, self.cutoff(152), priority=9)
        first = self.drain()
        self.assertEqual(first["executed"][0]["job_id"], high["job_id"])
        self.assertNotEqual(first["executed"][0]["job_id"], low["job_id"])
        second = self.drain()
        self.assertEqual(second["executed"][0]["job_id"], low["job_id"])

    def test_parallel_workers_never_run_the_same_job_twice(self):
        jobs = [submit_training(self.cfg, self.ridge["version"], self.snapshot, self.cutoff(index))
                for index in (170, 172, 174)]
        queue = [job["job_id"] for job in jobs]
        result = self.drain(workers=3)
        executed = [item["job_id"] for item in result["executed"]]
        self.assertEqual(len(executed), len(set(executed)), "a job was executed twice")
        self.assertEqual(set(executed), set(queue))
        self.assertTrue(all(item["status"] == "succeeded" for item in result["executed"]))
        self.assertEqual(result["workers"], 3)
        with self.assertRaises(ValueError):
            run_worker(self.cfg, once=True, workers=9)

    # --------------------------------------------------------------- C-3 retention
    def test_retention_never_removes_selected_published_or_depended_versions(self):
        personal = []
        for index in (180, 184, 188):
            submit_training(self.cfg, self.ridge["version"], self.snapshot, self.cutoff(index))
            outcome = self.drain()["executed"][0]
            self.assertEqual(outcome["status"], "succeeded")
            personal.append(outcome["model_version"])
        comparison = compare_models(self.cfg, personal[0], self.ridge["version"], self.snapshot, self.final_cutoff)
        select_model(self.cfg, personal[0], confirm_personal=True)
        self.assertIn(comparison["verdict"], ("candidate_improved", "candidate_degraded", "inconclusive"))
        plan = plan_retention(self.cfg, keep=0)
        protected = {item["version"] for item in plan["protected"]}
        self.assertIn(personal[0], protected, "the selected version must be protected")
        self.assertIn(self.ridge["version"], protected, "published versions must be protected")
        self.assertNotIn(personal[0], [item["version"] for item in plan["delete"]])
        applied = apply_retention(self.cfg, plan)
        self.assertNotIn(personal[0], applied["deleted"])
        self.assertNotIn(self.ridge["version"], applied["deleted"])
        self.assertTrue(all(version in applied["deleted"] for version in personal[1:]))
        log = retention_log(self.cfg)
        self.assertEqual(len(log), len(applied["deleted"]))
        with self.assertRaises(ValueError):
            get_model(self.cfg, personal[1])
        self.assertTrue(get_model(self.cfg, personal[0])[0])

    def test_retention_dry_run_deletes_nothing(self):
        before = len(train_list(self.cfg))
        plan = plan_retention(self.cfg, keep=2)
        self.assertTrue(plan["dry_run"])
        self.assertEqual(len(train_list(self.cfg)), before)
        self.assertTrue(all(item["bytes"] >= 0 for item in plan["delete"]))

    # ------------------------------------------------------- C-4 segmented compare
    def test_segmented_comparison_records_budget_and_segments(self):
        alternative = train_platform(self.cfg, self.snapshot, self.contract, self.cutoff(150), "momentum",
                                     confirm_platform_data=True)
        for _ in range(1):
            record = compare_models(self.cfg, alternative["version"], self.ridge["version"],
                                    self.snapshot, self.final_cutoff, segments=True)
        self.assertIn("liquidity", record["segments"])
        self.assertIn("phase", record["segments"])
        for split in record["segments"].values():
            self.assertTrue(split["segments"], "each split must produce at least one segment")
            for segment in split["segments"].values():
                self.assertIn(segment["verdict"], ("candidate_improved", "candidate_degraded",
                                                   "inconclusive", "insufficient_evidence"))
        self.assertIn("attempts_before", record["multiple_comparison"])
        self.assertIn("budget", record["multiple_comparison"])
        self.assertIn(record["verdict"], ("candidate_improved", "candidate_degraded", "inconclusive", "insufficient_evidence"))

    def test_exhausted_comparison_budget_reports_insufficient_evidence(self):
        alternative = train_platform(self.cfg, self.snapshot, self.contract, self.cutoff(152), "momentum",
                                     confirm_platform_data=True)
        with patch("stock_predict_mailer.model_training.COMPARISON_BUDGET", 0):
            record = compare_models(self.cfg, alternative["version"], self.ridge["version"],
                                    self.snapshot, self.final_cutoff)
        self.assertEqual(record["verdict"], "insufficient_evidence")
        self.assertTrue(record["multiple_comparison"]["note"])
        self.assertEqual(record["multiple_comparison"]["remaining"], 0)


if __name__ == "__main__":
    unittest.main()
