"""Local HTTP contract regression; synthetic data and file artifacts only."""
import base64
import tempfile
import threading
import time
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

from stock_predict_mailer.agent_service.adapters import MockPredictionAdapter
from stock_predict_mailer.control.server import make_server


class BackendHTTPTests(unittest.TestCase):
    def test_task_report_download_and_list(self):
        with tempfile.TemporaryDirectory() as folder:
            server = make_server(Path(folder), 0, Fernet.generate_key())
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}') as client:
                    client.get('/')
                    client.headers['X-CSRF-Token'] = client.get('/api/session').json()['csrf_token']
                    model = client.post('/api/models', json={'name': 'local mock'}).json()
                    settings = client.get('/api/settings').json()
                    settings['default_model_id'] = model['id']
                    settings['mail']['allow_synthetic'] = True
                    settings['mail']['recipient_allowlist'] = ['local@example.invalid']
                    client.put('/api/settings', json=settings).raise_for_status()
                    key = client.post('/api/memory/access', json={}).json()['key']
                    client.headers['X-Memory-Key'] = key
                    cid = client.post('/api/conversations', json={}).json()['id']
                    imported = client.post('/api/knowledge/documents', json={
                        'filename': 'evidence.txt', 'data': base64.b64encode('甲公司收入12亿元，来源尚需核实'.encode()).decode(),
                        'metadata': {'document_date': '2000-01-01', 'available_date': '2000-01-01'}})
                    self.assertEqual(imported.status_code, 202)
                    self.assertEqual(server.engine.knowledge.process_one()['status'], 'ready')

                    task = client.post('/api/tasks', json={'prediction': MockPredictionAdapter().fetch(), 'conversation_id': cid, 'notify': True, 'recipient': 'local@example.invalid', 'knowledge_query': '甲公司', 'knowledge_to_model': True}).json()
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        task = client.get('/api/tasks/' + task['id']).json()
                        if task['status']['state'] in ('completed', 'failed', 'canceled'):
                            break
                        time.sleep(0.02)
                    self.assertEqual(task['status']['state'], 'completed')
                    url = '/api/tasks/' + task['id']
                    report = client.get(url + '/report')
                    self.assertEqual(report.status_code, 200)
                    self.assertIn('text/html', report.headers['Content-Type'])
                    del client.headers['X-Memory-Key']
                    self.assertEqual(client.get(url + '/report').status_code, 403)
                    self.assertNotIn(task['id'], str(client.get('/api/tasks').json()))
                    client.headers['X-Memory-Key'] = key
                    self.assertEqual(client.get(url + '/mail').json()['status'], 'simulated')
                    self.assertEqual(client.post(url + '/mail/resolve', json={'delivered': True}).status_code, 400)

                    self.assertIn(task['id'], str(client.get('/api/tasks').json()))
                    analysis = client.get(url + '/analysis').json()
                    self.assertEqual(analysis['prediction']['prediction_id'], task['artifacts'][0]['parts'][0]['data']['analysis']['prediction']['prediction_id'])
                    citation = analysis['knowledge_evidence']['results'][0]['citation_id']
                    self.assertIn(citation, report.text)
                    mail_id = client.get(url + '/mail').json()['id']
                    eml = (Path(folder) / 'agent-outbox' / (mail_id + '.eml')).read_bytes()
                    message = BytesParser(policy=policy.default).parsebytes(eml)
                    for subtype in ('plain', 'html'):
                        body = message.get_body(preferencelist=(subtype,)).get_content()
                        self.assertIn(citation, body)
                        self.assertIn('12亿元', body)
                    with server.engine.store.db() as con:
                        self.assertEqual(con.execute('SELECT owner FROM memory_tasks WHERE task=?', (task['id'],)).fetchone()[0],
                                         server.engine.memory.owner(key))

                    self.assertEqual(client.get(url + '/report/../../config/local.toml').status_code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
