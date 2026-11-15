"""Queue depth and worker liveness: the console must not have to guess."""
from __future__ import annotations

import base64
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet

from stock_predict_mailer.agent_service.contracts import ServiceError, utcnow
from stock_predict_mailer.control.memory import Memory
from stock_predict_mailer.control.server import make_server
from stock_predict_mailer.control.store import Store
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
        self.owner = self.memory.create_owner()["owner"]
        self.other = self.memory.create_owner()["owner"]
        self.kb = Knowledge(self.store)

    def close(self):
        self.tmp.cleanup()


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(self.f.close)
        self.kb, self.owner, self.other = self.f.kb, self.f.owner, self.f.other

    def test_counts_and_attention_stay_inside_one_owner(self):
        for name in ('a.txt', 'b.txt'):
            self.kb.upload(self.owner, name, name.encode(), META)
        self.kb.upload(self.other, 'c.txt', b'gamma', META)
        mine = self.kb.queue(self.owner)
        self.assertEqual((mine['counts']['pending'], mine['waiting'], mine['total']), (2, 2, 2))
        self.assertEqual(mine['counts']['ready'], 0)
        self.assertEqual(self.kb.queue(self.other)['counts']['pending'], 1)
        self.assertEqual(mine['attention'], [])

    def test_failed_document_surfaces_with_a_readable_reason(self):
        did = self.kb.upload(self.owner, 'bad.txt', b'alpha', META)['id']
        with patch('stock_predict_mailer.private_knowledge.service.clean', side_effect=ValueError('boom')):
            self.assertEqual(self.kb.process_one()['status'], 'failed')
        queue = self.kb.queue(self.owner)
        self.assertEqual(queue['counts']['failed'], 1)
        self.assertEqual(queue['attention'][0]['id'], did)
        self.assertEqual(queue['attention'][0]['error_message'], '文件解析或导入失败，请检查格式和当前步骤')

    def test_heartbeat_moves_between_idle_busy_and_stopped(self):
        self.assertFalse(self.kb.worker_status()['seen'])
        self.kb.heartbeat('host-a', 4242, state='idle')
        status = self.kb.worker_status()
        self.assertEqual((status['seen'], status['online'], status['state']), (True, True, 'idle'))
        self.kb.heartbeat('host-a', 4242, state='busy', current='doc-1', processed=1)
        self.assertEqual(self.kb.worker_status()['current'], 'doc-1')
        self.kb.heartbeat('host-a', 4242, state='stopped')
        status = self.kb.worker_status()
        self.assertEqual((status['seen'], status['online'], status['state']), (True, False, 'stopped'))

    def test_silent_worker_is_offline_rather_than_never_started(self):
        self.kb.heartbeat('host-a', 4242, state='busy')
        with self.kb.db() as con:
            con.execute("UPDATE workers SET beat=?", ((utcnow() - timedelta(seconds=120)).isoformat(),))
        status = self.kb.worker_status()
        self.assertTrue(status['seen'])
        self.assertFalse(status['online'])
        self.assertGreaterEqual(status['age'], 90)

    def test_running_document_is_hidden_from_another_owner(self):
        did = self.kb.upload(self.owner, 'a.txt', b'alpha', META)['id']
        self.kb.heartbeat('host-a', 4242, state='busy', current=did)
        self.assertEqual(self.kb.queue(self.owner)['worker']['current_logical'], 'a.txt')
        seen = self.kb.queue(self.other)['worker']
        self.assertEqual(seen['state'], 'busy')
        self.assertIsNone(seen['current'])
        self.assertIsNone(seen['current_logical'])

    def test_limit_is_bounded(self):
        for broken in (0, 21, True, '5'):
            with self.assertRaises(ServiceError):
                self.kb.queue(self.owner, limit=broken)

    def test_once_worker_leaves_a_stopped_heartbeat_with_its_count(self):
        for name in ('a.txt', 'b.txt'):
            self.kb.upload(self.owner, name, name.encode(), META)
        with patch.dict('os.environ', {'STOCK_PREDICT_MAILER_MASTER_KEY': self.f.key.decode()}):
            self.assertEqual(run(self.f.root, once=True), 0)
        status = self.kb.worker_status()
        self.assertEqual((status['state'], status['processed'], status['online']), ('stopped', 2, False))
        self.assertEqual(self.kb.queue(self.owner)['counts']['ready'], 2)


class QueueHTTPTests(unittest.TestCase):
    def test_queue_route_reports_counts_and_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_server(Path(tmp), 0, Fernet.generate_key())
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}', trust_env=False) as client:
                    client.get('/')
                    client.headers['X-CSRF-Token'] = client.get('/api/session').json()['csrf_token']
                    client.headers['X-Memory-Key'] = client.post('/api/memory/access', json={}).json()['key']
                    client.post('/api/knowledge/documents', json={'filename': 'a.txt',
                        'data': base64.b64encode(b'alpha').decode(), 'metadata': META})
                    data = client.get('/api/knowledge/queue').json()
                    self.assertEqual((data['counts']['pending'], data['waiting']), (1, 1))
                    self.assertFalse(data['worker']['seen'])
                    server.engine.knowledge.heartbeat('host-a', 4242, state='idle')
                    self.assertTrue(client.get('/api/knowledge/queue').json()['worker']['online'])
            finally:
                server.shutdown()
                server.server_close()
