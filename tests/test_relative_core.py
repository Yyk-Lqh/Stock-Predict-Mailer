import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_server import relative_core as relative

LIST_HEADER = "股票代码,日期,概率,周收益\n"
PREDICTION_HEADER = "股票代码,日期,周序,概率,下周收益\n"


class RelativeListingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.big = Path(self.folder.name)
        self.root = self.big / "相对市场跌涨"
        self.root.mkdir()
        (self.big / "stock_data117.csv").write_text(
            "股票代码,股票名称\n000001,平安银行\n600000,浦发银行\n000002,万科A\n", encoding="utf-8-sig")
        patcher = mock.patch.dict(os.environ, {
            "STOCK_PREDICT_MAILER_DATAMART_BIG_DIR": str(self.big),
            "STOCK_PREDICT_MAILER_DATAMART_RELATIVE_DIR": str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_sides_slice_the_full_list(self):
        (self.root / "名单_20261120.csv").write_text(
            LIST_HEADER + "000001,2026-11-20,0.9,0.01\n600000,2026-11-20,0.5,0.0\n000002,2026-11-20,0.1,-0.02\n",
            encoding="utf-8-sig")
        both = json.loads(relative.listing(top=2))
        self.assertEqual([row["code"] for row in both["buy"]["items"]], ["000001", "600000"])
        self.assertEqual([row["code"] for row in both["avoid"]["items"]], ["000002", "600000"])
        self.assertEqual(both["buy"]["items"][0]["name"], "平安银行")
        self.assertEqual(both["total"], 3)
        everything = json.loads(relative.listing(side="all"))
        self.assertEqual(everything["returned"], 3)

    def test_as_of_reads_the_prediction_week(self):
        (self.root / "预测_涨_相对_0w_8s_abcd12.csv").write_text(
            PREDICTION_HEADER
            + "000001,2026-11-13,1,0.2,0.01\n600000,2026-11-13,1,0.8,0.02\n"
            + "000001,2026-11-20,2,0.9,0.03\n600000,2026-11-20,2,0.4,0.0\n", encoding="utf-8-sig")
        (self.root / "名单_20261120.csv").write_text(
            LIST_HEADER + "000001,2026-11-20,0.9,0.03\n", encoding="utf-8-sig")
        history = json.loads(relative.listing(side="buy", top=1, as_of="2026-11-13"))
        self.assertEqual(history["source"], "预测_涨_相对_0w_8s_abcd12.csv")
        self.assertEqual(history["as_of"], "2026-11-13")
        self.assertEqual(history["items"][0]["code"], "600000")

    def test_missing_artifacts_and_invalid_side(self):
        missing = json.loads(relative.listing())
        self.assertEqual(missing["error"]["code"], "ARTIFACT_MISSING")
        bad = json.loads(relative.listing(side="middle"))
        self.assertEqual(bad["error"]["code"], "INVALID_ARGUMENT")

    def test_status_reports_list_behind_predictions(self):
        (self.root / "周度特征缓存.csv").write_text(LIST_HEADER, encoding="utf-8-sig")
        (self.root / "名单_20261113.csv").write_text(
            LIST_HEADER + "000001,2026-11-13,0.9,0.01\n", encoding="utf-8-sig")
        (self.root / "预测_涨_相对_0w_8s_abcd12.csv").write_text(
            PREDICTION_HEADER + "000001,2026-11-20,2,0.9,0.01\n", encoding="utf-8-sig")
        os.utime(self.root / "名单_20261113.csv", (1_700_000_000, 1_700_000_000))
        report = json.loads(relative.status())
        self.assertTrue(report["list_behind_predictions"])
        self.assertEqual(report["latest_list_date"], "20261113")
        self.assertTrue(report["hints"])


if __name__ == "__main__":
    unittest.main()
