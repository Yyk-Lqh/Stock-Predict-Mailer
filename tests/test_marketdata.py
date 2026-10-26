import csv
import io
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from stock_predict_mailer import dataset_auth
from stock_predict_mailer.core import Config
from stock_predict_mailer.data import FIELDS, demo_csv, import_csv, load_snapshot
from stock_predict_mailer.marketdata import freshness, latest_snapshot, update_bars, update_history


def _slice(source: Path, target: Path, days: list[str]) -> Path:
    rows = list(csv.DictReader(io.StringIO(source.read_text(encoding="utf-8"))))
    selected = [row for row in rows if row["date"] in set(days)]
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(selected)
    target.write_text(text.getvalue(), encoding="utf-8")
    return target


class MarketDataUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = Config(self.root / "state")
        self.full = demo_csv(self.root / "full.csv", 200, 6)
        rows = list(csv.DictReader(io.StringIO(self.full.read_text(encoding="utf-8"))))
        self.days = sorted({row["date"] for row in rows})
        self.base_days, self.new_days = self.days[:150], self.days[150:]
        self.base_csv = _slice(self.full, self.root / "base.csv", self.base_days)
        self.new_csv = _slice(self.full, self.root / "new.csv", self.new_days)
        self.base = import_csv(self.cfg, self.base_csv, synthetic=True)["snapshot_id"]

    def cutoff_for(self, day: str, offset: int = 0) -> str:
        shifted = date.fromisoformat(day) + timedelta(days=offset)
        return f"{shifted.isoformat()}T20:00:00+08:00"

    def test_incremental_update_appends_without_touching_the_base(self):
        result = update_bars(self.cfg, [self.new_csv], cutoff=self.cutoff_for(self.new_days[-1]), market="cn_a")
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["added_rows"], len(self.new_days) * 6)
        self.assertEqual(result["verdict"], "fresh")
        self.assertNotEqual(result["snapshot_id"], self.base)
        base_manifest, base_rows = load_snapshot(self.cfg, self.base)
        _, merged_rows = load_snapshot(self.cfg, result["snapshot_id"])
        self.assertEqual(len(base_rows), 150 * 6)
        self.assertEqual(len(merged_rows), 200 * 6)
        self.assertLessEqual({(row["date"], row["security_id"]) for row in base_rows},
                             {(row["date"], row["security_id"]) for row in merged_rows})
        self.assertEqual(base_manifest["end"], self.base_days[-1])
        history = update_history(self.cfg)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["base_snapshot"], self.base)
        self.assertEqual(history[0]["verdict"], "fresh")
        # Self-collected data starts as personal-only; platform use needs a recorded grant.
        authorization = dataset_auth.record(self.cfg, result["snapshot_id"])
        self.assertEqual(authorization["personal_training"], 1)
        self.assertEqual(authorization["platform_training"], 0)

    def test_identical_reimport_is_a_no_change(self):
        first = update_bars(self.cfg, [self.new_csv], cutoff=self.cutoff_for(self.new_days[-1]))
        second = update_bars(self.cfg, [self.new_csv], cutoff=self.cutoff_for(self.new_days[-1]),
                             base=first["snapshot_id"])
        self.assertEqual(second["status"], "no_change")
        self.assertEqual(second["snapshot_id"], first["snapshot_id"])
        self.assertEqual(len(update_history(self.cfg)), 1)

    def test_conflicting_restatement_is_rejected(self):
        rows = list(csv.DictReader(io.StringIO(self.new_csv.read_text(encoding="utf-8"))))
        rows[0]["close"] = str(float(rows[0]["close"]) * 1.5)
        rows[0]["high"] = rows[0]["close"]
        conflict = self.root / "conflict.csv"
        text = io.StringIO(newline="")
        writer = csv.DictWriter(text, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        conflict.write_text(text.getvalue(), encoding="utf-8")
        first = update_bars(self.cfg, [self.new_csv], cutoff=self.cutoff_for(self.new_days[-1]))
        with self.assertRaises(ValueError) as caught:
            update_bars(self.cfg, [conflict], cutoff=self.cutoff_for(self.new_days[-1]), base=first["snapshot_id"])
        self.assertIn("conflict", str(caught.exception))

    def test_stale_update_is_refused_unless_accepted(self):
        late_cutoff = self.cutoff_for(self.new_days[-1], offset=10)
        with self.assertRaises(ValueError) as caught:
            update_bars(self.cfg, [self.new_csv], cutoff=late_cutoff, max_staleness_days=3)
        self.assertIn("days before the cutoff", str(caught.exception))
        accepted = update_bars(self.cfg, [self.new_csv], cutoff=late_cutoff, max_staleness_days=3, allow_stale=True)
        self.assertEqual(accepted["verdict"], "stale_accepted")
        self.assertEqual(accepted["stale_days"], 10)
        self.assertEqual(update_history(self.cfg)[0]["verdict"], "stale_accepted")

    def test_one_bar_repeated_across_files_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            update_bars(self.cfg, [self.new_csv, self.new_csv], cutoff=self.cutoff_for(self.new_days[-1]))
        self.assertIn("more than one file", str(caught.exception))

    def test_freshness_reports_lag_without_rewriting_anything(self):
        snapshot = latest_snapshot(self.cfg)
        self.assertEqual(snapshot, self.base)
        check = freshness(self.cfg, self.base, self.cutoff_for(self.days[-1], offset=7), max_staleness_days=5)
        self.assertEqual(check["status"], "stale")
        self.assertEqual(check["stale_days"], 7 + (date.fromisoformat(self.days[-1]) - date.fromisoformat(self.base_days[-1])).days)
        self.assertEqual(check["latest_session"], self.base_days[-1])

    def test_unknown_base_snapshot_is_rejected(self):
        with self.assertRaises(ValueError):
            update_bars(self.cfg, [self.new_csv], cutoff=self.cutoff_for(self.new_days[-1]), base="0" * 64)


if __name__ == "__main__":
    unittest.main()
