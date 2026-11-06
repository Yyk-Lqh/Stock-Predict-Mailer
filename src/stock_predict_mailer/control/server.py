"""Loopback-only configuration console with same-origin session/CSRF checks."""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import secrets
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ..agent_service.contracts import ServiceError, decode
from .a2a import A2AService, card
from .orchestrator import Orchestrator
from .store import Store

STATIC = Path(__file__).with_name("web")


def make_server(root, port=8767, master_key=None):
    store = Store(root, master_key)
    engine = Orchestrator(store)
    session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        server_version = "StockAgent/1"

        def log_message(self, *args):
            pass  # Request bodies, tokens, tool text and provider errors never enter logs.

        def output(self, value, status=200, content_type="application/json; charset=utf-8", cookie=False):
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() if isinstance(value, (dict, list)) else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if cookie:
                self.send_header("Set-Cookie", f"spm_session={session}; HttpOnly; SameSite=Strict; Path=/")
            self.end_headers()
            self.wfile.write(raw)

        def guard(self, mutation=False, a2a=False):
            authority = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if authority not in allowed:
                raise ServiceError("FORBIDDEN", "不允许的 Host")
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + a for a in allowed}:
                raise ServiceError("FORBIDDEN", "不允许的 Origin")
            if a2a:
                token = os.environ.get("SPM_A2A_TOKEN", "")
                if token and hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                    return
            try:
                cookies = SimpleCookie(self.headers.get("Cookie", ""))
                valid = cookies.get("spm_session") and hmac.compare_digest(cookies["spm_session"].value, session)
            except Exception:
                valid = False
            if not valid:
                raise ServiceError("FORBIDDEN", "请从本机控制台建立会话")
            if mutation and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf):
                raise ServiceError("FORBIDDEN", "缺少有效 CSRF token")

        def body(self):
            try:
                size = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                size = -1
            if not 0 <= size <= 1024 * 1024 or not self.headers.get("Content-Type", "").startswith("application/json"):
                raise ServiceError("INVALID_INPUT", "需要不超过 1 MiB 的 JSON 请求体")
            value = decode(self.rfile.read(size))
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

        def handle_request(self, method):
            try:
                path = urlsplit(self.path).path
                if method == "GET" and path in ("/", "/app.js", "/style.css"):
                    # Check Host/Origin even before minting a local session.
                    allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
                    if self.headers.get("Host") not in allowed or self.headers.get("Origin") not in (None, *("http://" + a for a in allowed)):
                        raise ServiceError("FORBIDDEN", "仅允许本机同源访问")
                    filename = "index.html" if path == "/" else path[1:]
                    content_type = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}[filename]
                    self.output((STATIC / filename).read_bytes(), content_type=content_type, cookie=path == "/")
                    return
                self.guard(method != "GET", a2a=path.startswith("/a2a/") or path == "/.well-known/agent-card.json")
                if method == "GET" and path == "/api/session":
                    self.output({"csrf_token": csrf, "temperature_note": "温度控制随机性，不是预测准确率或置信度；默认 0.2。"})
                    return
                if method == "GET" and path == "/.well-known/agent-card.json":
                    self.output(card(f"http://127.0.0.1:{self.server.server_port}"))
                    return
                if method == "GET" and path.startswith("/a2a/") and path.endswith("/agent-card.json"):
                    self.output(card(f"http://127.0.0.1:{self.server.server_port}", path.split("/")[2]))
                    return
                if method == "POST" and path.startswith("/a2a/"):
                    role = path.split("/")[-1]
                    self.output(asyncio.run(A2AService(engine).dispatch(self.body(), role)))
                    return
                parts = path.strip("/").split("/")
                if len(parts) < 2 or parts[0] != "api":
                    raise ServiceError("NOT_FOUND", "接口不存在")
                kind = parts[1]
                if kind in ("conversations", "memory"):
                    route = parts[2:]
                    if kind == "memory" and route == ["access"] and method == "POST":
                        self.output(engine.memory.create_owner(), 201)
                        return
                    owner = engine.memory.owner(self.headers.get("X-Memory-Key", ""))
                    if kind == "conversations" and not route and method == "POST":
                        self.output(engine.memory.new(owner), 201)
                    elif kind == "conversations" and not route and method == "GET":
                        self.output(engine.memory.conversations(owner))
                    elif kind == "conversations" and len(route) == 1 and method == "GET":
                        self.output(engine.memory.conversation(owner, route[0]))
                    elif kind == "memory" and route == ["settings"] and method in ("GET", "PUT"):
                        self.output(engine.memory.settings(owner, self.body() if method == "PUT" else None))
                    elif kind == "memory" and route == ["pending"] and method == "GET":
                        self.output(engine.memory.pending(owner))
                    elif kind == "memory" and not route and method == "GET":
                        self.output(engine.memory.entries(owner))
                    elif kind == "memory" and len(route) == 1 and method == "PUT":
                        self.output(engine.memory.update(owner, route[0], self.body()))
                    elif kind == "memory" and len(route) == 1 and method == "DELETE":
                        engine.memory.delete(owner, route[0])
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
                    if len(parts) >= 3 and (owner := engine.memory.task_owner(parts[2])):
                        if engine.memory.owner(self.headers.get("X-Memory-Key", "")) != owner:
                            raise ServiceError("FORBIDDEN", "此任务属于其他会话所有者")
                    if method == "POST" and len(parts) == 2:
                        payload = self.body()
                        owner = engine.memory.owner(self.headers.get("X-Memory-Key", "")) if payload.get("conversation_id") is not None else None
                        self.output(engine.submit(payload, owner), 202)
                    elif method == "GET" and len(parts) == 3:
                        self.output(store.task(parts[2]))
                    elif method == "GET" and len(parts) == 4 and parts[3] == "events":
                        try:
                            after = int(parse_qs(urlsplit(self.path).query).get("after", ["0"])[0])
                            if not 0 <= after <= 2**63 - 1:
                                raise ValueError()
                        except ValueError:
                            raise ServiceError("INVALID_INPUT", "进度游标无效") from None
                        self.output({"events": store.events(parts[2], after)})
                    elif method == "POST" and len(parts) == 4 and parts[3] == "cancel":
                        self.output(engine.cancel(parts[2]))
                    else:
                        raise ServiceError("NOT_FOUND", "任务接口不存在")
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
                        self.output(asyncio.run(engine.models.test(pid, store.settings())))
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
            except Exception:
                self.output({"error": {"code": "INTERNAL_ERROR", "message": "本地操作失败，请检查配置或工作区", "retryable": False}}, 500)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.store, server.engine = store, engine
    return server


def serve(root, port=8767):
    server = make_server(root, port)
    print(f"配置控制台：http://127.0.0.1:{server.server_port}（仅本机）", flush=True)
    try:
        server.serve_forever()
    finally:
        for tid in list(server.engine.active):
            server.engine.cancel(tid)
        server.server_close()
