"""Scoped connectors that submit accepted source snapshots to the document queue."""
import hashlib
import ipaddress
import json
import re
import uuid
from datetime import timedelta
from time import monotonic
from urllib.parse import urlsplit

import httpx

from ..agent_service.contracts import ServiceError, utcnow
from .parsing import clean, parse

PROVIDERS = {"notion": "Notion", "jina": "Jina Reader", "firecrawl": "Firecrawl", "watercrawl": "WaterCrawl"}
AVAILABLE = ("notion", "jina")
IDENT = re.compile(r"[0-9a-f]{32}")
MAX_CONTENT = 512 * 1024
MAX_BATCH = 5


def segment_preview(filename, content, size):
    draft = clean(parse(filename, content), size)
    return {"chunks": [item["text"] for item in draft["chunks"][:3]], "count": len(draft["chunks"])}


def rich_text(parts):
    return "".join(part.get("plain_text", "") for part in parts if isinstance(part, dict))


def web_url(value):
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 1300 or any(ord(c) <= 32 for c in value):
            raise ValueError()
        parsed = httpx.URL(value)
        host = parsed.host.rstrip(".").lower()
        if (parsed.scheme not in ("https", "http") or parsed.userinfo or not host
                or parsed.port is not None or "\\" in value):
            raise ValueError()
        try:
            public = ipaddress.ip_address(host).is_global
        except ValueError:
            public = "." in host and not host.endswith((".local", ".localhost", ".internal", ".test", ".invalid"))
        if not public:
            raise ValueError()
        return str(parsed.copy_with(fragment=None))
    except (ValueError, httpx.InvalidURL) as error:
        raise ServiceError("SOURCE_URL", "请输入不含凭据的公开 HTTP(S) 网页地址") from error


class SourceAdapter:
    def __init__(self, transport=None):
        self.transport = transport

    def request(self, provider, token, method, endpoint, **kwargs):
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if provider == "notion":
            headers["Notion-Version"] = "2026-03-11"
            url = "https://api.notion.com/v1/" + endpoint
        else:
            headers["X-Respond-With"] = "markdown"
            url = "https://r.jina.ai/" + endpoint
        try:
            with httpx.Client(transport=self.transport, timeout=15, trust_env=False, follow_redirects=False) as client:
                with client.stream(method, url, headers=headers, **kwargs) as response:
                    if response.status_code == 401:
                        raise ServiceError("SOURCE_AUTH", "连接凭据无效或已撤销，请重新配置")
                    if response.status_code == 403:
                        raise ServiceError("SOURCE_PERMISSION", "来源拒绝访问，请检查页面共享或凭据权限")
                    if response.status_code == 429:
                        raise ServiceError("SOURCE_RATE_LIMIT", "来源暂时限制请求，请稍后重试", True)
                    if response.status_code != 200:
                        raise ServiceError("SOURCE_UNAVAILABLE", "来源不可访问，服务返回 " + str(response.status_code), True)
                    payload = bytearray()
                    for block in response.iter_bytes():
                        payload.extend(block)
                        if len(payload) > MAX_CONTENT * 4:
                            raise ServiceError("FILE_LIMIT", "来源响应超出导入限制")
            result = json.loads(payload)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except httpx.TimeoutException as error:
            raise ServiceError("SOURCE_TIMEOUT", "读取来源超时，可重试", True) from error
        except httpx.HTTPError as error:
            raise ServiceError("SOURCE_UNAVAILABLE", "读取来源失败，请检查连接后重试", True) from error
        except (ValueError, UnicodeError) as error:
            raise ServiceError("SOURCE_UNAVAILABLE", "来源响应格式异常") from error

    def test(self, provider, token):
        if provider == "notion":
            result = self.request(provider, token, "GET", "users/me")
            bot = result.get("bot") or {}
            if result.get("type") != "bot" or not isinstance(bot, dict):
                raise ServiceError("SOURCE_AUTH", "请使用具有页面读取权限的 Notion 集成令牌")
            return str(bot.get("workspace_name") or result.get("name") or "Notion 集成")[:200]
        self.web(token, "https://example.com/")
        return "Jina Reader"

    def pages(self, token, query, cursor):
        data = {"filter": {"value": "page", "property": "object"}, "page_size": 20}
        if query:
            data["query"] = query
        if cursor:
            data["start_cursor"] = cursor
        result = self.request("notion", token, "POST", "search", json=data)
        items = []
        for page in result.get("results", []):
            if page.get("object") != "page" or page.get("archived") or page.get("in_trash"):
                continue
            try:
                key = uuid.UUID(page["id"]).hex
                url = web_url(page["url"])
            except (KeyError, ValueError, ServiceError):
                continue
            props = page.get("properties", {}).values()
            title = next((rich_text(item["title"]) for item in props if item.get("type") == "title"), "")
            items.append({"id": key, "title": (title or "未命名页面")[:200], "url": url})
        return {"items": items, "next_cursor": result.get("next_cursor") if result.get("has_more") else None}

    def notion(self, token, key):
        if not isinstance(key, str) or not IDENT.fullmatch(key):
            raise ServiceError("INVALID_INPUT", "请选择一个可访问的 Notion 页面")
        page = self.request("notion", token, "GET", "pages/" + key)
        if page.get("archived") or page.get("in_trash"):
            raise ServiceError("SOURCE_UNAVAILABLE", "页面已归档或在回收站")
        props = page.get("properties", {}).values()
        title = next((rich_text(item["title"]) for item in props if item.get("type") == "title"), "") or "未命名页面"
        lines, visits, total = [], 0, 0
        started = monotonic()

        def read(block, depth):
            nonlocal visits, total
            if depth > 4:
                raise ServiceError("FILE_LIMIT", "页面嵌套超过 4 层，请拆分后导入")
            cursor = None
            while True:
                if monotonic() - started > 20:
                    raise ServiceError("SOURCE_TIMEOUT", "读取页面子块超时，可重试", True)
                visits += 1
                if visits > 24:
                    raise ServiceError("FILE_LIMIT", "页面包含太多子块，请拆分后导入")
                params = {"page_size": 50, **({"start_cursor": cursor} if cursor else {})}
                data = self.request("notion", token, "GET", "blocks/" + block + "/children", params=params)
                for item in data.get("results", []):
                    kind = item.get("type")
                    value = item.get(kind, {})
                    if kind == "table_row":
                        line = " | ".join(rich_text(cell) for cell in value.get("cells", []))
                    else:
                        line = rich_text(value.get("rich_text", []))
                    if line.strip():
                        total += len(line.encode()) + 6
                        if total > MAX_CONTENT:
                            raise ServiceError("FILE_LIMIT", "单页正文超过 512 KiB")
                        lines.append(("#" * int(kind[-1]) + " " if kind in ("heading_1", "heading_2", "heading_3") else "") + line)
                    if item.get("has_children") and kind not in ("child_page", "child_database"):
                        read(uuid.UUID(item["id"]).hex, depth + 1)
                cursor = data.get("next_cursor")
                if not cursor or not data.get("has_more"):
                    break

        read(key, 0)
        return self.snapshot("notion", key, title, web_url(page.get("url")), "\n\n".join(lines))

    def web(self, token, value):
        address = web_url(value)
        result = self.request("jina", token, "GET", address)
        data = result.get("data")
        if not isinstance(data, dict):
            raise ServiceError("SOURCE_UNAVAILABLE", "网页读取服务没有返回正文数据")
        key = hashlib.sha256(address.encode()).hexdigest()
        return self.snapshot("jina", key, data.get("title") or urlsplit(address).hostname,
                             web_url(data.get("url") or address), data.get("content"))

    @staticmethod
    def snapshot(provider, key, title, url, body):
        if not isinstance(body, str) or not body.strip():
            raise ServiceError("SOURCE_EMPTY", "来源没有可导入的正文")
        title = str(title).replace("\n", " ").strip()[:180] or "未命名资料"
        body = body.strip()
        if len(body.encode()) > MAX_CONTENT:
            raise ServiceError("FILE_LIMIT", "单页正文超过 512 KiB")
        return {"provider": provider, "source_id": key, "title": title, "url": url,
                "fetched_at": utcnow().isoformat(), "body": body}


class KnowledgeSources:
    def __init__(self, knowledge, adapter=None):
        self.kb = knowledge
        self.adapter = adapter or SourceAdapter()
        with knowledge.db() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS source_connections (
                    owner TEXT NOT NULL, provider TEXT NOT NULL, revision TEXT NOT NULL,
                    body BLOB NOT NULL, failed TEXT, PRIMARY KEY(owner,provider));
                CREATE TABLE IF NOT EXISTS source_previews (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, library TEXT NOT NULL,
                    provider TEXT NOT NULL, revision TEXT NOT NULL, expires TEXT NOT NULL, body BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS source_preview_owner ON source_previews(owner,expires);
            """)

    def _connection(self, owner, provider):
        self.kb.ensure(owner)
        with self.kb.db() as con:
            return con.execute("SELECT revision,body,failed FROM source_connections WHERE owner=? AND provider=?",
                               (owner, provider)).fetchone()

    def status(self, owner):
        items = []
        for provider, title in PROVIDERS.items():
            row = self._connection(owner, provider) if provider in AVAILABLE else None
            state = ("unavailable" if provider not in AVAILABLE else "unconfigured" if row is None
                     else "failed" if row["failed"] else "connected")
            value = self.kb.opened(row["body"]) if row else {}
            items.append({"id": provider, "name": title, "state": state, "workspace": value.get("workspace", ""),
                          "tested_at": value.get("tested_at"), "error": row["failed"] if row else None})
        return items

    def configure(self, owner, provider, raw=None, *, remove=False):
        if provider not in AVAILABLE:
            raise ServiceError("SOURCE_UNAVAILABLE", "此工具暂未接入")
        self.kb.ensure(owner)
        if remove:
            with self.kb.db() as con:
                con.execute("DELETE FROM source_connections WHERE owner=? AND provider=?", (owner, provider))
            return {"state": "unconfigured"}
        token = raw.get("token")
        if set(raw) != {"token"} or not isinstance(token, str) or not 8 <= len(token) <= 3000 or any(c.isspace() for c in token):
            raise ServiceError("INVALID_INPUT", "请输入有效的集成令牌或 API Key")
        try:
            workspace = self.adapter.test(provider, token)
        except ServiceError as error:
            with self.kb.db() as con:
                con.execute("""INSERT INTO source_connections VALUES (?,?,?,?,?)
                    ON CONFLICT(owner,provider) DO UPDATE SET failed=excluded.failed
                    WHERE source_connections.failed IS NOT NULL""",
                            (owner, provider, uuid.uuid4().hex, self.kb.seal({}), error.message))
            raise
        tested_at = utcnow().isoformat()
        with self.kb.db() as con:
            con.execute("INSERT OR REPLACE INTO source_connections VALUES (?,?,?,?,NULL)",
                        (owner, provider, uuid.uuid4().hex, self.kb.seal({"workspace": workspace,
                                                                       "token": token, "tested_at": tested_at})))
        return {"state": "connected", "workspace": workspace, "tested_at": tested_at}

    def use(self, owner, provider, fn):
        if provider not in AVAILABLE:
            raise ServiceError("SOURCE_UNAVAILABLE", "此工具暂未接入")
        row = self._connection(owner, provider)
        if row is None:
            raise ServiceError("SOURCE_UNBOUND", "请先绑定或配置来源")
        token = self.kb.opened(row["body"]).get("token")
        if not token:
            raise ServiceError("SOURCE_UNBOUND", row["failed"] or "请先绑定或配置来源")
        try:
            value = fn(token)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ServiceError("SOURCE_UNAVAILABLE", "来源响应格式异常") from error
        except ServiceError as error:
            if error.code == "SOURCE_AUTH":
                with self.kb.db() as con:
                    con.execute("UPDATE source_connections SET failed=? WHERE owner=? AND provider=? AND revision=?",
                                (error.message, owner, provider, row["revision"]))
            raise
        with self.kb.db() as con:
            con.execute("UPDATE source_connections SET failed=NULL WHERE owner=? AND provider=? AND revision=?",
                        (owner, provider, row["revision"]))
        return value, row["revision"]

    def pages(self, owner, raw):
        query, cursor = raw.get("q", ""), raw.get("cursor")
        if (set(raw) - {"q", "cursor"} or not isinstance(query, str) or len(query.strip()) > 100
                or cursor is not None and (not isinstance(cursor, str) or len(cursor) > 200)):
            raise ServiceError("INVALID_INPUT", "页面搜索参数无效")
        return self.use(owner, "notion", lambda token: self.adapter.pages(token, query.strip(), cursor))[0]

    def preview(self, owner, library, provider, raw):
        items = raw.get("items")
        if (library != "default" and not IDENT.fullmatch(library)
                or set(raw) != {"items"} or not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH
                or any(not isinstance(value, str) or not 1 <= len(value) <= 1300 for value in items)):
            raise ServiceError("INVALID_INPUT", "每次可预览 1–5 条来源")
        output = []
        read = self.adapter.notion if provider == "notion" else self.adapter.web
        for item in dict.fromkeys(items):
            try:
                snapshot, revision = self.use(owner, provider, lambda token, selected=item: read(token, selected))
                key, now = uuid.uuid4().hex, utcnow()
                with self.kb.db() as con:
                    con.execute("DELETE FROM source_previews WHERE expires<?", (now.isoformat(),))
                    con.execute("INSERT INTO source_previews VALUES (?,?,?,?,?,?,?)",
                                (key, owner, library, provider, revision, (now + timedelta(minutes=30)).isoformat(),
                                 self.kb.seal(snapshot)))
                    con.execute("""DELETE FROM source_previews WHERE owner=? AND id IN (
                        SELECT id FROM source_previews WHERE owner=? ORDER BY rowid DESC LIMIT -1 OFFSET 20)""",
                                (owner, owner))
                output.append({**{k: v for k, v in snapshot.items() if k != "body"},
                               "input": item, "id": key, "excerpt": snapshot["body"][:1600]})
            except ServiceError as error:
                output.append({"input": item, "error": error.message, "code": error.code})
        return output

    def accepted_preview(self, owner, library, key):
        if not isinstance(key, str) or not IDENT.fullmatch(key):
            raise ServiceError("INVALID_INPUT", "来源预览标识无效")
        with self.kb.db() as con:
            row = con.execute("""SELECT p.body FROM source_previews p JOIN source_connections c
                ON c.owner=p.owner AND c.provider=p.provider AND c.revision=p.revision
                WHERE p.id=? AND p.owner=? AND p.library=? AND expires>=? AND c.failed IS NULL""",
                              (key, owner, library, utcnow().isoformat())).fetchone()
        if not row:
            raise ServiceError("NOT_FOUND", "来源预览已过期或授权已更新，请重新读取")
        return self.kb.opened(row["body"])

    def import_preview(self, owner, library, raw, *, segments=False):
        key, size = raw.get("id"), raw.get("chunk_size", 1600)
        if set(raw) - {"id", "chunk_size"} or type(size) is not int or not 400 <= size <= 4000:
            raise ServiceError("INVALID_INPUT", "分段长度需要 400–4000 字符")
        snapshot = self.accepted_preview(owner, library, key)
        content = ("# " + snapshot["title"] + "\n\n" + snapshot["body"]).encode()
        if segments:
            return segment_preview("source.md", content, size)
        scope = self.kb.library_owner(owner, library)
        origin = {key: value for key, value in snapshot.items() if key != "body"}
        identity = snapshot["provider"] + ":" + snapshot["source_id"]
        filename = re.sub(r'[/\\<>:"|?*\x00-\x1f]', "_", snapshot["title"])[:180].rstrip(". ") + ".md"
        return self.kb.upload(scope, filename, content,
                              {"source": PROVIDERS[snapshot["provider"]], "available_date": snapshot["fetched_at"][:10]},
                              identity, chunk_size=size, origin=origin)
