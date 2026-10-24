from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .core import connect, load_config, tracked_run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local stock research; synthetic demo is not investment evidence")
    parser.add_argument("--config", type=Path, default=Path("config/example.toml"))
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Initialize local metadata")
    sub.add_parser("status", help="Show recent runs")
    demo = sub.add_parser("demo-data", help="Generate SYNTHETIC bars; weekdays are not an exchange calendar")
    demo.add_argument("--days", type=int, default=900)
    demo.add_argument("--stocks", type=int, default=16)
    ingest = sub.add_parser("import-csv", help="Import licensed daily bars from CSV")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--synthetic", action="store_true")
    summary = sub.add_parser("snapshot", help="Validate and summarize an immutable snapshot")
    summary.add_argument("snapshot_id")
    research = sub.add_parser("research", help="Run SYNTHETIC-only purged research")
    research.add_argument("snapshot_id")
    research.add_argument("--cutoff", required=True)
    research.add_argument("--trees", action="store_true", help="Require optional LightGBM installation")
    kb_add = sub.add_parser("kb-add", help="Index local Markdown or text with explicit ACL")
    kb_add.add_argument("path", type=Path)
    kb_add.add_argument("--published-at", required=True)
    kb_add.add_argument("--available-at", required=True)
    kb_add.add_argument("--allow", action="append", required=True)
    kb_search = sub.add_parser("kb-search", help="Search authorized, time-filtered local evidence")
    kb_search.add_argument("query")
    kb_search.add_argument("--cutoff", required=True)
    kb_revoke = sub.add_parser("kb-revoke", help="Revoke a document version")
    kb_revoke.add_argument("document_id")
    report = sub.add_parser("report", help="Build escaped deterministic HTML with evidence")
    report.add_argument("experiment_id")
    report.add_argument("--query", default="风险 策略 模型")
    pipeline = sub.add_parser("demo-run", help="Offline synthetic end-to-end pipeline; never sends mail")
    pipeline.add_argument("--cutoff", required=True)
    pipeline.add_argument("--recipient", default="preview@example.invalid")
    pipeline.add_argument("--trees", action="store_true")
    queue = sub.add_parser("queue-mail", help="Create local .eml preview, not delivery")
    queue.add_argument("report_id")
    queue.add_argument("--recipient", required=True)
    queue.add_argument("--sender", default="research@example.invalid")
    sub.add_parser("outbox", help="List local mail status")
    send = sub.add_parser("send-mail", help="Explicitly deliver ONE queued message using SMTP environment")
    send.add_argument("outbox_id")
    send.add_argument("--allow-synthetic", action="store_true")
    send.add_argument("--allow-stale", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    if args.command == "init":
        with tracked_run(cfg, "init"):
            print(json.dumps({"workspace": str(cfg.workspace), "status": "initialized"}))
    elif args.command == "status":
        with connect(cfg) as con:
            print(json.dumps([dict(row) for row in con.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 20")], indent=2))
    elif args.command in ("demo-run", "queue-mail", "outbox", "send-mail"):
        from .delivery import deliver, enqueue, outbox
        from .pipeline import demo_run
        if args.command == "demo-run":
            result = demo_run(cfg, args.cutoff, args.recipient, args.trees)
        elif args.command == "queue-mail":
            result = enqueue(cfg, args.report_id, args.recipient, args.sender)
        elif args.command == "outbox":
            result = outbox(cfg)
        else:
            result = {"status": deliver(cfg, args.outbox_id, allow_synthetic=args.allow_synthetic, allow_stale=args.allow_stale)}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "submitted" else 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command in ("kb-add", "kb-search", "kb-revoke", "report"):
        from .knowledge import ingest_document, retrieve, revoke
        from .report import build_report
        with tracked_run(cfg, args.command):
            if args.command == "kb-add":
                result = ingest_document(cfg, args.path, args.published_at, args.available_at, args.allow)
            elif args.command == "kb-search":
                result = retrieve(cfg, args.query, args.cutoff)
            elif args.command == "kb-revoke":
                revoke(cfg, args.document_id)
                result = {"revoked": args.document_id}
            else:
                built = build_report(cfg, args.experiment_id, args.query)
                result = {"report_id": built["report_id"], "path": str(cfg.workspace / "reports" / built["report_id"] / "report.html")}
            print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "research":
        from .research import experiment
        with tracked_run(cfg, "research"):
            result = experiment(cfg, args.snapshot_id, args.cutoff, trees=args.trees)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        from .data import demo_csv, import_csv, snapshot_summary

        with tracked_run(cfg, args.command):
            if args.command == "demo-data":
                path = demo_csv(cfg.workspace / "demo.csv", args.days, args.stocks)
                result = import_csv(cfg, path, synthetic=True)
            elif args.command == "import-csv":
                result = import_csv(cfg, args.path, synthetic=args.synthetic)
            else:
                result = snapshot_summary(cfg, args.snapshot_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
