"""
基本面季度数据采集 V2 —— 增量补采版（防断联加固 v2 + 增量模式）

核心设计：
1. socket 超时兜底：绝不死循环、绝不无限阻塞（20 秒必返回）
2. 全局限速：每分钟最多 40 次请求
3. 连续 5 次请求超过 2 秒 → 判定降速，立即停止（含超时路径）
4. 每 20 次请求打印进度
5. 每只股票落盘一次，批结束与中断时兜底落盘，中断可续
6. 跳过 DNS 解析，直连服务器 IP
7. 连续 8 只股票网络失败 → 判定断网/半死，立即停止
8. 防断联双保险：会话满 40 分钟或每 10 只主动重连；未登录错误自动重连重试
9. 增量补采：设置 增量起点 后，已完成股票只补采该季度起的新报告期；
   新股票仍采全量历史；落盘按 (code, report_date) 去重
"""
import os
import time
import random
import socket

import pandas as pd

socket.setdefaulttimeout(20)

import baostock as bs
import baostock.common.context as bs_context
import baostock.common.contants as cons

cons.BAOSTOCK_SERVER_IP = '114.94.20.42'

import baostock.util.socketutil as _su

QUERY_TIMEOUT = 20

_patch_calls = 0

_original_send_msg = _su.send_msg


def _safe_send_msg(msg):
    global _patch_calls
    _patch_calls += 1
    n = _patch_calls
    if n <= 5:
        print(f"  [补丁] send_msg 第 {n} 次调用 len={len(msg)}", flush=True)
    t0 = time.time()
    result = _original_send_msg(msg)
    if n <= 5:
        print(f"  [补丁] 第 {n} 次调用返回  {time.time() - t0:.2f}s  "
              f"{'None' if result is None else f'len={len(result)}'}", flush=True)
    return result


_su.send_msg = _safe_send_msg
print(f"[自检] 补丁已挂载：{_su.send_msg.__name__}", flush=True)

# 路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = SCRIPT_DIR

POOL_FILE = os.path.join(DATA_DIR, 'stock_data117.csv')
OUTPUT_FILE = os.path.join(DATA_DIR, 'fundamental_quarterly_new.csv')
LOG_FILE = os.path.join(SCRIPT_DIR, '重采进度.log')

START_YEAR = 2009
END_YEAR = 2026
END_QUARTER = 3

# 增量补采模式：设为 (年, 季) 后，已完成股票只补采该季度起的新报告期，
# 新股票仍采全量历史。例：2028 年补 2027 数据 → END_YEAR=2027, END_QUARTER=4,
# 增量起点 = (2026, 4)；None = 老行为（新股票全量，老股票跳过）
incremental_start = None
# 节奏
MAX_PER_MINUTE = 40
MAX_STOCKS_PER_RUN = 0
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


PROFIT_FIELDS = ['pubDate', 'roeAvg', 'npMargin', 'gpMargin', 'epsTTM', 'MBRevenue']
BALANCE_FIELDS = ['pubDate', 'liabilityToAsset', 'currentRatio']
GROWTH_FIELDS = ['pubDate', 'YOYNI', 'YOYPNI', 'YOYEPSBasic']
CASHFLOW_FIELDS = ['pubDate', 'CAToAsset', 'NCAToAsset']

RENAME_MAP = {
    'pubDate': 'pub_date', 'roeAvg': 'ROE', 'npMargin': 'net_margin',
    'gpMargin': 'gross_margin', 'epsTTM': 'eps_ttm', 'MBRevenue': 'main_revenue',
    'YOYNI': 'net_profit_yoy', 'YOYPNI': 'attrib_net_profit_yoy',
    'YOYEPSBasic': 'eps_yoy', 'liabilityToAsset': 'debt_to_asset',
    'currentRatio': 'current_ratio', 'CAToAsset': 'current_asset_ratio',
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
    print(msg, flush=True)
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
    print("  [login] 连接中...", flush=True)
    rs = bs.login()
    print(f"  [login] {rs.error_code} {rs.error_msg}", flush=True)
    if rs.error_code != '0':
        raise RuntimeError(f"login failed {rs.error_code}: {rs.error_msg}")
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
                f'SLOW 连续 {SLOW_STOP_COUNT} 次请求 >{SLOW_SECONDS}s（最近 {cost:.1f}s）')
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
                print(f"      {tag} 第 {_req_count} 次请求  {cost:.2f}s", flush=True)
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


def _fetch_stock(code, quarters=None):
    symbol = _symbol_of(code)
    rows = []
    if quarters is None:
        quarters = [(y, q) for y in range(START_YEAR, END_YEAR + 1)
                    for q in range(1, 5) if not (y == END_YEAR and q > END_QUARTER)]
    for year, quarter in quarters:
        profit = _query(bs.query_profit_data, symbol, year, quarter, f'{symbol} {year}Q{quarter}')
        balance = _query(bs.query_balance_data, symbol, year, quarter, f'{symbol} {year}Q{quarter}')
        growth = _query(bs.query_growth_data, symbol, year, quarter, f'{symbol} {year}Q{quarter}')
        cashflow = _query(bs.query_cash_flow_data, symbol, year, quarter, f'{symbol} {year}Q{quarter}')
        report_dates = set(profit) | set(balance) | set(growth) | set(cashflow)
        for rd in sorted(report_dates):
            row = {'code': code, 'report_date': rd}
            pubs = []
            for table, fields in ((profit, PROFIT_FIELDS), (balance, BALANCE_FIELDS),
                                  (growth, GROWTH_FIELDS), (cashflow, CASHFLOW_FIELDS)):
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
        return [], set()
    try:
        df = pd.read_csv(OUTPUT_FILE, dtype={'code': str}, encoding='utf-8-sig')
        df = df.rename(columns=INVERSE_MAP)
        log(f"续采：已有 {len(df)} 行 / {df['code'].nunique()} 只")
        return df.to_dict('records'), set(df['code'].unique())
    except Exception as e:
        log(f"读旧文件失败 {type(e).__name__}: {e}，从头开始")
        return [], set()


def _save(rows):
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if not df.empty:
        if 'code' in df.columns and 'report_date' in df.columns:
            df = df.drop_duplicates(subset=['code', 'report_date'], keep='last')
        df.to_csv(OUTPUT_FILE, encoding='utf-8-sig', index=False)


def _preflight():
    try:
        _login()
    except Exception as e:
        log(f"预检失败：{e}")
        return False
    try:
        rs = bs.query_profit_data(PROBE_SYMBOL, year=PROBE_YEAR, quarter=PROBE_QUARTER)
        if rs.error_code != '0':
            log(f"预检查询异常：{rs.error_code} {rs.error_msg}")
            return False
        n = 0
        while rs.next():
            rs.get_row_data()
            n += 1
        log(f"预检通过（{PROBE_SYMBOL} {PROBE_YEAR}Q{PROBE_QUARTER}，{n} 行）")
        return n > 0
    except Exception as e:
        log(f"预检异常：{type(e).__name__}: {e}")
        return False


def main():
    pool_df = pd.read_csv(POOL_FILE, usecols=['股票代码'],
                          dtype={'股票代码': str}, encoding='utf-8-sig')
    stock_pool = sorted(pool_df['股票代码'].str.zfill(6).unique())

    all_rows, done_codes = _load_existing()
    if incremental_start:
        # 增量模式：所有股票都参与，已完成股票只补新季度
        todo = [c for c in stock_pool if not c.startswith('9')]
        est_q = (END_YEAR - incremental_start[0] + 1) * 4
    else:
        todo = [c for c in stock_pool if c not in done_codes and not c.startswith('9')]
        est_q = 71
    if MAX_STOCKS_PER_RUN:
        todo = todo[:MAX_STOCKS_PER_RUN]

    est_min = len(todo) * est_q * 4 / MAX_PER_MINUTE
    log("=" * 62)
    log(f"股票池 {len(stock_pool)} | 已完成 {len(done_codes)} | 本轮 {len(todo)}")
    if incremental_start:
        log(f"增量补采：{incremental_start[0]}Q{incremental_start[1]} 起  ~  {END_YEAR}Q{END_QUARTER}")
    log(f"限速 每分钟 {MAX_PER_MINUTE} 次  →  预计 {est_min / 60:.1f} 小时")
    log("=" * 62)

    if not todo:
        log("全部采完")
        return

    if not _preflight():
        return

    batches = [todo[i:i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
    failed, start_count, stop_reason = [], len(done_codes), None
    fail_streak = 0
    saved_rows_len = len(all_rows)

    try:
        for b_idx, batch in enumerate(batches, 1):
            for code in batch:
                age = time.time() - _last_login_time
                n_done = len(done_codes) - start_count
                if age >= REFRESH_MINUTES * 60 or (n_done > 0 and n_done % REFRESH_EVERY == 0):
                    log(f"  主动刷新会话（会话 {age / 60:.0f} 分钟 / 本轮 {n_done} 只）")
                    try:
                        _reconnect()
                    except Exception as e:
                        log(f"  刷新会话失败 {type(e).__name__}: {e}，继续采")
                try:
                    if incremental_start and code in done_codes:
                        y0, q0 = incremental_start
                        quarters = [(y, q) for y in range(y0, END_YEAR + 1)
                                    for q in range(1, 5)
                                    if not (y == END_YEAR and q > END_QUARTER)
                                    and not (y == y0 and q < q0)]
                        rows = _fetch_stock(code, quarters)
                    else:
                        rows = _fetch_stock(code)
                    if not rows:
                        if incremental_start and code in done_codes:
                            log(f"  ~ {code} 增量区间暂无新报告期，跳过")
                            continue
                        raise RuntimeError('EMPTY 无报告期')
                except Exception as e:
                    text = str(e)
                    failed.append(code)
                    if _is_ban(text):
                        stop_reason = 'banned'
                        log(f"  {code} 命中黑名单")
                        break
                    if 'SLOW' in text:
                        stop_reason = 'slow'
                        log(f"  {code} {text[:80]}")
                        break
                    if text.startswith('NET'):
                        fail_streak += 1
                        if fail_streak >= FAIL_STREAK_STOP:
                            stop_reason = 'net_streak'
                            log(f"  {code} 连续 {FAIL_STREAK_STOP} 只 NET 失败，疑似断网，停止")
                            break
                    log(f"  {code} 失败 {text[:80]}")
                    continue

                fail_streak = 0
                all_rows.extend(rows)
                done_codes.add(code)
                if (len(done_codes) - start_count) % SAVE_EVERY == 0:
                    _save(all_rows)
                    saved_rows_len = len(all_rows)
                log(f"  + {code}  {len(rows)} 期  "
                    f"[{len(done_codes) - start_count}/{len(todo)}]  累计 {len(all_rows)} 行")

            log(f"第 {b_idx}/{len(batches)} 批结束  累计 {len(done_codes)}/{len(stock_pool)}")
            if len(all_rows) > saved_rows_len:
                _save(all_rows)
                saved_rows_len = len(all_rows)

            if stop_reason == 'banned':
                log("\n>>> 黑名单，停 12~24 小时")
                break
            if stop_reason == 'slow':
                log(f"\n>>> 服务端降速（连续 {SLOW_STOP_COUNT} 次 >{SLOW_SECONDS}s），已停止")
                log(">>> 停 4 小时后再跑")
                break
            if stop_reason == 'net_streak':
                log("\n>>> 连续网络失败，已停止；用 测试Iip解封.py 探测后重跑")
                break
            if MAX_STOCKS_PER_RUN and (len(done_codes) - start_count) >= MAX_STOCKS_PER_RUN:
                log(f"\n>>> 已达上限 {MAX_STOCKS_PER_RUN} 只，正常退出")
                break
            if b_idx < len(batches):
                log(f"  休息 {BATCH_REST} 秒...")
                time.sleep(BATCH_REST)
    except KeyboardInterrupt:
        log("\n手动中断，已采数据已落盘")
    finally:
        try:
            if len(all_rows) > saved_rows_len:
                _save(all_rows)
        except Exception as e:
            log(f"兜底保存失败 {type(e).__name__}: {e}")
        try:
            bs.logout()
        except Exception:
            pass
        if failed:
            path = os.path.join(SCRIPT_DIR, '重采失败列表.txt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(sorted(set(failed))))
            log(f"\n失败 {len(set(failed))} 只 -> {path}")

    if not all_rows:
        log("未采集到任何数据，请先用 测试Iip解封.py 探测 IP 状态")
        return

    result = pd.DataFrame(all_rows).rename(columns=RENAME_MAP)
    for c in list(RENAME_MAP.values())[1:]:
        result[c] = pd.to_numeric(result[c], errors='coerce')
    _save(result)

    log(f"\n本轮结束：{len(result)} 行 / {result['code'].nunique()} 只")
    log(f"总请求 {_req_count} 次")


if __name__ == '__main__':
    main()