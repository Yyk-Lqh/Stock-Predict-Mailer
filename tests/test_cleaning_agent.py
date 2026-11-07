"""Evidence-gated cleaning model, durable review and protocol acceptance tests."""
from __future__ import annotations

import copy
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import httpx

from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.control.server import make_server
from stock_predict_mailer.private_knowledge.cleaner import (
    CleanerAdapter,
    batches,
    cleaner_config,
    extract,
    validate_candidate,
)
from test_private_knowledge import META, Fixture

RELATION = '自2026年1月1日起，乙公司是甲公司的供应商。'
EVENT = '2026年10月3日，乙公司发生停产事件。'
METRIC = '甲公司2026年第三季度营业收入为12.30亿元。'


def candidate(text, *, kind='relation', subject='甲公司', predicate='供应商', object='乙公司', **overrides):
    return {'kind': kind, 'chunk': 0, 'quote': text, 'start': 0, 'end': len(text), 'subject': subject,
            'predicate': predicate, 'object': object, 'assertion': 'asserted', 'valid_from': None,
            'valid_to': None, 'event_date': None, 'value': None, 'unit': None, 'period': None, **overrides}


class FakeCleaner:
    def __init__(self, proposals=None):
        self.proposals = proposals or []
        self.calls = 0

    def generate(self, cfg, chunks, metadata, *, timeout=None):
        self.calls += 1
        return copy.deepcopy(self.proposals)


class CleaningTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(self.f.close)
        self.kb, self.owner = self.f.kb, self.f.owner
        self.fake = FakeCleaner([candidate(RELATION, valid_from='2026-01-01')])
        self.kb.cleaner = self.fake
        self.cfg = {'provider': 'ollama', 'base_url': 'http://127.0.0.1:11434', 'model': 'fixture-cleaner', 'version': 'test-v1'}
        self.kb.cleaning_config(self.owner, self.cfg)

    def pending_review(self, text=RELATION, filename='announcement.txt'):
        did = self.kb.upload(self.owner, filename, text.encode(), META)['id']
        result = self.kb.process_one()
        self.assertEqual(result['status'], 'review', result)
        return did

    def approve(self, did, ids=None):
        review = self.kb.review(self.owner, did)
        approved = ids if ids is not None else [c['id'] for c in review['extraction']['candidates'] if c['validated']]
        return self.kb.review(self.owner, did, 'approve', review['digest'], approved)

    def test_disabled_by_default_and_independent_config(self):
        self.assertEqual(self.kb.cleaning_config(self.f.other)['provider'], 'none')
        self.assertEqual(self.kb.config(self.owner)['provider'], 'none')
        self.assertEqual(self.f.store.settings()['limits']['max_subagents'], 3)
        self.kb.cleaning_config(self.owner, {**self.cfg, 'api_key': 'cleaner-fixture-key'})
        self.assertNotIn('cleaner-fixture-key', json.dumps(self.kb.cleaning_config(self.owner)))
        self.assertNotIn(b'cleaner-fixture-key', (self.kb.root / 'knowledge.sqlite3').read_bytes())
        self.kb.cleaning_config(self.owner, {**self.cfg, 'base_url': 'http://127.0.0.1:12345'})
        self.assertFalse(self.kb.cleaning_config(self.owner)['has_secret'])

    def test_review_is_required_before_old_version_switch(self):
        self.kb.cleaning_config(self.owner, {})
        old = self.f.ready('announcement.txt', '旧的甲公司资料'.encode())
        self.kb.cleaning_config(self.owner, self.cfg)
        did = self.pending_review()
        self.assertTrue(self.kb.document(self.owner, old)['active'])
        self.assertFalse(self.kb.document(self.owner, did)['active'])
        self.assertEqual(self.kb.search(self.owner, '供应商')['results'], [])
        approved = self.approve(did)
        self.assertEqual(approved['status'], 'pending')
        self.assertEqual(approved['review']['decision'], 'approve')
        self.assertEqual(self.kb.process_one()['status'], 'ready')
        self.assertFalse(self.kb.document(self.owner, old)['active'])
        self.assertEqual(self.fake.calls, 1)
        result = self.kb.search(self.owner, '甲公司', entity='甲公司')
        self.assertEqual(result['relations'][0]['origin'], 'model_reviewed')
        self.assertIn(RELATION, result['relations'][0]['evidence'])
        self.assertTrue(result['results'][0]['extractions'])

    def test_invalid_quotes_numbers_and_dates_cannot_be_approved(self):
        self.fake.proposals = [candidate(RELATION, quote='甲公司与虚构公司合作。', end=11),
                               candidate(RELATION, valid_from='2025-01-01')]
        did = self.pending_review()
        result = self.kb.review(self.owner, did)
        self.assertTrue(all(not c['validated'] for c in result['extraction']['candidates']))
        with self.assertRaises(ServiceError):
            self.kb.review(self.owner, did, 'approve', result['digest'], [result['extraction']['candidates'][0]['id']])
        self.approve(did, [])
        self.assertEqual(self.kb.process_one()['status'], 'ready')
        self.assertFalse(self.kb.search(self.owner, '甲公司')['relations'])

    def test_metric_exact_value_unit_period_and_label(self):
        chunk = {'text': METRIC, 'fields': {}, 'location': {'line': 1}}
        good = candidate(METRIC, kind='metric', predicate='营业收入', object=None,
                         value='12.30', unit='亿元', period='2026年第三季度')
        self.assertTrue(validate_candidate(good, [chunk], {0})['validated'])
        for changes in ({'value': '12.3'}, {'unit': '元'}, {'period': '2025年第三季度'}, {'predicate': '净利润'}, {'value': '2026'}):
            self.assertFalse(validate_candidate({**good, **changes}, [chunk], {0})['validated'], changes)

    def test_negation_rumor_and_unknown_direction_preserved(self):
        for text, assertion in [('甲公司否认乙公司是其供应商。', 'negated'), ('乙公司可能是甲公司的供应商。', 'uncertain')]:
            self.fake.proposals = [candidate(text, assertion=assertion)]
            did = self.pending_review(text, assertion + '.txt')
            state = self.kb.review(self.owner, did)['extraction']
            self.assertTrue(state['candidates'][0]['validated'])
            self.approve(did)
            self.assertEqual(self.kb.process_one()['status'], 'ready')
            self.assertFalse(self.kb.search(self.owner, '甲公司')['relations'])
            bad = validate_candidate(candidate(text), [{'text': text, 'location': {}}], {0})
            self.assertIn('UNCERTAINTY_OR_NEGATION_LOST', bad['validation_errors'])
        co_occurrence = '甲公司和乙公司参加同一场大会。'
        self.assertFalse(validate_candidate(candidate(co_occurrence), [{'text': co_occurrence, 'location': {}}], {0})['validated'])

    def test_owner_stale_review_reject_and_delete(self):
        did = self.pending_review()
        with self.assertRaises(ServiceError):
            self.kb.review(self.f.other, did)
        review = self.kb.review(self.owner, did)
        with self.assertRaises(ServiceError):
            self.kb.review(self.owner, did, 'approve', 'stale', [])
        self.kb.review(self.owner, did, 'reject', review['digest'], [])
        self.assertEqual(self.kb.document(self.owner, did)['status'], 'rejected')
        self.kb.reextract(self.owner, did)
        self.assertEqual(self.kb.process_one()['status'], 'review')
        self.kb.delete(self.owner, did)
        with self.assertRaises(ServiceError):
            self.kb.review(self.owner, did)
        with self.kb.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM review_audit WHERE doc=?', (did,)).fetchone()[0], 0)

    def test_failed_model_and_retry_do_not_publish(self):
        did = self.kb.upload(self.owner, 'retry.txt', RELATION.encode(), META)['id']
        with patch.object(self.fake, 'generate', side_effect=ServiceError('CLEANER_UNAVAILABLE', 'private marker')):
            self.assertEqual(self.kb.process_one()['status'], 'failed')
        self.assertEqual(self.kb.document(self.owner, did)['step'], 'extracting')
        self.assertEqual(self.kb.search(self.owner, '甲公司')['results'], [])
        self.kb.retry(self.owner, did)
        with patch('stock_predict_mailer.private_knowledge.service.parse', side_effect=AssertionError('must resume')):
            self.assertEqual(self.kb.process_one()['status'], 'review')
        self.assertEqual(self.kb.review(self.owner, did)['extraction']['calls'], 2)

    def test_changed_config_requires_explicit_reset(self):
        did = self.kb.upload(self.owner, 'retry.txt', RELATION.encode(), META)['id']
        with patch.object(self.fake, 'generate', side_effect=TimeoutError()):
            self.kb.process_one()
        self.kb.cleaning_config(self.owner, {**self.cfg, 'model': 'new-version'})
        self.kb.retry(self.owner, did)
        self.assertEqual(self.kb.process_one()['error'], 'CLEANER_CONFIG_CHANGED')
        self.kb.reextract(self.owner, did)
        self.assertEqual(self.kb.process_one()['status'], 'review')

    def test_completed_batches_survive_failure_and_call_budget(self):
        self.kb.cleaning_config(self.owner, {**self.cfg, 'max_input_chars': 2000, 'max_calls': 3})
        text = '\n'.join('甲' * 1450 + str(i) for i in range(3))
        did = self.kb.upload(self.owner, 'long.txt', text.encode(), META)['id']
        values = [[], ServiceError('CLEANER_UNAVAILABLE', 'failure'), [], []]
        with patch.object(self.fake, 'generate', side_effect=values) as call:
            self.assertEqual(self.kb.process_one()['status'], 'failed')
            self.kb.retry(self.owner, did)
            self.assertEqual(self.kb.process_one()['error'], 'CLEANER_LIMIT')
            self.assertEqual(call.call_count, 3)
        state = self.kb.review(self.owner, did)['extraction']
        self.assertEqual(state['completed'], 2)
        self.assertEqual(state['calls'], 3)

    def test_budget_and_external_consent_prevent_requests(self):
        self.kb.cleaning_config(self.owner, {**self.cfg, 'budget_usd': 0.0, 'input_usd_per_million': 1.0})
        self.kb.upload(self.owner, 'budget.txt', RELATION.encode(), META)
        self.assertEqual(self.kb.process_one()['error'], 'CLEANER_BUDGET')
        self.assertEqual(self.fake.calls, 0)
        remote = {**self.cfg, 'base_url': 'https://external.example', 'allow_external': False}
        # The actual adapter must block remote content before opening the connection.
        with patch('stock_predict_mailer.private_knowledge.cleaner.build_opener') as network, self.assertRaises(ServiceError):
            CleanerAdapter().generate(cleaner_config(remote), [{'index': 0, 'text': RELATION}], {})
        network.assert_not_called()

    def test_same_period_metric_conflicts_are_explicit(self):
        for value, name in [('12.30', 'a.txt'), ('13.00', 'b.txt')]:
            text = f'甲公司2026年第三季度营业收入为{value}亿元。'
            self.fake.proposals = [candidate(text, kind='metric', predicate='营业收入', object=None,
                                              value=value, unit='亿元', period='2026年第三季度')]
            did = self.pending_review(text, name)
            self.approve(did)
            self.assertEqual(self.kb.process_one()['status'], 'ready')
        answer = self.kb.answer(self.owner, '甲公司营业收入')
        conflict = next(c for c in answer['conflicts'] if c.get('unit') == '亿元')
        self.assertEqual(conflict['subject'], '甲公司')
        self.assertEqual({s['value'] for s in conflict['sources']}, {'12.30', '13.00'})

    def test_equal_decimal_values_are_not_conflicts(self):
        for value, name in [('12.30', 'a.txt'), ('12.300', 'b.txt')]:
            text = f'甲公司2026年第三季度营业收入为{value}亿元。'
            self.fake.proposals = [candidate(text, kind='metric', predicate='营业收入', object=None,
                                              value=value, unit='亿元', period='2026年第三季度')]
            did = self.pending_review(text, name)
            self.approve(did)
            self.kb.process_one()
        self.assertEqual(self.kb.answer(self.owner, '甲公司营业收入')['conflicts'], [])

    def test_assertion_and_entity_whitespace_cannot_be_silently_changed(self):
        raw = candidate(RELATION, subject=' ')
        checked = validate_candidate(raw, [{'text': RELATION, 'location': {}}], {0})
        self.assertFalse(checked['validated'])
        raw = candidate(RELATION, valid_from='20260101')
        self.assertFalse(validate_candidate(raw, [{'text': RELATION, 'location': {}}], {0})['validated'])

    def test_supply_chain_approved_typed_event_and_future_event(self):
        did = self.pending_review()
        self.approve(did)
        self.kb.process_one()
        event = candidate(EVENT, kind='event', subject='乙公司', predicate='停产', object=None, event_date='2026-10-03')
        self.fake.proposals = [event]
        did = self.pending_review(EVENT, 'event.txt')
        self.approve(did)
        self.kb.process_one()
        answer = self.kb.answer(self.owner, '甲公司供应链风险', entity='甲公司', as_of='2026-11-01')
        self.assertTrue(answer['inferences'])
        self.assertEqual(len(answer['inferences'][0]['evidence_ids']), 2)
        before = self.kb.answer(self.owner, '甲公司供应链风险', entity='甲公司', as_of='2026-10-02')
        self.assertEqual(before['inferences'], [])


class CleanerServer(BaseHTTPRequestHandler):
    requests = []
    invalid = False

    def log_message(self, *args):
        pass

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        type(self).requests.append((self.path, data))
        supplied = json.loads(data['messages'][1]['content'])['chunks']
        text = supplied[0]['text']
        proposals = {'candidates': [candidate(text, chunk=supplied[0]['index'], valid_from='2026-01-01')]}
        content = 'not-json' if self.invalid else json.dumps(proposals, ensure_ascii=False)
        body = {'done': True, 'message': {'content': content}} if self.path == '/api/chat' else {
            'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class CleanerProtocolTests(unittest.TestCase):
    def test_both_real_http_protocols_and_invalid_output(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), CleanerServer)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            CleanerServer.requests, CleanerServer.invalid = [], False
            for provider, suffix in [('ollama', ''), ('openai_compatible', '/v1')]:
                cfg = cleaner_config({'provider': provider, 'base_url': f'http://127.0.0.1:{server.server_port}' + suffix, 'model': 'fixture'})
                result = CleanerAdapter().generate(cfg, [{'index': 0, 'text': RELATION}], {})
                self.assertEqual(result[0]['valid_from'], '2026-01-01')
                path, payload = CleanerServer.requests[-1]
                self.assertEqual(path, '/api/chat' if provider == 'ollama' else '/v1/chat/completions')
                schema = payload['format'] if provider == 'ollama' else payload['response_format']['json_schema']['schema']
                self.assertFalse(schema['additionalProperties'])
                CleanerServer.invalid = True
                with self.assertRaises(ServiceError):
                    CleanerAdapter().generate(cfg, [{'index': 0, 'text': RELATION}], {})
                CleanerServer.invalid = False
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_timeout_does_not_become_success_on_retry(self):
        cfg = cleaner_config({'provider': 'ollama', 'base_url': 'http://127.0.0.1:11434', 'model': 'fixture', 'document_timeout_seconds': 1})
        draft = {'chunks': [{'text': RELATION, 'fields': {}, 'location': {}}]}
        saved = []
        with patch('stock_predict_mailer.private_knowledge.cleaner.time.monotonic', side_effect=[0., 2.]), self.assertRaises(ServiceError):
            extract(FakeCleaner([]), cfg, draft, {}, lambda s: saved.append(copy.deepcopy(s)), lambda: None)
        with self.assertRaises(ServiceError):
            extract(FakeCleaner([]), cfg, draft, {}, lambda _: None, lambda: None, saved[-1])

    def test_no_silent_input_truncation(self):
        cfg = cleaner_config({'max_input_chars': 2000})
        draft = [{'text': 'x', 'fields': {}, 'location': {}}]
        with self.assertRaises(ServiceError):
            list(batches(draft, cfg, {'source': 'x' * 2500}))


class ReviewHTTPTests(unittest.TestCase):
    def test_review_and_config_api_private_key_and_csrf(self):
        f = Fixture()
        server = make_server(f.root, 0, f.key)
        server.engine.knowledge.cleaner = FakeCleaner([candidate(RELATION, valid_from='2026-01-01')])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}') as client:
                client.get('/')
                client.headers['X-CSRF-Token'] = client.get('/api/session').json()['csrf_token']
                client.headers['X-Memory-Key'] = f.access['key']
                config = {'provider': 'ollama', 'base_url': 'http://127.0.0.1:11434', 'model': 'fixture'}
                self.assertEqual(client.put('/api/knowledge/cleaner/config', json=config).status_code, 200)
                doc = server.engine.knowledge.upload(f.owner, 'a.txt', RELATION.encode(), META)
                server.engine.knowledge.process_one()
                route = '/api/knowledge/documents/' + doc['id'] + '/review'
                review = client.get(route).json()
                ids = [c['id'] for c in review['extraction']['candidates']]
                client.headers['X-Memory-Key'] = f.memory.create_owner()['key']
                self.assertEqual(client.get(route).status_code, 404)
                client.headers['X-Memory-Key'] = f.access['key']
                request = {'decision': 'approve', 'digest': review['digest'], 'approved_ids': ids}
                self.assertEqual(client.post(route, json=request).status_code, 200)
                self.assertEqual(server.engine.knowledge.process_one()['status'], 'ready')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            f.close()
