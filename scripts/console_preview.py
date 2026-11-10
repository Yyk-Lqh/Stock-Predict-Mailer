"""控制台前端预览服务（仅开发用）。

不启动真实后端、不需要 STOCK_PREDICT_MAILER_MASTER_KEY、不读写任何工作区数据：
把 src/stock_predict_mailer/control/web/ 下的四个真实文件原样送出，
并用内存里的假数据应答 /api/*，用于核对布局、状态语义与交互。

    python scripts/console_preview.py --port 8790
    # 打开 http://127.0.0.1:8790

假数据刻意覆盖三种状态：正常完成、分析降级、邮件模拟投递。
这不是验收环境：真实契约与失败处理仍以 console 后端为准。
"""
from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

WEB = Path(__file__).resolve().parents[1] / "src" / "stock_predict_mailer" / "control" / "web"
FILES = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
         "/style.css": ("style.css", "text/css"), "/memory.js": ("memory.js", "text/javascript")}

MODEL = {
    "id": "previewmodel01", "name": "Mock 分析模型", "provider": "mock", "base_url": "https://api.openai.com/v1",
    "model": "mock-analysis", "timeout_seconds": 20, "retries": 1,
    "supported_parameters": ["temperature", "max_tokens", "response_format"],
    "temperature_min": 0.0, "temperature_max": 2.0, "parameters": {"max_tokens": 512},
    "reasoning_effort_map": {}, "input_usd_per_million": None, "output_usd_per_million": None,
    "enabled": True, "has_secret": False, "secret_mask": "", "env_keys": [],
}
SERVER = {
    "id": "previewmcp01", "name": "本地行情 Mock", "transport": "streamable_http",
    "url": "http://127.0.0.1:8766/mcp", "command": "", "args": [], "env_keys": [],
    "timeout_seconds": 15, "allowed_tools": ["get_context"], "allowed_resources": [],
    "effects": {"get_context": "read"}, "enabled": True, "has_secret": False, "secret_mask": "",
}
SETTINGS = {
    "default_reasoning_effort": "medium", "default_model_id": MODEL["id"], "global_temperature": 0.2,
    "agents": {role: {"model_id": None, "endpoint_id": None, "temperature": None, "tools": []}
               for role in ("main", "prediction", "risk", "advice")},
    "limits": {"max_subagents": 3, "max_depth": 1, "max_calls": 8, "timeout_seconds": 90,
               "child_timeout_seconds": 20, "budget_usd": 0.1},
    "mail": {"chart_delivery": "inline", "transport": "file", "sender": "research@example.invalid",
             "recipient_allowlist": ["preview@example.invalid"], "allow_synthetic": True,
             "mcp_server_id": None, "mcp_tool": None, "host": "", "port": 587, "tls": "starttls",
             "user_env": "SMTP_USER", "password_env": "SMTP_PASSWORD"},
}
MODELS: list[dict] = [dict(MODEL)]
SERVERS: list[dict] = [dict(SERVER)]
ENDPOINTS: list[dict] = []
TASKS: dict[str, dict] = {}
FRESH = False  # ?fresh=1 期间为 True：假装这台机器还没配过任何东西
HOLD = False   # ?hold=1 期间为 True：任务永远停在「运行中」，用来看运行图的动画


def NOW() -> datetime:
    return datetime.now(timezone.utc)


def _analysis(request: dict, degraded: bool) -> dict:
    prediction = request.get("prediction") or {}
    facts = (request.get("context") or {}).get("facts") or []
    ids = [f["id"] for f in facts] or ["F-01", "F-02"]
    if not facts:
        facts = [
            {"id": "F-01", "name": "收盘价", "value": 10.58, "unit": "CNY", "source": "上游行情快照",
             "observed_at": (NOW() - timedelta(days=1)).isoformat(), "available_at": (NOW() - timedelta(days=1)).isoformat()},
            {"id": "F-02", "name": "成交量", "value": 32000, "unit": "手", "source": "上游行情快照",
             "observed_at": (NOW() - timedelta(days=1)).isoformat(), "available_at": (NOW() - timedelta(days=1)).isoformat()},
        ]
    return {
        "schema_version": "1", "analysis_id": "preview-" + uuid.uuid4().hex[:8], "generated_at": NOW().isoformat(),
        "status": "degraded" if degraded else "ok", "mode": "orchestrated_bounded", "prediction": prediction,
        "facts": facts,
        "inferences": [
            {"code": "MODEL_UP", "text": f"{ids[0]} 与 {ids[1]} 同时指向短期动能偏强，但缺少同期行业对照。",
             "evidence_ids": [ids[0], ids[1]]},
            {"code": "VERIFY", "text": "上游未提供置信度，方向结论只能作为待验证假设。", "evidence_ids": [ids[0]]},
        ],
        "recommendations": ["不追高，等待回调后确认成交量是否延续。", "把行业指数同期表现补充为事实后再判断相对强弱。"],
        "limitations": (["风险分支超时，风险段由主 Agent 在可用事实内补写。"] if degraded else []) +
                       ["没有行业指数与估值分位，无法判断相对位置。"],
        "risks": ["单一交易日的量价关系不稳定，容易被次日噪声打断。"],
    }


def _brief(request: dict) -> dict:
    p = request.get("prediction") or {}
    return {"subject": p.get("subject"), "direction": p.get("direction"), "horizon": p.get("horizon"),
            "confidence": p.get("confidence"), "synthetic": p.get("synthetic"),
            "notify": bool(request.get("notify")), "recipient": request.get("recipient"),
            "goal": request.get("goal"), "conversation_id": request.get("conversation_id")}


def _task_body(task_id: str, request: dict, polls: int, stamp: datetime | None = None, fail: str | None = None) -> dict:
    state = "failed" if fail else ("submitted" if polls < 1 else ("working" if polls < 4 else "completed"))
    task = {"kind": "task", "id": task_id, "contextId": "preview-ctx",
            "status": {"state": state, "timestamp": (stamp or NOW()).isoformat()},
            "metadata": {"request": _brief(request)}, "artifacts": []}
    if fail:
        task["metadata"]["error"] = {"code": fail, "message": "预览用失败样本", "retryable": False}
        return task
    if HOLD and state == "completed":
        state = "working"
        task["status"]["state"] = state
    if state != "completed":
        return task
    subject = (request.get("prediction") or {}).get("subject") or ""
    degraded = subject.endswith(".DEG")
    mail = None
    if request.get("notify"):
        mail = {"id": "mail-" + uuid.uuid4().hex[:6],
                "status": "uncertain" if subject.endswith(".UNC") else "simulated", "attempts": 1,
                "next_attempt": None, "recipient": request.get("recipient") or "preview@example.invalid"}
    data = {
        "analysis": _analysis(request, degraded),
        "children": [
            {"id": "child-pred", "role": "prediction", "status": "completed", "depth": 1, "tools": [],
             "data_fields": ["prediction", "facts"]},
            {"id": "child-risk", "role": "risk", "status": "failed" if degraded else "completed", "depth": 1,
             "tools": [], "data_fields": ["prediction"], **({"error": "CALL_TIMEOUT"} if degraded else {})},
            {"id": "child-advice", "role": "advice", "status": "completed", "depth": 1, "tools": [],
             "data_fields": ["prediction", "facts"]},
        ],
        "conflicts": [] if not degraded else [{"role": "risk", "code": "DIRECTION_CONFLICT", "reason": "与预测分支方向相反，已排除"}],
        "usage": {"calls": 7, "reserved_usd": 0, "budget_usd": SETTINGS["limits"]["budget_usd"]},
        "mail": mail, "report_path": "preview-only",
    }
    task["artifacts"] = [{"parts": [{"kind": "data", "data": data}]}]
    return task


def _seed() -> None:
    """给记录页准备几条不同状态的历史任务（预览用，不写入任何工作区）。"""
    samples = [
        ("DEMO.SZ", "up", 5, "trading_days", True, 99, None, 1.2),
        ("600519.SH", "down", 3, "trading_days", False, 99, None, 4.5),
        ("000001.SZ", "up", 10, "calendar_days", True, 99, None, 26.0),
        ("DEMO.DEG", "flat", 5, "trading_days", False, 99, None, 30.0),
        ("300750.SZ", "down", 1, "hours", False, 99, None, 51.0),
        ("688111.SH", "up", 5, "trading_days", False, 99, "MODEL_REQUIRED", 55.0),
        ("DEMO.UNC", "up", 5, "trading_days", True, 99, None, 6.0),
        ("002594.SZ", "up", 5, "trading_days", False, 0, None, 0.05),
    ]
    for subject, direction, value, unit, notify, polls, fail, hours in samples:
        stamp = NOW() - timedelta(hours=hours)
        request = {"prediction": {"subject": subject, "direction": direction, "confidence": None,
                                  "horizon": {"value": value, "unit": unit}, "synthetic": False,
                                  "generated_at": stamp.isoformat()},
                   "notify": notify, "recipient": "preview@example.invalid" if notify else None,
                   "goal": "overview"}
        tid = uuid.uuid4().hex
        TASKS[tid] = {"request": request, "polls": polls, "stamp": stamp, "fail": fail}


def _events(request: dict, after: int, fail: str | None = None) -> list[dict]:
    steps = [{"id": "validate", "label": "校验预测与数据"}, {"id": "main", "label": "主 Agent 分析"},
             {"id": "prediction", "label": "预测分析"}, {"id": "risk", "label": "风险分析"},
             {"id": "advice", "label": "建议生成"}, {"id": "charts", "label": "生成分析图表"},
             {"id": "report", "label": "汇总并保存报告"}]
    if request.get("notify"):
        steps.append({"id": "mail", "label": "按授权交付邮件"})
    degraded = ((request.get("prediction") or {}).get("subject") or "").endswith(".DEG")
    timeline = [
        {"seq": 1, "kind": "plan", "label": "执行计划", "status": "pending", "timestamp": NOW().isoformat(),
         "steps": steps, "execution": {"effort": "medium", "label": "中", "model": "mock-analysis",
                                       "native_reasoning_effort": None,
                                       "limits": {"max_steps": 8, "max_tool_calls": 2, "max_calls": 8,
                                                  "timeout_seconds": 90, "max_subagents": 3, "budget_usd": 0.1}}},
        {"seq": 2, "kind": "step", "step": "validate", "label": "校验 DEMO.SZ 的预测结果", "status": "completed",
         "timestamp": NOW().isoformat(), "summary": ["概率字段未提供，按 null 处理"]},
        {"seq": 3, "kind": "step", "step": "main", "label": "主 Agent 分析", "status": "completed",
         "timestamp": NOW().isoformat(), "temperature": 0.2},
        {"seq": 4, "kind": "step", "step": "prediction", "label": "预测分析分支", "status": "completed",
         "timestamp": NOW().isoformat()},
        {"seq": 5, "kind": "step", "step": "risk", "label": "风险分析分支",
         "status": "failed" if degraded else "completed", "timestamp": NOW().isoformat(),
         **({"code": "CALL_TIMEOUT", "summary": ["20 秒内未返回"]} if degraded else {})},
        {"seq": 6, "kind": "step", "step": "advice", "label": "建议生成分支", "status": "completed",
         "timestamp": NOW().isoformat()},
        {"seq": 7, "kind": "step", "step": "charts", "label": "生成分析图表", "status": "completed",
         "timestamp": NOW().isoformat()},
        {"seq": 8, "kind": "step", "step": "report", "label": "汇总并保存报告", "status": "completed",
         "timestamp": NOW().isoformat()},
    ]
    if fail:
        # 失败样本停在第一个阶段，不要伪造后面「已完成」的分支，否则和失败说明自相矛盾
        timeline[1] = {"seq": 2, "kind": "step", "step": "validate", "label": "准备模型调用",
                       "status": "failed", "code": fail, "timestamp": NOW().isoformat(),
                       "summary": ["任务在调用模型前停止"]}
        timeline = timeline[:2]
    if HOLD:
        # 停在第 5 条之前：前三个阶段已完成，「风险分析」保持运行中，运行图才有东西可看。
        timeline = timeline[:5]
        timeline[-1] = {**timeline[-1], "status": "running"}
    return [event for event in timeline if event["seq"] > after]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        size = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(size) or b"{}") if size else {}

    def do_GET(self):
        path = urlsplit(self.path).path
        # ?fresh=1 模拟全新安装：没有模型、没有外部工具、没有历史任务，用来看首屏的三步清单。
        # 开关记在进程里，因为页面加载后前端再发的 /api/* 请求不会再带这个参数；?fresh=0 复位。
        fresh = parse_qs(urlsplit(self.path).query).get("fresh", [])
        hold = parse_qs(urlsplit(self.path).query).get("hold", [])
        if hold:
            global HOLD
            HOLD = hold[0] == "1"
        if fresh:
            global FRESH
            FRESH = fresh[0] == "1"
        if path in FILES:
            name, ctype = FILES[path]
            raw = (WEB / name).read_bytes()
            if name == "index.html" and "demo=1" in self.path:
                raw = raw.replace(
                    b"</body>",
                    b"<script>addEventListener('load',function(){var s=function(m){return new Promise(function(r){setTimeout(r,m)})};"
                    b"document.getElementById('try-sample').click();s(300).then(function(){"
                    b"if(location.search.indexOf('unc=1')>0){var f=document.getElementById('p-subject');"
                    b"f.value='DEMO.UNC';f.dispatchEvent(new Event('input',{bubbles:true}));"
                    b"document.getElementById('task-notify').checked=true;"
                    b"document.getElementById('task-recipient').value='preview@example.invalid';}"
                    b"document.getElementById('task-form').dispatchEvent(new Event('submit',{cancelable:true}));return s(6000)}).then(function(){"
                    b"if(location.search.indexOf('focus=1')>0){document.getElementById('task-form').hidden=true;"
                    b"document.querySelector('[data-view-pane=analysis] .page-head').hidden=true;}});});</script></body>",
                )
            if name == "index.html" and "allow=" in self.path:
                # ?allow=ok|bad|empty 直接打开设置页并填好收件人清单，用来核对复述的三种语气。
                mode = parse_qs(urlsplit(self.path).query).get("allow", [""])[0]
                value = {"ok": "preview@example.invalid\nrisk@example.invalid",
                         "bad": "preview@example.invalid\npreview.example.invalid",
                         "empty": ""}.get(mode, "")
                raw = raw.replace(
                    b"</body>",
                    b"<script>addEventListener('load',function(){setTimeout(function(){"
                    b"document.querySelector('[data-view=\"settings\"]').click();"
                    b"document.querySelector('[data-panel=\"settings\"]').click();"
                    b"setTimeout(function(){var a=document.getElementById('mail-allowlist');"
                    b"a.value=" + json.dumps(value).encode() + b";"
                    b"a.dispatchEvent(new Event('input',{bubbles:true}));},600);},400);});</script></body>",
                )
            self.send_response(200)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if path == "/__frame":
            # 设备宽度检查用：Windows 无头窗口有最小宽度，只能在 iframe 里压到 390。
            query = parse_qs(urlsplit(self.path).query)
            width = query.get("w", ["390"])[0]
            tail = query.get("q", [""])[0]
            inner = "/" + (tail if tail.startswith("#") else "?" + tail) if tail else "/"
            body = (
                '<!doctype html><html><head><meta charset="utf-8"><style>'
                'html,body{margin:0;background:#07080a}iframe{border:0;display:block;'
                f'width:{width}px;height:1500px}}</style></head>'
                f'<body><iframe src="{inner}"></iframe></body></html>'
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/session":
            return self.send_json({"csrf_token": "preview"})
        if path == "/api/models":
            return self.send_json([] if FRESH else MODELS)
        if path == "/api/mcp":
            return self.send_json([] if FRESH else SERVERS)
        if path == "/api/agents":
            return self.send_json(ENDPOINTS)
        if path == "/api/settings":
            return self.send_json({**SETTINGS, "default_model_id": None} if FRESH else SETTINGS)
        if path == "/api/conversations" or path == "/api/memory":
            return self.send_json([])
        if path == "/api/memory/pending":
            return self.send_json({"items": [], "next_before": None})
        if path == "/api/memory/settings":
            return self.send_json({"enabled": True, "context_bytes": 6000, "recent_turns": 3})
        match = re.fullmatch(r"/api/tasks/([0-9a-f]+)/events", path)
        if match:
            task = TASKS.get(match.group(1))
            after = int(re.search(r"after=(\d+)", self.path).group(1)) if "after=" in self.path else 0
            return self.send_json({"events": _events(task["request"], after, task.get("fail")) if task else []})
        if path == "/api/tasks":
            query = parse_qs(urlsplit(self.path).query)
            limit = int(query.get("limit", ["30"])[0])
            offset = int(query.get("before", ["0"])[0])
            ordered = [] if FRESH else sorted(TASKS.items(), key=lambda kv: kv[1].get("stamp") or NOW(), reverse=True)
            bodies = [_task_body(tid, rec["request"], rec["polls"], rec.get("stamp"), rec.get("fail"))
                      for tid, rec in ordered]
            page = bodies[offset:offset + limit]
            return self.send_json({"items": page,
                                   "next_before": offset + len(page) if offset + len(page) < len(bodies) else None})
        match = re.fullmatch(r"/api/tasks/([0-9a-f]+)", path)
        if match:
            task = TASKS.get(match.group(1))
            if not task:
                return self.send_json({"error": {"code": "NOT_FOUND", "message": "任务不存在"}}, 404)
            task["polls"] += 1
            return self.send_json(_task_body(match.group(1), task["request"], task["polls"],
                                             task.get("stamp"), task.get("fail")))
        return self.send_json({"error": {"code": "NOT_FOUND", "message": "预览服务未实现该接口"}}, 404)

    def do_POST(self):
        path = urlsplit(self.path).path
        data = self.body()
        if path == "/api/tasks":
            task_id = uuid.uuid4().hex
            TASKS[task_id] = {"request": data, "polls": 0, "stamp": NOW()}
            body = _task_body(task_id, data, 0)
            return self.send_json(body, 202)
        match = re.fullmatch(r"/api/tasks/([0-9a-f]+)/mail/resolve", path)
        if match:
            return self.send_json({"id": "mail-preview", "status": "delivered" if data.get("delivered") else "failed"})
        match = re.fullmatch(r"/api/tasks/([0-9a-f]+)/cancel", path)
        if match and match.group(1) in TASKS:
            task = TASKS[match.group(1)]
            task["polls"] = 99
            return self.send_json(_task_body(match.group(1), task["request"], 99))
        if path == "/api/models":
            record = {**MODEL, **data, "id": uuid.uuid4().hex[:16], "has_secret": bool(data.get("api_key")),
                      "secret_mask": "sk-****" if data.get("api_key") else "", "env_keys": []}
            MODELS.append(record)
            return self.send_json(record, 201)
        if path == "/api/mcp":
            record = {**SERVER, **data, "id": uuid.uuid4().hex[:16], "has_secret": bool(data.get("auth_token"))}
            SERVERS.append(record)
            return self.send_json(record, 201)
        if path == "/api/agents":
            record = {**data, "id": uuid.uuid4().hex[:16]}
            ENDPOINTS.append(record)
            return self.send_json(record, 201)
        if path == "/api/settings":
            SETTINGS.update(data)
            return self.send_json(SETTINGS)
        if path == "/api/settings/reset-temperature":
            SETTINGS["global_temperature"] = 0.2
            return self.send_json(SETTINGS)
        if re.fullmatch(r"/api/models/[0-9a-zA-Z]+/test", path):
            return self.send_json({"message": "Mock 服务连接正常，未产生费用。"})
        if re.fullmatch(r"/api/mcp/[0-9a-zA-Z]+/test", path):
            return self.send_json({"protocol_version": "2025-06-18", "tools": [
                {"name": "get_context", "inputSchema": {"type": "object", "properties": {"subject": {"type": "string"}}},
                 "outputSchema": {"type": "object"}}], "resources": []})
        return self.send_json({"ok": True})

    def do_PUT(self):
        path = urlsplit(self.path).path
        data = self.body()
        if path == "/api/settings":
            SETTINGS.update(data)
            return self.send_json(SETTINGS)
        for items, collection in ((MODELS, "models"), (SERVERS, "mcp"), (ENDPOINTS, "agents")):
            match = re.fullmatch(rf"/api/{collection}/([0-9a-zA-Z]+)", path)
            if match:
                for index, item in enumerate(items):
                    if item["id"] == match.group(1):
                        items[index] = {**item, **data}
                        return self.send_json(items[index])
        return self.send_json({"ok": True})

    def do_DELETE(self):
        path = urlsplit(self.path).path
        for items, collection in ((MODELS, "models"), (SERVERS, "mcp"), (ENDPOINTS, "agents")):
            match = re.fullmatch(rf"/api/{collection}/([0-9a-zA-Z]+)", path)
            if match:
                items[:] = [item for item in items if item["id"] != match.group(1)]
        return self.send_json({"ok": True})


def main() -> None:
    _seed()
    parser = argparse.ArgumentParser(description="控制台前端预览（假数据）")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"预览：http://127.0.0.1:{args.port}  （Ctrl+C 结束）")
    server.serve_forever()


if __name__ == "__main__":
    main()
