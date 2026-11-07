"""Regression coverage for pre-publish upload races and batch authorization."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from unittest import TestCase
from unittest.mock import patch

from stock_predict_mailer.agent_service.contracts import ServiceError
from stock_predict_mailer.core import atomic_write
from test_private_knowledge import META, Fixture


class PublicationRegressionTests(TestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(self.f.close)
        self.kb, self.owner = self.f.kb, self.f.owner

    def test_concurrent_duplicate_upload_keeps_one_original(self):
        first_write, second_write, release = Event(), Event(), Event()
        lock = Lock()
        writes = 0
        def delayed_write(path, data):
            nonlocal writes
            with lock:
                writes += 1
                first = writes == 1
            if first:
                first_write.set()
                if not release.wait(3):
                    raise AssertionError('upload test timed out')
            else:
                second_write.set()
            return atomic_write(path, data)
        with patch('stock_predict_mailer.private_knowledge.service.atomic_write', side_effect=delayed_write), ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(self.kb.upload, self.owner, 'same.txt', b'Company risk', META)
            self.assertTrue(first_write.wait(3))
            two = pool.submit(self.kb.upload, self.owner, 'same.txt', b'Company risk', META)
            second_write.wait(.3)
            release.set()
            self.assertEqual(one.result()['id'], two.result()['id'])
        self.assertEqual(writes, 1)
        self.assertEqual(len(list((self.kb.root / self.owner).glob('*.bin'))), 1)
        self.assertEqual(len(self.kb.listing(self.owner)), 1)

    def test_stale_retry_cannot_requeue_a_completed_import(self):
        doc = self.kb.upload(self.owner, 'retry.txt', b'Company risk', META)
        with patch('stock_predict_mailer.private_knowledge.service.clean', side_effect=ValueError('temporary')):
            self.assertEqual(self.kb.process_one()['status'], 'failed')
        read, release, progressed = Event(), Event(), Event()
        original = self.kb._row
        lock, calls = Lock(), 0
        def slow_read(con, owner, did):
            nonlocal calls
            row = original(con, owner, did)
            with lock:
                calls += 1
                first = calls == 1
            if first:
                read.set()
                if not release.wait(3):
                    raise AssertionError('retry test timed out')
            return row
        def fast_retry():
            try:
                self.kb.retry(self.owner, doc['id'])
                return self.kb.process_one()['status']
            except ServiceError as exc:
                return exc.code
            finally:
                progressed.set()
        with patch.object(self.kb, '_row', side_effect=slow_read), ThreadPoolExecutor(max_workers=2) as pool:
            slow = pool.submit(self.kb.retry, self.owner, doc['id'])
            self.assertTrue(read.wait(3))
            fast = pool.submit(fast_retry)
            progressed.wait(.3)
            release.set()
            slow.result()
            self.assertEqual(fast.result(), 'INVALID_STATE')
        self.assertEqual(self.kb.process_one()['status'], 'ready')

    def remote(self):
        return {'provider': 'openai_compatible', 'base_url': 'https://embedding.example/v1', 'model': 'fixture', 'allow_external': True}

    def test_revoking_during_rebuild_stops_next_batch(self):
        self.f.ready('many.txt', '\n'.join(f'Company risk {i}' for i in range(17)).encode())
        self.kb.config(self.owner, self.remote())
        calls = []
        def revoking(cfg, texts):
            calls.append(len(texts))
            self.kb.config(self.owner, {**self.remote(), 'allow_external': False})
            return [[1., 0.] for _ in texts]
        with patch.object(self.kb.adapter, 'embed', side_effect=revoking), self.assertRaises(ServiceError):
            self.kb.rebuild(self.owner)
        self.assertEqual(calls, [16])
        self.assertIsNone(self.kb.config(self.owner)['active_index'])

    def test_deleted_import_stops_next_batch(self):
        self.kb.config(self.owner, self.remote())
        with patch.object(self.kb.adapter, 'embed', return_value=[[1., 0.]]):
            self.kb.rebuild(self.owner)
        doc = self.kb.upload(self.owner, 'many.txt', '\n'.join(f'Company risk {i}' for i in range(17)).encode(), META)
        calls = []
        def deleting(cfg, texts):
            calls.append(len(texts))
            self.kb.delete(self.owner, doc['id'])
            return [[1., 0.] for _ in texts]
        with patch.object(self.kb.adapter, 'embed', side_effect=deleting):
            self.assertEqual(self.kb.process_one()['status'], 'deleted')
        self.assertEqual(calls, [16])

    def test_revoking_during_import_stops_next_batch(self):
        self.kb.config(self.owner, self.remote())
        with patch.object(self.kb.adapter, 'embed', return_value=[[1., 0.]]):
            self.kb.rebuild(self.owner)
        self.kb.upload(self.owner, 'many.txt', '\n'.join(f'Company risk {i}' for i in range(17)).encode(), META)
        calls = []
        def revoking(cfg, texts):
            calls.append(len(texts))
            self.kb.config(self.owner, {**self.remote(), 'allow_external': False})
            return [[1., 0.] for _ in texts]
        with patch.object(self.kb.adapter, 'embed', side_effect=revoking):
            self.assertEqual(self.kb.process_one()['error'], 'EXTERNAL_CONSENT')
        self.assertEqual(calls, [16])
