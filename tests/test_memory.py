import sqlite3
import time
import unittest
from unittest.mock import AsyncMock, patch

import test_control
from stock_predict_mailer.agent_service.adapters import MockContextAdapter, MockPredictionAdapter


class MemoryFlowTests(unittest.TestCase):
    setUp = test_control.ConsoleAPITests.setUp
    tearDown = test_control.ConsoleAPITests.tearDown

    def access(self):
        result = self.client.post("/api/memory/access").json()
        self.client.headers["X-Memory-Key"] = result["key"]
        return result["key"]

    def conversation(self):
        response = self.client.post("/api/conversations")
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def run_task(self, cid, **fields):
        response = self.client.post("/api/tasks", json={"conversation_id": cid, **fields})
        self.assertEqual(response.status_code, 202, response.text)
        tid = response.json()["id"]
        for _ in range(150):
            task = self.client.get(f"/api/tasks/{tid}").json()
            if task["status"]["state"] in ("completed", "failed", "canceled"):
                break
            time.sleep(.02)
        self.assertEqual(task["status"]["state"], "completed", task)
        for _ in range(100):
            if tid not in self.server.engine.active:
                break
            time.sleep(.01)
        return tid, task["artifacts"][0]["parts"][0]["data"]["analysis"]

    def test_pending_pages_are_private_stable_and_non_consuming(self):
        key = self.access()
        cid = self.conversation()
        memory = self.server.engine.memory
        owner = memory.owner(key)
        other = memory.create_owner()
        with self.server.engine.store.db() as con:
            for i in range(205):
                con.execute('INSERT INTO memory_pending VALUES (?,?,?,?,?)',
                            (f'pending-{i}', owner, cid, i, memory.seal({'content': f'记忆{i}'})))
            con.execute('INSERT INTO memory_pending VALUES (?,?,?,?,?)',
                        ('private-other', other['owner'], cid, 999, memory.seal({'content': 'other secret'})))
        legacy = self.client.get('/api/memory/pending').json()
        self.assertIsInstance(legacy, list)
        self.assertEqual(len(legacy), 100)
        self.assertEqual(legacy[0]['id'], 'pending-0')
        response = self.client.get('/api/memory/pending?limit=100')
        self.assertEqual(response.status_code, 200)
        page = response.json()
        self.assertIsInstance(page, dict)
        self.assertEqual(len(page['items']), 100)
        seen = page['items'][:]
        with self.server.engine.store.db() as con:
            con.execute('DELETE FROM memory_pending WHERE id=?', ('pending-104',))
            con.execute('INSERT INTO memory_pending VALUES (?,?,?,?,?)',
                        ('new-pending', owner, cid, 1000, memory.seal({'content': 'new'})))
        while page['next_before'] is not None:
            page = self.client.get('/api/memory/pending', params={'before': page['next_before'], 'limit': 100}).json()
            seen.extend(page['items'])
        ids = [item['id'] for item in seen]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {f'pending-{i}' for i in range(205)} - {'pending-104'})
        self.assertTrue(all(item['source_conversation'] == cid for item in seen))
        self.assertEqual(self.client.get('/api/memory/pending?before=0').json()['items'], [])
        with self.server.engine.store.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM memory_pending WHERE owner=?', (owner,)).fetchone()[0], 205)
        self.client.headers['X-Memory-Key'] = other['key']
        self.assertEqual([i['id'] for i in self.client.get('/api/memory/pending?limit=100').json()['items']], ['private-other'])
        del self.client.headers['X-Memory-Key']
        self.assertEqual(self.client.get('/api/memory/pending?limit=100').status_code, 403)

    def test_pending_rejects_invalid_pagination(self):
        self.access()
        for query in ('before=-1', 'before=9223372036854775808', 'before=no', 'limit=0', 'limit=101',
                      'limit=', 'before=', 'limit=1&limit=2', 'befor=1'):
            with self.subTest(query=query):
                response = self.client.get('/api/memory/pending?' + query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error']['code'], 'INVALID_INPUT')

    def test_history_pagination_delete_preserves_task_privacy(self):
        self.access()
        cid = self.conversation()
        memory = self.server.engine.memory
        with self.server.engine.store.db() as con:
            for i in range(25):
                con.execute('INSERT INTO conversation_turns(conversation,body) VALUES (?,?)', (cid, memory.seal({'message': str(i)})))
        first = self.client.get('/api/conversations/' + cid).json()
        second = self.client.get('/api/conversations/' + cid, params={'before': first['next_before']}).json()
        self.assertEqual(len(first['messages']), 20)
        self.assertEqual(len(second['messages']), 5)
        self.assertFalse({m['seq'] for m in first['messages']} & {m['seq'] for m in second['messages']})
        self.assertEqual(len(self.client.get('/api/conversations/' + cid + '/export').json()['messages']), 25)
        self.assertEqual(self.client.delete('/api/conversations/' + cid).status_code, 200)
        self.assertEqual(self.client.get('/api/conversations/' + cid).status_code, 404)
        owner = memory.owner(self.client.headers['X-Memory-Key'])
        with self.server.engine.store.db() as con:
            for i in range(101):
                con.execute('INSERT INTO memory_vectors VALUES (?,?,?,?,?,?,?)',
                            (str(i), owner, str(i), 'preference', None, memory.seal({'id': str(i)}), memory.seal({})))
        page = self.client.get('/api/memory?limit=100').json()
        tail = self.client.get('/api/memory', params={'before': page['next_before'], 'limit': 100}).json()
        self.assertEqual(len(page['items']), 100)
        self.assertEqual(len(tail['items']), 1)
        self.assertEqual(self.client.delete('/api/memory/access').json()['status'], 'revoked')
        self.assertEqual(self.client.get('/api/memory').status_code, 403)



    def test_compacts_and_resumes_validated_steps_with_exact_conditions(self):
        self.access()
        cid = self.conversation()
        self.client.put("/api/memory/settings", json={"enabled": True, "context_bytes": 1024, "recent_turns": 1})
        profile = self.f.mcp()
        settings = self.f.store.settings()
        settings["agents"]["main"]["tools"] = [profile["id"] + ":get_context"]
        self.f.store.save_settings(settings)
        prediction = {**MockPredictionAdapter().fetch(), "value": 12.25, "value_unit": "CNY"}
        constraints = ["预测周期保持 5 个交易日", "以 CNY 报告，保留 12.25"]
        # This fixture overrides the predicted value, so the upstream returns facts only:
        # a chart whose forecast ended at 10.74 would be correctly rejected as inconsistent.
        context = {k: v for k, v in MockContextAdapter().fetch().items() if k != "chart_data"}
        with patch.object(self.server.engine.mcp, "call", new=AsyncMock(return_value=context)) as tool:
            self.run_task(cid, prediction=prediction, constraints=constraints, message="请保持预测周期。")
            for _ in range(3):
                tid, analysis = self.run_task(cid, message="刚才那只股票，按前面的条件继续分析")
            self.assertEqual(tool.await_count, 1)
        self.assertEqual(analysis["prediction"]["subject"], prediction["subject"])
        self.assertEqual(analysis["prediction"]["horizon"], prediction["horizon"])
        self.assertEqual(analysis["user_constraints"], constraints)
        session = self.client.get(f"/api/conversations/{cid}").json()
        earliest = session["summary"][0]
        self.assertEqual(earliest["prediction"]["value"], 12.25)
        self.assertEqual(earliest["prediction"]["value_unit"], "CNY")
        self.assertEqual(earliest["steps"]["tools"], "completed")
        self.assertTrue(earliest["facts"][0]["source"])
        events = self.client.get(f"/api/tasks/{tid}/events").json()["events"]
        self.assertTrue(any("已压缩" in event["label"] for event in events))
        self.assertTrue(any("复用" in event["label"] for event in events))

    def test_cross_conversation_recall_edit_delete_and_owner_boundaries(self):
        key = self.access()
        cid = self.conversation()
        p = MockPredictionAdapter().fetch()
        pref = {"kind": "preference", "content": "偏好简版报告", "tags": ["报告格式"], "report_format": "brief"}
        historic = {"kind": "prediction", "content": "旧预测", "tags": ["预测"], "subject": p["subject"],
                    "applies_at": p["generated_at"], "data_version": p["model_version"]}
        self.run_task(cid, prediction={**p, "direction": "down"}, remember=[historic])
        self.run_task(cid, message="请记住我偏好简版报告")
        tid, analysis = self.run_task(self.conversation(), prediction={**p, "direction": "up"}, message="生成报告")
        self.assertEqual(analysis["report_format"], "brief")
        self.assertEqual(analysis["prediction"]["direction"], "up")
        self.assertEqual(analysis["inferences"][0]["code"], "MODEL_UP")
        events = self.client.get(f"/api/tasks/{tid}/events").json()["events"]
        self.assertTrue(any("prediction" in event.get("types", []) for event in events))
        mid = next(item["id"] for item in self.client.get("/api/memory").json() if item["kind"] == "preference")
        self.access()
        self.assertEqual(self.client.get("/api/memory").json(), [])
        for path in (f"/api/tasks/{tid}", f"/api/tasks/{tid}/events", f"/api/conversations/{cid}"):
            self.assertIn(self.client.get(path).status_code, (403, 404))
        self.assertEqual(self.client.delete(f"/api/memory/{mid}").status_code, 404)
        self.client.headers["X-Memory-Key"] = key
        self.assertEqual(self.client.put(f"/api/memory/{mid}", json={**pref, "content": "偏好标准版", "report_format": "standard"}).status_code, 200)
        _, corrected = self.run_task(self.conversation(), prediction=p)
        self.assertEqual(corrected["report_format"], "standard")
        self.assertEqual(self.client.delete(f"/api/memory/{mid}").status_code, 200)
        after, _ = self.run_task(self.conversation(), prediction=p)
        self.assertFalse(any("preference" in event.get("types", []) for event in self.client.get(f"/api/tasks/{after}/events").json()["events"]))

    def test_vector_write_failure_preserves_turn_until_retry(self):
        self.access()
        cid = self.conversation()
        self.client.put("/api/memory/settings", json={"enabled": True, "context_bytes": 1024, "recent_turns": 1})
        self.run_task(cid, prediction=MockPredictionAdapter().fetch(), message="保留较早原文和 3.14 CNY")
        with patch.object(self.server.engine.memory, "_write_vector", side_effect=sqlite3.OperationalError("simulated write failure")):
            tid, _ = self.run_task(cid, message="请记住持续关注这只股票",
                                   remember=[{"kind": "watchlist", "content": "关注 DEMO.SZ", "subject": "DEMO.SZ", "tags": ["关注标的"]}])
        events = self.client.get(f"/api/tasks/{tid}/events").json()["events"]
        self.assertTrue(any(event.get("code") == "MEMORY_WRITE_PENDING" for event in events))
        state = self.client.get(f"/api/conversations/{cid}").json()
        self.assertEqual(state["summary"], [])
        self.assertIn("3.14 CNY", state["messages"][0]["message"])
        self.assertEqual(len(self.client.get("/api/memory/pending").json()), 1)
        self.run_task(cid, message="继续")
        self.assertEqual(self.client.get("/api/memory/pending").json(), [])
        self.assertEqual(self.client.get("/api/memory").json()[0]["content"], "关注 DEMO.SZ")
