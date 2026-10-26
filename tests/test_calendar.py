import csv
import io
import tempfile
import unittest
from pathlib import Path

from stock_predict_mailer.calendar import (
    action_map,
    adjust_rows,
    calendar_status,
    import_actions,
    import_calendar,
    market_context,
)
from stock_predict_mailer.contracts import prepare_rows, read_contract, validate_contract
from stock_predict_mailer.core import Config
from stock_predict_mailer.data import demo_csv, import_csv, load_snapshot


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> Path:
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    path.write_text(text.getvalue(), encoding="utf-8")
    return path


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = Config(self.root / "state")
        self.contract = read_contract(Path("config/task-demo.json"))
        self.csv = demo_csv(self.root / "bars.csv", 200, 6)
        self.snapshot = import_csv(self.cfg, self.csv, synthetic=True)["snapshot_id"]
        _, self.raw = load_snapshot(self.cfg, self.snapshot)
        self.dates = sorted({row["date"] for row in self.raw})
        self.cutoff = f"{self.dates[-1]}T20:00:00+08:00"

    def test_calendar_import_is_idempotent_and_traceable(self):
        path = _write_csv(self.root / "calendar.csv", ["date"], [{"date": d} for d in self.dates])
        first = import_calendar(self.cfg, path, "synthetic", source="owner export 2026-10-26")
        self.assertEqual(first["imported"], len(self.dates))
        self.assertEqual(first["added"], len(self.dates))
        second = import_calendar(self.cfg, path, "synthetic", source="owner export 2026-10-26")
        self.assertEqual(second["added"], 0)
        self.assertEqual(second["total_sessions"], len(self.dates))
        status = calendar_status(self.cfg, "synthetic")
        self.assertTrue(status["certified"])
        self.assertEqual(status["sessions"], len(self.dates))
        self.assertFalse(calendar_status(self.cfg, "cn_a")["certified"])

    def test_certified_calendar_skips_a_missing_session_instead_of_compressing(self):
        gap = self.dates[100]
        without_gap = [row for row in self.raw if not (row["security_id"] == "SYN000" and row["date"] == gap)]
        observed_calendar = sorted({row["date"] for row in without_gap if row["security_id"] == "SYN000"})
        certified = self.dates  # the exchange did trade on the gap day
        _, observed = prepare_rows(without_gap, self.contract, self.cutoff)
        _, respected = prepare_rows(without_gap, self.contract, self.cutoff, sessions=certified)
        self.assertTrue(observed and respected)

        def by_key(rows):
            return {(row["date"], row["security_id"]): row for row in rows}

        observed_map, respected_map = by_key(observed), by_key(respected)
        # A label that would have matured through the gap must end later, never
        # be pulled one session closer by dropping the missing day.
        before_gap = [row for row in respected_map.values() if row["date"] < gap and (row["date"], row["security_id"]) in observed_map]
        self.assertTrue(before_gap)
        shifted = [row for row in before_gap if row["label_end"] != observed_map[(row["date"], row["security_id"])]["label_end"]]
        self.assertTrue(shifted, "dropping a benchmark day must not silently move the label window")
        index = {day: i for i, day in enumerate(certified)}
        for row in respected_map.values():
            self.assertEqual(row["label_end"], certified[index[row["date"]] + self.contract["horizon"] + 1])
        for row in observed_map.values():
            self.assertEqual(row["label_end"], observed_calendar[observed_calendar.index(row["date"]) + self.contract["horizon"] + 1])

    def test_actions_import_and_adjustment_math(self):
        path = _write_csv(self.root / "actions.csv",
                          ["security_id", "ex_date", "kind", "price_factor"],
                          [{"security_id": "SYN001", "ex_date": self.dates[120], "kind": "split", "price_factor": "0.5"}])
        result = import_actions(self.cfg, path, source="owner reconciliation")
        self.assertEqual(result["imported"], 1)
        actions = action_map(self.cfg)
        adjusted, summary = adjust_rows(self.raw, actions)
        lookup = {(row["date"], row["security_id"]): row for row in adjusted}
        before = [row for row in self.raw if row["security_id"] == "SYN001" and row["date"] < self.dates[120]]
        after = [row for row in self.raw if row["security_id"] == "SYN001" and row["date"] >= self.dates[120]]
        sample_before, sample_after = before[0], after[0]
        self.assertAlmostEqual(lookup[(sample_before["date"], "SYN001")]["close"], sample_before["close"] * 0.5)
        self.assertAlmostEqual(lookup[(sample_before["date"], "SYN001")]["volume"], sample_before["volume"] * 2)
        self.assertAlmostEqual(lookup[(sample_after["date"], "SYN001")]["close"], sample_after["close"])
        self.assertTrue(summary["adjusted"])
        # Securities without an action are passed through untouched.
        untouched = [row for row in self.raw if row["security_id"] == "SYN002"]
        for row in untouched:
            self.assertEqual(lookup[(row["date"], "SYN002")]["close"], row["close"])
            self.assertEqual(lookup[(row["date"], "SYN002")]["volume"], row["volume"])

    def test_adjustment_repairs_labels_that_cross_the_ex_date(self):
        ex_date = self.dates[120]
        path = _write_csv(self.root / "actions.csv",
                          ["security_id", "ex_date", "kind", "price_factor"],
                          [{"security_id": "SYN001", "ex_date": ex_date, "kind": "split", "price_factor": "0.5"}])
        import_actions(self.cfg, path)
        actions = action_map(self.cfg)
        adjusted_contract = validate_contract({**self.contract, "price_basis": "backward_adjusted"})
        _, plain = prepare_rows(self.raw, self.contract, self.cutoff)
        _, adjusted = prepare_rows(self.raw, adjusted_contract, self.cutoff, actions=actions)
        plain_y = {(row["date"], row["security_id"]): row["y"] for row in plain}
        adjusted_y = {(row["date"], row["security_id"]): row["y"] for row in adjusted}
        self.assertEqual(set(plain_y), set(adjusted_y))
        spanning = [row for row in plain if row["security_id"] == "SYN001"
                    and row["entry_date"] < ex_date <= row["label_end"]]
        clean = [row for row in plain if row["security_id"] == "SYN001"
                 and (row["label_end"] < ex_date or row["entry_date"] >= ex_date)]
        self.assertTrue(spanning, "the fixture must contain a label that spans the ex-date")
        # A split inside the holding period corrupts the raw open-to-open return;
        # adjustment is what makes that label usable, and it must not touch the rest.
        self.assertTrue(all(abs(plain_y[(r["date"], r["security_id"])] - adjusted_y[(r["date"], r["security_id"])]) > 1e-6
                            for r in spanning))
        self.assertTrue(all(abs(plain_y[(r["date"], r["security_id"])] - adjusted_y[(r["date"], r["security_id"])]) < 1e-9
                            for r in clean))

    def test_features_are_scale_invariant_except_across_the_ex_date(self):
        ex_date = self.dates[120]
        path = _write_csv(self.root / "actions.csv",
                          ["security_id", "ex_date", "kind", "price_factor"],
                          [{"security_id": "SYN001", "ex_date": ex_date, "kind": "split", "price_factor": "0.5"}])
        import_actions(self.cfg, path)
        actions = action_map(self.cfg)
        adjusted_contract = validate_contract({**self.contract, "price_basis": "backward_adjusted"})
        plain_features, _ = prepare_rows(self.raw, self.contract, self.cutoff)
        adjusted_features, _ = prepare_rows(self.raw, adjusted_contract, self.cutoff, actions=actions)
        plain = {(row["date"], row["security_id"]): row["x"] for row in plain_features}
        changed = {(row["date"], row["security_id"]): row["x"] for row in adjusted_features}
        self.assertEqual(set(plain), set(changed))
        position = {day: index for index, day in enumerate(self.dates)}
        for key in plain:
            day, security = key
            spans = security == "SYN001" and position[day] - 20 < position[ex_date] <= position[day]
            delta = max(abs(a - b) for a, b in zip(plain[key], changed[key], strict=True))
            if spans:
                self.assertGreater(delta, 1e-6)
            else:
                # A uniform scale is mathematically invariant for these ratios;
                # only floating-point noise is allowed here.
                self.assertLess(delta, 1e-9)

    def test_unadjusted_contract_ignores_actions(self):
        path = _write_csv(self.root / "actions.csv",
                          ["security_id", "ex_date", "kind", "price_factor"],
                          [{"security_id": "SYN001", "ex_date": self.dates[120], "kind": "split", "price_factor": "0.5"}])
        import_actions(self.cfg, path)
        adjusted_contract = validate_contract({**self.contract, "price_basis": "backward_adjusted"})
        sessions, actions = market_context(self.cfg, self.contract)
        self.assertIsNone(actions, "unadjusted contracts must not receive adjusted prices")
        self.assertIsNone(sessions)
        sessions, actions = market_context(self.cfg, adjusted_contract)
        self.assertIsNotNone(actions)

    def test_forward_adjusted_basis_is_rejected(self):
        path = _write_csv(self.root / "actions.csv",
                          ["security_id", "ex_date", "kind", "price_factor"],
                          [{"security_id": "SYN001", "ex_date": self.dates[120], "kind": "split", "price_factor": "0.5"}])
        import_actions(self.cfg, path)
        with self.assertRaises(ValueError):
            adjust_rows(self.raw, action_map(self.cfg), "forward_adjusted")

    def test_invalid_action_rows_are_rejected(self):
        bad_kind = _write_csv(self.root / "bad1.csv", ["security_id", "ex_date", "kind", "price_factor"],
                              [{"security_id": "SYN001", "ex_date": self.dates[5], "kind": "bonus", "price_factor": "0.5"}])
        with self.assertRaises(ValueError):
            import_actions(self.cfg, bad_kind)
        bad_factor = _write_csv(self.root / "bad2.csv", ["security_id", "ex_date", "kind", "price_factor"],
                                [{"security_id": "SYN001", "ex_date": self.dates[5], "kind": "split", "price_factor": "0"}])
        with self.assertRaises(ValueError):
            import_actions(self.cfg, bad_factor)
        missing = _write_csv(self.root / "bad3.csv", ["security_id", "ex_date", "kind", "price_factor"],
                             [{"security_id": "SYN001", "ex_date": self.dates[5], "kind": "split", "price_factor": "0.5"}])
        with self.assertRaises(ValueError):
            import_calendar(self.cfg, missing, "synthetic")

    def test_calendar_requires_a_source(self):
        path = _write_csv(self.root / "calendar.csv", ["date"], [{"date": d} for d in self.dates])
        with self.assertRaises(ValueError):
            import_calendar(self.cfg, path, "synthetic", source="  ")


if __name__ == "__main__":
    unittest.main()
