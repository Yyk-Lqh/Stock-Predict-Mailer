"""Evaluation harness: what counts as a hit, a miss and an empty shelf."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.knowledge_api import open_store
from stock_predict_mailer.private_knowledge import evaluation

META = {"document_date": "2026-10-01", "available_date": "2026-10-01"}
RELATION = json.dumps([{"subject": "甲公司", "predicate": "供应商", "object": "乙公司",
                        "valid_from": "2026-01-01", "valid_to": "2026-12-31"}], ensure_ascii=False)


class EvalFixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "workspace"
        self.root.mkdir()
        self.kb, self.owner = open_store(self.root)

    def add(self, logical, text, metadata=None, process=True, name=None):
        item = self.kb.upload(self.owner, name or Path(logical).name + ".txt", text.encode(),
                              {**META, **(metadata or {})}, logical)
        if process:
            result = self.kb.process_one()
            if result is None or result["status"] != "ready":
                raise AssertionError(result)
        return item["id"]

    def write(self, cases, name="cases.json"):
        path = self.base / name
        path.write_text(json.dumps({"version": 1, "cases": cases}, ensure_ascii=False), encoding="utf-8")
        return path

    def run(self, cases, **kwargs):
        kwargs.setdefault("progress", False)
        return evaluation.run(self.root, self.write(cases), **kwargs)

    def close(self):
        self.tmp.cleanup()


def case(ident, query, **expect):
    return {"id": ident, "query": query, "as_of": "2026-11-01", "expect": expect}


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.f = EvalFixture()
        self.addCleanup(self.f.close)

    def test_slot_prefix_and_keyword_make_a_pass(self):
        self.f.add("研报/中金/半导体设备国产化率跟踪", "半导体设备国产化率提升至 35%。")
        report = self.f.run([case("c1", "半导体设备国产化率", logical=["研报/中金/半导体设备国产化率跟踪"], keywords=["国产化率"])])
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["totals"]["pass_rate"], 1.0)
        self.assertEqual((report["metrics"]["mrr"], report["metrics"]["mean_recall"]), (1.0, 1.0))

    def test_wrong_domain_fails_even_when_something_was_returned(self):
        # 两个域都有资料，才谈得上「检索跑到了别的域」；单域为空是 blocked，不是 fail。
        self.f.add("研报/中金/跟踪", "利率走廊 与 宏观 政策")
        self.f.add("产业/电力设备/产能", "动力电池 产能 扩张")
        report = self.f.run([case("c1", "利率走廊", domains=["产业"])])
        item = report["results"][0]
        self.assertEqual(item["status"], "fail")
        self.assertFalse(item["checks"]["domain"])
        self.assertEqual(item["mrr"], 0.0)

    def test_missing_slot_is_blocked_not_counted_as_a_miss(self):
        report = self.f.run([case("c1", "不存在的资料", logical=["公告/不存在/某公告"])])
        self.assertEqual((report["totals"]["evaluated"], report["totals"]["blocked"]), (0, 1))
        self.assertEqual(report["blocked"][0]["gold_missing"][0]["status"], "absent")
        self.assertEqual(report["verdict"], "empty")

    def test_domain_only_case_on_an_empty_domain_is_blocked(self):
        # An empty shelf must not be scored as a retrieval miss: the fix is import, not reindex.
        self.f.add("研报/中金/跟踪", "国产化率 提升")
        report = self.f.run([case("c1", "利率走廊", domains=["宏观"])])
        self.assertEqual(report["totals"]["blocked"], 1)
        self.assertIn("期望域内没有可检索的资料", report["blocked"][0]["gold_missing"][0]["detail"])

    def test_unprocessed_slot_reports_its_real_status(self):
        self.f.add("公告/甲公司/回购", "回购股份方案", process=False)
        report = self.f.run([case("c1", "回购", logical=["公告/甲公司/回购"])])
        self.assertEqual(report["blocked"][0]["gold_missing"][0]["status"], "pending")

    def test_a_pending_revision_does_not_hide_the_active_version(self):
        # 上传新版本后旧版本仍是 active，检索照样能读到；这时说「没资料」是误报。
        self.f.add("公告/甲公司/回购", "回购 股份 方案")
        self.f.add("公告/甲公司/回购", "回购 股份 方案（修订）", process=False)
        report = self.f.run([case("c1", "回购 股份", logical=["公告/甲公司/回购"])])
        self.assertEqual(report["totals"]["evaluated"], 1)
        self.assertEqual(report["results"][0]["status"], "pass")

    def test_partial_slot_recall_can_be_tolerated_per_case(self):
        self.f.add("公告/甲公司/回购", "回购 股份 方案")
        self.f.add("财报/甲公司/2026Q3", "回购 股份 说明")
        # limit=1 只可能取回一个槽位，用它制造真实的部分召回。
        strict = self.f.run([case("c1", "回购 股份", logical=["公告/甲公司/回购", "财报/甲公司/2026Q3"])], limit=1)
        loose = self.f.run([case("c2", "回购 股份", logical=["公告/甲公司/回购", "财报/甲公司/2026Q3"], min_recall=0.5)], limit=1)
        self.assertEqual(strict["results"][0]["status"], "fail")
        self.assertEqual(strict["results"][0]["recall"], 0.5)
        self.assertEqual(loose["results"][0]["status"], "pass")

    def test_point_in_time_leak_is_a_gate_not_a_score(self):
        # search() filters these out, so the guard is tested against its own input:
        # a leak means a backtest cannot be reproduced, which must not look like a miss.
        leaked = evaluation._leaks([{"citation_id": "abc:0", "metadata": {"available_date": "2026-12-01", "document_date": "2026-10-01"}}], "2026-11-01")
        self.assertEqual(leaked[0]["available_date"], "2026-12-01")
        self.assertEqual(evaluation._leaks([{"citation_id": "abc:0", "metadata": {"available_date": "2026-10-01", "document_date": None}}], "2026-11-01"), [])

    def test_relation_expectation_needs_the_graph(self):
        # 关系行只在结构化文件里抽取；同样的内容存成 .txt 不会被当成关系证据。
        self.f.add("供应链/甲公司/供应商关系", RELATION, name="供应商关系.json")
        self.f.add("供应链/甲公司/备注", "供应商 名单 见附表")
        with_graph = self.f.run([case("c1", "甲公司 供应商", domains=["供应链"], relation=True)], limit=4)
        self.assertEqual(with_graph["results"][0]["status"], "pass")
        flat = self.f.run([case("c2", "供应商 名单", domains=["供应链"], relation=True)], limit=4)
        self.assertEqual(flat["results"][0]["status"], "fail")
        self.assertFalse(flat["results"][0]["checks"]["relation"])

    def test_answer_mode_checks_inference_and_keeps_mode_explicit(self):
        self.f.add("供应链/甲公司/供应商关系", RELATION, name="供应商关系.json")
        self.f.add("供应链/乙公司/停产事件", "乙公司发生停产事件，交期可能延长。")
        report = self.f.run([case("c1", "甲公司 乙公司 停产", domains=["供应链"], inference=True)],
                            answer=True, limit=6)
        self.assertEqual(report["results"][0]["status"], "pass")
        self.assertTrue(report["answer"])
        self.assertTrue(report["results"][0]["checks"]["mode"])

    def test_answer_mode_reports_a_missing_inference(self):
        # 只有关系、没有事件：推断必须为空，否则「有推断」这条断言就是白送的。
        self.f.add("供应链/甲公司/供应商关系", RELATION, name="供应商关系.json")
        report = self.f.run([case("c1", "甲公司 供应商", domains=["供应链"], inference=True)],
                            answer=True, limit=4)
        self.assertEqual(report["results"][0]["status"], "fail")
        self.assertFalse(report["results"][0]["checks"]["inference"])


class JudgementTests(unittest.TestCase):
    def setUp(self):
        self.f = EvalFixture()
        self.addCleanup(self.f.close)
        self.f.add("研报/中金/跟踪", "半导体设备国产化率提升至 35%。")
        self.f.add("产业/电力设备/产能", "动力电池 产能 扩张")

    def test_threshold_decides_the_verdict(self):
        # c2 的查询词与产业资料没有共同字，取不到结果；两域都有资料，所以是 fail 不是 blocked。
        cases = [case("c1", "国产化率", domains=["研报"]), case("c2", "利率走廊", domains=["产业"])]
        self.assertEqual(self.f.run(cases, threshold=0.4)["verdict"], "pass")
        self.assertEqual(self.f.run(cases, threshold=0.6)["verdict"], "fail")

    def test_a_critical_failure_overrides_a_good_rate(self):
        cases = [case("c1", "国产化率", domains=["研报"]),
                 {**case("c2", "利率走廊", domains=["产业"]), "critical": True}]
        report = self.f.run(cases, threshold=0.4)
        self.assertEqual(report["totals"]["pass_rate"], 0.5)
        self.assertEqual(report["verdict"], "fail")
        self.assertEqual(report["critical_failed"], ["c2"])

    def test_domain_breakdown_counts_a_multi_domain_case_in_each(self):
        report = self.f.run([case("c1", "国产化率", domains=["研报", "产业"])])
        self.assertEqual({name: bucket["pass_rate"] for name, bucket in report["by_domain"].items()},
                         {"研报": 1.0, "产业": 1.0})

    def test_corpus_summary_explains_an_empty_workspace(self):
        empty = EvalFixture()
        self.addCleanup(empty.close)
        report = empty.run([case("c1", "任意", domains=["研报"])])
        self.assertEqual(report["corpus"]["slots"], 0)
        self.assertEqual(report["verdict"], "empty")
        self.assertTrue(report["note"])


class CaseFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def check(self, payload):
        path = self.root / "cases.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return evaluation._load(path)

    def test_unknown_keys_are_rejected_rather_than_ignored(self):
        # A typo in "expect" would otherwise score as a miss and look like a bad index.
        with self.assertRaises(ServiceError):
            evaluation._case(1, {"id": "c1", "query": "q", "expect": {"domian": ["研报"]}}, "2026-11-01")
        with self.assertRaises(ServiceError):
            self.check({"cases": [{"id": "c1", "query": "q"}], "case": []})

    def test_a_case_must_name_something_to_hit(self):
        with self.assertRaises(ServiceError):
            evaluation._case(1, {"id": "c1", "query": "q", "expect": {"keywords": ["x"]}}, "2026-11-01")

    def test_dates_and_numbers_are_validated(self):
        with self.assertRaises(ServiceError):
            evaluation._case(1, {"id": "c1", "query": "q", "as_of": "2026/11/01", "expect": {"domains": ["研报"]}}, "2026-11-01")
        with self.assertRaises(ServiceError):
            evaluation._case(1, {"id": "c1", "query": "q", "expect": {"domains": ["研报"], "min_recall": 1.5}}, "2026-11-01")
        with self.assertRaises(ServiceError):
            # 坏代码要在跑之前指出是哪条用例，而不是让 search() 中断整轮。
            evaluation._case(1, {"id": "c1", "query": "q", "stock_code": "60000", "expect": {"domains": ["研报"]}}, "2026-11-01")
        with self.assertRaises(ServiceError):
            evaluation._load(self.root / "missing.json")

    def test_duplicate_ids_stop_the_run(self):
        fixture = EvalFixture()
        self.addCleanup(fixture.close)
        report = fixture.write([case("c1", "q", domains=["研报"]), case("c1", "q", domains=["研报"])])
        with self.assertRaises(ServiceError):
            evaluation.run(fixture.root, report, progress=False)

    def test_shipped_example_set_parses(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "knowledge-eval" / "cases.json"
        cases = evaluation._load(path)
        prepared = [evaluation._case(number, item, "2026-11-01") for number, item in enumerate(cases, start=1)]
        self.assertEqual(len(prepared), 20)
        self.assertEqual({item["id"] for item in prepared if item["critical"]}, {"q03", "q06", "q07", "q20"})
        self.assertTrue(all(item["expect"]["domains"] for item in prepared))


if __name__ == '__main__':
    unittest.main()
