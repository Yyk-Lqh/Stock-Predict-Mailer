"""On-demand catalog snapshots with explicit cache age and pagination quality."""
import csv
import io
import os
import random
import sys
import time

import requests

from .paths import data_dir, workspace
from .quality import (
    DEFAULT_CACHE_AGE,
    DataQualityError,
    atomic_json,
    cache_state,
    code_of,
    number,
    read_json,
    today,
    utc_now,
    write_snapshot,
)
from .runtime import check_cancelled, path_for, pause, progress, serialize

DATA2_DIR = str(data_dir())
SESSIONS_DIR = str(workspace() / "sessions")
CACHE_FILE = os.path.join(SESSIONS_DIR, "cache_stock_data.json")
OUTPUT_FILE = os.path.join(DATA2_DIR, "stock_data117.csv")
URL = "https://pushguest.eastmoney.com/api/qt/clist/get"
PARAMS = {"timil": 1, "np": 1, "fltt": 2, "invt": 2, "fs": "b:bk0500+f:!50",
          "fields": "f12,f13,f14,f1,f2,f4,f3,f152,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f23",
          "fid": "f3", "pn": 1, "pz": 100, "po": 1, "dect": 1,
          "ut": "fa5fd1943c7b386f172d6893dbfba10b", "wbp2u": "|0|0|0|web"}
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/", "Accept": "application/json"}
MAX_RETRY = 3
PRICE_FIELDS = ("f2", "f15", "f16", "f17", "f18")


def _path(name):
    return path_for(name, globals()[name])


def _echo(message):
    print(message, file=sys.stderr, flush=True)


def _build_params(pn=1):
    return dict(PARAMS, pn=pn, _=int(time.time() * 1000))


def _rows(raw):
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        raise DataQualityError("INVALID_DATA", "目录行必须为数组")
    result = []
    for item in raw:
        if not isinstance(item, dict) or not all(k in item for k in ("f12", "f14", "f5", *PRICE_FIELDS)):
            raise DataQualityError("INVALID_DATA", "目录字段不完整")
        row = dict(item)
        code_of(row["f12"])
        if not isinstance(row["f14"], str) or not row["f14"].strip():
            raise DataQualityError("INVALID_DATA", "股票名称缺失")
        for field in (*PRICE_FIELDS, "f5"):
            row[field] = number(row[field])
            if row[field] is not None and row[field] < 0:
                raise DataQualityError("INVALID_DATA", "价格和成交量不能为负数")
        high, low = row["f15"], row["f16"]
        if high is not None and low is not None and high < low:
            raise DataQualityError("INVALID_DATA", "最高价低于最低价")
        result.append(row)
    return result


def _page(response):
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise DataQualityError("INVALID_DATA", "来源没有返回目录数据")
    total = data.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or not 1 <= total <= 100000:
        raise DataQualityError("INVALID_DATA", "来源总数量无效")
    return total, _rows(data.get("diff"))


def _fetch_from_api():
    with requests.Session() as session:
        session.headers.update(HEADERS)
        for attempt in range(MAX_RETRY):
            check_cancelled()
            progress(stage="catalog_page", page=1)
            try:
                total, first = _page(session.get(URL, params=_build_params(), timeout=30))
                break
            except requests.RequestException:
                if attempt == MAX_RETRY - 1:
                    raise
                pause(random.uniform(60, 120))
        unique = {row["f12"]: row for row in first}
        duplicates, pages, reason = len(first) - len(unique), 1, None
        while len(unique) < total and pages < 1000:
            pause(random.uniform(1.5, 3))
            pages += 1
            check_cancelled()
            progress(stage="catalog_page", page=pages, received=len(unique), expected=total)
            try:
                count, part = _page(session.get(URL, params=_build_params(pages), timeout=30))
            except (requests.RequestException, ValueError):
                reason = "page_failed"
                break
            if count != total:
                reason = "total_changed"
                break
            before = len(unique)
            unique.update({row["f12"]: row for row in part})
            duplicates += len(part) - (len(unique) - before)
            if len(unique) == before:
                reason = "no_unique_progress"
                break
        complete = len(unique) == total and reason is None
        metadata = {"source": "eastmoney", "source_url": URL, "fetched_at": utc_now().isoformat(),
                    "source_as_of": None, "source_time_verified": False,
                    "completeness": "complete" if complete else "partial",
                    "expected_count": total, "row_count": len(unique), "pages": pages,
                    "duplicate_count": duplicates, "partial_reason": reason or (None if complete else "count_mismatch"),
                    "price_unit": "CNY", "price_transform": "legacy_divide_by_100", "volume_unit": "source_native"}
        return {"cache_version": 1, "metadata": metadata, "data": {"total": total, "diff": list(unique.values())}}


def _load_cache():
    return read_json(_path("CACHE_FILE"))


def _write_csv(rows, metadata):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["股票代码", "股票名称", "现价", "最高", "最低", "开盘", "昨收", "成交量"])
    for row in rows:
        writer.writerow([row["f12"], row["f14"],
                         *(None if row[k] is None else row[k] / 100 for k in PRICE_FIELDS), row["f5"]])
    return write_snapshot(_path("OUTPUT_FILE"), stream.getvalue().encode("utf-8-sig"), metadata)


@serialize(lambda: _path("OUTPUT_FILE"))
def crawl_catalog(force_refresh=False, max_cache_age_seconds=DEFAULT_CACHE_AGE, allow_stale=False):
    check_cancelled()
    # Validate parameters even when no cache exists.
    cache_state(None, max_cache_age_seconds)
    cached = not force_refresh and os.path.exists(_path("CACHE_FILE"))
    snapshot = _load_cache() if cached else _fetch_from_api()
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("data"), dict):
        raise DataQualityError("INVALID_DATA", "目录快照结构无效")
    version = snapshot.get("cache_version")
    if version not in (None, 1):
        raise DataQualityError("INVALID_DATA", "不支持的缓存版本")
    metadata = snapshot.get("metadata") if version == 1 else None
    if version == 1 and (not isinstance(metadata, dict) or metadata.get("source_url") != URL):
        raise DataQualityError("INVALID_DATA", "缓存来源元数据无效")
    state, age = cache_state(metadata, max_cache_age_seconds)
    if state != "fresh" and not allow_stale:
        raise DataQualityError("CACHE_STALE" if state == "stale" else "CACHE_UNVERIFIED",
                               "缓存已过期或缺少抓取时间；显式强刷或允许读取旧资料", cache_state=state)
    rows = _rows(snapshot["data"].get("diff"))
    unique = {row["f12"]: row for row in rows}
    if len(unique) != len(rows) or not rows:
        raise DataQualityError("INVALID_DATA", "快照含重复代码或没有股票")
    complete = "unknown"
    if metadata:
        complete = metadata.get("completeness")
        if (complete not in ("complete", "partial") or metadata.get("row_count") != len(rows)
                or metadata.get("expected_count") != snapshot["data"].get("total")):
            raise DataQualityError("INVALID_DATA", "缓存数量元数据不一致")
        if complete == "complete" and metadata["expected_count"] != len(rows):
            raise DataQualityError("INVALID_DATA", "完整快照存在数量缺口")
    result = {"ok": complete != "partial", "source": "缓存" if cached else "网络快照",
              "crawl_date": today(), "date_policy": "request_date", "stock_count": len(rows),
              "cache_state": state, "cache_age_seconds": age, "completeness": complete,
              "analysis_eligible": state == "fresh" and complete == "complete",
              "source_time_verified": False, "output_file": _path("OUTPUT_FILE")}
    if complete == "partial":
        return dict(result, error={"code": "PARTIAL_DATA", "message": "分页不完整，保留已有有效输出"}, metadata=metadata)
    check_cancelled()
    published = dict(metadata or {"source": "unverified_legacy_cache", "fetched_at": None,
                                  "source_as_of": None, "volume_unit": "source_native",
                                  "price_unit": "CNY", "price_transform": "legacy_divide_by_100"},
                     cache_state=state, completeness=complete, analysis_eligible=result["analysis_eligible"],
                     request_as_of=today(), source_time_verified=False)
    if not cached:
        atomic_json(_path("CACHE_FILE"), snapshot)
    result["metadata"] = _write_csv(rows, published)
    return result
