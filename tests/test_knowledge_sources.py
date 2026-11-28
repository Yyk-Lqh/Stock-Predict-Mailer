import base64
import threading
import unittest

import httpx

from stock_predict_mailer.control.server import make_server
from stock_predict_mailer.private_knowledge.sources import SourceAdapter
from test_control import Fixture


class SyntheticSources:
    page_id = "b" * 32
    notion_url = "https://www.notion.so/" + page_id
    token = "fixture-source-token"
    notion_content = "NotionRiskAlpha 量化避险资料与组合管理。"

    def __init__(self):
        self.expired = False
        self.attempts = 0
        self.adapter = SourceAdapter(transport=httpx.MockTransport(self.respond))

    def respond(self, request):
        if request.headers.get("authorization") != "Bearer " + self.token or self.expired:
            return httpx.Response(401)
        if request.url.host == "api.notion.com":
            assert request.headers["notion-version"] == "2026-03-11"
            page = {"id": self.page_id, "object": "page", "url": self.notion_url, "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "组合风控笔记"}]}}}
            path = request.url.path
            if path == "/v1/users/me":
                return httpx.Response(200, json={"type": "bot", "bot": {"workspace_name": "研究团队（测试）"}})
            if path == "/v1/search":
                return httpx.Response(200, json={"results": [page], "has_more": False})
            if path == "/v1/pages/" + self.page_id:
                return httpx.Response(200, json=page)
            if path.endswith("/children"):
                return httpx.Response(200, json={"results": [{
                    "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": self.notion_content}]}
                }], "has_more": False})
            return httpx.Response(404)
        assert request.url.host == "r.jina.ai"
        assert request.headers["accept"] == "application/json"
        if request.url.path.endswith("/retry"):
            self.attempts += 1
            if self.attempts == 1:
                raise httpx.ReadTimeout("fixture timeout")
        return httpx.Response(200, json={"data": {"title": "公开市场资料", "content": "WebRiskBeta 公开市场流动性研究。"}})


class KnowledgeSourceAPITests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.server = make_server(self.fixture.root, 0, self.fixture.key)
        self.sources = SyntheticSources()
        self.server.knowledge_sources.adapter = self.sources.adapter
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{self.server.server_port}", trust_env=False)
        self.client.get("/")
        self.client.headers["X-CSRF-Token"] = self.client.get("/api/session").json()["csrf_token"]
        self.library = "a" * 32

    def tearDown(self):
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.fixture.close()

    def call(self, method, route, data=None, library=None, status=200):
        headers = {"X-Knowledge-Library": library} if library else {}
        response = self.client.request(method, "/api/knowledge/" + route, json=data, headers=headers)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def create(self):
        return self.call("POST", "libraries", {"id": self.library, "name": "单独资料库"}, status=201)

    def configure(self, provider):
        result = self.call("PUT", f"sources/{provider}", {"token": self.sources.token})
        self.assertEqual(result["state"], "connected")
        self.assertNotIn(self.sources.token, str(self.call("GET", "sources")))

    def process(self):
        while self.server.engine.knowledge.process_one():
            pass

    def test_local_upload_is_idempotent_and_retrievable_only_in_target_library(self):
        first = self.create()
        self.assertEqual(self.create(), first)
        options = self.call("GET", "import/options", library=self.library)
        self.assertIn(".txt", options["formats"])
        self.assertEqual(options["chunk_size"], 1600)
        raw = ("QuarterAlpha 跨市场研究报告。" * 200).encode()
        preview = self.call("POST", "import/segments", {
            "filename": "quarter.txt", "text": raw.decode(), "chunk_size": 400
        }, self.library)
        upload = {"filename": "quarter.txt", "data": base64.b64encode(raw).decode(), "chunk_size": 400}
        item = self.call("POST", "documents", upload, self.library, 202)
        self.assertEqual(self.call("POST", "documents", upload, self.library, 202)["id"], item["id"])
        self.process()
        document = self.call("GET", "documents/" + item["id"], library=self.library)
        self.assertEqual(document["status"], "ready")
        self.assertEqual(preview["count"], len(document["chunks"]))
        self.assertTrue(all(len(chunk["text"]) <= 400 for chunk in document["chunks"]))
        self.assertEqual(self.call("GET", "documents")["total"], 0)
        self.call("GET", "documents/" + item["id"], status=404)
        found = self.call("POST", "search", {"query": "QuarterAlpha"}, self.library)["results"]
        self.assertTrue(found)
        self.assertEqual(found[0]["document_id"], item["id"])
        self.assertFalse(self.call("POST", "search", {"query": "QuarterAlpha"})["results"])

    def test_notion_snapshot_scopes_versions_and_expired_authorization(self):
        self.assertEqual(self.call("GET", "sources")["items"][0]["state"], "unconfigured")
        self.configure("notion")
        self.assertEqual(self.call("POST", "sources/notion/pages", {"q": "组合"})["items"][0]["id"], self.sources.page_id)

        def preview():
            return self.call("POST", "sources/notion/preview", {"items": [self.sources.page_id]}, self.library)["items"][0]

        original = preview()
        self.assertIn("NotionRiskAlpha", original["excerpt"])
        self.create()
        body = {"id": original["id"], "chunk_size": 400}
        self.call("POST", "import/submit", body, status=404)
        segments = self.call("POST", "import/segments", body, self.library)
        self.assertIn("NotionRiskAlpha", "\n".join(segments["chunks"]))
        one = self.call("POST", "import/submit", body, self.library)
        same = self.call("POST", "import/submit", {"id": preview()["id"], "chunk_size": 400}, self.library)
        self.assertEqual(one["id"], same["id"])
        self.sources.notion_content = "NotionRiskAlpha 更新后的内容含两种策略。"
        changed = self.call("POST", "import/submit", {"id": preview()["id"], "chunk_size": 400}, self.library)
        self.assertNotEqual(changed["id"], one["id"])
        self.assertEqual(changed["logical"], one["logical"])
        self.process()
        versions = self.call("GET", f"documents/{changed['id']}/versions", library=self.library)
        self.assertEqual(len(versions), 2)
        self.assertEqual(changed["metadata"]["origin"]["url"], self.sources.notion_url)
        self.sources.expired = True
        self.assertEqual(self.call("POST", "sources/notion/pages", {"q": ""}, status=400)["error"]["code"], "SOURCE_AUTH")
        self.assertEqual(self.call("GET", "sources")["items"][0]["state"], "failed")
        self.call("POST", "import/submit", body, self.library, 404)
        self.call("DELETE", "sources/notion")
        self.assertEqual(self.call("GET", "sources")["items"][0]["state"], "unconfigured")

    def test_web_partial_failure_retry_and_real_queue(self):
        self.call("PUT", "sources/jina", {"token": "bad-fixture-token"}, status=400)
        states = {item["id"]: item["state"] for item in self.call("GET", "sources")["items"]}
        self.assertEqual(states["jina"], "failed")
        self.assertEqual(states["firecrawl"], "unavailable")
        self.configure("jina")
        retry = "https://example.com/retry"
        items = self.call("POST", "sources/jina/preview", {
            "items": ["https://example.com/article", retry, "http://127.0.0.1/private"]
        })["items"]
        self.assertIn("WebRiskBeta", items[0]["excerpt"])
        self.assertEqual([item["code"] for item in items[1:]], ["SOURCE_TIMEOUT", "SOURCE_URL"])
        fetched = self.call("POST", "sources/jina/preview", {"items": [retry]})["items"][0]
        result = self.call("POST", "import/submit", {"id": fetched["id"]})
        self.assertEqual(result["status"], "pending")
        self.assertFalse(self.call("GET", "queue")["worker"]["online"])
        self.process()
        self.assertEqual(self.call("GET", "documents/" + result["id"])["status"], "ready")


if __name__ == "__main__":
    unittest.main()
