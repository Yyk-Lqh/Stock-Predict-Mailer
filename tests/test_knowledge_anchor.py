"""Entity anchoring: a question that names a subject must not return another issuer first."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from stock_predict_mailer.control.memory import Memory
from stock_predict_mailer.control.store import Store
from stock_predict_mailer.private_knowledge.service import Knowledge

META = {"document_date": "2026-10-01", "available_date": "2026-10-01"}


class AnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        store = Store(Path(self.tmp.name), Fernet.generate_key())
        self.owner = Memory(store).create_owner()['owner']
        self.kb = Knowledge(store)

    def ready(self, name, text, logical, **metadata):
        self.kb.upload(self.owner, name, text.encode(), {**META, **metadata}, logical)
        self.assertEqual(self.kb.process_one()['status'], 'ready')

    def bank(self):
        # 报表切片里不写公司名，只有元数据知道它属于谁 —— 关键词匹配永远连不上。
        self.ready('报表.md', '项目: 营业收入；本期: 1236.45；同比: 3.21', '财报/甲公司/2026Q3',
                   companies=['甲银行股份有限公司'], stock_codes=['600000.SH'])
        for name in ('乙银行', '丙银行'):
            self.ready(f'{name}.md', f'{name}股份有限公司 2026 年第三季度报告 营业收入 同比 增速',
                       f'公告/{name}/2026Q3', companies=[f'{name}股份有限公司'])

    def test_query_security_code_lifts_its_documents_above_better_worded_ones(self):
        self.bank()
        found = self.kb.search(self.owner, '600000.SH 三季报营收同比增速', limit=4)
        self.assertEqual(found['anchors'], [{'kind': 'stock_code', 'value': '600000.SH', 'source': 'query',
                                             'slots': ['财报/甲公司/2026Q3']}])
        self.assertEqual(found['results'][0]['logical'], '财报/甲公司/2026Q3')
        self.assertTrue(found['results'][0]['anchored'])
        # 锚定是一层排序，不是过滤器：别家的资料仍然排在后面，而不是消失。
        self.assertEqual({item['logical'] for item in found['results'][1:]}, {'公告/乙银行/2026Q3', '公告/丙银行/2026Q3'})

    def test_company_name_in_the_query_anchors_without_any_parameter(self):
        self.bank()
        found = self.kb.search(self.owner, '甲银行股份有限公司 三季报营收', limit=4)
        self.assertEqual([(item['kind'], item['value'], item['source']) for item in found['anchors']],
                         [('entity', '甲银行股份有限公司', 'query')])
        self.assertEqual(found['results'][0]['logical'], '财报/甲公司/2026Q3')

    def test_company_name_without_the_legal_suffix_still_anchors(self):
        self.bank()
        found = self.kb.search(self.owner, '甲银行 三季报营收', limit=4)
        self.assertEqual(found['results'][0]['logical'], '财报/甲公司/2026Q3')

    def test_explicit_entity_keeps_its_filter_semantics(self):
        self.bank()
        found = self.kb.search(self.owner, '三季报营收 营业收入', entity='甲银行股份有限公司', limit=4)
        self.assertEqual({item['logical'] for item in found['results']}, {'财报/甲公司/2026Q3'})
        self.assertEqual(found['anchors'][0]['source'], 'param')

    def test_pronoun_without_anchor_is_reported_instead_of_guessed(self):
        self.bank()
        found = self.kb.search(self.owner, '该公司三季报营收同比增速', limit=4)
        self.assertEqual(found['anchors'], [])
        self.assertTrue(any('指代' in warning for warning in found['warnings']))
        self.assertFalse(any(item['anchored'] for item in found['results']))

    def test_a_shorthand_entity_resolves_to_the_only_matching_company(self):
        self.bank()
        found = self.kb.search(self.owner, '三季报营收', entity='甲银行', limit=4)
        self.assertEqual(found['anchors'][0]['value'], '甲银行股份有限公司')
        self.assertEqual({item['logical'] for item in found['results']}, {'财报/甲公司/2026Q3'})

    def test_an_entity_that_matches_nothing_is_reported(self):
        self.bank()
        found = self.kb.search(self.owner, '三季报营收', entity='丁公司', limit=4)
        self.assertTrue(any('主体名称' in warning for warning in found['warnings']))
        self.assertEqual(found['results'], [])

    def test_anchors_point_at_the_active_version_not_a_superseded_one(self):
        self.ready('旧.md', '项目: 营业收入；旧口径', '财报/甲公司/2026Q3',
                   companies=['甲银行股份有限公司'], stock_codes=['600000.SH'])
        self.ready('新.md', '项目: 营业收入；新口径', '财报/甲公司/2026Q3',
                   companies=['甲银行股份有限公司'], stock_codes=['600000.SH'])
        found = self.kb.search(self.owner, '600000.SH 营业收入', limit=4)
        self.assertTrue(found['results'])
        self.assertTrue(all(item['anchored'] for item in found['results']))
        self.assertIn('新口径', found['results'][0]['text'])


if __name__ == '__main__':
    unittest.main()
