"""指数成分池采集 —— 沪深300 / 中证A500 → 股票目录 CSV

数据源：
- 沪深300：东方财富 pushguest 行情列表（bk0500 板块）
- 中证A500：东方财富 datacenter 成分报表（RPT_INDEX_TS_COMPONENT，TYPE="6"，500 只，与沪深300 重叠约 238 只）

输出列与现有 stock_data117.csv 保持同构（股票代码/股票名称/现价/最高/最低/开盘/昨收/成交量），
下游（历史爬虫、基本面爬虫）只读"股票代码"列，其余字段留空无影响。

时间口径与原有设定一致：
- 基准日 DEFAULT_CRAWL_DATE = 2026-10-23（与旧项目 mcp562/catalog_crawler.py 相同）；
- 历史日线：2009-10-23 ~ 2026-10-23（步骤2 原设定）；
- 基本面：2009Q1 ~ 2026Q3（步骤5 原设定，即基准日推导的上一个完整季度）。
注意：东财披露的是当前公示成分，无历史快照接口；若在调样窗口（6/12 月）
运行，实际成分可能与基准日口径略有出入，属数据源限制。

用法：
    python 拉取指数成分.py --mode a500                      # → stock_data_a500.csv
    python 拉取指数成分.py --mode hs300                     # → stock_data_hs300.csv
    python 拉取指数成分.py --mode merged                    # 300 ∪ A500 → stock_data117.csv
    python 拉取指数成分.py --mode merged --out-dir ..\\数据集_合并
    python 拉取指数成分.py --mode merged --base <现有池文件>  # 指定合并基线（默认 ./stock_data117.csv）

防封机制（与 步骤(1) 目录爬虫一致）：
- 默认优先复用 sessions/ 下的本地缓存，不重复请求；
- --refresh 强刷时：首页预热 + 5~10 秒随机延迟 + 最多 3 次重试（间隔 60~120 秒）；
- 翻页间隔 1.5~3 秒随机，按代码去重；
- 强刷一次后 10 分钟内勿重复强刷，否则 IP 封禁约 1 小时。
"""
import argparse
import csv
import json
import os
import random
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 数据基准日：与旧项目 mcp562/catalog_crawler.py 的 DEFAULT_CRAWL_DATE 保持一致，
# 不跟随系统时间，保证成分/历史/基本面三处时间口径统一
DEFAULT_CRAWL_DATE = "2026-10-23"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

COLUMNS = ["股票代码", "股票名称", "现价", "最高", "最低", "开盘", "昨收", "成交量"]

MAX_RETRY = 3

# 缓存目录与旧项目 sessions/ 结构保持一致，防重复请求被封
CACHE_DIR = os.path.join(os.path.dirname(BASE_DIR), "sessions")
HS300_CACHE = os.path.join(CACHE_DIR, "cache_hs300.json")
A500_CACHE = os.path.join(CACHE_DIR, "cache_a500.json")


def _load_cache(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(path, rows):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "rows": rows}, f, ensure_ascii=False, indent=1)
    print(f"[缓存] 已保存 {path}", flush=True)

# ---------- 沪深300：pushguest 行情列表（沿用步骤1的接口） ----------
HS300_URL = "https://pushguest.eastmoney.com/api/qt/clist/get"
HS300_PARAMS = {
    "timil": 1,
    "np": 1,
    "fltt": 2,
    "invt": 2,
    "fs": "b:bk0500+f:!50",
    "fields": "f12,f13,f14,f1,f2,f4,f3,f152,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f23",
    "fid": "f3",
    "pn": 1,
    "pz": 100,
    "po": 1,
    "dect": 1,
    "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    "wbp2u": "|0|0|0|web",
}

# ---------- 中证A500：datacenter 成分报表 ----------
A500_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
A500_PARAMS = {
    "sortColumns": "SECURITY_CODE",
    "sortTypes": "-1",
    "pageSize": 50,
    "pageNumber": 1,
    "reportName": "RPT_INDEX_TS_COMPONENT",
    "columns": "SECUCODE,SECURITY_CODE,TYPE,SECURITY_NAME_ABBR,CLOSE_PRICE,"
               "INDUSTRY,REGION,WEIGHT,EPS,BPS,ROE,TOTAL_SHARES,"
               "FREE_SHARES,FREE_CAP",
    "quoteColumns": "f2,f3",
    "quoteType": "0",
    "source": "WEB",
    "client": "WEB",
    "filter": '(TYPE="6")',
}


def _session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _price(v):
    return v / 100 if isinstance(v, (int, float)) else v


def fetch_hs300(refresh=False):
    """拉取沪深300行情列表，返回 [{code,name,now,high,low,open,yclose,vol}]

    默认优先复用本地缓存（防封）；refresh=True 时强制请求。
    """
    if not refresh:
        cached = _load_cache(HS300_CACHE)
        if cached:
            print(f"[沪深300] 复用缓存（{cached['saved_at']}），--refresh 可强刷",
                  flush=True)
            return cached["rows"]
    session = _session()
    for i in range(MAX_RETRY):
        try:
            try:
                session.get("https://quote.eastmoney.com/", timeout=10)
            except Exception:
                pass
            time.sleep(random.uniform(5, 10))
            params = {**HS300_PARAMS, "_": int(time.time() * 1000)}
            response = session.get(HS300_URL, params=params, timeout=30)
            data = response.json()
            if not data.get("data"):
                raise RuntimeError("返回无 data 字段")
            diff = data["data"].get("diff") or []
            if isinstance(diff, dict):
                diff = list(diff.values())
            total = data["data"].get("total", 0)
            pn = 1
            while total and len(diff) < total:
                pn += 1
                time.sleep(random.uniform(1.5, 3))
                p = {**HS300_PARAMS, "pn": pn, "_": int(time.time() * 1000)}
                d2 = session.get(HS300_URL, params=p, timeout=30).json().get("data") or {}
                part = d2.get("diff") or []
                if isinstance(part, dict):
                    part = list(part.values())
                if not part:
                    break
                diff.extend(part)
                print(f"  补第 {pn} 页 {len(part)} 条  累计 {len(diff)} / {total}", flush=True)
            uniq = {str(i["f12"]): i for i in diff}
            rows = []
            for i in uniq.values():
                rows.append({
                    "code": str(i["f12"]).zfill(6),
                    "name": i["f14"],
                    "now": _price(i["f2"]),
                    "high": _price(i["f15"]),
                    "low": _price(i["f16"]),
                    "open": _price(i["f17"]),
                    "yclose": _price(i["f18"]),
                    "vol": i["f5"],
                })
            print(f"[沪深300] 拉取 {len(rows)} 只", flush=True)
            _save_cache(HS300_CACHE, rows)
            return rows
        except Exception as e:
            print(f"[沪深300] 第 {i + 1} 次请求失败: {e}", flush=True)
            if i == MAX_RETRY - 1:
                raise
            time.sleep(random.uniform(60, 120))


def fetch_a500(refresh=False):
    """拉取中证A500成分（datacenter 报表，自动翻页），返回同样结构

    默认优先复用本地缓存（防封）；refresh=True 时强制请求。
    """
    if not refresh:
        cached = _load_cache(A500_CACHE)
        if cached:
            print(f"[中证A500] 复用缓存（{cached['saved_at']}），--refresh 可强刷",
                  flush=True)
            return cached["rows"]
    session = _session()
    for i in range(MAX_RETRY):
        try:
            time.sleep(random.uniform(2, 4))
            first = session.get(A500_URL, params={**A500_PARAMS, "pageNumber": 1},
                                timeout=30).json()
            result = first.get("result") or {}
            pages = int(result.get("pages") or 0)
            count = int(result.get("count") or 0)
            rows = list(result.get("data") or [])
            print(f"[中证A500] 第 1/{pages} 页  累计 {len(rows)} / {count}", flush=True)
            for pn in range(2, pages + 1):
                time.sleep(random.uniform(1.5, 3))
                p = {**A500_PARAMS, "pageNumber": pn}
                j = session.get(A500_URL, params=p, timeout=30).json()
                part = (j.get("result") or {}).get("data") or []
                if not part:
                    break
                rows.extend(part)
                print(f"[中证A500] 第 {pn}/{pages} 页  累计 {len(rows)} / {count}", flush=True)
            uniq = {}
            for r in rows:
                uniq[str(r["SECURITY_CODE"]).zfill(6)] = r
            out = []
            for r in uniq.values():
                out.append({
                    "code": str(r["SECURITY_CODE"]).zfill(6),
                    "name": r.get("SECURITY_NAME_ABBR", ""),
                    "now": r.get("CLOSE_PRICE"),
                    "high": "",
                    "low": "",
                    "open": "",
                    "yclose": "",
                    "vol": "",
                })
            print(f"[中证A500] 拉取 {len(out)} 只（去重后）", flush=True)
            if not out:
                raise RuntimeError("A500 返回 0 行")
            _save_cache(A500_CACHE, out)
            return out
        except Exception as e:
            print(f"[中证A500] 第 {i + 1} 次请求失败: {e}", flush=True)
            if i == MAX_RETRY - 1:
                raise
            time.sleep(random.uniform(60, 120))


def load_pool(path):
    """读现有池 CSV，返回同样结构（缺失字段留空）"""
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            code = str(r.get("股票代码", "")).strip().zfill(6)
            if not code:
                continue
            rows.append({
                "code": code,
                "name": r.get("股票名称", ""),
                "now": r.get("现价", ""),
                "high": r.get("最高", ""),
                "low": r.get("最低", ""),
                "open": r.get("开盘", ""),
                "yclose": r.get("昨收", ""),
                "vol": r.get("成交量", ""),
            })
    print(f"[基线池] {path}  读取 {len(rows)} 只", flush=True)
    return rows


def merge_pools(*pools, keep_bj=False):
    """按股票代码合并去重（先出现的优先），可选过滤北交所(4/8开头)"""
    merged = {}
    filtered_bj = 0
    for pool in pools:
        for r in pool:
            code = r["code"]
            if not keep_bj and code.startswith(("4", "8")):
                filtered_bj += 1
                continue
            if code not in merged:
                merged[code] = r
    rows = sorted(merged.values(), key=lambda r: r["code"])
    print(f"[合并] 去重后 {len(rows)} 只" +
          (f"（已过滤北交所 {filtered_bj} 条）" if filtered_bj else ""), flush=True)
    return rows


def write_pool(rows, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for r in rows:
            writer.writerow([r["code"], r["name"], r["now"], r["high"],
                             r["low"], r["open"], r["yclose"], r["vol"]])
    print(f"[完成] {len(rows)} 只 → {path}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="沪深300 / 中证A500 成分池采集")
    ap.add_argument("--mode", choices=["hs300", "a500", "merged"], required=True,
                    help="hs300=只拉沪深300；a500=只拉中证A500；merged=300∪A500")
    ap.add_argument("--out-dir", default=BASE_DIR, help="输出目录（默认脚本所在目录）")
    ap.add_argument("--out-name", default=None,
                    help="输出文件名（默认 hs300→stock_data_hs300.csv，a500→stock_data_a500.csv，merged→stock_data117.csv）")
    ap.add_argument("--base", default=None,
                    help="merged 模式的合并基线 CSV（默认 <out-dir>/stock_data117.csv，不存在则用实时沪深300）")
    ap.add_argument("--keep-bj", action="store_true", help="保留北交所代码（默认过滤 4/8 开头）")
    ap.add_argument("--refresh", action="store_true",
                    help="忽略本地缓存强制请求（10 分钟内勿重复强刷）")
    args = ap.parse_args()

    print(f"[基准日] {DEFAULT_CRAWL_DATE}（历史 2009-10-23~2026-10-23，基本面 2009Q1~2026Q3）",
          flush=True)

    out_dir = os.path.abspath(args.out_dir)
    default_names = {"hs300": "stock_data_hs300.csv",
                     "a500": "stock_data_a500.csv",
                     "merged": "stock_data117.csv"}
    out_path = os.path.join(out_dir, args.out_name or default_names[args.mode])

    if args.mode == "hs300":
        rows = fetch_hs300(refresh=args.refresh)
        rows = merge_pools(rows, keep_bj=args.keep_bj)
    elif args.mode == "a500":
        rows = fetch_a500(refresh=args.refresh)
        rows = merge_pools(rows, keep_bj=args.keep_bj)
    else:
        base_path = args.base or os.path.join(out_dir, "stock_data117.csv")
        if os.path.exists(base_path):
            base = load_pool(base_path)
        else:
            print(f"[提示] 基线 {base_path} 不存在，改用实时沪深300", flush=True)
            base = fetch_hs300(refresh=args.refresh)
        a500 = fetch_a500(refresh=args.refresh)
        rows = merge_pools(base, a500, keep_bj=args.keep_bj)
        print(f"[合并] 基线 {len(base)} 只 + A500 {len(a500)} 只 → {len(rows)} 只", flush=True)

    write_pool(rows, out_path)


if __name__ == "__main__":
    main()
