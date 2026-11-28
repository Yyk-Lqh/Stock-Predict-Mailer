"""Loopback-only configuration console with same-origin session/CSRF checks."""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import InvalidToken

from ..agent_service.contracts import ServiceError, decode
from ..agent_service.mail import MailService
from ..agent_service.reporting import render
from ..naming import env
from ..operations.components import Component
from ..plugins.errors import PluginError
from ..private_knowledge.parsing import FORMATS as KNOWLEDGE_FORMATS
from ..private_knowledge.sources import MAX_CONTENT, KnowledgeSources, segment_preview
from .a2a import SESSION_COOKIE, A2AService, card
from .forecast_preview import evaluate as forecast_evaluate
from .forecast_preview import preview as forecast_preview
from .forecast_views import detail as forecast_detail
from .forecast_views import listing as forecast_listing
from .market_feed import MarketFeed
from .modes import LEGACY, MODES, PROFESSIONAL, STANDARD, TASK_MODE_SQL, require_mode, task_mode, with_task_mode
from .orchestrator import Orchestrator
from .store import Store
from .task_records import listing as task_records
from .workflow_chat import WorkflowChat

STATIC = Path(__file__).with_name("web")
BROWSER_MEMORY_MAX_AGE = 365 * 24 * 60 * 60


def make_server(root, port=8767, master_key=None, market=None):
    store = Store(root, master_key)
    engine = Orchestrator(store)
    workflow_chat = WorkflowChat(engine)
    knowledge_sources = KnowledgeSources(engine.knowledge)
    market = MarketFeed(store.root) if market is None else market
    session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    workspace_id = hashlib.sha256(str(store.root.resolve()).encode()).hexdigest()[:16]
    browser_memory_cookie = f"spm_memory_{workspace_id}"

    class Handler(BaseHTTPRequestHandler):
        server_version = "StockAgent/1"

        def log_message(self, *args):
            pass  # Request bodies, tokens, tool text and provider errors never enter logs.

        def output(self, value, status=200, content_type="application/json; charset=utf-8", cookie=False,
                   browser_key=None):
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() if isinstance(value, (dict, list)) else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if cookie:
                self.send_header("Set-Cookie", f"{SESSION_COOKIE}={session}; HttpOnly; SameSite=Strict; Path=/")
            if browser_key is not None:
                sealed = store.cipher.encrypt(browser_key.encode()).decode()
                self.send_header("Set-Cookie", f"{browser_memory_cookie}={sealed}; HttpOnly; SameSite=Strict; "
                                 f"Path=/api/memory/browser-access; Max-Age={BROWSER_MEMORY_MAX_AGE}")
            try:
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True  # A canceled read has no client left to receive an error response.

        def guard(self, mutation=False, a2a=False):
            authority = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if authority not in allowed:
                raise ServiceError("FORBIDDEN", "不允许的 Host")
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + a for a in allowed}:
                raise ServiceError("FORBIDDEN", "不允许的 Origin")
            if a2a:
                token = env("A2A_TOKEN")
                if token and hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                    return
            try:
                cookies = SimpleCookie(self.headers.get("Cookie", ""))
                valid = cookies.get(SESSION_COOKIE) and hmac.compare_digest(cookies[SESSION_COOKIE].value, session)
            except Exception:
                valid = False
            if not valid:
                raise ServiceError("FORBIDDEN", "请从本机控制台建立会话")
            if mutation and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf):
                raise ServiceError("FORBIDDEN", "缺少有效 CSRF token")

        def knowledge_owner(self):
            scope = self.headers.get("X-Knowledge-Scope", "")
            token = self.headers.get("X-Memory-Key", "")
            if scope not in ("", "local", "private"):
                raise ServiceError("INVALID_INPUT", "无效的知识库范围")
            if scope == "private" or (not scope and token):
                return engine.memory.owner(token)
            return engine.memory.local_knowledge_owner()

        def browser_memory_access(self):
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            saved = cookies.get(browser_memory_cookie)
            saved_key = ""
            if saved:
                try:
                    saved_key = store.cipher.decrypt(saved.value.encode(), ttl=BROWSER_MEMORY_MAX_AGE).decode()
                except (InvalidToken, UnicodeDecodeError):
                    pass
            # Adopt the current tab's existing key when removing the manual UI.
            for key in (self.headers.get("X-Memory-Key", ""), saved_key):
                if not key:
                    continue
                try:
                    engine.memory.owner(key)
                except ServiceError as error:
                    if error.code != "FORBIDDEN":
                        raise
                else:
                    return key
            return engine.memory.create_owner()["key"]

        def body(self):
            try:
                size = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                size = -1
            maximum = 15 * 1024 * 1024 if urlsplit(self.path).path == "/api/knowledge/documents" else 1024 * 1024
            if not 0 <= size <= maximum or not self.headers.get("Content-Type", "").startswith("application/json"):
                raise ServiceError("INVALID_INPUT", f"需要不超过 {maximum // (1024 * 1024)} MiB 的 JSON 请求体")
            value = decode(self.rfile.read(size), max_bytes=maximum)
            if not isinstance(value, dict):
                raise ServiceError("INVALID_INPUT", "JSON 顶层须为对象")
            return value

        def do_GET(self):
            self.handle_request("GET")

        def do_POST(self):
            self.handle_request("POST")

        def do_PUT(self):
            self.handle_request("PUT")

        def do_DELETE(self):
            self.handle_request("DELETE")

        def request_mode(self, *, write=False):
            mode = self.headers.get("X-Analysis-Mode")
            if mode is not None and mode not in (MODES if write else (*MODES, LEGACY)):
                raise ServiceError("INVALID_INPUT", "分析模式无效")
            return (mode or STANDARD) if write else mode

        def handle_request(self, method):
            try:
                path = urlsplit(self.path).path
                if method == "GET" and path in ("/", "/app.js", "/memory.js", "/style.css"):
                    # Check Host/Origin even before minting a local session.
                    allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
                    if self.headers.get("Host") not in allowed or self.headers.get("Origin") not in (None, *("http://" + a for a in allowed)):
                        raise ServiceError("FORBIDDEN", "仅允许本机同源访问")
                    filename = "index.html" if path == "/" else path[1:]
                    content_type = ("text/javascript" if filename.endswith(".js") else
                                    "text/css" if filename.endswith(".css") else "text/html") + "; charset=utf-8"
                    self.output((STATIC / filename).read_bytes(), content_type=content_type, cookie=path == "/")
                    return
                self.guard(method != "GET", a2a=path.startswith("/a2a/") or path == "/.well-known/agent-card.json")
                if method == "GET" and path == "/api/session":
                    self.output({"csrf_token": csrf, "browser_memory_access": True, "workspace_id": workspace_id,
                                 "temperature_note": "温度控制随机性，不是预测准确率或置信度；默认 0.2。"})
                    return
                if method == "GET" and path == "/.well-known/agent-card.json":
                    self.output(card(f"http://127.0.0.1:{self.server.server_port}"))
                    return
                if method == "GET" and path.startswith("/a2a/") and path.endswith("/agent-card.json"):
                    self.output(card(f"http://127.0.0.1:{self.server.server_port}", path.split("/")[2]))
                    return
                if method == "POST" and path.startswith("/a2a/"):
                    role = path.split("/")[-1]
                    # 记忆密钥只用于知识检索这类按 owner 隔离的读取；编排入口不依赖它。
                    self.output(asyncio.run(A2AService(engine).dispatch(self.body(), role,
                                                                       owner_key=self.headers.get("X-Memory-Key", ""))))
                    return
                parts = path.strip("/").split("/")
                if len(parts) < 2 or parts[0] != "api":
                    raise ServiceError("NOT_FOUND", "接口不存在")
                kind = parts[1]
                if kind == "workflows":
                    from .workflow import catalog, freeze, workflow_issues
                    from .workflow_runtime import preview
                    from .workflow_wiring import issue

                    if len(parts) >= 3 and parts[2] == "definitions":
                        require_mode(PROFESSIONAL, self.request_mode())
                        owner = engine.memory.owner(self.headers.get("X-Memory-Key", ""))
                        route = parts[3:]
                        if not route and method == "GET":
                            query = parse_qs(urlsplit(self.path).query)
                            model = query.get("model_id", [None])[0]
                            try:
                                tools = json.loads(query["tools"][0]) if "tools" in query else None
                            except ValueError:
                                raise ServiceError("INVALID_INPUT", "工具选择格式无效") from None
                            self.output(workflow_chat.list(owner, model=model, tools=tools))
                        elif not route and method == "POST":
                            self.output(workflow_chat.save(owner, self.body()), 201)
                        elif len(route) == 1 and method == "PUT":
                            self.output(workflow_chat.save(owner, self.body(), flow_id=route[0]))
                        elif len(route) >= 2 and route[1] == "revisions":
                            if len(route) == 2 and method == "GET":
                                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                                try:
                                    before = int(query.get("before", [str(2**63 - 1)])[0])
                                    if not 1 <= before <= 2**63 - 1 or set(query) - {"before"} or len(query.get("before", [])) > 1:
                                        raise ValueError()
                                except ValueError:
                                    raise ServiceError("INVALID_INPUT", "版本历史游标无效") from None
                                self.output(workflow_chat.revisions(owner, route[0], before=before))
                            elif len(route) == 3 and method == "GET":
                                self.output(workflow_chat.get(owner, route[0], route[2]))
                            elif len(route) == 4 and route[3] == "restore" and method == "POST":
                                self.output(workflow_chat.restore(owner, route[0], route[2], self.body()), 201)
                            else:
                                raise ServiceError("NOT_FOUND", "流程版本接口不存在")
                        elif len(route) in (2, 3) and route[1] == "runs" and method == "GET":
                            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                            node = query.get("node", [None])[0]
                            kind = query.get("kind", [None])[0]
                            try:
                                before = int(query.get("before", [str(2**63 - 1)])[0])
                                if not 1 <= before <= 2**63 - 1 or set(query) - {"before", "node", "kind"} or any(len(v) != 1 for v in query.values()):
                                    raise ValueError()
                            except ValueError:
                                raise ServiceError("INVALID_INPUT", "运行历史游标无效") from None
                            if (node is not None or kind is not None) and (len(route) != 2 or not all(
                                    re.fullmatch(r"[A-Za-z0-9_-]{1,64}", item or "") for item in (node, kind))):
                                raise ServiceError("INVALID_INPUT", "节点运行查询无效")
                            self.output(workflow_chat.history(owner, route[0], before=before,
                                                              task_id=route[2] if len(route) == 3 else None,
                                                              node_id=node, node_type=kind))
                        elif len(route) == 2 and route[1] == "runs" and method == "POST":
                            body = self.body()
                            self.output(workflow_chat.submit(owner, route[0], body, knowledge_owner=self.knowledge_owner), 202)
                        else:
                            raise ServiceError("NOT_FOUND", "流程对话接口不存在")
                    elif method == "GET" and parts[2:] == ["catalog"]:
                        self.output(catalog())
                    elif method == "GET" and parts[2:] == ["tools", "mcp"]:
                        from .workflow_tools import authorized_mcp

                        self.output({"bindings": authorized_mcp(store)})
                    elif method == "GET" and parts[2:] == ["database", "discover"]:
                        from .workflow_database import discover

                        self.output(discover(store))
                    elif method == "POST" and parts[2:] == ["database", "discover"]:
                        from .workflow_database import discover

                        body = self.body()
                        self.output(discover(store, scope=body.get("scope"), directory=body.get("directory")))
                    elif method == "POST" and parts[2:] == ["database", "inspect"]:
                        from .workflow_database import inspect

                        self.output(inspect(store, self.body().get("path")))
                    elif method == "POST" and parts[2:] == ["validate"]:
                        require_mode(PROFESSIONAL, self.request_mode())
                        body = self.body()
                        try:
                            settings = engine.execution_settings(store.settings(), body.get("model_id"), body.get("tools"))
                            issues = workflow_issues(body.get("workflow"), engine, settings)
                        except ServiceError as error:
                            issues = [issue(error.code, error.message)]
                        self.output({"issues": issues, "runnable": not any(item["severity"] == "error" for item in issues)})
                    elif method == "POST" and parts[2:] == ["preview"]:
                        require_mode(PROFESSIONAL, self.request_mode())
                        body = self.body()
                        raw = body.get("request")
                        settings = store.settings()
                        if isinstance(raw, dict):
                            settings = engine.execution_settings(settings, raw.get("model_id"), raw.get("tools"))
                        spec = freeze(body.get("workflow"), engine, settings)
                        if isinstance(raw, dict) and not spec.get("variables"):
                            owner = engine.memory.owner(self.headers.get("X-Memory-Key", "")) if raw.get("conversation_id") is not None else None
                            request = engine.prepare(raw, owner, mode=PROFESSIONAL,
                                                     knowledge_owner=self.knowledge_owner() if raw.get("knowledge_query") else None)
                        else:
                            request = None
                        self.output(preview(spec, request, settings))
                    elif method == "GET" and parts[2:] == ["runs"]:
                        require_mode(PROFESSIONAL, self.request_mode())
                        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                        try:
                            before = int(query.get("before", [str(2**63 - 1)])[0])
                            if not 1 <= before <= 2**63 - 1:
                                raise ValueError()
                        except ValueError:
                            raise ServiceError("INVALID_INPUT", "运行记录游标无效") from None
                        owner = engine.memory.owner(self.headers["X-Memory-Key"]) if self.headers.get("X-Memory-Key") else None
                        with store.db() as con:
                            rows = con.execute(
                                "SELECT t.rowid,t.body FROM tasks t LEFT JOIN memory_tasks m ON m.task=t.id "
                                "WHERE t.rowid<? AND (m.owner IS NULL OR m.owner=?) "
                                f"AND {TASK_MODE_SQL}='professional' "
                                "AND json_extract(t.body,'$.contextId')=t.id ORDER BY t.rowid DESC LIMIT 31",
                                (before, owner),
                            ).fetchall()
                        items = []
                        for _, raw in rows[:30]:
                            task = json.loads(raw)
                            meta = task.get("metadata", {})
                            workflow = meta.get("workflow") or {}
                            items.append({"id": task["id"], "mode": PROFESSIONAL, "status": task["status"], "subject": meta.get("request", {}).get("subject"),
                                          "version": workflow.get("version"), "debug": workflow.get("debug")})
                        self.output({"items": items, "next_before": rows[29][0] if len(rows) > 30 else None})
                    else:
                        raise ServiceError("NOT_FOUND", "工作流接口不存在")
                    return
                if kind == "forecasts":
                    if method != "GET" or len(parts) != 2:
                        raise ServiceError("NOT_FOUND", "预测列表仅支持只读查询")
                    query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                    if set(query) - {"before", "limit", "state"} or any(len(values) != 1 for values in query.values()):
                        raise ServiceError("INVALID_INPUT", "预测列表参数无效")
                    try:
                        before = int(query.get("before", [str(2**63 - 1)])[0])
                        limit = int(query.get("limit", ["20"])[0])
                    except ValueError:
                        raise ServiceError("INVALID_INPUT", "分页参数须为整数") from None
                    owner = engine.memory.owner(self.headers["X-Memory-Key"]) if self.headers.get("X-Memory-Key") else None
                    self.output(forecast_listing(store, owner, before=before, limit=limit, state=query.get("state", ["all"])[0]))
                    return
                if kind == "knowledge":
                    owner = self.knowledge_owner()
                    kb, route = engine.knowledge, parts[2:]
                    library = self.headers.get("X-Knowledge-Library", "default")
                    if route == ["libraries"] and method == "GET":
                        self.output({"items": kb.libraries(owner)})
                        return
                    if route == ["libraries"] and method == "POST":
                        self.output(kb.create_library(owner, self.body()), 201)
                        return
                    if route == ["sources"] and method == "GET":
                        self.output({"items": knowledge_sources.status(owner)})
                        return
                    if len(route) == 2 and route[0] == "sources" and method in ("PUT", "DELETE"):
                        self.output(knowledge_sources.configure(owner, route[1], self.body() if method == "PUT" else None,
                                                                remove=method == "DELETE"))
                        return
                    if route == ["sources", "notion", "pages"] and method == "POST":
                        self.output(knowledge_sources.pages(owner, self.body()))
                        return
                    if len(route) == 3 and route[0] == "sources" and route[2] == "preview" and method == "POST":
                        self.output({"items": knowledge_sources.preview(owner, library, route[1], self.body())})
                        return
                    if route in (["import", "segments"], ["import", "submit"]) and method == "POST":
                        raw = self.body()
                        if route[-1] == "segments" and "text" in raw:
                            filename, value, size = raw.get("filename"), raw["text"], raw.get("chunk_size")
                            if (not isinstance(filename, str) or not filename.lower().endswith((".txt", ".md"))
                                    or not isinstance(value, str) or not 1 <= len(value.encode()) <= MAX_CONTENT
                                    or type(size) is not int or not 400 <= size <= 4000):
                                raise ServiceError("INVALID_INPUT", "分段预览支持 512 KiB 以内的 TXT 或 Markdown")
                            self.output(segment_preview(filename, value.encode(), size))
                        else:
                            self.output(knowledge_sources.import_preview(owner, library, raw, segments=route[-1] == "segments"))
                        return
                    owner = kb.library_owner(owner, library)
                    if route == ["import", "options"] and method == "GET":
                        self.output({"formats": sorted(KNOWLEDGE_FORMATS), "max_file_bytes": 10 * 1024 * 1024,
                                     "max_files": 5, "chunk_size": 1600, "preview_max_bytes": MAX_CONTENT,
                                     "cleaner": kb.cleaning_config(owner)["provider"]})
                        return
                    if route == ["queue"] and method == "GET":
                        self.output(kb.queue(owner))
                    elif route == ["documents"] and method == "GET":
                        filters = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                        if set(filters) - {"limit", "offset", "status"} or any(len(values) != 1 for values in filters.values()):
                            raise ServiceError("INVALID_INPUT", "分页仅接受单个 limit、offset 与 status")
                        try:
                            limit = int(filters.get("limit", ["50"])[0])
                            offset = int(filters.get("offset", ["0"])[0])
                        except ValueError:
                            raise ServiceError("INVALID_INPUT", "分页参数须为整数") from None
                        self.output(kb.catalog(owner, limit=limit, offset=offset, status=filters.get("status", [None])[0]))
                    elif route == ["documents"] and method == "POST":
                        data = self.body()
                        try:
                            raw = base64.b64decode(data["data"], validate=True)
                        except (KeyError, TypeError, ValueError, binascii.Error):
                            raise ServiceError("INVALID_INPUT", "需要 base64 文件内容") from None
                        self.output(kb.upload(owner, data.get("filename"), raw, data.get("metadata"), data.get("logical"),
                                              chunk_size=data.get("chunk_size", 1600)), 202)
                    elif route == ["config"] and method in ("GET", "PUT"):
                        self.output(kb.config(owner, self.body() if method == "PUT" else None))
                    elif route == ["cleaner", "config"] and method in ("GET", "PUT"):
                        self.output(kb.cleaning_config(owner, self.body() if method == "PUT" else None))
                    elif route == ["cleaner", "test"] and method == "POST":
                        self.output(kb.test_cleaner(owner))
                    elif route == ["profile"] and method in ("GET", "PUT"):
                        self.output(kb.profile(owner, self.body() if method == "PUT" else None))
                    elif route == ["recall-history"] and method == "GET":
                        params = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                        pages = params.get("page", ["1"])
                        if set(params) - {"page"} or len(pages) != 1:
                            raise ServiceError("INVALID_INPUT", "召回记录只接受单个页码")
                        try:
                            page = int(pages[0])
                        except ValueError:
                            raise ServiceError("INVALID_INPUT", "页码须为整数") from None
                        self.output(kb.recall_history(owner, page))
                    elif route == ["test"] and method == "POST":
                        self.output(kb.test(owner))
                    elif route == ["indexes"] and method == "GET":
                        self.output(kb.indexes(owner))
                    elif route == ["rebuild"] and method == "POST":
                        self.output(kb.rebuild(owner))
                    elif route in (["search"], ["answer"]) and method == "POST":
                        data = self.body()
                        record = data.pop("record", False) if route == ["search"] else False
                        allowed = {"query", "as_of", "start_date", "stock_code", "entity", "limit", "retrieval"}
                        if set(data) - allowed or "query" not in data or type(record) is not bool:
                            raise ServiceError("INVALID_INPUT", "检索参数无效")
                        operation = kb.answer if route == ["answer"] else kb.recall if record else kb.search
                        self.output(operation(owner, **data))
                    elif len(route) == 2 and route[0] == "citations" and method == "GET":
                        self.output(kb.citation(owner, route[1]))
                    elif len(route) >= 2 and route[0] == "documents":
                        did = route[1]
                        if len(route) == 2 and method == "GET":
                            self.output(kb.document(owner, did, detail=True))
                        elif len(route) == 2 and method == "DELETE":
                            self.output(kb.delete(owner, did))
                        elif route[2:] == ["review"] and method == "GET":
                            self.output(kb.review(owner, did))
                        elif route[2:] == ["review"] and method == "POST":
                            body = self.body()
                            if set(body) != {"decision", "digest", "approved_ids"}:
                                raise ServiceError("INVALID_INPUT", "需要 decision/digest/approved_ids")
                            self.output(kb.review(owner, did, **body))
                        elif route[2:] == ["reextract"] and method == "POST":
                            self.output(kb.reextract(owner, did), 202)
                        elif route[2:] == ["retry"] and method == "POST":
                            self.output(kb.retry(owner, did), 202)
                        elif route[2:] == ["retire"] and method == "POST":
                            self.output(kb.retire(owner, did))
                        elif route[2:] == ["versions"] and method == "GET":
                            self.output(kb.versions(owner, kb.document(owner, did)["logical"]))
                        elif route[2:] == ["original"] and method == "GET":
                            filename, raw = kb.original(owner, did)
                            self.output({"filename": filename, "data": base64.b64encode(raw).decode()})
                        else:
                            raise ServiceError("NOT_FOUND", "资料接口不存在")
                    else:
                        raise ServiceError("NOT_FOUND", "知识库接口不存在")
                    return
                if kind in ("conversations", "memory"):
                    route = parts[2:]
                    if kind == "memory" and route == ["browser-access"] and method == "POST":
                        key = self.browser_memory_access()
                        self.output({"key": key}, browser_key=key)
                        return
                    if kind == "memory" and route == ["access"] and method == "POST":
                        self.output(engine.memory.create_owner(), 201)
                        return
                    owner = engine.memory.owner(self.headers.get("X-Memory-Key", ""))
                    mode = self.request_mode()
                    query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                    paged_pending = kind == "memory" and route == ["pending"]
                    if (not route or paged_pending) and method == "GET" and query:
                        if set(query) - {"before", "limit"} or any(len(values) != 1 for values in query.values()):
                            raise ServiceError("INVALID_INPUT", "分页仅接受单个 before 和 limit")
                        try:
                            before = int(query.get("before", [str(2**63 - 1)])[0])
                            limit = int(query.get("limit", ["100"])[0])
                        except ValueError:
                            raise ServiceError("INVALID_INPUT", "分页参数无效") from None
                        self.output(engine.memory.page(owner, "pending" if paged_pending else kind, before, limit, mode))
                        return
                    if kind == "memory" and route == ["access"] and method == "DELETE":
                        self.output(engine.memory.revoke(owner))
                        return
                    if kind == "conversations" and len(route) == 2 and route[1] == "export" and method == "GET":
                        self.output(engine.memory.export_conversation(owner, route[0], mode))
                        return
                    if kind == "conversations" and not route and method == "POST":
                        self.output(engine.memory.new(owner, self.request_mode(write=True)), 201)
                    elif kind == "conversations" and not route and method == "GET":
                        self.output(engine.memory.conversations(owner, mode))
                    elif kind == "conversations" and len(route) == 1 and method == "GET":
                        query = parse_qs(urlsplit(self.path).query)
                        try:
                            before = int(query.get("before", [str(2**63 - 1)])[0])
                            limit = int(query.get("limit", ["20"])[0])
                        except ValueError:
                            raise ServiceError("INVALID_INPUT", "历史分页参数无效") from None
                        self.output(engine.memory.conversation(owner, route[0], before, limit, mode))
                    elif kind == "conversations" and len(route) == 1 and method == "DELETE":
                        with engine.lock:
                            self.output(engine.memory.delete_conversation(owner, route[0], self.request_mode(write=True)))
                    elif kind == "memory" and route == ["settings"] and method in ("GET", "PUT"):
                        self.output(engine.memory.settings(owner, self.body() if method == "PUT" else None))
                    elif kind == "memory" and route == ["pending"] and method == "GET":
                        self.output(engine.memory.pending(owner, mode))
                    elif kind == "memory" and not route and method == "GET":
                        self.output(engine.memory.entries(owner, mode))
                    elif kind == "memory" and len(route) == 1 and method == "PUT":
                        self.output(engine.memory.update(owner, route[0], self.body(), self.request_mode(write=True)))
                    elif kind == "memory" and len(route) == 1 and method == "DELETE":
                        engine.memory.delete(owner, route[0], self.request_mode(write=True))
                        self.output({"status": "deleted"})
                    else:
                        raise ServiceError("NOT_FOUND", "记忆接口不存在")
                    return
                if kind == "settings":
                    if method == "GET" and len(parts) == 2:
                        self.output(store.settings())
                    elif method == "PUT" and len(parts) == 2:
                        self.output(store.save_settings(self.body()))
                    elif method == "POST" and parts[2:] == ["reset-temperature"]:
                        value = store.settings()
                        value["global_temperature"] = 0.2
                        for conf in value["agents"].values():
                            conf["temperature"] = None
                        self.output(store.save_settings(value))
                    else:
                        raise ServiceError("NOT_FOUND", "设置接口不存在")
                    return
                if kind == "tasks":
                    if method == "GET" and parts[2:] == ["records"]:
                        owner = engine.memory.owner(self.headers["X-Memory-Key"]) if self.headers.get("X-Memory-Key") else None
                        self.output(task_records(store, owner, self.request_mode(), parse_qs(
                            urlsplit(self.path).query, keep_blank_values=True)))
                        return
                    if len(parts) >= 3 and (owner := engine.memory.task_owner(parts[2])):
                        if engine.memory.owner(self.headers.get("X-Memory-Key", "")) != owner:
                            raise ServiceError("FORBIDDEN", "此任务属于其他会话所有者")
                    mode = self.request_mode()
                    if len(parts) >= 3 and mode is not None:
                        require_mode(task_mode(store.task(parts[2])), mode)
                    if method == "POST" and len(parts) == 5 and parts[3:] == ["forecast", "evaluate"]:
                        require_mode(task_mode(store.task(parts[2])), self.request_mode(write=True))
                        if urlsplit(self.path).query:
                            raise ServiceError("INVALID_INPUT", "评估参数须通过 JSON 请求体提供")
                        self.output(forecast_evaluate(store, parts[2], self.body()))
                    elif method == "POST" and len(parts) == 5 and parts[3:] == ["forecast", "preview"]:
                        if urlsplit(self.path).query:
                            raise ServiceError("INVALID_INPUT", "预览参数须通过 JSON 请求体提供")
                        self.output(forecast_preview(store, parts[2], self.body()))
                    elif method == "GET" and len(parts) == 4 and parts[3] == "forecast":
                        if urlsplit(self.path).query:
                            raise ServiceError("INVALID_INPUT", "任务预测详情不接受查询参数")
                        self.output({**forecast_detail(store, parts[2]), "mode": task_mode(store.task(parts[2]))})
                    elif method == "POST" and len(parts) == 2:
                        from .workflow_values import dataflow, needs_knowledge

                        payload = self.body()
                        workflow = payload.get("workflow")
                        graph = workflow.get("graph") if isinstance(workflow, dict) else None
                        scoped = payload.get("conversation_id") is not None or dataflow(graph)
                        owner = engine.memory.owner(self.headers.get("X-Memory-Key", "")) if scoped else None
                        knowledge_owner = self.knowledge_owner() if payload.get("knowledge_query") or needs_knowledge(graph) else None
                        self.output(engine.submit(payload, owner, knowledge_owner=knowledge_owner, mode=mode), 202)
                    elif method == "GET" and len(parts) == 2:
                        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                        order = query.get("order", ["asc"])[0]
                        if order not in ("asc", "desc") or any(len(values) != 1 for values in query.values()):
                            raise ServiceError("INVALID_INPUT", "任务分页参数无效")
                        try:
                            limit = int(query.get("limit", ["50"])[0])
                            cursor = int(query.get("before" if order == "desc" else "after",
                                                     [str(2**63 - 1) if order == "desc" else "0"])[0])
                            if not 0 <= cursor <= 2**63 - 1 or not 1 <= limit <= 100:
                                raise ValueError()
                        except ValueError:
                            raise ServiceError("INVALID_INPUT", "任务分页参数无效") from None
                        owner = engine.memory.owner(self.headers['X-Memory-Key']) if self.headers.get('X-Memory-Key') else None
                        compare = "<" if order == "desc" else ">"
                        with store.db() as con:
                            rows = con.execute(
                                "SELECT t.rowid,t.body FROM tasks t LEFT JOIN memory_tasks m ON m.task=t.id "
                                f"WHERE t.rowid{compare}? AND (m.owner IS NULL OR m.owner=?) "
                                f"AND (? IS NULL OR {TASK_MODE_SQL}=?) "
                                "AND json_extract(t.body,'$.metadata.workflow.debug') IS NULL "
                                f"ORDER BY t.rowid {order} LIMIT ?", (cursor, owner, mode, mode, limit + 1)
                            ).fetchall()
                        body = {"items": [with_task_mode(json.loads(r[1])) for r in rows[:limit]]}
                        body["next_before" if order == "desc" else "next_after"] = rows[limit - 1][0] if len(rows) > limit else None
                        self.output(body)
                    elif method == "GET" and len(parts) == 4 and parts[3] in ("report", "analysis", "mail"):
                        task = store.task(parts[2])
                        if task["status"]["state"] != "completed" or not task["artifacts"]:
                            raise ServiceError("NOT_READY", "任务尚无正式报告")
                        result = task["artifacts"][0]["parts"][0]["data"]
                        if result.get("workflow_debug"):
                            raise ServiceError("NOT_READY", "单节点调试只提供运行记录")
                        if "analysis" not in result and parts[3] != "mail":
                            raise ServiceError("NOT_READY", "该任务只提供工作流输出和运行记录")
                        if parts[3] == "report":
                            self.output(render(result["analysis"])[1].encode(), content_type="text/html; charset=utf-8")
                        elif parts[3] == "analysis":
                            self.output(result["analysis"])
                        else:
                            mail = result.get("mail") or {"status": "not_requested"}
                            if mail.get("id"):
                                service = MailService(store.root, store.settings()["mail"])
                                try:
                                    mail = service.public(service.get(mail["id"]))
                                except ServiceError as exc:
                                    if exc.code != "INVALID_INPUT":
                                        raise
                                    with store.db() as con:
                                        exists = con.execute("SELECT 1 FROM sqlite_master WHERE name='mcp_mail'").fetchone()
                                        marker = con.execute("SELECT status FROM mcp_mail WHERE id=?", (mail["id"],)).fetchone() if exists else None
                                    if marker:
                                        mail = {"id": mail["id"], "status": "uncertain" if marker[0] == "sending" else marker[0]}
                            self.output(mail)
                    elif method == "POST" and len(parts) == 5 and parts[3:] == ["mail", "resolve"]:
                        task = store.task(parts[2])
                        require_mode(task_mode(task), self.request_mode(write=True))
                        if task["status"]["state"] != "completed":
                            raise ServiceError("NOT_READY", "任务尚未完成")
                        mail = task["artifacts"][0]["parts"][0]["data"].get("mail") or {}
                        if not mail.get("id"):
                            raise ServiceError("NOT_FOUND", "任务无可管理邮件")
                        body = self.body()
                        if set(body) != {"delivered"} or type(body["delivered"]) is not bool:
                            raise ServiceError("INVALID_INPUT", "需要 delivered 布尔字段")
                        service = MailService(store.root, store.settings()["mail"])
                        self.output(service.resolve(mail["id"], body["delivered"]))
                    elif method == "GET" and len(parts) == 3:
                        self.output(with_task_mode(store.task(parts[2])))
                    elif method == "GET" and len(parts) == 4 and parts[3] == "events":
                        try:
                            after = int(parse_qs(urlsplit(self.path).query).get("after", ["0"])[0])
                            if not 0 <= after <= 2**63 - 1:
                                raise ValueError()
                        except ValueError:
                            raise ServiceError("INVALID_INPUT", "进度游标无效") from None
                        self.output({"events": store.events(parts[2], after)})
                    elif method == "POST" and len(parts) == 4 and parts[3] == "cancel":
                        self.output(engine.cancel(parts[2], self.request_mode(write=True)))
                    elif method == "POST" and len(parts) == 4 and parts[3] == "continue":
                        require_mode(PROFESSIONAL, self.request_mode(write=True))
                        owner = engine.memory.owner(self.headers.get("X-Memory-Key", ""))
                        self.output(engine.continue_workflow(parts[2], owner, self.body()), 202)
                    elif method == "DELETE" and len(parts) == 3:
                        self.output(engine.delete_task(parts[2], self.request_mode(write=True)))
                    else:
                        raise ServiceError("NOT_FOUND", "任务接口不存在")
                    return
                if kind == "registry":
                    if method == "GET" and len(parts) == 2:
                        try:
                            from ..core import Config
                            from ..model_registry import describe_models
                        except ImportError as exc:
                            raise ServiceError("NOT_READY", f"模型注册表需要 research 额外依赖（缺少 {exc.name}）") from None
                        self.output({"models": describe_models(Config(store.root))})
                    else:
                        raise ServiceError("NOT_FOUND", "模型注册表接口不存在")
                    return
                if kind == "plugins":
                    from ..plugins import github

                    if method == "GET" and len(parts) == 2:
                        from ..plugins.doctor import check

                        self.output(check(store.root))
                    elif method == "POST" and parts[2:] == ["github"]:
                        self.output(github.install(store.root, self.body().get("url")), 201)
                    elif method == "DELETE" and len(parts) == 4 and parts[2] == "github":
                        github.remove(store.root, parts[3])
                        self.output({"status": "deleted"})
                    else:
                        raise ServiceError("NOT_FOUND", "插件接口不存在")
                    return
                if kind == "market":
                    if method == "GET" and parts[2:] == ["snapshot"]:
                        self.output(market.payload())
                    else:
                        raise ServiceError("NOT_FOUND", "行情接口不存在")
                    return
                if kind not in ("models", "mcp", "agents"):
                    raise ServiceError("NOT_FOUND", "配置集合不存在")
                if method == "GET" and len(parts) == 2:
                    self.output(store.list(kind))
                elif method == "GET" and len(parts) == 3:
                    self.output(store.get(kind, parts[2]))
                elif method == "POST" and len(parts) == 2:
                    self.output(store.put(kind, self.body()), 201)
                elif method == "PUT" and len(parts) == 3:
                    self.output(store.put(kind, self.body(), parts[2]))
                elif method == "DELETE" and len(parts) == 3:
                    store.delete(kind, parts[2])
                    self.output({"status": "deleted"})
                elif method == "POST" and len(parts) == 4:
                    pid, action = parts[2:]
                    if kind == "models" and action == "test":
                        revision = store.get("models", pid).get("config_revision")
                        body = self.body() if self.headers.get("Content-Length") not in (None, "0") else {}
                        if set(body) - {"config_revision"} or body.get("config_revision", revision) != revision:
                            raise ServiceError("CONFIG_CONFLICT", "模型配置已有更新，请刷新后再测试")
                        result = asyncio.run(engine.models.test(pid, store.settings()))
                        if store.get("models", pid).get("config_revision") != revision:
                            raise ServiceError("CONFIG_CONFLICT", "测试期间模型配置已有更新，请刷新后重试")
                        self.output({**result, "config_revision": revision})
                    elif kind == "mcp" and action == "test":
                        self.output(asyncio.run(engine.mcp.discover(pid)))
                    elif kind == "mcp" and action == "call":
                        body = self.body()
                        self.output(asyncio.run(engine.mcp.call(pid, body.get("tool"), body.get("arguments", {}))))
                    elif kind == "mcp" and action == "read":
                        self.output(asyncio.run(engine.mcp.read(pid, self.body().get("uri"))))
                    else:
                        raise ServiceError("NOT_FOUND", "操作不存在")
                else:
                    raise ServiceError("NOT_FOUND", "配置接口不存在")
            except ServiceError as exc:
                status = 403 if exc.code in ("FORBIDDEN", "PERMISSION_DENIED") else 404 if exc.code == "NOT_FOUND" else 400
                self.output(exc.as_dict(), status)
            except PluginError as exc:
                self.output(exc.as_dict(), 404 if exc.code == "PLUGIN_NOT_FOUND" else 400)
            except Exception:
                self.output({"error": {"code": "INTERNAL_ERROR", "message": "本地操作失败，请检查配置或工作区", "retryable": False}}, 500)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.store, server.engine = store, engine
    server.knowledge_sources = knowledge_sources
    return server


def serve(root, port=8767, *, runtime_id=None):
    config = {"port": port, "vault_mode": "production" if env("MASTER_KEY") else "development"}
    with Component(root, "console", config, instance=runtime_id) as component:
        server = make_server(root, port)
        print(f"配置控制台：http://127.0.0.1:{server.server_port}（仅本机）", flush=True)
        if server.store.development_mode:
            print("开发模式：无需主密钥环境变量，使用独立开发配置库和自动生成的本机开发密钥。", flush=True)
        server.timeout = .2
        component.phase("running", port=server.server_port)
        try:
            while not component.should_stop():
                server.handle_request()
        finally:
            component.phase("stopping")
            active = server.engine.close_admission()
            server.server_close()
            for tid in active:
                try:
                    server.engine.cancel(tid)
                except ServiceError:
                    pass
            # Keep the lease and heartbeat while async effects unwind. No force kill.
            while server.engine.active:
                time.sleep(.05)
