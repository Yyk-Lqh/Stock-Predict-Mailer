"""Internal fixed-component launcher; stdout/stderr are never captured as logs."""
import argparse
from pathlib import Path

from ..agent_service.config import load
from ..cli_io import utf8_console
from .components import COMPONENTS


def main(argv=None):
    utf8_console()
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--component", choices=COMPONENTS, required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--poll", type=float, required=True)
    args = parser.parse_args(argv)
    try:
        cfg = load(args.config)
        if cfg["workspace"].resolve() != args.workspace.resolve():
            return 2
        if args.component != "crawler_worker" and args.root.resolve() != cfg["workspace"].resolve():
            return 2
        if args.component == "console":
            from ..control.server import serve
            serve(args.root, args.port, runtime_id=args.instance)
            return 0
        if args.component == "knowledge_worker":
            from ..private_knowledge.worker import run
            return run(args.root, poll=args.poll, runtime_id=args.instance)
        from mcp_server.jobs import JobStore
        from mcp_server.jobs_cli import work
        return work(JobStore(args.root), poll=args.poll, runtime_id=args.instance)
    except Exception:
        # Component contexts log a fixed failed event; never persist raw exceptions.
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
