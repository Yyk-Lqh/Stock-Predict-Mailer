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
from .agent_service.contracts import ServiceError, decode, prediction
from .agent_service.mail import MailService
from .agent_service.reporting import save_report
from .bars_fetch import FetchError
from .cli_io import utf8_console
from .naming import COMMAND, PROJECT_NAME, SUMMARY_ZH, banner
from .plugins.errors import PluginError

MANIFEST_COLUMNS = "path,logical,source,document_date,available_date,valid_to,companies,industries,topics,stock_codes"


def read_json(path):
    with path.open("rb") as stream:
        return decode(stream.read(1024 * 1024 + 1))


def main(argv=None):
    utf8_console()
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
    run.add_argument("--evaluation-definition", type=Path, help="显式提供评价定义，先归档本次预测再分析")
    forest = sub.add_parser("predict-rf", help="用交付的随机森林与月频特征导出 v1 预测 JSON")
    forest.add_argument("--features", type=Path, required=True)
    forest.add_argument("--model", type=Path, help="已交付模型文件的位置")
    forest.add_argument("--output", type=Path, required=True)
    forecasts = sub.add_parser("forecast", help="显式归档预测、查询到期状态并按事前定义离线评估")
    forecast_sub = forecasts.add_subparsers(dest="forecast_action", required=True)
    register = forecast_sub.add_parser("register")
    register.add_argument("--prediction", type=Path, required=True)
    register.add_argument("--definition", type=Path, required=True)
    for name in ("list", "show", "evaluate"):
        command = forecast_sub.add_parser(name)
        if name != "list":
            command.add_argument("forecast_id")
        command.add_argument("--as-of")
        if name == "list":
            command.add_argument("--limit", type=int, default=50)
            command.add_argument("--offset", type=int, default=0)
        if name == "evaluate":
            command.add_argument("--observation", type=Path)
            command.add_argument("--dry-run", action="store_true")
    send = sub.add_parser("send", help="发送或重试一条已入队邮件")
    send.add_argument("message_id")
    status = sub.add_parser("mail-status", help="查询邮件状态")
    status.add_argument("message_id")
    listing = sub.add_parser("mail-list", help="列出邮件队列（最新入队优先）")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--status", choices=("pending", "retry", "failed", "uncertain", "submitted", "simulated"))
    migration = sub.add_parser("mail-migrate", help="默认只读迁移预演；显式 apply 仅导入隔离归档，不投递")
    migration.add_argument("--source-workspace", type=Path)
    migration.add_argument("--principal", default="owner")
    migration.add_argument("--limit", type=int, default=1000)
    migration.add_argument("--apply", action="store_true")
    migration.add_argument("--target-workspace", type=Path)
    migration.add_argument("--expected-plan")
    archive = sub.add_parser("mail-archive", help="只读列出隔离归档，不进入待发队列")
    archive.add_argument("--target-workspace", type=Path)
    archive.add_argument("--principal", default="owner")
    archive.add_argument("--limit", type=int, default=20)
    for name in ("mail-binding-plan", "mail-bind", "legacy-binding-plan", "legacy-bind"):
        command = sub.add_parser(name, help="只读审阅或显式确认端点绑定；不投递邮件")
        command.add_argument("message_id")
        command.add_argument("--principal", default="owner")
        if name.endswith("-bind"):
            command.add_argument("--expected-plan", required=True)
    sub.add_parser("mail-history-plan", help="只读核对旧 MCP 回执切换界限")
    history_ack = sub.add_parser("mail-history-ack", help="显式记录旧 MCP 回执及新预测时间界限；不投递")
    history_ack.add_argument("--expected-plan", required=True)
    history_ack.add_argument("--not-before", required=True)
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
    doctor = sub.add_parser("doctor", help="只读检查工作区、数据库、任务、密钥与端口；不启动或恢复服务")
    doctor.add_argument("--port", type=int, default=8767)
    doctor.add_argument("--crawler-workspace", type=Path)
    doctor.add_argument("--skip-port-check", action="store_true")
    sub.add_parser("plugins-list", help="列出内置插件白名单、声明能力与可选依赖状态；不联网")
    plugin_check = sub.add_parser("plugins-check", help="体检插件依赖与行情源链，指出大厅能否启动；不联网")
    plugin_check.add_argument("--market", type=Path, help="含 market.json 的目录；留空检查默认链")
    bars = sub.add_parser("bars-fetch", help="从已声明的行情源取日线，写出数据契约 CSV 与来源记录；需联网")
    bars.add_argument("--symbols", required=True, help="逗号分隔，如 sh.600519,sz.000001")
    bars.add_argument("--start", required=True, help="起始日期 YYYY-MM-DD")
    bars.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    bars.add_argument("--output", type=Path, required=True, help="输出 CSV 路径；来源记录写在同名 .provenance.json")
    bars.add_argument("--source", default="market_eastmoney", help="已声明的行情源 id，见 plugins-list")
    bars.add_argument("--timeout", type=float, default=8.0)
    bars.add_argument("--assume-session-close", action="store_true",
                      help="历史回补时把 available_at 记为当日 18:00；默认写真实取数时间")
    runtime = sub.add_parser("runtime", help="组件状态、显式后台启动、实例匹配停止与有界生命周期日志")
    runtime_sub = runtime.add_subparsers(dest="runtime_action", required=True)
    for name in ("status", "start", "stop", "logs"):
        command = runtime_sub.add_parser(name)
        command.add_argument("component", choices=("console", "knowledge_worker", "crawler_worker"))
        command.add_argument("--crawler-workspace", type=Path)
        if name == "start":
            command.add_argument("--port", type=int, default=8767)
            command.add_argument("--poll", type=float, default=2)
        if name == "stop":
            command.add_argument("--instance", required=True)
            command.add_argument("--wait", type=float, default=10)
        if name == "logs":
            command.add_argument("--limit", type=int, default=50)
    backup = sub.add_parser("backup", help="只读备份计划、显式加密快照、认证校验及隔离恢复")
    backup_sub = backup.add_subparsers(dest="backup_action", required=True)
    for name in ("plan", "create", "verify", "restore"):
        command = backup_sub.add_parser(name)
        if name in ("plan", "create"):
            command.add_argument("--crawler-workspace", type=Path)
            command.add_argument("--port", type=int, default=8767)
        if name == "create":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--expected-plan", required=True)
        if name in ("verify", "restore"):
            command.add_argument("--archive", type=Path, required=True)
        if name == "restore":
            command.add_argument("--target", type=Path, required=True)
        if name != "plan":
            command.add_argument("--key-env")
    db = sub.add_parser("db", help="结构报告、迁移预检/演练及显式单库事务迁移")
    db_sub = db.add_subparsers(dest="db_action", required=True)
    for name in ("status", "plan", "preflight", "migrate"):
        command = db_sub.add_parser(name)
        if name == "migrate":
            command.add_argument("--store", choices=("mail", "control", "development", "knowledge", "legacy", "crawler"), required=True)
            command.add_argument("--expected-preflight", required=True)
            command.add_argument("--accept-authorization-change", action="store_true")
        elif name != "preflight":
            command.add_argument("--store", choices=("all", "mail", "control", "development", "knowledge", "legacy", "crawler"), default="all")
        command.add_argument("--crawler-workspace", type=Path)
        if name in ("preflight", "migrate"):
            command.add_argument("--archive", type=Path, required=True)
            command.add_argument("--expected-plan", required=True)
            command.add_argument("--port", type=int, default=8767)
            command.add_argument("--key-env")
        if name == "plan":
            command.add_argument("--rehearse", action="store_true")
            command.add_argument("--expected-plan")
    args = parser.parse_args(argv)
    try:
        if args.command == "backup" and args.backup_action in ("verify", "restore"):
            from .operations import backup
            result = backup.verify(args.archive, key_env=args.key_env) if args.backup_action == "verify" else backup.restore(args.archive, args.target, key_env=args.key_env)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
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
        if args.command == "plugins-list":
            from .plugins.registry import describe

            print(json.dumps(describe(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "plugins-check":
            from .plugins.doctor import check

            report = check(args.market)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ok"] else 2
        if args.command == "bars-fetch":
            from . import bars_fetch

            result = bars_fetch.run(args.symbols, args.start, args.end, args.output, source=args.source,
                                    timeout=args.timeout, assume_session_close=args.assume_session_close)
            for warning in result["warnings"]:
                print(f"警告：{warning}", file=sys.stderr)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        cfg = load(args.config)
        if args.command == "forecast":
            from .agent_service.forecast_archive import ForecastArchive
            archive = ForecastArchive(cfg["workspace"])
            if args.forecast_action == "register":
                result = archive.register(read_json(args.prediction), read_json(args.definition))
            elif args.forecast_action == "list":
                result = archive.listing(as_of=args.as_of, limit=args.limit, offset=args.offset)
            elif args.forecast_action == "show":
                result = archive.show(args.forecast_id, as_of=args.as_of)
            else:
                result = archive.evaluate(args.forecast_id, read_json(args.observation) if args.observation else None,
                                          as_of=args.as_of, dry_run=args.dry_run)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result.get("state") in ("not_due", "awaiting_observation") else 0
        if args.command == "db":
            from .operations import schema_planning
            if args.db_action == "migrate":
                from .operations.migration import apply
                result = apply(cfg, args.config, args.archive, args.expected_plan, args.expected_preflight, store=args.store,
                               crawler_workspace=args.crawler_workspace, port=args.port, key_env=args.key_env,
                               accept_authorization_change=args.accept_authorization_change)
            elif args.db_action == "preflight":
                from .operations.migration_preflight import check
                result = check(cfg, args.config, args.archive, args.expected_plan, crawler_workspace=args.crawler_workspace,
                               port=args.port, key_env=args.key_env)
            elif args.db_action == "status":
                result = schema_planning.report(cfg, crawler_workspace=args.crawler_workspace, store=args.store)
            else:
                result = schema_planning.plan(cfg, crawler_workspace=args.crawler_workspace, store=args.store, rehearse=args.rehearse, expected_plan=args.expected_plan)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if args.db_action == "migrate":
                return 0
            return 2 if not result["ready"] else 0 if result["mode"] in ("isolated_rehearsal", "read_only_migration_preflight") else 1 if result["changes"] else 0
        if args.command == "backup":
            from .operations import backup
            if args.backup_action == "plan":
                result = backup.plan(cfg, args.config, crawler_workspace=args.crawler_workspace, port=args.port)
            else:
                result = backup.create(cfg, args.config, args.output, args.expected_plan, crawler_workspace=args.crawler_workspace, port=args.port, key_env=args.key_env)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("ready", True) else 2
        if args.command == "runtime":
            from .operations import components, lifecycle
            root = lifecycle.selected_root(cfg, args.component, args.crawler_workspace)
            if args.runtime_action == "start":
                result = lifecycle.start(cfg, args.config, args.component, crawler_workspace=args.crawler_workspace, port=args.port, poll=args.poll)
            elif args.runtime_action == "stop":
                result = lifecycle.stop(root, args.component, args.instance, args.wait)
            elif args.runtime_action == "logs":
                result = {"events": components.logs(root, args.component, args.limit)}
            else:
                result = components.status(root, args.component)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            state = result.get("state")
            if state in ("invalid_record", "different_host", "pid_reused", "failed", "dead"):
                return 2
            return 1 if result.get("timed_out") or state in ("unknown", "stale", "clock_skew", "starting", "transition", "stopping", "instance_changed") else 0
        if args.command == "doctor":
            from .operations.diagnostics import diagnose
            result = diagnose(cfg, crawler_workspace=args.crawler_workspace, port=args.port, check_port=not args.skip_port_check)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return {"ok": 0, "warning": 1, "error": 2}[result["status"]]
        if args.command == "mail-migrate":
            from .mail_core.migration import import_archive, plan_migration
            source = args.source_workspace or cfg["workspace"]
            if args.apply:
                if not args.target_workspace or not args.expected_plan:
                    raise ServiceError("INVALID_INPUT", "apply 需要独立 target-workspace 与已审阅 expected-plan")
                result = import_archive(source, args.target_workspace, args.expected_plan, args.principal, args.limit)
                print(json.dumps({"mode": "archive_import", "result": result}, ensure_ascii=False, indent=2))
                return 0
            if args.target_workspace or args.expected_plan:
                raise ServiceError("INVALID_INPUT", "target-workspace/expected-plan 仅用于显式 apply")
            plan = plan_migration(source, args.principal, args.limit)
            print(json.dumps({"mode": "dry_run", "plan": plan}, ensure_ascii=False, indent=2))
            return 0 if plan["ready"] else 2
        if args.command == "mail-archive":
            from .mail_core.migration import list_archive
            print(json.dumps(list_archive(args.target_workspace or cfg["workspace"], args.principal, args.limit), ensure_ascii=False, indent=2))
            return 0
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
        if args.command in ("mail-history-plan", "mail-history-ack"):
            from .mail_core.history import acknowledge, review
            result = review(cfg["workspace"]) if args.command == "mail-history-plan" else acknowledge(mail, args.expected_plan, args.not_before)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command in ("mail-binding-plan", "mail-bind", "legacy-binding-plan", "legacy-bind"):
            from .core import Config
            mail.cfg = Config(cfg["workspace"], principal=args.principal)
            if args.command.startswith("legacy-"):
                from .mail_core.legacy import bind_old, binding_plan
                result = binding_plan(mail.cfg, args.message_id) if args.command.endswith("-plan") else bind_old(mail.cfg, args.message_id, args.expected_plan)
            else:
                result = mail.binding_plan(args.message_id) if args.command.endswith("-plan") else mail.bind(args.message_id, args.expected_plan)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "run":
            p = adapter(cfg["prediction"]["adapter"], {**cfg["prediction"], "role": "prediction"}).fetch()
            p = prediction(p, max_age=cfg["agent"].get("max_age_seconds", 86400))
            forecast = None
            if args.evaluation_definition is not None:
                from .agent_service.forecast_archive import ForecastArchive
                forecast = ForecastArchive(cfg["workspace"]).register(p, read_json(args.evaluation_definition))
            ctx = cfg["context"]
            c = None if ctx["adapter"] == "none" else adapter(ctx["adapter"], {
                **ctx, "role": "context", "prediction": p, "max_age_seconds": cfg["agent"].get("max_age_seconds", 86400)}).fetch()
            analysis = AnalysisAgent(cfg["agent"]).analyze(p, c, forecast_record=forecast["record"] if forecast else None)
            folder = save_report(cfg["workspace"], analysis, cfg["timezone"])
            result = mail.enqueue(analysis, args.recipient or cfg["mail"]["recipient"])
            if args.send:
                result = mail.deliver(result["id"])
            output = {"analysis_id": analysis["analysis_id"], "analysis_status": analysis["status"],
                      "report": str(folder / "report.html"), "mail": result}
            if "input_evidence" in analysis:
                output["input_snapshot"] = str(cfg["workspace"] / "input-snapshots" / (analysis["input_evidence"]["snapshot_id"] + ".json"))
            if forecast is not None:
                output["forecast"] = {"created": forecast["created"], **analysis["forecast_evidence"]}
            print(json.dumps(output, ensure_ascii=False, indent=2))
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
    except PluginError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False))
        return 2
    except FetchError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False))
        return 2
    except (OSError, sqlite3.Error):
        print(json.dumps(ServiceError("LOCAL_IO", "本地存储或锁不可用，请稍后重试", True).as_dict(), ensure_ascii=False))
        return 2
    except RuntimeError:
        print(json.dumps(ServiceError("LOCAL_IO", "另一个投递进程正在运行", True).as_dict(), ensure_ascii=False))
        return 2
