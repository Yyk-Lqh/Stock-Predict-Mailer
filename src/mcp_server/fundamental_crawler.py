"""基本面季度数据采集 —— MCP 按需调用封装。

来源：数据面2/我已无力2，要更新数据面就用这个_步骤(5).py

改动说明：
1. END_YEAR / END_QUARTER 不再各自硬编码，跟随目录爬虫（catalog_crawler）
   里硬编码的默认爬取日期 DEFAULT_CRAWL_DATE 推导
   （2026-10-23 -> 2026Q3）；
2. collect_fundamental(max_stocks, end_date) 支持不改目录日期、
   单独指定数据面截止日期（end_date 不为空时覆盖默认推导）；
3. 已有数据面 CSV 自动作为基线续采：已完成股票只补旧文件最新报告期起
   的增量区间，新股票采全量历史，落盘按 (code, report_date) 去重追加；
4. MAX_STOCKS_PER_RUN 改为 max_stocks 参数，0 = 全量；
5. 所有路径基于本文件位置绝对化解析；
6. 控制台输出走 stderr，避免污染 MCP stdio 协议。

原有防封机制全部保留：socket 超时兜底、全局限速、降速停采、
断网熔断、会话主动刷新、增量补采、断点续采。
"""
import os
import random
import socket
import sys
import time
from datetime import date

import pandas as pd

socket.setdefaulttimeout(20)

import baostock as bs
import baostock.common.context as bs_context
import baostock.common.contants as cons

cons.BAOSTOCK_SERVER_IP = '114.94.20.42'

import baostock.util.socketutil as _su

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from catalog_crawler import DEFAULT_CRAWL_DATE  # noqa: E402

QUERY_TIMEOUT = 20

_patch_calls = 0
_original_send_msg = _su.send_msg


def _echo(msg):
    print(msg, file=sys.stderr, flush=True)


def _safe_send_msg(msg):
    global _patch_calls
    _patch_calls += 1
    n = _patch_calls
    if n <= 5:
        _echo(f'  [补丁] send_msg 第 {n} 次调用 len={len(msg)}')
    t0 = time.time()
    result = _original_send_msg(msg)
    if n <= 5:
        _echo(f'  [补丁] 第 {n} 次调用返回  {time.time() - t0:.2f}s  '
              f"{'None' if result is None else f'len={len(result)}'}")
    return result


_su.send_msg = _safe_send_msg

# 路径：数据目录固定为 数据面2
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), '数据面2')

POOL_FILE = os.path.join(DATA_DIR, 'stock_data117.csv')
OUTPUT_FILE = os.path.join(DATA_DIR, 'fundamental_quarterly_new.csv')
LOG_FILE = os.path.join(DATA_DIR, '重采进度.log')

START_YEAR = 2009


def _derive_end_quarter(as_of):
    """由日期推导数据面采集截止季度。

    规则：取该日期所在季度的上一个完整季度。
    例：2026-10-23 -> 2026Q3；2026-09-30 -> 2026Q2。
    """
    d = date.fromisoformat(as_of)
    month = d.month - 3
    year = d.year
    if month <= 0:
        month += 12
        year -= 1
    return year, (month - 1) // 3 + 1


# 截止季度默认跟随目录爬取里设定的日期推导（不再各自硬编码）
END_YEAR, END_QUARTER = _derive_end_quarter(DEFAULT_CRAWL_DATE)

# 增量补采模式：设为 (年, 季) 后，已完成股票只补采该季度起的新报告期；
# None = 自动增量：从旧文件最新报告期所在季度起补采（含该季度，
# 可捕获迟发布与数据修正）。新股票仍采全量历史；
# 落盘按 (code, report_date) 去重，新报告期行接在对应股票区块末尾。
incremental_start = None
# 节奏
MAX_PER_MINUTE = 40
BATCH_SIZE = 25
BATCH_REST = 180

SLOW_SECONDS = 2.0
SLOW_STOP_COUNT = 5
PROGRESS_EVERY = 20
FAIL_STREAK_STOP = 8
SAVE_EVERY = 1

BAN_MARK = '10001011'
NET_ERROR_MARKS = ('10002007', '10002005', '10002008', 'timed out',
                   '接收数据异常', '网络', 'reconnect failed')
NO_LOGIN_CODE = '10001001'
NET_RETRY_DELAYS = (10, 30)
RECONNECT_MIN_GAP = 20
REFRESH_MINUTES = 40
REFRESH_EVERY = 10

PROBE_SYMBOL = 'sh.600000'
PROBE_YEAR, PROBE_QUARTER = 2024, 4

PROFIT_FIELDS = ['pubDate', 'roeAvg', 'npMargin', 'gpMargin', 'epsTTM',
                 'MBRevenue']
BALANCE_FIELDS = ['pubDate', 'liabilityToAsset', 'currentRatio']
GROWTH_FIELDS = ['pubDate', 'YOYNI', 'YOYPNI', 'YOYEPSBasic']
CASHFLOW_FIELDS = ['pubDate', 'CAToAsset', 'NCAToAsset']

RENAME_MAP = {
    'pubDate': 'pub_date', 'roeAvg': 'ROE', 'npMargin': 'net_margin',
    'gpMargin': 'gross_margin', 'epsTTM': 'eps_ttm',
    'MBRevenue': 'main_revenue', 'YOYNI': 'net_profit_yoy',
    'YOYPNI': 'attrib_net_profit_yoy', 'YOYEPSBasic': 'eps_yoy',
    'liabilityToAsset': 'debt_to_asset', 'currentRatio': 'current_ratio',
    'CAToAsset': 'current_asset_ratio',
    'NCAToAsset': 'non_current_asset_ratio',
}
INVERSE_MAP = {v: k for k, v in RENAME_MAP.items()}


class RateLimiter:
    def __init__(self, max_per_minute):
        self.interval = 60.0 / max_per_minute
        self.last = 0.0

    def wait(self):
        gap = self.interval - (time.time() - self.last)
        if gap > 0:
            time.sleep(gap + random.uniform(0, 0.05))
        self.last = time.time()


_limiter = RateLimiter(MAX_PER_MINUTE)
_req_count = 0
_slow_streak = 0
_last_reconnect = 0.0
_last_login_time = 0.0


def log(msg):
    _echo(msg)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(msg + '\n')


def _is_ban(text):
    low = str(text).lower()
    return BAN_MARK in low or 'black' in low or '黑名单' in low


def _is_net(text):
    low = str(text).lower()
    return any(m.lower() in low for m in NET_ERROR_MARKS)


def _login():
    global _last_login_time
    _echo('  [login] 连接中...')
    rs = bs.login()
    _echo(f'  [login] {rs.error_code} {rs.error_msg}')
    if rs.error_code != '0':
        raise RuntimeError(f'login failed {rs.error_code}: {rs.error_msg}')
    if getattr(bs_context, 'default_socket', None):
        bs_context.default_socket.settimeout(QUERY_TIMEOUT)
    _last_login_time = time.time()


def _reconnect():
    global _last_reconnect
    gap = RECONNECT_MIN_GAP - (time.time() - _last_reconnect)
    if gap > 0:
        time.sleep(gap)
    try:
        bs.logout()
    except Exception:
        pass
    time.sleep(3)
    _login()
    _last_reconnect = time.time()


def _check_speed(cost):
    global _slow_streak
    if cost > SLOW_SECONDS:
        _slow_streak += 1
        if _slow_streak >= SLOW_STOP_COUNT:
            raise RuntimeError(
                f'SLOW 连续 {SLOW_STOP_COUNT} 次请求 >{SLOW_SECONDS}s'
                f'（最近 {cost:.1f}s）')
    else:
        _slow_streak = 0


def _query(func, symbol, year, quarter, tag):
    global _req_count
    last = ''
    for delay in (0,) + NET_RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        _limiter.wait()
        t0 = time.time()
        _req_count += 1
        try:
            rs = func(symbol, year=year, quarter=quarter)
        except Exception as e:
            _check_speed(time.time() - t0)
            last = f'{type(e).__name__}: {e}'
            if _is_ban(last):
                raise RuntimeError(f'BAN {symbol} {last}')
            if _is_net(last):
                _reconnect()
            continue
        cost = time.time() - t0
        _check_speed(cost)
        if rs.error_code == '0':
            if _req_count % PROGRESS_EVERY == 0:
                _echo(f'      {tag} 第 {_req_count} 次请求  {cost:.2f}s')
            out = {}
            while rs.next():
                row = dict(zip(rs.fields, rs.get_row_data()))
                out[row['statDate']] = row
            return out
        last = f'{rs.error_code}: {rs.error_msg}'
        if _is_ban(last):
            raise RuntimeError(f'BAN {symbol} {last}')
        if _is_net(last) or rs.error_code == NO_LOGIN_CODE:
            _reconnect()
        else:
            return {}
    raise RuntimeError(f'NET {symbol} {year}Q{quarter} {last}')


def _symbol_of(code):
    if code.startswith(('6', '9')):
        return f'sh.{code}'
    if code.startswith(('4', '8')):
        return f'bj.{code}'
    return f'sz.{code}'


def _fetch_stock(code, quarters=None, end_year=None, end_quarter=None):
    symbol = _symbol_of(code)
    rows = []
    if quarters is None:
        ey = end_year if end_year is not None else END_YEAR
        eq = end_quarter if end_quarter is not None else END_QUARTER
        quarters = [(y, q) for y in range(START_YEAR, ey + 1)
                    for q in range(1, 5)
                    if not (y == ey and q > eq)]
    for year, quarter in quarters:
        profit = _query(bs.query_profit_data, symbol, year, quarter,
                        f'{symbol} {year}Q{quarter}')
        balance = _query(bs.query_balance_data, symbol, year, quarter,
                         f'{symbol} {year}Q{quarter}')
        growth = _query(bs.query_growth_data, symbol, year, quarter,
                        f'{symbol} {year}Q{quarter}')
        cashflow = _query(bs.query_cash_flow_data, symbol, year, quarter,
                          f'{symbol} {year}Q{quarter}')
        report_dates = set(profit) | set(balance) | set(growth) | set(cashflow)
        for rd in sorted(report_dates):
            row = {'code': code, 'report_date': rd}
            pubs = []
            for table, fields in ((profit, PROFIT_FIELDS),
                                  (balance, BALANCE_FIELDS),
                                  (growth, GROWTH_FIELDS),
                                  (cashflow, CASHFLOW_FIELDS)):
                tr = table.get(rd, {})
                for field in fields:
                    if field == 'pubDate':
                        v = tr.get('pubDate', '')
                        if v:
                            pubs.append(v)
                    else:
                        row[field] = tr.get(field, '')
            row['pubDate'] = max(pubs) if pubs else ''
            rows.append(row)
    return rows


def _load_existing():
    if not os.path.exists(OUTPUT_FILE):
        return [], set(), None
    try:
        df = pd.read_csv(OUTPUT_FILE, dtype={'code': str},
                         encoding='utf-8-sig')
        df = df.rename(columns=INVERSE_MAP)
        latest_q = None
        if 'report_date' in df.columns:
            rd = pd.to_datetime(df['report_date'], errors='coerce').dropna()
            if not rd.empty:
                latest_q = rd.max().to_period('Q')
        log(f"续采：已有 {len(df)} 行 / {df['code'].nunique()} 只，"
            f"最新报告期 {latest_q if latest_q is not None else '无'}")
        return df.to_dict('records'), set(df['code'].unique()), latest_q
    except Exception as e:
        log(f'读旧文件失败 {type(e).__name__}: {e}，从头开始')
        return [], set(), None


def _save(rows):
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if not df.empty:
        if 'code' in df.columns and 'report_date' in df.columns:
            df = df.drop_duplicates(subset=['code', 'report_date'],
                                    keep='last')
            df = df.sort_values(['code', 'report_date'],
                                kind='stable').reset_index(drop=True)
        df.to_csv(OUTPUT_FILE, encoding='utf-8-sig', index=False)


def _preflight():
    try:
        _login()
    except Exception as e:
        log(f'预检失败：{e}')
        return False
    try:
        rs = bs.query_profit_data(PROBE_SYMBOL, year=PROBE_YEAR,
                                  quarter=PROBE_QUARTER)
        if rs.error_code != '0':
            log(f'预检查询异常：{rs.error_code} {rs.error_msg}')
            return False
        n = 0
        while rs.next():
            rs.get_row_data()
            n += 1
        log(f'预检通过（{PROBE_SYMBOL} {PROBE_YEAR}Q{PROBE_QUARTER}，{n} 行）')
        return n > 0
    except Exception as e:
        log(f'预检异常：{type(e).__name__}: {e}')
        return False


def _summary(ok, stock_pool, done_codes, all_rows, msg='',
             stop_reason=None, failed=None, extra=None,
             end_quarter_label=None):
    summary = {
        'ok': ok,
        'message': msg,
        'crawl_date': DEFAULT_CRAWL_DATE,
        'end_quarter': end_quarter_label or f'{END_YEAR}Q{END_QUARTER}',
        'pool_size': len(stock_pool),
        'done_total': len(done_codes),
        'rows': len(all_rows),
        'stop_reason': stop_reason,
        'failed': sorted(set(failed)) if failed else [],
        'output_file': OUTPUT_FILE,
    }
    if extra:
        summary.update(extra)
    return summary


def collect_fundamental(max_stocks=0, end_date=None):
    """按需采集基本面季度数据（股票池来自目录爬虫输出）。

    已有数据面 CSV 自动作为基线续采：已完成股票只补旧文件最新
    报告期起的增量区间，新股票采全量历史，落盘按
    (code, report_date) 去重追加。

    max_stocks: 0 = 全量；>0 = 本轮最多采集 N 只（长任务建议分批）。
    end_date: 截止日期 'YYYY-MM-DD'；None = 默认跟随目录爬取的日期
              DEFAULT_CRAWL_DATE（不改目录日期时保持 None）。
    """
    if end_date:
        end_year, end_quarter = _derive_end_quarter(end_date)
    else:
        end_year, end_quarter = END_YEAR, END_QUARTER

    pool_df = pd.read_csv(POOL_FILE, usecols=['股票代码'],
                          dtype={'股票代码': str}, encoding='utf-8-sig')
    stock_pool = sorted(pool_df['股票代码'].str.zfill(6).unique())

    all_rows, done_codes, latest_q = _load_existing()

    def _result(ok, msg='', stop_reason=None, failed=None, extra=None):
        return _summary(ok, stock_pool, done_codes, all_rows, msg=msg,
                        stop_reason=stop_reason, failed=failed, extra=extra,
                        end_quarter_label=f'{end_year}Q{end_quarter}')

    inc_start = incremental_start
    if inc_start is None and latest_q is not None:
        inc_start = (latest_q.year, latest_q.quarter)
        log(f'自动增量：旧文件最新报告期 {latest_q}，'
            f'从 {inc_start[0]}Q{inc_start[1]} 起补采')

    if inc_start:
        y0, q0 = inc_start
        inc_quarters = [(y, q) for y in range(y0, end_year + 1)
                        for q in range(1, 5)
                        if not (y == end_year and q > end_quarter)
                        and not (y == y0 and q < q0)]
        if not inc_quarters:
            log(f'增量起点 {y0}Q{q0} 已在采集范围 '
                f'{end_year}Q{end_quarter} 之外，无需补采')
            return _result(True, msg='增量起点已在截止季度之外，无需补采')
        todo = [c for c in stock_pool if not c.startswith('9')]
        est_q = len(inc_quarters)
    else:
        inc_quarters = None
        todo = [c for c in stock_pool
                if c not in done_codes and not c.startswith('9')]
        est_q = 71
    if max_stocks:
        todo = todo[:max_stocks]

    est_min = len(todo) * est_q * 4 / MAX_PER_MINUTE
    log('=' * 62)
    if end_date:
        log(f'截止季度 {end_year}Q{end_quarter}'
            f'（由指定日期 {end_date} 推导）')
    else:
        log(f'截止季度 {end_year}Q{end_quarter}'
            f'（跟随目录爬取日期 {DEFAULT_CRAWL_DATE}）')
    log(f'股票池 {len(stock_pool)} | 已完成 {len(done_codes)}'
        f' | 本轮 {len(todo)}')
    if inc_start:
        log(f'增量补采：{inc_start[0]}Q{inc_start[1]} 起  ~  '
            f'{end_year}Q{end_quarter}')
    log(f'限速 每分钟 {MAX_PER_MINUTE} 次  →  预计 {est_min / 60:.1f} 小时')
    log('=' * 62)

    if not todo:
        log('全部采完')
        return _result(True, msg='全部采完')

    if not _preflight():
        return _result(False, msg='预检失败，请用 测试Iip解封.py 探测 IP 状态')

    batches = [todo[i:i + BATCH_SIZE]
               for i in range(0, len(todo), BATCH_SIZE)]
    failed, start_count, stop_reason = [], len(done_codes), None
    fail_streak = 0
    saved_rows_len = len(all_rows)

    try:
        for b_idx, batch in enumerate(batches, 1):
            for code in batch:
                age = time.time() - _last_login_time
                n_done = len(done_codes) - start_count
                if age >= REFRESH_MINUTES * 60 or (
                        n_done > 0 and n_done % REFRESH_EVERY == 0):
                    log(f'  主动刷新会话（会话 {age / 60:.0f} 分钟 / '
                        f'本轮 {n_done} 只）')
                    try:
                        _reconnect()
                    except Exception as e:
                        log(f'  刷新会话失败 {type(e).__name__}: {e}，继续采')
                try:
                    if inc_quarters and code in done_codes:
                        rows = _fetch_stock(code, inc_quarters)
                    else:
                        rows = _fetch_stock(code, end_year=end_year,
                                            end_quarter=end_quarter)
                    if not rows:
                        if inc_quarters and code in done_codes:
                            log(f'  ~ {code} 增量区间暂无新报告期，跳过')
                            continue
                        raise RuntimeError('EMPTY 无报告期')
                except Exception as e:
                    text = str(e)
                    failed.append(code)
                    if _is_ban(text):
                        stop_reason = 'banned'
                        log(f'  {code} 命中黑名单')
                        break
                    if 'SLOW' in text:
                        stop_reason = 'slow'
                        log(f'  {code} {text[:80]}')
                        break
                    if text.startswith('NET'):
                        fail_streak += 1
                        if fail_streak >= FAIL_STREAK_STOP:
                            stop_reason = 'net_streak'
                            log(f'  {code} 连续 {FAIL_STREAK_STOP} 只 '
                                f'NET 失败，疑似断网，停止')
                            break
                    log(f'  {code} 失败 {text[:80]}')
                    continue

                fail_streak = 0
                all_rows.extend(rows)
                done_codes.add(code)
                if (len(done_codes) - start_count) % SAVE_EVERY == 0:
                    _save(all_rows)
                    saved_rows_len = len(all_rows)
                log(f'  + {code}  {len(rows)} 期  '
                    f'[{len(done_codes) - start_count}/{len(todo)}]  '
                    f'累计 {len(all_rows)} 行')

            log(f'第 {b_idx}/{len(batches)} 批结束  '
                f'累计 {len(done_codes)}/{len(stock_pool)}')
            if len(all_rows) > saved_rows_len:
                _save(all_rows)
                saved_rows_len = len(all_rows)

            if stop_reason == 'banned':
                log('\n>>> 黑名单，停 12~24 小时')
                break
            if stop_reason == 'slow':
                log(f'\n>>> 服务端降速（连续 {SLOW_STOP_COUNT} 次 '
                    f'>{SLOW_SECONDS}s），已停止')
                log('>>> 停 4 小时后再跑')
                break
            if stop_reason == 'net_streak':
                log('\n>>> 连续网络失败，已停止；用 测试Iip解封.py 探测后重跑')
                break
            if max_stocks and (len(done_codes) - start_count) >= max_stocks:
                log(f'\n>>> 已达上限 {max_stocks} 只，正常退出')
                break
            if b_idx < len(batches):
                log(f'  休息 {BATCH_REST} 秒...')
                time.sleep(BATCH_REST)
    except KeyboardInterrupt:
        log('\n手动中断，已采数据已落盘')
    finally:
        try:
            if len(all_rows) > saved_rows_len:
                _save(all_rows)
        except Exception as e:
            log(f'兜底保存失败 {type(e).__name__}: {e}')
        try:
            bs.logout()
        except Exception:
            pass
        if failed:
            path = os.path.join(DATA_DIR, '重采失败列表.txt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(sorted(set(failed))))
            log(f'\n失败 {len(set(failed))} 只 -> {path}')

    if not all_rows:
        log('未采集到任何数据，请先用 测试Iip解封.py 探测 IP 状态')
        return _result(False, msg='未采集到任何数据',
                       stop_reason=stop_reason, failed=failed)

    result = pd.DataFrame(all_rows).rename(columns=RENAME_MAP)
    for c in list(RENAME_MAP.values())[1:]:
        result[c] = pd.to_numeric(result[c], errors='coerce')
    _save(result)

    log(f"\n本轮结束：{len(result)} 行 / {result['code'].nunique()} 只")
    log(f'总请求 {_req_count} 次')
    return _result(True, msg='采集完成', stop_reason=stop_reason,
                   failed=failed,
                   extra={'this_run': len(done_codes) - start_count,
                          'requests': _req_count})
