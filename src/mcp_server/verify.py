"""Offline verification using temporary synthetic data; external checks are opt-in."""
import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def verify_offline():
    from mcp_server import catalog_crawler as catalog
    from mcp_server import fundamental_crawler as fund
    from mcp_server.quality import utc_now

    with tempfile.TemporaryDirectory(prefix="crawler-verify-") as temporary:
        root = Path(temporary)
        cache, output = root / "cache.json", root / "catalog.csv"
        cache.write_text(json.dumps({"cache_version": 1, "metadata": {
            "source": "eastmoney", "source_url": catalog.URL, "source_as_of": None,
            "fetched_at": utc_now().isoformat(), "completeness": "complete", "row_count": 1, "expected_count": 1},
            "data": {"total": 1, "diff": [
            {"f12": "000001", "f14": "SYNTHETIC", "f2": 1234, "f15": 1300,
             "f16": 1100, "f17": 1200, "f18": 1190, "f5": 42}]}}), encoding="utf-8")
        with (patch.object(catalog, "CACHE_FILE", str(cache)),
              patch.object(catalog, "OUTPUT_FILE", str(output)),
              patch.object(catalog, "DATA2_DIR", str(root)),
              patch.object(catalog, "_fetch_from_api", side_effect=AssertionError("Offline verification cannot fetch"))):
            result = catalog.crawl_catalog()
        with output.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not result["ok"] or len(rows) != 1 or rows[0]["股票代码"] != "000001":
            raise RuntimeError("Synthetic catalog verification failed")
        for value, expected in (("2026-10-23", (2026, 3)), ("2026-09-30", (2026, 2)),
                                ("2026-01-10", (2025, 4))):
            if fund._derive_end_quarter(value) != expected:
                raise RuntimeError(f"Quarter derivation failed: {value}")
    return {"ok": True, "mode": "offline_synthetic", "catalog_rows": 1, "quarter_cases": 3}


def main(argv=None):
    from stock_predict_mailer.cli_io import utf8_console
    utf8_console()
    parser = argparse.ArgumentParser(description="临时合成数据验证，不改写业务资料")
    parser.add_argument("--online", action="store_true", help="额外执行一次 baostock 联网预检")
    args = parser.parse_args(argv)
    try:
        result = verify_offline()
        if args.online:
            from mcp_server import fundamental_crawler as fund
            try:
                result["online_ok"] = fund._preflight()
            finally:
                fund.bs.logout()
            if not result["online_ok"]:
                raise RuntimeError("baostock preflight failed")
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "hint": "uv sync --extra crawler"}, ensure_ascii=False))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
