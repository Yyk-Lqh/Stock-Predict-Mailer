"""Alias expansion: it must widen recall without inventing evidence."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from stock_predict_mailer.control.memory import Memory
from stock_predict_mailer.control.store import Store
from stock_predict_mailer.private_knowledge.aliases import ALIASES, expand
from stock_predict_mailer.private_knowledge.service import Knowledge

META = {"document_date": "2026-10-01", "available_date": "2026-10-01"}


class ExpansionTableTests(unittest.TestCase):
    def test_a_report_period_maps_to_the_canonical_heading(self):
        query, applied = expand('三季报营收')
        self.assertIn('第三季度报告', query)
        self.assertIn('Q3', query)
        self.assertIn('营业收入', query)
        self.assertEqual([item['alias'] for item in applied], ['三季报', '营收'])
        self.assertIn('第三季度报告', applied[0]['canonical'])

    def test_longer_alias_claims_its_characters_first(self):
        _, applied = expand('三季报')
        # 「季报」是「三季报」的一部分，单独再扩展一次只会重复添加同样的全称。
        self.assertNotIn('季报', [item['alias'] for item in applied])
        self.assertEqual([item['alias'] for item in applied], ['三季报'])

    def test_latin_abbreviations_match_regardless_of_case(self):
        query, applied = expand('cpi 权重')
        self.assertEqual(applied, [{'alias': 'CPI', 'canonical': ['居民消费价格指数']}])
        self.assertIn('居民消费价格指数', query)

    def test_wording_that_is_already_canonical_is_left_alone(self):
        self.assertEqual(expand('营业收入 同比'), ('营业收入 同比', []))
        self.assertEqual(expand('供应链风险'), ('供应链风险', []))

    def test_neighbouring_concepts_are_not_treated_as_synonyms(self):
        # 产能利用率与开工率是两个不同口径，映射会把「问 A 答 B」变成静默行为。
        self.assertEqual(expand('产能利用率'), ('产能利用率', []))
        self.assertEqual(expand('降息'), ('降息', []))

    def test_table_has_no_duplicate_or_self_referential_members(self):
        for alias, canonical in ALIASES.items():
            self.assertTrue(canonical, alias)
            self.assertNotIn(alias, canonical)
            self.assertEqual(len(set(canonical)), len(canonical))


class AliasSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        store = Store(root, Fernet.generate_key())
        self.owner = Memory(store).create_owner()['owner']
        self.kb = Knowledge(store)

    def ready(self, name, text, logical):
        self.kb.upload(self.owner, name, text.encode(), META, logical)
        self.assertEqual(self.kb.process_one()['status'], 'ready')

    def test_canonical_document_outranks_one_that_only_echoes_the_shorthand(self):
        self.ready('报表.md', '项目: 营业收入；本期: 1236.45', '财报/测试公司/2026Q3')
        self.ready('口语.md', '营收 说明', '其他/口语')
        plain, _ = expand('营收')
        # 没有别名时，只提「营收」两个字的短文档命中更多词；这正是漏检的机制。
        found = self.kb.search(self.owner, '营收', limit=2)
        self.assertEqual(found['results'][0]['logical'], '财报/测试公司/2026Q3')
        self.assertEqual(found['aliases'], [{'alias': '营收', 'canonical': ['营业收入']}])
        self.assertIn('营业收入', plain)

    def test_expansion_reaches_a_heading_written_in_full(self):
        self.ready('公告.md', '上海某银行 2026 年第三季度报告 未经审计', '公告/某银行/三季报')
        self.ready('口语.md', '三季报 摘要', '其他/口语')
        found = self.kb.search(self.owner, '三季报', limit=2)
        self.assertEqual(found['results'][0]['logical'], '公告/某银行/三季报')

    def test_answer_carries_the_expansion_it_used(self):
        self.ready('报表.md', '项目: 营业收入；本期: 1236.45', '财报/测试公司/2026Q3')
        data = self.kb.answer(self.owner, '营收 同比', limit=4)
        self.assertEqual(data['aliases'], [{'alias': '营收', 'canonical': ['营业收入']}])
        self.assertIn('营业收入', data['answer'])

    def test_query_without_aliases_reports_none(self):
        self.ready('报表.md', '项目: 营业收入；本期: 1236.45', '财报/测试公司/2026Q3')
        self.assertEqual(self.kb.search(self.owner, '营业收入')['aliases'], [])


if __name__ == '__main__':
    unittest.main()
