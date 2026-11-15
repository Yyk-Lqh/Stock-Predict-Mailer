"""Batch import: planning, manifest authority, idempotency and date safety."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.knowledge_api import open_store
from stock_predict_mailer.private_knowledge import importer


class ImportFixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "workspace"
        self.root.mkdir()
        self.inbox = self.base / "inbox"
        self.inbox.mkdir()

    def write(self, rel, text="甲公司供应商停产，交付存在风险。"):
        path = self.inbox / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def manifest(self, rows, name="manifest.csv"):
        path = self.base / name
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=importer.COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in importer.COLUMNS})
        return path

    def run(self, **kwargs):
        return importer.run(self.root, self.inbox, progress=False, **kwargs)

    def open_kb(self):
        return open_store(self.root)

    def close(self):
        self.tmp.cleanup()


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.f = ImportFixture()
        self.addCleanup(self.f.close)

    def test_directory_tree_supplies_logical_and_manifest_supplies_tags(self):
        self.f.write("公告/甲公司/供应链公告.txt")
        manifest = self.f.manifest([{
            "path": "公告/甲公司/供应链公告.txt", "source": "交易所公告", "document_date": "2026-03-01",
            "available_date": "2026-03-02", "valid_to": "2027-03-01",
            "companies": "甲公司、乙公司", "industries": "汽车零部件", "topics": "供应链;产能",
            "stock_codes": "600000.SH, 000001.SZ"}])
        summary = self.f.run(manifest=manifest)
        self.assertEqual(summary["totals"], {"queued": 1, "skipped": 0, "failed": 0})
        item = summary["queued"][0]
        self.assertEqual(item["logical"], "公告/甲公司/供应链公告")
        self.assertEqual(item["metadata"]["companies"], ["甲公司", "乙公司"])
        self.assertEqual(item["metadata"]["topics"], ["供应链", "产能"])
        self.assertEqual(item["metadata"]["valid_to"], "2027-03-01")
        kb, owner = self.f.open_kb()
        stored = kb.document(owner, item["document_id"])
        self.assertEqual(stored["metadata"]["source"], "交易所公告")
        self.assertEqual(stored["logical"], "公告/甲公司/供应链公告")

    def test_dry_run_plans_without_writing(self):
        self.f.write("宏观/利率.txt")
        manifest = self.f.manifest([{"path": "宏观/利率.txt", "available_date": "2026-05-02"}])
        summary = self.f.run(manifest=manifest, dry_run=True)
        self.assertEqual(summary["queued"][0]["status"], "planned")
        kb, owner = self.f.open_kb()
        self.assertEqual(kb.catalog(owner)["total"], 0)

    def test_repeat_import_skips_unchanged_content(self):
        self.f.write("研报/深度.md")
        first = self.f.run(available="2026-05-02")
        second = self.f.run(available="2026-05-02")
        self.assertEqual(first["totals"]["queued"], 1)
        self.assertEqual(second["totals"]["queued"], 0)
        self.assertIn("内容已存在", second["skipped"][0]["reason"])

    def test_missing_available_date_fails_instead_of_defaulting_to_today(self):
        self.f.write("公告/无日期.txt")
        summary = self.f.run()
        self.assertEqual(summary["totals"]["failed"], 1)
        self.assertIn("缺少可用日期", summary["failed"][0]["error"])

    def test_available_date_falls_back_to_document_date_and_is_reported(self):
        self.f.write("公告/有日期.txt")
        manifest = self.f.manifest([{"path": "公告/有日期.txt", "document_date": "2026-04-01"}])
        summary = self.f.run(manifest=manifest)
        self.assertEqual(summary["queued"][0]["metadata"]["available_date"], "2026-04-01")
        self.assertEqual(summary["warnings"]["available_date_inferred"], 1)

    def test_manifest_is_authoritative(self):
        self.f.write("公告/登记.txt")
        self.f.write("公告/未登记.txt")
        manifest = self.f.manifest([{"path": "公告/登记.txt", "available_date": "2026-03-02"},
                                    {"path": "公告/缺失.txt", "available_date": "2026-03-02"}])
        summary = self.f.run(manifest=manifest)
        self.assertEqual(summary["totals"]["queued"], 1)
        self.assertIn("清单未登记", summary["skipped"][0]["reason"])
        self.assertEqual([item["path"] for item in summary["failed"]], ["公告/缺失.txt"])
        self.assertIn("文件不存在", summary["failed"][0]["error"])

    def test_unsupported_and_oversized_files_are_skipped(self):
        self.f.write("公告/说明.docx.bak")
        (self.f.inbox / "公告").mkdir(exist_ok=True)
        (self.f.inbox / "公告" / "空.txt").write_bytes(b"")
        summary = self.f.run(available="2026-03-02")
        reasons = [item["reason"] for item in summary["skipped"]]
        self.assertEqual(len(reasons), 2)
        self.assertTrue(all("不支持" in reason or "空文件" in reason for reason in reasons), reasons)

    def test_write_manifest_prefills_paths_and_refuses_to_overwrite(self):
        self.f.write("公告/甲公司/公告.txt")
        target = self.f.base / "骨架.csv"
        result = self.f.run(write_manifest=target)
        self.assertEqual(result["rows"], 1)
        text = target.read_text(encoding="utf-8-sig").splitlines()
        self.assertIn("公告/甲公司/公告", text[1])
        with self.assertRaises(ServiceError) as caught:
            self.f.run(write_manifest=target)
        self.assertIn("清单已存在", caught.exception.message)

    def test_manifest_rejects_unknown_column(self):
        self.f.write("公告/甲.txt")
        path = self.f.base / "错列.csv"
        path.write_text("path,comapnies\n公告/甲.txt,甲公司\n", encoding="utf-8-sig")
        with self.assertRaises(ServiceError) as caught:
            self.f.run(manifest=path)
        self.assertIn("未知列", caught.exception.message)

    def test_changed_content_becomes_a_new_version_of_the_same_slot(self):
        path = self.f.write("公告/甲公司/公告.txt", "第一版：停产。")
        self.f.run(available="2026-03-02")
        path.write_text("第二版：已复产。", encoding="utf-8")
        summary = self.f.run(available="2026-03-02")
        self.assertEqual(summary["totals"]["queued"], 1)
        kb, owner = self.f.open_kb()
        self.assertEqual(len(kb.versions(owner, "公告/甲公司/公告")), 2)

    def test_limit_caps_one_run(self):
        for index in range(3):
            self.f.write(f"公告/{index}.txt", f"第 {index} 份资料。")
        summary = self.f.run(available="2026-03-02", limit=2)
        self.assertEqual(summary["totals"]["queued"], 2)
        self.assertIn("--limit", summary["skipped"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
