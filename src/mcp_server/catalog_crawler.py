"""目录爬虫 —— MCP 按需调用封装。

来源：数据面2/股票爬虫（收集预测目录）步骤(1).py

改动说明：
1. 顶层脚本逻辑函数化为 crawl_catalog()，按需调用；
2. 缓存与输出路径改为绝对路径（不再依赖运行目录）；
3. 默认爬取日期硬编码为 DEFAULT_CRAWL_DATE，
   数据面采集的截止季度跟随本值推导；
4. 控制台输出走 stderr，避免污染 MCP stdio 协议。

注意：完成一次强刷（force_refresh=True）后 10 分钟内勿再次强刷，
否则 IP 封禁约 1 小时。
"""
import csv
import json
import os
import random
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA2_DIR = os.path.join(BASE_DIR, '数据面2')
SESSIONS_DIR = os.path.join(BASE_DIR, 'sessions')

# 目录默认爬取日期（写在代码里）。数据面采集的截止季度跟随本值推导。
DEFAULT_CRAWL_DATE = '2026-10-23'

CACHE_FILE = os.path.join(SESSIONS_DIR, 'cache_stock_data.json')
OUTPUT_FILE = os.path.join(DATA2_DIR, 'stock_data117.csv')

URL = 'https://pushguest.eastmoney.com/api/qt/clist/get'
PARAMS = {
    'timil': 1,
    'np': 1,
    'fltt': 2,          # 2 = 返回 ×100 整数；1 = 原始浮点（那时不用 /100）
    'invt': 2,
    'fs': 'b:bk0500+f:!50',
    'fields': 'f12,f13,f14,f1,f2,f4,f3,f152,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f23',
    'fid': 'f3',                  # 按涨跌幅排序
    'pn': 1,                      # 页码
    'pz': 100,                    # 每页条数
    'po': 1,                      # 1 = 降序
    'dect': 1,
    'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
    'wbp2u': '|0|0|0|web',
    '_': int(time.time() * 1000),
}
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Referer': 'https://quote.eastmoney.com/',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
}

MAX_RETRY = 3


def _echo(msg):
    print(msg, file=sys.stderr, flush=True)


def _build_params(pn=1):
    return {**PARAMS, 'pn': pn, '_': int(time.time() * 1000)}


def _fetch_from_api():
    """请求东方财富行情列表，带重试与分页补全，成功后写缓存。"""
    session = requests.Session()
    session.headers.update(HEADERS)
    for i in range(MAX_RETRY):
        try:
            try:
                session.get('https://quote.eastmoney.com/', timeout=10)
            except Exception:
                pass
            time.sleep(random.uniform(5, 10))
            response = session.get(URL, params=_build_params(), timeout=30)
            data = response.json()
            if data.get('data'):
                diff = data['data'].get('diff') or []
                if isinstance(diff, dict):  # 只有 1 条时返回 dict
                    diff = list(diff.values())
                total = data['data'].get('total', 0)
                pn = 1
                while total and len(diff) < total:
                    pn += 1
                    time.sleep(random.uniform(1.5, 3))
                    try:
                        d2 = (session.get(URL, params=_build_params(pn),
                                          timeout=30)
                              .json().get('data') or {})
                    except Exception as e:
                        _echo(f'  补第 {pn} 页失败: {e}，'
                              f'保留已拿到的 {len(diff)} 条')
                        break
                    part = d2.get('diff') or []
                    if isinstance(part, dict):
                        part = list(part.values())
                    if not part:
                        break
                    diff.extend(part)
                    _echo(f'  补第 {pn} 页 {len(part)} 条   '
                          f'累计 {len(diff)} / {total}')
                # 按代码去重（盘中 fid=f3 排序会变，可能重复）
                data['data']['diff'] = list(
                    {str(i['f12']): i for i in diff}.values())
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            _echo(f'[缓存] 数据已保存到 {CACHE_FILE}')
            return data
        except Exception as e:
            _echo(f'第 {i + 1} 次请求失败: {e}')
            if i < MAX_RETRY - 1:
                time.sleep(random.uniform(60, 120))
    raise RuntimeError('多次重试仍失败，请稍后再运行')


def _load_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def _price(v):
    return v / 100 if isinstance(v, (int, float)) else v


def _write_csv(rows):
    os.makedirs(DATA2_DIR, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['股票代码', '股票名称', '现价', '最高', '最低',
                         '开盘', '昨收', '成交量'])
        for i in rows:
            writer.writerow([
                i['f12'], i['f14'],
                _price(i['f2']), _price(i['f15']), _price(i['f16']),
                _price(i['f17']), _price(i['f18']), i['f5'],
            ])


def crawl_catalog(force_refresh=False):
    """抓取股票行情目录并输出 stock_data117.csv（按需调用）。

    force_refresh=False 时优先复用本地缓存（防封禁）；
    force_refresh=True 时强制请求实时行情。
    """
    if force_refresh or not os.path.exists(CACHE_FILE):
        _echo('[目录爬虫] 请求东方财富实时行情...')
        data = _fetch_from_api()
        source = '实时'
    else:
        _echo(f'[目录爬虫] 读取本地缓存: {CACHE_FILE}')
        data = _load_cache()
        source = '缓存'
    rows = data['data']['diff']
    _write_csv(rows)
    _echo(f'[完成] 目录数据已保存到 {OUTPUT_FILE}（{len(rows)} 只）')
    return {
        'ok': True,
        'source': source,
        'crawl_date': DEFAULT_CRAWL_DATE,
        'stock_count': len(rows),
        'output_file': OUTPUT_FILE,
    }
