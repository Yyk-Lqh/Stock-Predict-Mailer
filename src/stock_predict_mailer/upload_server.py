"""Loopback-only upload UI. Not an Internet-facing or multi-user service."""
from __future__ import annotations

import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .core import Config
from .intake import intake_paths, latest, list_uploads, process, publish_bars, scan_incoming, upload
from .intake_readers import MAX_BYTES, IntakeError


def make_server(cfg: Config, port: int = 8765) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(32)
    assets = Path(__file__).parent / "web"
    intake_paths(cfg)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # no private filenames, queries or tokens in access logs

        def reply(self, status, data, content_type="application/json; charset=utf-8"):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8") if isinstance(data, (dict, list)) else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def check(self, api=False, write=False):
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            host = self.headers.get("Host", "")
            if host not in hosts:
                self.reply(403, {"error": "仅允许本机地址访问"})
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin != f"http://{host}":
                self.reply(403, {"error": "拒绝跨站请求"})
                return False
            if write and origin != f"http://{host}":
                self.reply(403, {"error": "写入请求需要同源标识"})
                return False
            if api and not hmac.compare_digest(self.headers.get("X-Upload-Token", ""), token):
                self.reply(403, {"error": "页面会话已失效，请刷新"})
                return False
            return True

        def do_GET(self):
            parsed = urlsplit(self.path)
            if not self.check(api=parsed.path.startswith("/api/")):
                return
            if parsed.path == "/":
                page = (assets / "index.html").read_text(encoding="utf-8").replace("__SESSION_TOKEN__", token)
                self.reply(200, page.encode("utf-8"), "text/html; charset=utf-8")
            elif parsed.path in ("/app.js", "/style.css"):
                suffix = "application/javascript" if parsed.path.endswith(".js") else "text/css"
                self.reply(200, (assets / parsed.path[1:]).read_bytes(), suffix + "; charset=utf-8")
            elif parsed.path == "/api/uploads":
                self.reply(200, {"uploads": list_uploads(cfg), "incoming": str(intake_paths(cfg) / "incoming")})
            elif parsed.path.startswith("/api/uploads/"):
                try:
                    self.reply(200, latest(cfg, parsed.path.rsplit("/", 1)[1]))
                except (ValueError, FileNotFoundError):
                    self.reply(404, {"error": "找不到文件记录"})
            else:
                self.reply(404, {"error": "路径不存在"})

        def do_POST(self):
            if not self.check(api=True, write=True):
                return
            parsed = urlsplit(self.path)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = MAX_BYTES if parsed.path == "/api/upload" else 128 * 1024
                if length <= 0 or length > limit or self.headers.get("Transfer-Encoding"):
                    self.reply(413, {"error": "请求为空或超过大小限制"})
                    return
                self.connection.settimeout(30)
                body = self.rfile.read(length)
                if len(body) != length:
                    raise IntakeError("上传未完成，请重试")
                if parsed.path == "/api/upload":
                    name = parse_qs(parsed.query).get("name", [""])[0]
                    result = upload(cfg, name, body)
                else:
                    values = json.loads(body)
                    if not isinstance(values, dict):
                        raise IntakeError("请求应为 JSON 对象")
                    if parsed.path == "/api/process":
                        result = process(cfg, values["upload_id"], values.get("options"))
                    elif parsed.path == "/api/publish":
                        if type(values.get("table_index")) is not int:
                            raise IntakeError("表格编号需要整数")
                        result = publish_bars(cfg, values["upload_id"], values["table_index"])
                    elif parsed.path == "/api/scan":
                        result = {"processed": scan_incoming(cfg)}
                    else:
                        self.reply(404, {"error": "路径不存在"})
                        return
                self.reply(200, result)
            except (ValueError, KeyError, TypeError, FileNotFoundError) as exc:
                message = str(exc)[:240] if isinstance(exc, (IntakeError, ValueError)) else "请求字段无效或文件不存在"
                self.reply(400, {"error": message})
            except Exception:
                self.reply(500, {"error": "处理未完成，请查看本地文件及格式；原件未被删除"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(cfg: Config, port: int = 8765):
    with make_server(cfg, port) as server:
        print(f"本机数据接入中心：http://127.0.0.1:{server.server_port}", flush=True)
        print(f"文件投放目录：{intake_paths(cfg) / 'incoming'}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
