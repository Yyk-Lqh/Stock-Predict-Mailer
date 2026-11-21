import csv
import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from stock_predict_mailer.bars_audit import audit
from stock_predict_mailer.calendar import import_actions, import_calendar
from stock_predict_mailer.cli import main
from stock_predict_mailer.core import Config
from stock_predict_mailer.data import FIELDS


def bar(day, symbol="sh.600519", close=10.0, available=None):
    return {"date": day, "security_id": symbol, "open": close, "high": close, "low": close,
            "close": close, "volume": 1000,
            "available_at": available or f"{day}T18:00:00+08:00", "source": "test"}


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name) / "ws"
        self.root.mkdir()
        self.cfg = Config(self.root)

    def tearDown(self):
        self.folder.cleanup()

    def write(self, rows, name="bars.csv"):
        path = Path(self.folder.name) / name
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        path.write_text(buffer.getvalue(), encoding="utf-8")
        return path

    def certify(self, days, market="CN"):
        path = Path(self.folder.name) / "calendar.csv"
        path.write_text("date\n" + "\n".join(days) + "\n", encoding="utf-8")
        import_calendar(self.cfg, path, market)
        return path

    def test_a_clean_file_reports_no_problems(self):
        report = audit(self.cfg, self.write([bar("2026-11-17"), bar("2026-11-18")]))
        self.assertTrue(report["ok"])
        self.assertEqual(report["rows"], 2)
        self.assertEqual(report["range"], ["2026-11-17", "2026-11-18"])
        self.assertEqual(report["problems"]["duplicates"], [])
        self.assertFalse(report["calendar"]["certified"])

    def test_duplicates_and_unreadable_rows_are_hard_problems(self):
        duplicate = self.write([bar("2026-11-17"), bar("2026-11-17")])
        report = audit(self.cfg, duplicate)
        self.assertFalse(report["ok"])
        self.assertEqual(report["problems"]["duplicates"], [{"security_id": "sh.600519", "date": "2026-11-17", "count": 2}])
        broken = self.write([bar("2026-11-17"), bar("2026-11-18", close=0.0)])
        report = audit(self.cfg, broken)
        self.assertFalse(report["ok"])
        self.assertEqual(report["problems"]["bad_rows"], [1])

    def test_available_at_before_the_close_is_a_hard_problem(self):
        path = self.write([bar("2026-11-17"), bar("2026-11-18", available="2026-11-18T10:00:00+08:00")])
        report = audit(self.cfg, path)
        self.assertFalse(report["ok"])
        self.assertEqual(report["problems"]["available_at_before_close"][0]["date"], "2026-11-18")

    def test_dates_outside_the_certified_calendar_are_hard_problems(self):
        self.certify(["2026-11-17", "2026-11-18"])
        report = audit(self.cfg, self.write([bar("2026-11-17"), bar("2026-11-19")]), market="CN")
        self.assertFalse(report["ok"])
        self.assertEqual(report["problems"]["dates_outside_calendar"], ["2026-11-19"])
        self.assertTrue(report["calendar"]["certified"])

    def test_missing_sessions_are_reported_without_failing(self):
        self.certify(["2026-11-17", "2026-11-18", "2026-11-19"])
        report = audit(self.cfg, self.write([bar("2026-11-17"), bar("2026-11-19")]), market="CN")
        self.assertTrue(report["ok"])
        self.assertEqual(report["problems"]["missing_sessions"], {"sh.600519": ["2026-11-18"]})

    def test_panel_dates_stand_in_when_no_calendar_is_given(self):
        rows = [bar("2026-11-17"), bar("2026-11-18"), bar("2026-11-19"),
                bar("2026-11-17", symbol="sz.000001"), bar("2026-11-19", symbol="sz.000001")]
        report = audit(self.cfg, self.write(rows))
        self.assertTrue(report["ok"])
        self.assertEqual(report["problems"]["missing_sessions"], {"sz.000001": ["2026-11-18"]})
        self.assertIn("未指定 --market", report["notes"][0])

    def test_large_moves_are_linked_to_registered_actions(self):
        rows = [bar("2026-11-17", close=10.0), bar("2026-11-18", close=5.0)]
        path = self.write(rows)
        without = audit(self.cfg, path)
        self.assertEqual(without["large_moves"][0]["change"], -0.5)
        self.assertFalse(without["large_moves"][0]["action_registered"])
        actions = Path(self.folder.name) / "actions.csv"
        actions.write_text("security_id,ex_date,kind,price_factor\nsh.600519,2026-11-18,split,0.5\n", encoding="utf-8")
        import_actions(self.cfg, actions)
        with_action = audit(self.cfg, path)
        self.assertTrue(with_action["large_moves"][0]["action_registered"])

    def test_available_at_is_compared_as_an_instant(self):
        same_moment = self.write([bar("2026-11-18", available="2026-11-18T07:30:00+00:00")])
        self.assertTrue(audit(self.cfg, same_moment)["ok"])
        too_early = self.write([bar("2026-11-18", available="2026-11-18T06:30:00+00:00")])
        report = audit(self.cfg, too_early)
        self.assertFalse(report["ok"])
        self.assertEqual(report["timezone"], "Asia/Shanghai")

    def test_a_file_without_the_contract_columns_is_refused(self):
        path = Path(self.folder.name) / "bad.csv"
        path.write_text("date,security_id\n2026-11-17,sh.600519\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            audit(self.cfg, path)


@unittest.skipUnless(importlib.util.find_spec("pyarrow"), "需要 research 额外依赖（pyarrow）")
class IngestGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        (base / "ws").mkdir()
        self.root = base / "ws"
        self.config = base / "config.toml"
        self.config.write_text('workspace = "./ws"\ntimezone = "Asia/Shanghai"\n', encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, rows):
        path = Path(self.temp.name) / name
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        path.write_text(buffer.getvalue(), encoding="utf-8")
        return path

    def run_cli(self, *args):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = main(["legacy", "--config", str(self.config), *args])
        return code, out.getvalue(), err.getvalue()

    def test_import_refuses_a_bar_known_before_the_close(self):
        path = self.write("bad.csv", [bar("2026-11-18", available="2026-11-18T10:00:00+08:00")])
        code, out, err = self.run_cli("import-csv", str(path))
        self.assertEqual(code, 2)
        self.assertIn("核对未通过", err)
        self.assertIn("available_at_before_close", out)
        self.assertFalse((self.root / "snapshots").exists())

    def test_the_flag_lets_a_known_bad_file_through(self):
        path = self.write("bad.csv", [bar("2026-11-18", available="2026-11-18T10:00:00+08:00")])
        code, _, _ = self.run_cli("import-csv", str(path), "--allow-audit-problems")
        self.assertEqual(code, 0)
        self.assertTrue(list((self.root / "snapshots").iterdir()))

    def test_a_clean_file_imports_normally(self):
        path = self.write("good.csv", [bar("2026-11-17"), bar("2026-11-18")])
        code, out, _ = self.run_cli("import-csv", str(path))
        self.assertEqual(code, 0)
        self.assertIn('"row_count": 2', out)


class CliTests(unittest.TestCase):
    def test_exit_code_follows_the_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "ws").mkdir()
            config = root / "config.toml"
            config.write_text('workspace = "./ws"\ntimezone = "Asia/Shanghai"\n', encoding="utf-8")
            clean = root / "clean.csv"
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerow(bar("2026-11-17"))
            clean.write_text(buffer.getvalue(), encoding="utf-8")
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(["legacy", "--config", str(config), "bars-audit", str(clean)]), 0)
            self.assertIn('"ok": true', out.getvalue())
            duplicated = root / "dup.csv"
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows([bar("2026-11-17"), bar("2026-11-17")])
            duplicated.write_text(buffer.getvalue(), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["legacy", "--config", str(config), "bars-audit", str(duplicated)]), 2)


if __name__ == "__main__":
    unittest.main()
