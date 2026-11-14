"""一键验证脚本：验证爬虫 MCP 封装是否跑通。

用法（在项目根目录）：
  python mcp_server/verify.py            # 纯离线：用已有缓存/数据验证，不联网
  python mcp_server/verify.py --online   # 追加联网预检（baostock 登录 + 单次查询）

离线覆盖：
1. 模块导入与截止季度推导（数据面截止默认跟随目录日期，支持指定日期覆盖）
2. 目录爬虫走缓存路径 → 重写 数据面2/stock_data117.csv（同源数据，无害）
3. 数据面采集本地链路：股票池解析、旧数据读取、增量起点识别
4. MCP 服务导入与 crawler_status 状态工具
5. [--online] baostock 真实登录与预检查询（仅 1 登录 + 1 查询）
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

passed = 0
failed = 0


def check(name, cond, detail=''):
    global passed, failed
    if cond:
        passed += 1
        print(f'[PASS] {name} {detail}')
    else:
        failed += 1
        print(f'[FAIL] {name} {detail}')


args = argparse.ArgumentParser(description='爬虫 MCP 封装一键验证')
args.add_argument('--online', action='store_true',
                  help='追加联网预检（baostock 登录 + 单次查询）')
args = args.parse_args()

print('== 1. 模块导入与日期推导 ==')
from catalog_crawler import (DEFAULT_CRAWL_DATE, CACHE_FILE, OUTPUT_FILE,
                             crawl_catalog)
import fundamental_crawler as fund
from fundamental_crawler import (END_QUARTER, END_YEAR, POOL_FILE,
                                 OUTPUT_FILE as FUND_OUT)

check('目录默认爬取日期为硬编码值',
      DEFAULT_CRAWL_DATE == '2026-10-23', DEFAULT_CRAWL_DATE)
check('截止季度跟随目录日期 2026-10-23 -> 2026Q3',
      fund._derive_end_quarter('2026-10-23') == (2026, 3),
      f'实际 {END_YEAR}Q{END_QUARTER}')
check('指定截止日期覆盖 2026-09-30 -> 2026Q2',
      fund._derive_end_quarter('2026-09-30') == (2026, 2))
check('推导边界 2026-12-31 -> 2026Q3',
      fund._derive_end_quarter('2026-12-31') == (2026, 3))
check('推导跨年 2026-01-10 -> 2025Q4',
      fund._derive_end_quarter('2026-01-10') == (2025, 4))
check('缓存文件存在', os.path.exists(CACHE_FILE), CACHE_FILE)

print('== 2. 目录爬虫走缓存（不联网）==')
if os.path.exists(CACHE_FILE):
    result = crawl_catalog(force_refresh=False)
    check('目录爬取返回 ok', result.get('ok') is True,
          f"source={result.get('source')}")
    check('输出 CSV 已生成', os.path.exists(OUTPUT_FILE), OUTPUT_FILE)
    df = pd.read_csv(OUTPUT_FILE, dtype={'股票代码': str},
                     encoding='utf-8-sig')
    expect_cols = ['股票代码', '股票名称', '现价', '最高', '最低',
                   '开盘', '昨收', '成交量']
    check('CSV 列名与原格式一致', list(df.columns) == expect_cols,
          str(list(df.columns)))
    check('股票代码无空值', df['股票代码'].notna().all())
    check('行数与返回股票数一致',
          len(df) == result.get('stock_count'), f'{len(df)} 只')
    check('代码为 6 位字符串格式', df['股票代码'].str.len().eq(6).all())
else:
    check('缓存文件存在', False, '缺少缓存，无法离线验证目录爬虫')

print('== 3. 数据面采集本地链路 ==')
check('股票池文件可读（目录爬虫输出）', os.path.exists(POOL_FILE), POOL_FILE)

if os.path.exists(POOL_FILE):
    pool = pd.read_csv(POOL_FILE, usecols=['股票代码'],
                       dtype={'股票代码': str}, encoding='utf-8-sig')
    codes = sorted(pool['股票代码'].str.zfill(6).unique())
    check('股票池去重补零', len(codes) > 0, f'{len(codes)} 只，示例 {codes[:3]}')
    b_codes = [c for c in codes if c.startswith('9')]
    print(f'[INFO] 9 开头 B 股 {len(b_codes)} 只'
          f'（数据面采集会自动跳过；目录里没有也正常）')


if os.path.exists(FUND_OUT):
    rows, done, latest_q = fund._load_existing()
    check('旧数据读取正常', len(rows) > 0, f'{len(rows)} 行 / {len(done)} 只')
    check('最新报告期识别（增量起点）', latest_q is not None, str(latest_q))
else:
    print('[SKIP] 无 fundamental_quarterly_new.csv，跳过旧数据读取')

print('== 4. MCP 服务导入与状态工具（不联网）==')
from server import crawler_status

status = crawler_status()
print(status)
check('状态工具返回 JSON', status.startswith('{'))

if args.online:
    print('== 5. 联网预检（baostock，仅 1 登录 + 1 查询）==')
    try:
        ok = fund._preflight()
        check('baostock 预检通过', ok)
    except Exception as e:
        check('baostock 预检通过', False, f'{type(e).__name__}: {e}')
else:
    print('== 5. 联网预检已跳过（需要时加 --online）==')

print(f'\n结果：{passed} 通过 / {failed} 失败')
sys.exit(1 if failed else 0)
