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
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    if args.command == "init":
        with tracked_run(cfg, "init"):
            print(json.dumps({"workspace": str(cfg.workspace), "status": "initialized"}))
    elif args.command == "status":
        with connect(cfg) as con:
            print(json.dumps([dict(row) for row in con.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 20")], indent=2))
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
