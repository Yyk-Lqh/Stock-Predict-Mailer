"""Search presentation: version slots, expiry marks and echoed filters."""
from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.control.memory import Memory
from stock_predict_mailer.control.server import make_server
from stock_predict_mailer.control.store import Store
from stock_predict_mailer.private_knowledge.service import Knowledge

META = {"document_date": "2026-10-01", "available_date": "2026-10-01"}


class Fixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root, Fernet.generate_key())
        self.memory = Memory(self.store)
        self.owner = self.memory.create_owner()["owner"]
        self.kb = Knowledge(self.store)

    def ready(self, name, raw, metadata=None, logical=None):
        doc = self.kb.upload(self.owner, name, raw, metadata or META, logical)
        result = self.kb.process_one()
        if result is None or result["status"] != "ready":
            raise AssertionError(result)
        return doc["id"]

    def close(self):
        self.tmp.cleanup()


class SearchGroupingTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(self.f.close)
        self.kb, self.owner = self.f.kb, self.f.owner

    def test_one_long_document_does_not_crowd_out_others(self):
        long_id = self.f.ready('长报告.md', '\n'.join(f'供应链风险第{n}条：客户集中度上升' for n in range(6)).encode())
        short_id = self.f.ready('短报告.md', '供应链风险提示：单一客户占比过高'.encode(), logical='其他资料')
        found = self.kb.search(self.owner, '供应链风险', limit=2)
        # 每份资料先占一个名额，否则一份多切片资料会把另一个来源整个挤掉。
        self.assertEqual(len(found['results']), 2)
        self.assertEqual({item['logical'] for item in found['results']}, {'长报告.md', '其他资料'})
        self.assertEqual({item['document_id'] for item in found['results']}, {long_id, short_id})
        self.assertEqual(found['logical_total'], 2)
        group = next(g for g in found['groups'] if g['logical'] == '长报告.md')
        self.assertEqual((group['hits'], group['shown']), (6, 1))
        self.assertEqual(group['document_date'], '2026-10-01')

    def test_grouping_keeps_score_order_within_a_version(self):
        self.f.ready('多段.md', '\n'.join(f'营业收入 {n} 亿元，供应链稳定' for n in range(4)).encode())
        found = self.kb.search(self.owner, '营业收入', limit=3)
        scores = [item['score'] for item in found['results']]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(len({item['logical'] for item in found['results']}), 1)

    def test_hidden_versions_are_counted_not_silently_dropped(self):
        for name in ('甲.md', '乙.md', '丙.md'):
            self.f.ready(name, f'{name} 供应链 风险 提示'.encode())
        found = self.kb.search(self.owner, '供应链', limit=2)
        self.assertEqual((len(found['groups']), found['logical_total']), (2, 3))
        self.assertTrue(all(group['shown'] for group in found['groups']))

    def test_expired_document_is_marked_but_kept(self):
        self.f.ready('季报.md', '营业收入 12 亿元'.encode(),
                     {**META, 'valid_to': '2026-10-05'})
        after = self.kb.search(self.owner, '营业收入', as_of='2026-11-01')
        item, group = after['results'][0], after['groups'][0]
        self.assertTrue(item['expired'])
        self.assertTrue(group['expired'])
        self.assertEqual((group['valid_to'], group['document_date']), ('2026-10-05', '2026-10-01'))
        self.assertIn('资料已过有效期，仅作历史参考', item['warnings'])
        before = self.kb.search(self.owner, '营业收入', as_of='2026-10-03')
        self.assertFalse(before['results'][0]['expired'])
        self.assertFalse(before['groups'][0]['expired'])

    def test_table_columns_are_not_mistaken_for_conflicting_sources(self):
        # 表格行按行切片后，同一字段（本期）每行一个取值；那是数值列，不是来源冲突。
        self.f.ready('甲.csv', '项目,本期\n营业收入,1236.45\n净利润,402.18\n'.encode(), logical='财报/甲公司/2026Q3')
        self.assertEqual(self.kb.answer(self.owner, '本期')['conflicts'], [])
        self.f.ready('乙.csv', '项目,本期\n营业收入,2468.31\n'.encode(), logical='财报/乙公司/2026Q3')
        self.assertEqual(self.kb.answer(self.owner, '本期')['conflicts'], [])
        self.f.ready('丙.csv', '项目,本期\n营业收入,2500.00\n'.encode(), logical='财报/丙公司/2026Q3')
        self.assertEqual([item['field'] for item in self.kb.answer(self.owner, '本期')['conflicts']], ['本期'])

    def test_same_field_is_compared_within_one_subject_only(self):
        self.f.ready('甲.csv', '项目,本期\n营业收入,12\n'.encode(),
                     {**META, 'companies': ['甲银行']}, logical='财报/甲/2026Q3')
        self.f.ready('乙.csv', '项目,本期\n营业收入,13\n'.encode(),
                     {**META, 'companies': ['乙银行']}, logical='财报/乙/2026Q3')
        # 两家银行的「本期营业收入」本来就不该相等，这不是来源冲突。
        self.assertEqual(self.kb.answer(self.owner, '营业收入')['conflicts'], [])
        self.f.ready('丙.csv', '项目,本期\n营业收入,14\n'.encode(),
                     {**META, 'companies': ['甲银行']}, logical='财报/丙/2026Q3')
        conflict = next(item for item in self.kb.answer(self.owner, '营业收入')['conflicts'] if item['field'] == '本期')
        self.assertEqual({source['value'] for source in conflict['sources']}, {'12', '14'})

    def test_filters_are_echoed_for_the_console(self):
        self.f.ready('公告.md', '营业收入 12 亿元'.encode())
        found = self.kb.search(self.owner, '营业收入', as_of='2026-11-01', start_date='2026-10-01', limit=5)
        self.assertEqual((found['as_of'], found['start_date'], found['limit']), ('2026-11-01', '2026-10-01', 5))
        self.assertEqual(self.kb.search(self.owner, '营业收入', start_date='2026-10-02')['results'], [])
        self.assertEqual(self.kb.search(self.owner, '营业收入', start_date='2026-10-02')['groups'], [])

    def test_empty_result_still_reports_scope(self):
        found = self.kb.search(self.owner, '不存在的关键词')
        self.assertEqual((found['results'], found['groups'], found['logical_total']), ([], [], 0))

    def test_domain_scope_filters_before_ranking(self):
        self.f.ready('回购.md', '供应链 风险 提示'.encode(), logical='公告/甲公司/回购')
        self.f.ready('跟踪.md', '供应链 风险 提示'.encode(), logical='研报/中金/跟踪')
        allowed = self.kb.search(self.owner, '供应链风险', domains=['研报'])
        self.assertEqual({item['logical'] for item in allowed['results']}, {'研报/中金/跟踪'})
        self.assertEqual((allowed['domains'], allowed['logical_total']), (['研报'], 1))
        # 空列表表示什么都不许读，与「不限制」必须区分开。
        self.assertEqual(self.kb.search(self.owner, '供应链风险', domains=[])['results'], [])
        self.assertIsNone(self.kb.search(self.owner, '供应链风险')['domains'])
        with self.assertRaises(ServiceError):
            self.kb.search(self.owner, '供应链风险', domains='研报')


class AnswerRouteTests(unittest.TestCase):
    """The answer pane reads fields, not the joined text; keep that contract explicit."""

    def test_answer_route_returns_structured_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_server(Path(tmp), 0, Fernet.generate_key())
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}', timeout=30, trust_env=False) as client:
                    client.get('/')
                    client.headers['X-CSRF-Token'] = client.get('/api/session').json()['csrf_token']
                    client.headers['X-Memory-Key'] = client.post('/api/memory/access', json={}).json()['key']
                    rows = [{'subject': '甲公司', 'predicate': '供应商', 'object': '乙公司',
                             'valid_from': '2026-01-01', 'valid_to': '2026-12-31'}]
                    for name, body in (('关系.json', json.dumps(rows, ensure_ascii=False)),
                                       ('事件.txt', '乙公司发生停产事件，交期可能延长。')):
                        client.post('/api/knowledge/documents', json={'filename': name,
                            'data': base64.b64encode(body.encode()).decode(), 'metadata': META})
                    self.assertEqual(server.engine.knowledge.process_one()['status'], 'ready')
                    self.assertEqual(server.engine.knowledge.process_one()['status'], 'ready')
                    data = client.post('/api/knowledge/answer',
                                       json={'query': '甲公司供应链风险', 'limit': 4, 'as_of': '2026-11-01'}).json()
                    self.assertEqual(data['mode'], 'evidence_extract')
                    # 查询侧的两层加工（别名、锚定）必须活着穿过接口，控制台才有东西回显。
                    self.assertEqual(data['aliases'], [])
                    self.assertEqual(data['anchors'], [])
                    self.assertTrue(data['results'] and data['relations'] and data['inferences'])
                    self.assertTrue(all({'text', 'evidence_ids', 'kind'} <= set(item) for item in data['inferences']))
                    self.assertTrue(all({'doc', 'chunk', 'subject', 'predicate', 'object'} <= set(item) for item in data['relations']))
                    self.assertTrue(data['answer'])
                    self.assertTrue(data['warnings'])
                    self.assertEqual(client.post('/api/knowledge/answer', json={'query': ''}).status_code, 400)
                    self.assertEqual(client.post('/api/knowledge/answer', json={'query': '甲公司', 'limit': 0}).status_code, 400)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    unittest.main()
