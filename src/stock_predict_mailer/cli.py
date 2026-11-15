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
from .naming import COMMAND, PROJECT_NAME, SUMMARY_ZH, banner

MANIFEST_COLUMNS = "path,logical,source,document_date,available_date,valid_to,companies,industries,topics,stock_codes"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "legacy":
        try:
            from .legacy_cli import main as legacy_main
            return legacy_main(argv[1:])
        except ModuleNotFoundError:
            print(json.dumps({"error": {"code": "CONFIG_ERROR", "message": "旧功能需要安装 .[research,trees]", "retryable": False}}))
            return 2
    parser = argparse.ArgumentParser(prog=COMMAND, description=f"{PROJECT_NAME}：{SUMMARY_ZH}")
    parser.add_argument("--version", action="version", version=banner())
    parser.add_argument("--config", type=Path, default=Path("config/agent-example.toml"))
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="接入、分析、报告并入队；--send 执行配置的投递")
    run.add_argument("--recipient")
    run.add_argument("--send", action="store_true")
    forest = sub.add_parser("predict-rf", help="用交付的随机森林与月频特征导出 v1 预测 JSON")
    forest.add_argument("--features", type=Path, required=True)
    forest.add_argument("--model", type=Path, help="已交付模型文件的位置")
    forest.add_argument("--output", type=Path, required=True)
    send = sub.add_parser("send", help="发送或重试一条已入队邮件")
    send.add_argument("message_id")
    status = sub.add_parser("mail-status", help="查询邮件状态")
    status.add_argument("message_id")
    listing = sub.add_parser("mail-list", help="列出邮件队列（最新入队优先）")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--status", choices=("pending", "retry", "failed", "uncertain", "submitted", "simulated"))
    drain = sub.add_parser("mail-drain", help="投递所有到期邮件；由调度器周期调用")
    drain.add_argument("--limit", type=int, default=20)
    resolve = sub.add_parser("mail-resolve", help="人工确认 uncertain 邮件的真实结果")
    resolve.add_argument("message_id")
    resolve.add_argument("--delivered", action="store_true", help="确认已送达，不再重发")
    worker = sub.add_parser("knowledge-worker", help="独立资料清洗 Agent；不占分析子 Agent 名额")
    worker.add_argument("--once", action="store_true", help="处理当前所有待导入资料后退出")
    worker.add_argument("--poll", type=float, default=2)
    importer = sub.add_parser("knowledge-import", help="按目录或 CSV 清单批量导入知识资料")
    importer.add_argument("folder", type=Path, help="要导入的目录")
    importer.add_argument("--manifest", type=Path, help="CSV 清单，列为 %s" % MANIFEST_COLUMNS)
    importer.add_argument("--write-manifest", type=Path, help="按目录生成清单骨架后退出，不导入")
    importer.add_argument("--source", default="本地导入", help="清单未填来源时的默认值")
    importer.add_argument("--available", help="清单未填可用日期时的默认值 YYYY-MM-DD")
    importer.add_argument("--assume-available-today", action="store_true", help="缺日期时按今天可用；会污染历史回测，慎用")
    importer.add_argument("--principal", default="owner", help="写入身份；与控制台一致时用 KB_KEY 环境变量")
    importer.add_argument("--dry-run", action="store_true", help="只生成计划，不写库")
    importer.add_argument("--limit", type=int, help="本次最多导入多少个文件，用于试灌")
    importer.add_argument("--shallow", action="store_true", help="只扫当前目录，不递归")
    importer.add_argument("--process", action="store_true", help="导入后立即处理队列")
    importer.add_argument("--quiet", action="store_true", help="不打印逐文件进度")
    evaluate = sub.add_parser("knowledge-eval", help="用标注用例集给检索打分；不通过返回 2")
    evaluate.add_argument("cases", type=Path, help="用例 JSON，形如 {\"cases\": [...]}；示例见 examples/knowledge-eval/cases.json")
    evaluate.add_argument("--principal", default="owner", help="读取身份；与控制台一致时用 KB_KEY 环境变量")
    evaluate.add_argument("--limit", type=int, default=8, help="每条用例取回几段，1–20")
    evaluate.add_argument("--threshold", type=float, default=0.7, help="通过率下限，低于它整体判 fail")
    evaluate.add_argument("--as-of", help="用例未写 as_of 时的默认截止日期 YYYY-MM-DD")
    evaluate.add_argument("--answer", action="store_true", help="改评汇总回答：额外校验推断与冲突字段")
    evaluate.add_argument("--quiet", action="store_true", help="不打印逐条进度")
    acl = sub.add_parser("knowledge-acl", help="查看或设置 A2A 角色可读的知识库一级域")
    acl.add_argument("--role", choices=("main", "prediction", "risk", "advice"), help="角色；查询时留空表示列出全部")
    acl.add_argument("--domains", help="逗号分隔的一级域；传空字符串表示清空，该角色立即失去读取权")
    console = sub.add_parser("console", help="启动本机模型、MCP 与 Agent 配置控制台")
    console.add_argument("--port", type=int, default=8767)
    args = parser.parse_args(argv)
    try:
        if args.command == "predict-rf":
            from .agent_service.random_forest import MODEL_PATH, predict_file
            from .core import atomic_write

            model_path = args.model or MODEL_PATH
            if args.output.resolve() in (args.features.resolve(), model_path.resolve()):
                raise ServiceError("INVALID_INPUT", "输出路径不能覆盖特征或模型文件")
            result = predict_file(args.features, model_path)
            atomic_write(args.output, json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        cfg = load(args.config)
        if args.command == "knowledge-worker":
            from .private_knowledge.worker import run
            return run(cfg["workspace"], once=args.once, poll=args.poll)
        if args.command == "console":
            from .control.server import serve
            serve(cfg["workspace"], args.port)
            return 0
        if args.command == "knowledge-acl":
            from .control.store import Store
            store = Store(Path(cfg["workspace"]))
            settings = store.settings()
            if args.domains is None:
                for role, conf in settings["agents"].items():
                    if args.role and role != args.role:
                        continue
                    print(f"{role}: {','.join(conf['knowledge_domains']) or '（未授权，A2A 检索会拒绝）'}")
                return 0
            if not args.role:
                raise ServiceError("INVALID_INPUT", "设置 --domains 时必须指定 --role")
            settings["agents"][args.role]["knowledge_domains"] = [d.strip() for d in args.domains.split(",") if d.strip()]
            store.save_settings(settings)
            granted = settings["agents"][args.role]["knowledge_domains"]
            print(f"{args.role}: {','.join(granted) or '（已清空，该角色不能读取任何资料）'}")
            return 0
        if args.command == "knowledge-import":
            from .private_knowledge.importer import run as import_knowledge
            summary = import_knowledge(cfg["workspace"], args.folder, principal=args.principal,
                                       manifest=args.manifest, write_manifest=args.write_manifest,
                                       source=args.source, available=args.available,
                                       assume_available_today=args.assume_available_today,
                                       dry_run=args.dry_run, limit=args.limit, recursive=not args.shallow,
                                       progress=not args.quiet, process=args.process)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 2 if summary.get("failed") else 0
        if args.command == "knowledge-eval":
            from .private_knowledge.evaluation import run as evaluate_knowledge
            report = evaluate_knowledge(cfg["workspace"], args.cases, principal=args.principal, limit=args.limit,
                                        answer=args.answer, threshold=args.threshold, as_of=args.as_of,
                                        progress=not args.quiet)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["verdict"] == "pass" else 2
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
        if args.command == "mail-list":
            print(json.dumps(mail.listing(args.limit, args.status), ensure_ascii=False, indent=2))
            return 0
        if args.command == "mail-drain":
            summary = mail.drain(args.limit)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if all(item["status"] in ("submitted", "simulated") for item in summary["results"]) else 2
        if args.command == "mail-resolve":
            result = mail.resolve(args.message_id, delivered=args.delivered)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
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
