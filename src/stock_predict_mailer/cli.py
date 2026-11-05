"""Default result-consumer CLI. Historical research tools are lazy opt-in."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .agent_service.adapters import adapter
from .agent_service.analysis import AnalysisAgent
from .agent_service.config import load
from .agent_service.contracts import ServiceError
from .agent_service.mail import MailService
from .agent_service.reporting import save_report


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "legacy":
        try:
            from .legacy_cli import main as legacy_main
            return legacy_main(argv[1:])
        except ModuleNotFoundError:
            print(json.dumps({"error": {"code": "CONFIG_ERROR", "message": "旧功能需要安装 .[research,trees]", "retryable": False}}))
            return 2
    parser = argparse.ArgumentParser(description="预测分析 Agent + 邮件通知服务")
    parser.add_argument("--config", type=Path, default=Path("config/agent-example.toml"))
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="接入、分析、报告并入队；--send 执行配置的投递")
    run.add_argument("--recipient")
    run.add_argument("--send", action="store_true")
    send = sub.add_parser("send", help="发送或重试一条已入队邮件")
    send.add_argument("message_id")
    status = sub.add_parser("mail-status", help="查询邮件状态")
    status.add_argument("message_id")
    console = sub.add_parser("console", help="启动本机模型、MCP 与 Agent 配置控制台")
    console.add_argument("--port", type=int, default=8767)
    args = parser.parse_args(argv)
    try:
        cfg = load(args.config)
        if args.command == "console":
            from .control.server import serve
            serve(cfg["workspace"], args.port)
            return 0
        mail = MailService(cfg["workspace"], cfg["mail"], cfg["timezone"], analysis_settings=cfg["agent"])
        if args.command == "run":
            p = adapter(cfg["prediction"]["adapter"], {**cfg["prediction"], "role": "prediction"}).fetch()
            ctx = cfg["context"]
            c = None if ctx["adapter"] == "none" else adapter(ctx["adapter"], {**ctx, "role": "context"}).fetch()
            analysis = AnalysisAgent(cfg["agent"]).analyze(p, c)
            folder = save_report(cfg["workspace"], analysis, cfg["timezone"])
            result = mail.enqueue(analysis, args.recipient or cfg["mail"]["recipient"])
            if args.send:
                result = mail.deliver(result["id"])
            print(json.dumps({"analysis_id": analysis["analysis_id"], "analysis_status": analysis["status"],
                              "report": str(folder / "report.html"), "mail": result}, ensure_ascii=False, indent=2))
            return 0 if result["status"] in ("pending", "submitted", "simulated") else 2
        result = mail.deliver(args.message_id) if args.command == "send" else mail.public(mail.get(args.message_id))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if args.command == "mail-status" or result["status"] in ("submitted", "simulated") else 2
    except ServiceError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False))
        return 2
    except (OSError, sqlite3.Error):
        print(json.dumps(ServiceError("LOCAL_IO", "本地存储或锁不可用，请稍后重试", True).as_dict(), ensure_ascii=False))
        return 2
    except RuntimeError:
        print(json.dumps(ServiceError("LOCAL_IO", "另一个投递进程正在运行", True).as_dict(), ensure_ascii=False))
        return 2
