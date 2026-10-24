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
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    if args.command == "init":
        with tracked_run(cfg, "init"):
            print(json.dumps({"workspace": str(cfg.workspace), "status": "initialized"}))
    elif args.command == "status":
        with connect(cfg) as con:
            print(json.dumps([dict(row) for row in con.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 20")], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
