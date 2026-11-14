"""股票数据爬虫 MCP 服务（数据面2）。

所有爬虫均为按需工具：MCP 客户端显式调用才执行，服务启动时不自动爬取。

启动方式：
  stdio 协议:  python server.py
  HTTP 常驻:   python server.py --http --port 8000
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print('mcp 库不可用：本服务基于 1.x 的 FastMCP（2.x 已改名为 MCPServer），'
          '请执行: pip install "mcp>=1.8,<2"', file=sys.stderr)
    raise

from catalog_crawler import (DEFAULT_CRAWL_DATE,  # noqa: E402
                             OUTPUT_FILE as POOL_CSV,
                             crawl_catalog)
from fundamental_crawler import (END_QUARTER,  # noqa: E402
                                 END_YEAR,
                                 OUTPUT_FILE as FUND_CSV,
                                 collect_fundamental)

mcp = FastMCP('stock-data-crawler')


@mcp.tool()
def crawl_stock_catalog(force_refresh: bool = False) -> str:
    """按需调用目录爬虫：抓取股票行情目录，输出 数据面2/stock_data117.csv。

    args:
        force_refresh: True 强制请求实时行情；False（默认）优先复用
            本地缓存，防 IP 封禁。注意强刷后 10 分钟内勿再次强刷。
    """
    try:
        return json.dumps(crawl_catalog(force_refresh), ensure_ascii=False)
    except Exception as e:
        return f'目录爬取失败 {type(e).__name__}: {e}'


@mcp.tool()
def collect_fundamental_data(max_stocks: int = 0,
                             end_date: str = None) -> str:
    """按需调用数据面采集：基于已有数据面 CSV 追加采集各股票的新数据。

    已有 数据面2/fundamental_quarterly_new.csv 自动作为基线续采：
    已完成股票只补旧文件最新报告期起的增量区间，新股票采全量，
    落盘按 (code, report_date) 去重追加。

    args:
        max_stocks: 0 = 全量；>0 = 本轮最多采集 N 只（长任务建议分批）
        end_date: 截止日期 YYYY-MM-DD；None = 默认跟随目录爬取的日期
                  （不改目录日期时保持 None 即可）
    """
    try:
        return json.dumps(collect_fundamental(max_stocks, end_date),
                          ensure_ascii=False)
    except Exception as e:
        return f'数据面采集失败 {type(e).__name__}: {e}'


@mcp.tool()
def crawler_status() -> str:
    """查看爬虫配置与数据文件状态（不发起任何网络请求）。"""
    status = {
        'default_crawl_date': DEFAULT_CRAWL_DATE,
        'fundamental_end_quarter': f'{END_YEAR}Q{END_QUARTER}',
        'pool_file': POOL_CSV,
        'pool_exists': os.path.exists(POOL_CSV),
        'fundamental_file': FUND_CSV,
        'fundamental_exists': os.path.exists(FUND_CSV),
    }
    return json.dumps(status, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description='股票数据爬虫 MCP 服务')
    parser.add_argument('--http', action='store_true',
                        help='HTTP 常驻模式（默认 stdio）')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if args.http:
        mcp.run(transport='streamable-http', host='127.0.0.1',
                port=args.port)
    else:
        mcp.run()


if __name__ == '__main__':
    main()
