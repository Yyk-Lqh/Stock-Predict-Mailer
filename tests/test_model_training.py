import json
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from stock_predict_mailer import dataset_auth
from stock_predict_mailer.contracts import contract_id, read_contract
from stock_predict_mailer.core import Config, connect
from stock_predict_mailer.data import demo_csv, import_csv, load_snapshot
from stock_predict_mailer.model_registry import (evaluate_model, get_model, list_models, model_folder,
                                                 owner_key, personal_model_folder, predict_snapshot, publish_demo,
                                                 select_model, train_platform)
from stock_predict_mailer.model_training import (compare_models, latest_comparison, recover_stale, run_worker,
                                                 submit_training, train_cancel, train_list, train_status, training_folder)

SLEEPER = [sys.executable, "-c", "import time; time.sleep(30)"]
FAILER = [sys.executable, "-c", "import sys; sys.exit(3)"]


class PrivateTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = Config(self.root / "state", principal="publisher")
        self.contract = read_contract(Path("config/task-demo.json"))
        self.snapshot = import_csv(self.cfg, demo_csv(self.root / "bars.csv", 200, 6), synthetic=True)["snapshot_id"]
        _, raw = load_snapshot(self.cfg, self.snapshot)
        self.dates = sorted({r["date"] for r in raw})
        self.cutoff = f"{self.dates[-1]}T20:00:00+08:00"
        self.personal_cutoff = f"{self.dates[150]}T20:00:00+08:00"
        parent = train_platform(self.cfg, self.snapshot, self.contract, f"{self.dates[110]}T20:00:00+08:00",
                                confirm_platform_data=True)
        self.parent = parent["version"]
        evaluation = evaluate_model(self.cfg, self.parent, self.snapshot, self.cutoff)
        publish_demo(self.cfg, self.parent, evaluation["evaluation_id"])
        select_model(self.cfg, self.parent, allow_demo=True)

    def queue(self, snapshot=None, **kwargs):
        return submit_training(self.cfg, self.parent, snapshot or self.snapshot, self.personal_cutoff, **kwargs)

    def train_personal(self):
        job = self.queue()
        executed = run_worker(self.cfg, once=True, poll=0.05)["executed"]
        self.assertEqual(len(executed), 1, executed)
        self.assertEqual(executed[0]["status"], "succeeded", executed[0])
        return job, executed[0]

    def test_queue_runs_in_owner_namespace_without_switching_selection(self):
        job = self.queue()
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["method"], "full_retrain")
        self.assertEqual(job["algorithm"], "ridge")
        self.assertEqual(train_status(self.cfg, job["job_id"])["job"]["status"], "queued")
        result = run_worker(self.cfg, once=True, poll=0.05)["executed"][0]
        self.assertEqual(result["status"], "succeeded", result)
        version = result["model_version"]
        folder = personal_model_folder(self.cfg, "publisher", version)
        self.assertTrue((folder / "manifest.json").exists())
        self.assertEqual(folder.parts[-3], owner_key("publisher"))
        self.assertFalse(model_folder(self.cfg, version).exists())
        status = train_status(self.cfg, job["job_id"])
        self.assertEqual(status["job"]["status"], "succeeded")
        self.assertEqual(status["progress"]["stage"], "done")
        stages = [line.split()[-1] for line in (training_folder(self.cfg, "publisher", job["job_id"]) / "stages.log")
                  .read_text(encoding="utf-8").splitlines()]
        self.assertIn("loading_data", stages)
        self.assertEqual(stages[-1], "done")
        self.assertGreaterEqual(len(set(stages)), 3)
        self.assertTrue(set(stages) <= {"loading_data", "preparing_features", "training", "evaluating", "packaging", "done"})
        manifest, _, state = get_model(self.cfg, version)
        self.assertEqual((state["scope"], state["owner"], state["origin"]), ("personal", "publisher", "trained"))
        self.assertEqual(manifest["parent_version"], self.parent)
        self.assertEqual(manifest["method"], "full_retrain")
        self.assertEqual(manifest["training_snapshot"], self.snapshot)
        self.assertEqual(predict_snapshot(self.cfg, self.snapshot, self.cutoff, allow_demo=True)["model_version"], self.parent)
        with self.assertRaises(ValueError):
            predict_snapshot(self.cfg, self.snapshot, self.cutoff, version)
        with self.assertRaises(ValueError):
            publish_demo(self.cfg, version, "a" * 64)

    def test_duplicate_spec_merges_and_cancelled_job_keeps_old_model_usable(self):
        first = self.queue()
        again = self.queue()
        self.assertTrue(again["merged"])
        self.assertEqual(again["job_id"], first["job_id"])
        self.assertEqual(train_cancel(self.cfg, first["job_id"])["status"], "cancelled")
        self.assertEqual(run_worker(self.cfg, once=True)["executed"], [])
        retry = self.queue()
        self.assertFalse(retry["merged"])
        self.assertNotEqual(retry["job_id"], first["job_id"])
        self.assertEqual(predict_snapshot(self.cfg, self.snapshot, self.cutoff, allow_demo=True)["model_version"], self.parent)
        self.assertFalse((self.cfg.workspace / "registry" / "personal" / owner_key("publisher")).exists())

    def test_timeout_and_child_failure_are_isolated_from_selected_model(self):
        timed = self.queue(timeout_seconds=2)
        started = time.monotonic()
        result = run_worker(self.cfg, once=True, poll=0.05, child_command=SLEEPER)["executed"][0]
        self.assertEqual(result["status"], "timeout", result)
        self.assertEqual(result["error_category"], "timeout")
        self.assertLess(time.monotonic() - started, 25)
        self.assertIsNone(train_status(self.cfg, timed["job_id"])["result_version"])
        self.assertEqual(train_status(self.cfg, timed["job_id"])["job"]["status"], "timeout")
        failed = self.queue()
        outcome = run_worker(self.cfg, once=True, poll=0.05, child_command=FAILER)["executed"][0]
        self.assertEqual(outcome["status"], "failed", outcome)
        self.assertEqual(outcome["error_category"], "child_exit")
        self.assertEqual([job["status"] for job in train_list(self.cfg)][:2], ["failed", "timeout"])
        self.assertFalse((self.cfg.workspace / "registry" / "personal" / owner_key("publisher")).exists())
        self.assertEqual(predict_snapshot(self.cfg, self.snapshot, self.cutoff, allow_demo=True)["model_version"], self.parent)

    def test_running_job_can_be_cancelled(self):
        job = self.queue(timeout_seconds=60)
        captured = {}

        def work():
            captured["result"] = run_worker(self.cfg, once=True, poll=0.05, child_command=SLEEPER)

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        deadline = time.monotonic() + 20
        status = "queued"
        while time.monotonic() < deadline:
            status = train_status(self.cfg, job["job_id"])["job"]["status"]
            if status in ("preparing", "training"):
                break
            time.sleep(0.05)
        self.assertIn(status, ("preparing", "training"), status)
        self.assertEqual(train_cancel(self.cfg, job["job_id"])["status"], "cancelling")
        worker.join(30)
        self.assertFalse(worker.is_alive())
        self.assertEqual(captured["result"]["executed"][0]["status"], "cancelled")
        self.assertEqual(train_status(self.cfg, job["job_id"])["job"]["error_category"], "cancelled")

    def test_stale_worker_is_interrupted_not_completed(self):
        job = self.queue()
        stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with connect(self.cfg) as con:
            con.execute("UPDATE training_jobs SET status='training', stage='training', started_at=?, heartbeat_at=? WHERE job_id=?",
                        (stale, stale, job["job_id"]))
        self.assertEqual(recover_stale(self.cfg, 1), [job["job_id"]])
        status = train_status(self.cfg, job["job_id"])
        self.assertEqual(status["job"]["status"], "interrupted")
        self.assertEqual(status["job"]["error_category"], "worker_lost")
        self.assertIsNone(status["result_version"])

    def test_authorization_defaults_and_platform_denial(self):
        record = dataset_auth.describe(self.cfg, self.snapshot)["authorization"]
        self.assertTrue(record["platform_training"])
        dataset_auth.set_authorization(self.cfg, self.snapshot, platform=False, note="personal use only")
        with self.assertRaises(ValueError):
            train_platform(self.cfg, self.snapshot, self.contract, f"{self.dates[110]}T20:00:00+08:00",
                           confirm_platform_data=True)
        dataset_auth.set_authorization(self.cfg, self.snapshot, platform=True, note="confirmed redistribution rights")
        self.assertTrue(train_platform(self.cfg, self.snapshot, self.contract, f"{self.dates[110]}T20:00:00+08:00",
                                       confirm_platform_data=True)["version"])
        user = Config(self.root / "user", principal="alice")
        user_snapshot = import_csv(user, demo_csv(self.root / "user.csv", 200, 6), synthetic=False)["snapshot_id"]
        user_record = dataset_auth.describe(user, user_snapshot)["authorization"]
        self.assertTrue(user_record["personal_training"])
        self.assertFalse(user_record["platform_training"])
        with self.assertRaises(ValueError):
            submit_training(self.cfg, self.parent, user_snapshot, self.personal_cutoff)

    def test_rejects_undersized_or_unowned_data(self):
        small = import_csv(self.cfg, demo_csv(self.root / "small.csv", 80, 6), synthetic=True)["snapshot_id"]
        with self.assertRaises(ValueError) as caught:
            self.queue(snapshot=small)
        self.assertIn("60", str(caught.exception))
        with self.assertRaises(ValueError):
            self.queue(timeout_seconds=1)
        with self.assertRaises(ValueError):
            submit_training(self.cfg, self.parent, self.snapshot, self.personal_cutoff, method="residual")

    def test_comparison_uses_only_common_future_window_and_never_switches(self):
        _, result = self.train_personal()
        candidate = result["model_version"]
        candidate_manifest, _, _ = get_model(self.cfg, candidate)
        parent_manifest, _, _ = get_model(self.cfg, self.parent)
        with self.assertRaises(ValueError):
            compare_models(self.cfg, candidate, self.parent, self.snapshot, self.personal_cutoff)
        record = compare_models(self.cfg, candidate, self.parent, self.snapshot, self.cutoff)
        self.assertGreaterEqual(record["test_days"], 30)
        self.assertGreater(record["test_start"], max(candidate_manifest["train_label_end"], parent_manifest["train_label_end"]))
        self.assertEqual(record["label_end_boundary"], max(candidate_manifest["train_label_end"], parent_manifest["train_label_end"]))
        self.assertIn(record["verdict"], {"candidate_improved", "candidate_degraded", "inconclusive"})
        self.assertFalse(record["auto_switched"])
        self.assertLessEqual(record["rank_ic_difference"]["low"], record["rank_ic_difference"]["mean"])
        self.assertEqual(latest_comparison(self.cfg, candidate)["comparison_id"], record["comparison_id"])
        self.assertEqual(predict_snapshot(self.cfg, self.snapshot, self.cutoff, allow_demo=True)["model_version"], self.parent)
        with self.assertRaises(ValueError):
            select_model(self.cfg, candidate)
        selected = select_model(self.cfg, candidate, confirm_personal=True)
        self.assertEqual(selected["scope"], "personal")
        self.assertEqual(selected["comparison"]["verdict"], record["verdict"])
        with patch("stock_predict_mailer.native_models.fit_native", side_effect=AssertionError("must not train")), \
                patch("sklearn.linear_model.Ridge.fit", side_effect=AssertionError("must not fit")):
            prediction = predict_snapshot(self.cfg, self.snapshot, self.cutoff, allow_personal=True)
        self.assertFalse(prediction["training_performed"])
        self.assertEqual(prediction["model_scope"], "personal")
        self.assertEqual(prediction["model_version"], candidate)
        self.assertEqual(len(prediction["predictions"]), 5)

    def test_comparison_rejects_different_contract(self):
        other_contract = {**self.contract, "universe": ["SYN001", "SYN002", "SYN003", "SYN004"]}
        other = train_platform(self.cfg, self.snapshot, other_contract, f"{self.dates[110]}T20:00:00+08:00",
                               confirm_platform_data=True)
        evaluation = evaluate_model(self.cfg, other["version"], self.snapshot, self.cutoff)
        publish_demo(self.cfg, other["version"], evaluation["evaluation_id"])
        _, result = self.train_personal()
        with self.assertRaises(ValueError):
            compare_models(self.cfg, result["model_version"], other["version"], self.snapshot, self.cutoff)

    def test_cross_owner_isolation(self):
        job, result = self.train_personal()
        other = Config(self.cfg.workspace, principal="another-local-user")
        with self.assertRaises(ValueError):
            train_status(other, job["job_id"])
        with self.assertRaises(ValueError):
            train_cancel(other, job["job_id"])
        with self.assertRaises(ValueError):
            get_model(other, result["model_version"])
        self.assertEqual(train_list(other), [])
        self.assertTrue(all(model["scope"] == "platform" for model in list_models(other)))
        self.assertFalse((self.cfg.workspace / "registry" / "personal" / owner_key("another-local-user")).exists())

    def test_lightgbm_parent_retrains_natively(self):
        try:
            import lightgbm  # noqa: F401
        except ImportError:
            self.skipTest("install optional trees dependency")
        parent = train_platform(self.cfg, self.snapshot, self.contract, f"{self.dates[110]}T20:00:00+08:00",
                                "lightgbm", confirm_platform_data=True)
        evaluation = evaluate_model(self.cfg, parent["version"], self.snapshot, self.cutoff)
        publish_demo(self.cfg, parent["version"], evaluation["evaluation_id"])
        job = submit_training(self.cfg, parent["version"], self.snapshot, self.personal_cutoff)
        executed = run_worker(self.cfg, once=True, poll=0.05)["executed"][0]
        self.assertEqual(executed["status"], "succeeded", executed)
        self.assertEqual(executed["job_id"], job["job_id"])
        manifest, payload, _ = get_model(self.cfg, executed["model_version"])
        self.assertEqual(manifest["artifact"], "model.txt")
        self.assertTrue(payload.startswith(b"tree"))
        self.assertTrue((personal_model_folder(self.cfg, "publisher", executed["model_version"]) / "model.txt").exists())

    def test_job_spec_is_immutable_on_disk(self):
        job = self.queue()
        path = training_folder(self.cfg, "publisher", job["job_id"]) / "spec.json"
        spec = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(spec["parent_version"], self.parent)
        self.assertEqual(spec["snapshot_id"], self.snapshot)
        self.assertEqual(spec["contract_id"], contract_id(self.contract))
        self.assertEqual(spec["train_cutoff"], self.personal_cutoff)
        self.assertEqual(spec["max_seconds"], 300)
        self.assertEqual(spec["max_rows"], 200_000)
        with self.assertRaises(ValueError):
            submit_training(self.cfg, self.parent, self.snapshot, self.personal_cutoff, timeout_seconds=99999)


if __name__ == "__main__":
    unittest.main()
