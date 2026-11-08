"""Private knowledge acceptance tests, using stdlib unittest and local services."""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet

from stock_predict_mailer.agent_service.adapters import MockPredictionAdapter
from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.control.memory import Memory
from stock_predict_mailer.control.orchestrator import Orchestrator
from stock_predict_mailer.control.server import make_server
from stock_predict_mailer.control.store import Store
from stock_predict_mailer.private_knowledge.embedding import EmbeddingAdapter, configuration
from stock_predict_mailer.private_knowledge.parsing import clean, parse
from stock_predict_mailer.private_knowledge.service import Knowledge
from stock_predict_mailer.private_knowledge.worker import run

META = {"document_date": "2026-10-01", "available_date": "2026-10-01"}


class Fixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.key = Fernet.generate_key()
        self.store = Store(self.root, self.key)
        self.memory = Memory(self.store)
        self.access = self.memory.create_owner()
        self.owner = self.access["owner"]
        self.other = self.memory.create_owner()["owner"]
        self.kb = Knowledge(self.store)

    def ready(self, name, raw, metadata=None, logical=None):
        doc = self.kb.upload(self.owner, name, raw, metadata or META, logical)
        result = self.kb.process_one()
        if result is None or result["status"] != "ready":
            raise AssertionError(result)
        return doc["id"]

    def close(self):
        self.tmp.cleanup()


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(self.f.close)
        self.kb, self.owner = self.f.kb, self.f.owner

    def test_duplicate_json_keys_rejected_at_any_depth(self):
        for raw in (b'{"revenue":12,"revenue":13}', b'{"x":{"a":1,"a":2}}'):
            with self.assertRaises(ServiceError) as caught:
                parse('a.json', raw)
            self.assertEqual(caught.exception.code, 'REVIEW_REQUIRED')

    def test_duplicate_docx_headers_rejected(self):
        raw = io.BytesIO()
        xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:tbl>'
        for cells in (('收入', '收入'), ('12', '13')):
            xml += '<w:tr>' + ''.join('<w:tc><w:p><w:r><w:t>' + v + '</w:t></w:r></w:p></w:tc>' for v in cells) + '</w:tr>'
        xml += '</w:tbl></w:body></w:document>'
        with zipfile.ZipFile(raw, 'w') as archive:
            archive.writestr('word/document.xml', xml)
        with self.assertRaises(ServiceError):
            parse('a.docx', raw.getvalue())

    def test_amount_is_not_stock_identifier(self):
        self.f.ready('amount.csv', '公司,营业收入(元)\n甲公司,600000\n'.encode())
        self.assertEqual(self.kb.search(self.owner, '甲公司', stock_code='600000.SH')['results'], [])
        self.f.ready('stock.csv', '公司,股票代码\n乙公司,600000\n'.encode())
        self.assertTrue(self.kb.search(self.owner, '乙公司', stock_code='600000.SH')['results'])

    def test_locked_original_keeps_retryable_record(self):
        did = self.f.ready('locked.txt', b'locked original')
        with patch.object(Path, 'unlink', side_effect=PermissionError('locked')):
            with self.assertRaises((ServiceError, PermissionError)):
                self.kb.delete(self.owner, did)
        self.assertEqual(self.kb.document(self.owner, did)['id'], did)
        self.assertEqual(self.kb.delete(self.owner, did)['status'], 'deleted')

    def test_as_of_replays_published_version(self):
        old = self.f.ready('history.txt', b'company revenue 12', META)
        logical = self.kb.document(self.owner, old)['logical']
        new = self.f.ready('history.txt', b'company revenue 13',
                           {'document_date': '2026-11-01', 'available_date': '2026-11-01'}, logical)
        found = self.kb.search(self.owner, 'revenue', as_of='2026-10-15')['results']
        self.assertEqual([r['document_id'] for r in found], [old])
        self.kb.delete(self.owner, new)
        self.assertEqual(self.kb.search(self.owner, 'revenue', as_of='2026-10-15')['results'], [])

    def test_text_dedup_provenance_and_encrypted_original(self):
        raw = '# 收入\n营业收入 12 亿元\n营业收入 12 亿元\n'.encode()
        did = self.f.ready('研究.md', raw)
        self.assertEqual(self.kb.upload(self.owner, '研究.md', raw, META)['id'], did)
        detail = self.kb.document(self.owner, did, True)
        self.assertEqual(len(detail['chunks']), 2)
        self.assertEqual(detail['chunks'][1]['occurrences'], [{'line': 2}, {'line': 3}])
        self.assertEqual(detail['chunks'][1]['heading'], '收入')
        found = self.kb.search(self.owner, '营业收入')
        citation = found['results'][0]
        self.assertEqual(citation['metadata']['document_date'], '2026-10-01')
        self.assertEqual(self.kb.citation(self.owner, citation['citation_id'])['chunk']['location']['line'], 2)
        self.assertEqual(self.kb.original(self.owner, did)[1], raw)
        self.assertNotIn(raw, (self.kb.root / self.owner / (did + '.bin')).read_bytes())
        self.assertEqual(self.f.memory.entries(self.owner), [])

    def test_update_failure_retry_and_delete_every_index(self):
        old = self.f.ready('财务.csv', '股票代码,营业收入(亿元),统计周期\n600000,12,2026Q3\n'.encode())
        new = self.kb.upload(self.owner, '财务.csv', b'bad\xff', META)
        self.assertEqual(self.kb.process_one()['status'], 'failed')
        self.assertTrue(self.kb.document(self.owner, old)['active'])
        with patch('stock_predict_mailer.private_knowledge.service.parse', side_effect=ServiceError('TEMP', 'temporary')):
            self.kb.retry(self.owner, new['id'])
            self.assertEqual(self.kb.process_one()['error'], 'TEMP')
        new_id = self.f.ready('财务.csv', '股票代码,营业收入(亿元),统计周期\n600000,18,2026Q3\n'.encode())
        self.assertFalse(self.kb.document(self.owner, old)['active'])
        results = self.kb.search(self.owner, '营业收入', stock_code='600000.SH')['results']
        self.assertTrue(results)
        self.assertTrue(all(item['document_id'] == new_id for item in results))
        self.kb.rebuild(self.owner)
        self.kb.delete(self.owner, new_id)
        self.assertEqual(self.kb.search(self.owner, '营业收入')['results'], [])
        with self.kb.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM vectors WHERE chunk NOT IN (SELECT id FROM chunks)').fetchone()[0], 0)
        with self.assertRaises(ServiceError):
            self.kb.original(self.owner, new_id)
        # Retired original remains available for historical citations, never reactivated.
        self.assertTrue(self.kb.original(self.owner, old)[1])

    def test_time_filters_owner_and_noninterference(self):
        did = self.f.ready('risk.txt', '600000.SH 供应链风险'.encode())
        first = self.kb.search(self.owner, '供应链')['results']
        other = self.kb.upload(self.f.other, 'secret.txt', '供应链 供应链 私密独家资料'.encode(), META)
        self.kb.process_one()
        self.assertEqual(self.kb.search(self.owner, '供应链')['results'], first)
        self.assertEqual(self.kb.search(self.f.other, '600000.SH')['results'], [])
        self.assertEqual(self.kb.search(self.owner, '供应链', as_of='2026-09-01')['results'], [])
        self.assertEqual(self.kb.search(self.owner, '供应链', start_date='2026-10-02')['results'], [])
        for function, args in ((self.kb.document, (did,)), (self.kb.original, (did,)),
                               (self.kb.delete, (did,)), (self.kb.retry, (did,)), (self.kb.citation, (did + ':0',))):
            with self.assertRaises(ServiceError):
                function(self.f.other, *args)
        self.assertEqual(other['status'], 'pending')

    def test_supply_chain_evidence_and_expired_edges(self):
        rows = [
            {'subject': '甲公司', 'predicate': '供应商', 'object': '乙公司', 'valid_from': '2026/01/01', 'valid_to': '2026/12/31'},
            {'subject': '乙公司', 'predicate': '所属行业', 'object': '半导体', 'valid_from': '2025-01-01'},
            {'subject': '甲公司', 'predicate': '供应商', 'object': '旧供应商', 'valid_to': '2025-12-31'},
        ]
        self.f.ready('供应链.json', json.dumps(rows, ensure_ascii=False).encode())
        self.f.ready('事件.txt', '乙公司发生停产事件，半导体交期可能延长，影响规模未披露。'.encode())
        answer = self.kb.answer(self.owner, '甲公司的供应链风险', entity='甲公司', as_of='2026-11-01')
        self.assertIn('停产事件', answer['answer'])
        self.assertIn('供应商', answer['answer'])
        self.assertTrue(answer['inferences'])
        self.assertIn('条件性推断', answer['answer'])
        self.assertTrue(answer['relations'])
        self.assertFalse(any(e['object'] == '旧供应商' for e in answer['relations']))
        for relation in answer['relations']:
            proof = next(r for r in answer['results'] if r['chunk_id'] == relation['chunk'])
            self.assertIn(relation['subject'], proof['text'])
            self.assertIn('[' + proof['citation_id'] + ']', answer['answer'])
        self.assertEqual(self.kb.answer(self.f.other, '甲公司')['results'], [])

    def test_record_dates_conflicting_values_and_future_exclusion(self):
        self.f.ready('a.csv', '公司,日期,营业收入(亿元)\n甲公司,2026/10/01,12\n甲公司,2026/12/01,99\n'.encode())
        self.f.ready('b.csv', '公司,日期,营业收入(亿元)\n甲公司,2026/10/01,13\n'.encode())
        found = self.kb.answer(self.owner, '甲公司营业收入', as_of='2026-11-01')
        self.assertEqual(len(found['results']), 2)
        self.assertTrue(all(r['metadata']['data_date'] == '2026-10-01' for r in found['results']))
        conflict = next(c for c in found['conflicts'] if c['field'] == '营业收入(亿元)')
        self.assertEqual({s['value'] for s in conflict['sources']}, {'12', '13'})
        self.assertTrue(all(r['fields']['营业收入(亿元)'] != '99' for r in found['results']))

    def test_cleaning_preserves_values_dates_units_and_docx_table(self):
        parsed = parse('a.csv', '股票代码,日期,营业收入(万元),统计周期\n600000,2026/10/01,123.450,2026Q3\n'.encode())
        chunk = clean(parsed)['chunks'][0]
        self.assertEqual(chunk['fields']['营业收入(万元)'], '123.450')
        self.assertEqual(chunk['normalized_fields']['日期'], '2026-10-01')
        self.assertEqual(chunk['fields']['统计周期'], '2026Q3')
        self.assertEqual(chunk['location']['row'], 2)
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>公司研究</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>收入(亿元)</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>12.30</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
        did = self.f.ready('a.docx', raw.getvalue())
        detail = self.kb.document(self.owner, did, True)
        self.assertEqual(detail['chunks'][1]['fields'], {'收入(亿元)': '12.30'})
        self.assertEqual(detail['chunks'][1]['location']['table_block'], 2)
        self.assertTrue(detail['warnings'])

    @unittest.skipUnless(importlib.util.find_spec('openpyxl'), 'knowledge extra required')
    def test_excel_cells_formulas_and_units(self):
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet.title = '财报'
        sheet.append(['股票代码', '周期', '收入(亿元)'])
        sheet.append(['000001.SZ', '2026Q3', 12.5])
        sheet.append(['000001.SZ', '2026Q4', '=C2*2'])
        raw = io.BytesIO()
        book.save(raw)
        book.close()
        did = self.f.ready('a.xlsx', raw.getvalue())
        detail = self.kb.document(self.owner, did, True)
        self.assertEqual(detail['chunks'][0]['location']['cells'], 'A2:C2')
        self.assertEqual(detail['chunks'][0]['fields']['收入(亿元)'], '12.5')
        self.assertTrue(any('公式' in text for text in detail['warnings']))

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), 'knowledge extra required')
    def test_pdf_page_and_scan_review(self):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 10 280 Td (Company revenue 12 CNY) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        raw = io.BytesIO()
        writer.write(raw)
        self.assertTrue(PdfReader(io.BytesIO(raw.getvalue())).pages[0].extract_text())
        did = self.f.ready('report.pdf', raw.getvalue())
        self.assertEqual(self.kb.document(self.owner, did, True)['chunks'][0]['location']['page'], 1)
        blank = PdfWriter()
        blank.add_blank_page(width=300, height=300)
        raw = io.BytesIO()
        blank.write(raw)
        self.kb.upload(self.owner, 'scan.pdf', raw.getvalue(), META)
        self.assertEqual(self.kb.process_one()['error'], 'REVIEW_REQUIRED')

    def test_long_entity_is_flagged_instead_of_truncated(self):
        raw = json.dumps([{'subject': '甲' * 201, 'predicate': '供应商', 'object': '乙公司'}], ensure_ascii=False).encode()
        self.kb.upload(self.owner, 'long.json', raw, META)
        self.assertEqual(self.kb.process_one()['error'], 'REVIEW_REQUIRED')
        self.assertEqual(self.kb.search(self.owner, '乙公司')['results'], [])

    def test_two_importers_claim_each_job_once(self):
        from concurrent.futures import ThreadPoolExecutor
        for name in ('one.txt', 'two.txt'):
            self.kb.upload(self.owner, name, b'Company risk', META)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.kb.process_one(), range(4)))
        completed = [item for item in results if item]
        self.assertEqual(len(completed), 2)
        self.assertEqual(len({item['id'] for item in completed}), 2)
        self.assertTrue(all(item['status'] == 'ready' for item in completed))

    def test_worker_checkpoint_retry_uses_parsed_data_and_lock(self):
        did = self.kb.upload(self.owner, 'a.txt', b'Company risk', META)['id']
        with patch('stock_predict_mailer.private_knowledge.service.clean', side_effect=ValueError('private marker')):
            self.assertEqual(self.kb.process_one()['status'], 'failed')
        self.assertEqual(self.kb.document(self.owner, did)['step'], 'parsed')
        self.assertNotIn('private marker', json.dumps(self.kb.document(self.owner, did)))
        self.kb.retry(self.owner, did)
        with patch('stock_predict_mailer.private_knowledge.service.parse', side_effect=AssertionError('must resume')):
            self.assertEqual(self.kb.process_one()['status'], 'ready')
        self.kb.upload(self.owner, 'b.txt', b'Another risk', META)
        with patch.dict('os.environ', {'SPM_MASTER_KEY': self.f.key.decode()}):
            self.assertEqual(run(self.f.root, once=True), 0)
        self.assertEqual(len(self.kb.listing(self.owner)), 2)
        from stock_predict_mailer.core import Config
        from stock_predict_mailer.delivery import process_lock
        with patch.dict('os.environ', {'SPM_MASTER_KEY': self.f.key.decode()}), process_lock(Config(self.kb.root)), self.assertRaises(RuntimeError):
            run(self.f.root, once=True)
        with self.assertRaises(ServiceError):
            self.kb.upload(self.owner, '../escape.txt', b'bad')


class EmbedServer(BaseHTTPRequestHandler):
    requests = []
    dimension = 3
    invalid = False

    def log_message(self, *args):
        pass

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        type(self).requests.append((self.path, data))
        vectors = [[1.0, float('risk' in text.lower() or '风险' in text), .1][:self.dimension] for text in data['input']]
        if self.invalid:
            vectors = [[True]] * len(data['input'])
        result = {'embeddings': vectors} if self.path == '/api/embed' else {'data': [{'index': i, 'embedding': v} for i, v in reversed(list(enumerate(vectors)))]}
        raw = json.dumps(result).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(self.f.close)
        EmbedServer.requests, EmbedServer.dimension, EmbedServer.invalid = [], 3, False
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), EmbedServer)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def cfg(self, provider='ollama'):
        return {'provider': provider, 'base_url': self.url + ('/v1' if provider == 'openai_compatible' else ''),
                'model': 'local-test', 'version': 'v1', 'api_key': 'fixture-key'}

    def test_local_and_compatible_real_http_switch_atomic_failure(self):
        kb, owner = self.f.kb, self.f.owner
        self.f.ready('a.txt', b'Company risk')
        kb.config(owner, self.cfg())
        self.assertEqual(kb.test(owner)['dimension'], 3)
        first = kb.rebuild(owner)
        self.assertEqual(first['dimension'], 3)
        self.assertFalse(EmbedServer.requests[-1][1]['truncate'])
        kb.config(owner, self.cfg('openai_compatible'))
        self.assertEqual(kb.config(owner)['active_index'], first['id'])
        EmbedServer.invalid = True
        with self.assertRaises(ServiceError):
            kb.rebuild(owner)
        self.assertEqual(kb.config(owner)['active_index'], first['id'])
        self.assertEqual(kb.indexes(owner)[0]['status'], 'failed')
        EmbedServer.invalid = False
        second = kb.rebuild(owner)
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(EmbedServer.requests[-1][0], '/v1/embeddings')
        self.assertNotIn('fixture-key', json.dumps(kb.config(owner)))
        self.assertNotIn(b'fixture-key', (kb.root / 'knowledge.sqlite3').read_bytes())
        self.assertTrue(kb.search(owner, 'risk')['results'])
        self.assertEqual(kb.indexes(owner)[1]['status'], 'failed')
        EmbedServer.dimension = 2
        self.assertTrue(any('DIMENSION' in warning for warning in kb.search(owner, 'risk')['warnings']))

    def test_rebuild_mutation_and_failed_import_preserve_old(self):
        kb, owner = self.f.kb, self.f.owner
        did = self.f.ready('a.txt', b'Old risk')
        kb.config(owner, self.cfg())
        first = kb.rebuild(owner)['id']
        kb.upload(owner, 'a.txt', b'New risk', META)
        EmbedServer.invalid = True
        self.assertEqual(kb.process_one()['status'], 'failed')
        self.assertTrue(kb.document(owner, did)['active'])
        EmbedServer.invalid = False
        original = kb.adapter.embed
        def deleting(cfg, texts):
            result = original(cfg, texts)
            kb.delete(owner, did)
            return result
        with patch.object(kb.adapter, 'embed', side_effect=deleting), self.assertRaises(ServiceError):
            kb.rebuild(owner)
        self.assertEqual(kb.config(owner)['active_index'], first)
        self.assertEqual(kb.search(owner, 'Old')['results'], [])

    def test_revoking_remote_consent_stops_old_index_queries(self):
        kb, owner = self.f.kb, self.f.owner
        self.f.ready('a.txt', b'Company risk')
        kb.config(owner, {'provider': 'openai_compatible', 'base_url': 'https://remote.example/v1',
                          'model': 'test', 'allow_external': True})
        with patch.object(kb.adapter, 'embed', return_value=[[1., 0., 0.]]) as embed:
            kb.rebuild(owner)
            before = embed.call_count
            kb.config(owner, {'provider': 'openai_compatible', 'base_url': 'https://remote.example/v1',
                              'model': 'test', 'allow_external': False})
            result = kb.search(owner, 'risk')
            self.assertTrue(result['results'])
            self.assertTrue(any('EXTERNAL_CONSENT' in warning for warning in result['warnings']))
            self.assertEqual(embed.call_count, before)

    def test_external_consent_and_secret_destination(self):
        with self.assertRaises(ServiceError):
            configuration({'provider': 'ollama', 'base_url': 'https://external.example', 'model': 'a'})
        with self.assertRaises(ServiceError):
            configuration({'provider': 'ollama', 'base_url': 'http://external.example', 'model': 'a', 'allow_external': True})
        kb, owner = self.f.kb, self.f.owner
        kb.config(owner, self.cfg())
        kb.config(owner, {**self.cfg(), 'base_url': self.url + '/changed', 'api_key': ''})
        self.assertFalse(kb.config(owner)['has_secret'])
        self.assertEqual(EmbeddingAdapter().embed(configuration({}), ['test']), [])


class HTTPTests(unittest.TestCase):
    def test_owner_csrf_upload_search_citation_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_server(Path(tmp), 0, Fernet.generate_key())
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}') as client:
                    client.get('/')
                    csrf = client.get('/api/session').json()['csrf_token']
                    client.headers['X-CSRF-Token'] = csrf
                    key = client.post('/api/memory/access', json={}).json()
                    client.headers['X-Memory-Key'] = key['key']
                    response = client.post('/api/knowledge/documents', json={'filename': 'a.txt', 'data': base64.b64encode('甲公司风险'.encode()).decode(), 'metadata': META})
                    self.assertEqual(response.status_code, 202)
                    did = response.json()['id']
                    large = client.post('/api/knowledge/documents', json={'filename': 'large.txt',
                        'data': base64.b64encode(b'x' * (1024 * 1024)).decode(), 'metadata': META})
                    self.assertEqual(large.status_code, 202)
                    self.assertEqual(client.delete('/api/knowledge/documents/' + large.json()['id']).status_code, 200)
                    self.assertEqual(server.engine.knowledge.process_one()['status'], 'ready')
                    result = client.post('/api/knowledge/answer', json={'query': '甲公司'}).json()
                    self.assertTrue(result['results'])
                    self.assertEqual(client.get(result['results'][0]['citation_path']).status_code, 200)
                    client.headers['X-Memory-Key'] = client.post('/api/memory/access', json={}).json()['key']
                    self.assertEqual(client.get('/api/knowledge/documents/' + did).status_code, 404)
                    self.assertEqual(client.post('/api/knowledge/search', json={'query': '甲公司'}).json()['results'], [])
                    client.headers['X-Memory-Key'] = key['key']
                    client.headers['X-CSRF-Token'] = 'wrong'
                    self.assertEqual(client.delete('/api/knowledge/documents/' + did).status_code, 403)
                    client.headers['X-CSRF-Token'] = csrf
                    self.assertEqual(client.delete('/api/knowledge/documents/' + did).status_code, 200)
                    self.assertEqual(client.post('/api/knowledge/search', json={'query': '甲公司'}).json()['results'], [])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


class AnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_opt_in_knowledge_context_and_private_task(self):
        f = Fixture()
        self.addCleanup(f.close)
        f.ready('risk.txt', '甲公司供应链风险'.encode())
        model = f.store.put('models', {'name': 'Mock'})
        settings = f.store.settings()
        settings['default_model_id'] = model['id']
        f.store.save_settings(settings)
        engine = Orchestrator(f.store)
        cid = engine.memory.new(f.owner)['id']
        request = engine.prepare({'prediction': MockPredictionAdapter().fetch(), 'conversation_id': cid,
                                  'knowledge_query': '甲公司', 'knowledge_to_model': True, 'complexity': 'simple'}, f.owner)
        calls = []
        original = engine.models.generate
        async def capture(pid, role, data, settings, budget):
            calls.append(data)
            return await original(pid, role, data, settings, budget)
        with patch.object(engine.models, 'generate', side_effect=capture):
            result = await engine.execute('knowledge-test', request)
        self.assertEqual(result['status']['state'], 'completed')
        output = result['artifacts'][0]['parts'][0]['data']
        self.assertTrue(output['knowledge']['results'])
        self.assertEqual(calls[0]['source_material']['trust'], 'untrusted_source_material')
        with self.assertRaises(ServiceError):
            engine.prepare({'prediction': MockPredictionAdapter().fetch(), 'knowledge_query': '甲公司'}, f.owner)
