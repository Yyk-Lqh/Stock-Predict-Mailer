"""On-demand stock crawler MCP service. Startup never collects external data."""
import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.fastmcp import FastMCP

from mcp_server.paths import data_dir
from mcp_server.quality import DEFAULT_CACHE_AGE, DataQualityError, previous_quarter, snapshot_status, today
from stock_predict_mailer.cli_io import utf8_console


def _error(exc: Exception) -> str:
    missing = isinstance(exc, ModuleNotFoundError)
    return json.dumps({
        "ok": False,
        "error": {"code": exc.code if isinstance(exc, DataQualityError) else "DEPENDENCY_MISSING" if missing else "CRAWLER_FAILED",
                  "message": str(exc),
                  "hint": "uv sync --extra crawler" if missing else "检查采集日志及输入文件"},
        "details": exc.details if isinstance(exc, DataQualityError) else {},
    }, ensure_ascii=False)


def crawl_stock_catalog(force_refresh: bool = False, max_cache_age_seconds: int = DEFAULT_CACHE_AGE,
                        allow_stale: bool = False) -> str:
    """Collect catalog; expired/legacy caches require explicit allow_stale and remain marked unverified."""
    try:
        from mcp_server.catalog_crawler import crawl_catalog
        return json.dumps(crawl_catalog(force_refresh, max_cache_age_seconds, allow_stale), ensure_ascii=False)
    except Exception as exc:
        return _error(exc)


def collect_fundamental_data(max_stocks: int = 0, end_date: str | None = None,
                             allow_unverified_pool: bool = False) -> str:
    """Collect quarterly fundamentals. Zero max_stocks means all stocks (a long task)."""
    if max_stocks < 0:
        return json.dumps({"ok": False, "error": {"code": "INVALID_ARGUMENT", "message": "max_stocks must be nonnegative"}})
    try:
        from mcp_server.fundamental_crawler import collect_fundamental
        return json.dumps(collect_fundamental(max_stocks, end_date, allow_unverified_pool), ensure_ascii=False)
    except Exception as exc:
        return _error(exc)


def crawler_status() -> str:
    """Inspect paths without importing collection libraries or making network calls."""
    as_of = today()
    year, quarter = previous_quarter(as_of)
    pool = data_dir() / "stock_data117.csv"
    fundamental = data_dir() / "fundamental_quarterly_new.csv"
    return json.dumps({"default_crawl_date": as_of,
                       "date_policy": "current_date",
                       "fundamental_end_quarter": f"{year}Q{quarter}",
                       "pool_file": str(pool), "pool_exists": pool.exists(),
                       "fundamental_file": str(fundamental), "fundamental_exists": fundamental.exists(),
                       "catalog_quality": snapshot_status(pool),
                       "fundamental_quality": snapshot_status(fundamental)},
                      ensure_ascii=False)


def _job_call(method, *args):
    try:
        from mcp_server.jobs import JobStore
        return json.dumps({"ok": True, "result": getattr(JobStore(), method)(*args)}, ensure_ascii=False)
    except Exception as exc:
        return _error(exc)


def submit_crawler_job(kind: str, parameters: dict | None = None, request_key: str | None = None) -> str:
    """Queue a catalog/fundamental job; requires a separately launched worker and does not collect now."""
    return _job_call("submit", kind, parameters, request_key)


def get_crawler_job(job_id: str) -> str:
    """Read persisted job state, progress, checkpoint and result."""
    return _job_call("get", job_id)


def list_crawler_jobs(limit: int = 20) -> str:
    """List recent jobs without starting a worker or creating a database."""
    return _job_call("listing", limit)


def cancel_crawler_job(job_id: str) -> str:
    """Persist cooperative cancellation; completed files and requests cannot be undone."""
    return _job_call("cancel", job_id)


def resume_crawler_job(job_id: str) -> str:
    """Explicitly requeue a stopped/failed/partial job using its frozen plan."""
    return _job_call("resume", job_id)


def crawler_job_events(job_id: str, after: int = 0) -> str:
    """Read up to 100 ordered events; continue using the last seq as after."""
    return _job_call("events", job_id, after)


def build(port: int = 8000) -> FastMCP:
    server = FastMCP("stock-data-crawler", host="127.0.0.1", port=port, log_level="ERROR")
    for tool in (crawl_stock_catalog, collect_fundamental_data, crawler_status, submit_crawler_job,
                 get_crawler_job, list_crawler_jobs, cancel_crawler_job, resume_crawler_job, crawler_job_events):
        server.tool()(tool)
    return server


def main(argv=None):
    utf8_console()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("jobs", "worker"):
        from mcp_server.jobs_cli import main as jobs_main
        return jobs_main(argv)
    parser = argparse.ArgumentParser(description="股票采集 MCP 服务（启动不采集）", epilog="任务管理：jobs --help；独立执行：worker --help")
    parser.add_argument("--http", action="store_true", help="使用 Streamable HTTP；默认 stdio")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    build(args.port).run(transport="streamable-http" if args.http else "stdio")


if __name__ == "__main__":
    raise SystemExit(main())
