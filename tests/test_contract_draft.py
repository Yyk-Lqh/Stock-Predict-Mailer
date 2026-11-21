import csv
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from stock_predict_mailer.cli import main
from stock_predict_mailer.contracts import FEATURE_ORDER, contract_id, draft_contract
from stock_predict_mailer.core import Config
from stock_predict_mailer.data import FIELDS, import_csv


def bars(symbols, day="2026-11-18"):
    return [{"security_id": symbol, "date": day, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000,
             "available_at": f"{day}T18:00:00+08:00", "source": "test"} for symbol in symbols]


class DraftTests(unittest.TestCase):
    def test_the_universe_is_every_security_except_the_benchmark(self):
        contract = draft_contract(bars(["sh.000001", "sh.600519", "sz.000001", "sz.000333"]), "sh.000001")
        self.assertEqual(contract["universe"], ["sh.600519", "sz.000001", "sz.000333"])
        self.assertEqual(contract["features"], list(FEATURE_ORDER))
        self.assertEqual((contract["calendar"], contract["target"]),
                         ("benchmark_sessions", "open_to_open_excess_return"))
        self.assertEqual((contract["price_basis"], contract["volume_unit"]), ("unadjusted", "shares"))

    def test_drafting_twice_gives_the_same_id(self):
        source = bars(["sh.000001", "sh.600519", "sz.000001", "sz.000333"])
        self.assertEqual(contract_id(draft_contract(source, "sh.000001")),
                         contract_id(draft_contract(source, "sh.000001")))

    def test_repeated_rows_do_not_repeat_the_universe(self):
        source = bars(["sh.000001", "sh.600519", "sz.000001", "sz.000333"]) + \
            bars(["sh.000001", "sh.600519"], day="2026-11-19")
        contract = draft_contract(source, "sh.000001")
        self.assertEqual(len(contract["universe"]), len(set(contract["universe"])))

    def test_a_missing_benchmark_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            draft_contract(bars(["sh.600519", "sz.000001", "sz.000333"]), "sh.000001")
        self.assertIn("基准", str(caught.exception))

    def test_a_thin_universe_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            draft_contract(bars(["sh.000001", "sh.600519", "sz.000001"]), "sh.000001")
        self.assertIn("至少需要 3 个", str(caught.exception))


@unittest.skipUnless(importlib.util.find_spec("pyarrow"), "需要 research 额外依赖（pyarrow）")
class CommandTests(unittest.TestCase):
    def test_the_command_writes_a_contract_a_snapshot_supports(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "ws"
            root.mkdir()
            config = Path(folder) / "config.toml"
            config.write_text('workspace = "./ws"\ntimezone = "Asia/Shanghai"\n', encoding="utf-8")
            rows = bars(["sh.000001", "sh.600519", "sz.000001", "sz.000333"]) + \
                bars(["sh.000001", "sh.600519", "sz.000001", "sz.000333"], day="2026-11-19")
            raw = Path(folder) / "bars.csv"
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            raw.write_text(buffer.getvalue(), encoding="utf-8")
            snapshot = import_csv(Config(root), raw)["snapshot_id"]
            output = Path(folder) / "contract.json"
            with redirect_stdout(io.StringIO()) as printed:
                code = main(["legacy", "--config", str(config), "contract-draft", snapshot,
                             "--benchmark", "sh.000001", "--output", str(output)])
            self.assertEqual(code, 0)
            written = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(written["universe"], ["sh.600519", "sz.000001", "sz.000333"])
        self.assertIn('"contract_id"', printed.getvalue())


if __name__ == "__main__":
    unittest.main()
