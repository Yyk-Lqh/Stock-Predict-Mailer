"""Explicit standalone worker; no collection runs in the MCP management thread."""
import json
import sys
import threading
from contextlib import redirect_stdout

from .jobs import JobControl, JobStore
from .quality import DataQualityError
from .runtime import JobStopped, using_control, using_paths, workspace_lock

_execution_lock = threading.Lock()


def execute(kind, parameters, store):
    if kind == "catalog":
        from . import catalog_crawler as collector
        with using_paths({"DATA2_DIR": store.data, "SESSIONS_DIR": store.root / "sessions",
                                   "OUTPUT_FILE": store.data / "stock_data117.csv",
                                   "CACHE_FILE": store.root / "sessions" / "cache_stock_data.json"}):
            return collector.crawl_catalog(**parameters)
    from . import fundamental_crawler as collector
    collector._req_count = collector._slow_streak = 0
    with using_paths({"DATA_DIR": store.data, "POOL_FILE": store.data / "stock_data117.csv",
                               "OUTPUT_FILE": store.data / "fundamental_quarterly_new.csv",
                               "LOG_FILE": store.data / "重采进度.log"}):
        return collector.collect_fundamental(**parameters)


def run_once(store=None, executor=None, *, stop_event=None):
    if not _execution_lock.acquire(blocking=False):
        raise DataQualityError("WORKSPACE_BUSY", "同一进程已有采集 Worker")
    try:
        return _run_once(store, executor, stop_event)
    finally:
        _execution_lock.release()


def _run_once(store=None, executor=None, stop_event=None):
    store = store or JobStore()
    if not store.path.exists():
        return None
    with workspace_lock(store.data):
        row = store.claim()
        if row is None:
            return None
        control = JobControl(store, row, stop_event)
        try:
            with using_control(control):
                control.check()
                control.progress({"stage": "starting", "attempt": row["attempts"]})
                with redirect_stdout(sys.stderr):
                    parameters = json.loads(row["parameters"])
                    result = executor(row["kind"], parameters) if executor else execute(row["kind"], parameters, store)
            if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                raise DataQualityError("INVALID_DATA", "采集器未返回明确结果")
            if result.get("stop_reason") == "cancelled":
                state = "cancelled" if store.get(row["id"])["cancel_requested"] else "interrupted"
            elif result["ok"]:
                state = "completed"
            else:
                state = "partial" if result.get("completeness") == "partial" else "failed"
            return store.finish(row["id"], row["owner"], state, result, result.get("error"))
        except JobStopped:
            return store.finish(row["id"], row["owner"], "interrupted")
        except KeyboardInterrupt:
            store.finish(row["id"], row["owner"], "interrupted")
            raise
        except Exception as exc:
            error = {"code": exc.code if isinstance(exc, DataQualityError) else
                     "DEPENDENCY_MISSING" if isinstance(exc, ModuleNotFoundError) else "CRAWLER_FAILED",
                     "message": str(exc) if isinstance(exc, DataQualityError) else type(exc).__name__}
            if isinstance(exc, ModuleNotFoundError):
                error["hint"] = "uv sync --extra crawler"
            return store.finish(row["id"], row["owner"], "failed", error=error)
