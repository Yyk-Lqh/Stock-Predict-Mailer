"""CLI queue operations and an explicitly launched local worker."""
import argparse
import json
import math
import sqlite3

from stock_predict_mailer.agent_service.contracts import ServiceError

from .job_worker import run_once
from .jobs import JobStore
from .quality import DataQualityError


def work(store, *, once=False, poll=2, runtime_id=None):
    from stock_predict_mailer.operations.components import Component
    if not math.isfinite(poll) or not 0.1 <= poll <= 30:
        raise DataQualityError("INVALID_ARGUMENT", "poll 须为 0.1 至 30 秒")
    with Component(store.root, "crawler_worker", {"poll_seconds": poll, "once": once}, instance=runtime_id) as component:
        component.phase("idle")
        while not component.should_stop():
            try:
                component.phase("busy")
                if component.should_stop():
                    break
                result = run_once(store, stop_event=component.stopping)
            except DataQualityError as exc:
                if exc.code != "WORKSPACE_BUSY" or once:
                    raise
                result = None
            component.phase("idle")
            if result is not None and result["state"] == "interrupted":
                print(json.dumps({"ok": False, "job": result}, ensure_ascii=False))
                return 0 if component.stopping.is_set() else 130
            if once:
                print(json.dumps({"ok": True, "job": result}, ensure_ascii=False))
                return 0 if result is None or result["state"] == "completed" else 2
            if result is None:
                component.wait(poll)
        return 0


def _arguments(value):
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate argument")
            result[key] = item
        return result
    try:
        return json.loads(value, object_pairs_hook=unique)
    except (ValueError, RecursionError):
        raise DataQualityError("INVALID_ARGUMENT", "parameters 必须为有效且无重复字段的 JSON") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description="采集任务管理；提交不联网，Worker 显式启动")
    actions = parser.add_subparsers(dest="action", required=True)
    jobs = actions.add_parser("jobs")
    commands = jobs.add_subparsers(dest="command", required=True)
    submit = commands.add_parser("submit")
    submit.add_argument("--kind", choices=("catalog", "fundamental"), required=True)
    submit.add_argument("--parameters", default="{}")
    submit.add_argument("--request-key")
    listing = commands.add_parser("list")
    listing.add_argument("--limit", type=int, default=20)
    for name in ("status", "cancel", "resume", "events"):
        command = commands.add_parser(name)
        command.add_argument("job_id")
        if name == "events":
            command.add_argument("--after", type=int, default=0)
    worker = actions.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--poll", type=float, default=2)
    args = parser.parse_args(argv)
    store = JobStore()
    try:
        if args.action == "worker":
            return work(store, once=args.once, poll=args.poll)
        elif args.command == "submit":
            result = store.submit(args.kind, _arguments(args.parameters), args.request_key)
        elif args.command == "list":
            result = store.listing(args.limit)
        elif args.command == "events":
            result = store.events(args.job_id, args.after)
        else:
            result = getattr(store, {"status": "get", "cancel": "cancel", "resume": "resume"}[args.command])(args.job_id)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except DataQualityError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}}, ensure_ascii=False))
        return 2
    except ServiceError as exc:
        print(json.dumps({"ok": False, **exc.as_dict()}, ensure_ascii=False))
        return 2
    except (OSError, sqlite3.Error):
        print(json.dumps({"ok": False, "error": {"code": "LOCAL_IO", "message": "任务存储不可用"}}))
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
