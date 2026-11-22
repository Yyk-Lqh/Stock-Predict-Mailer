import os
import time
import random
from datetime import date, timedelta
import baostock as bs
import baostock.common.context as bs_context
import akshare as ak
import csv
import pandas as pd

COLUMNS = ["日期", "股票代码", "开盘", "最高", "最低", "收盘", "成交量", "市盈率", "市净率", "市销率"]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POOL_FILE = os.path.join(SCRIPT_DIR, "stock_data117.csv")
OUT_FILE = os.path.join(SCRIPT_DIR, "all_stock_history119.csv")

START_DATE = os.environ.get("STOCK_PREDICT_MAILER_BARS_START", "2009-10-23")
END_DATE = os.environ.get("STOCK_PREDICT_MAILER_BARS_END", "2026-10-23")

# 数据完整的判定线：默认比结束日期早 33 天（等价于原来的 2026-10-23 → 2026-09-20）
MIN_LAST_DATE = (os.environ.get("STOCK_PREDICT_MAILER_BARS_MIN_LAST")
                 or (date.fromisoformat(END_DATE) - timedelta(days=33)).isoformat())

bs.login()
if getattr(bs_context, "default_socket", None):
    bs_context.default_socket.settimeout(30)


def _reconnect():
    try:
        bs_context.default_socket.close()
    except Exception:
        pass
    time.sleep(5)
    bs.login()
    if getattr(bs_context, "default_socket", None):
        bs_context.default_socket.settimeout(30)


with open(POOL_FILE, "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    stock_codes = [row["股票代码"] for row in reader]

# 增量：只跳过"数据完整"的股票；残缺（最后日期 < MIN_LAST_DATE）的整只重采，
# 重采成功后旧行被替换，重采失败的保留旧数据等下次再试。
existing = set()
old_df = None
if os.path.exists(OUT_FILE):
    old_df = pd.read_csv(OUT_FILE, dtype={"股票代码": str}, encoding="utf-8-sig")
    old_df["_code"] = old_df["股票代码"].str.replace(r"^(sz|sh)\.", "", regex=True)
    last = old_df.groupby("_code")["日期"].max()
    existing = set(last[last >= MIN_LAST_DATE].index)
    incomplete = set(last.index) - existing
    if incomplete:
        print(f"残缺待补：{len(incomplete)} 只（最后日期 < {MIN_LAST_DATE}）", flush=True)
    stock_codes = [c for c in stock_codes if c not in existing]
    print(f"增量模式：完整 {len(existing)} 只，本轮待采 {len(stock_codes)} 只", flush=True)

if not stock_codes:
    print("无待采股票，跳过")
    bs.logout()
    raise SystemExit(0)


def _fetch_baostock(code):
    prefix = "sh" if code.startswith("6") else "sz"
    rs = bs.query_history_k_data_plus(
        f"{prefix}.{code}",
        "date,code,open,high,low,close,volume,peTTM,pbMRQ,psTTM",
        start_date=START_DATE,
        end_date=END_DATE,
        frequency="d",
        adjustflag="2"
    )
    data_list = []
    while (rs.error_code == '0') and rs.next():
        data_list.append(rs.get_row_data())
    df = pd.DataFrame(data_list, columns=rs.fields)
    if df.shape[1] != 10:
        raise ValueError(f"返回列数异常({df.shape[1]})，fields={rs.fields}")
    df.columns = COLUMNS
    return df

def _fetch_akshare(code):
    df = ak.stock_zh_b_daily(symbol=f"sh{code}")
    df = df.rename(columns={"date": "日期", "open": "开盘", "high": "最高", "low": "最低",
                            "close": "收盘", "volume": "成交量", "code": "股票代码"})
    for letter in ["市盈率", "市净率", "市销率"]:
        df[letter] = None
    # akshare 不支持日期参数，取回来后再按区间裁剪
    df["日期"] = df["日期"].astype(str)
    df = df[(df["日期"] >= START_DATE) & (df["日期"] <= END_DATE)]
    return df[["股票代码", "日期", "开盘", "收盘", "最高", "最低", "成交量", "市盈率", "市净率", "市销率"]]



all_data = []
failed = []
replaced = set()

for codes in stock_codes:
    for attempt in (1, 2):
        try:
            # akshare非常容易被禁ip发生错误，所以用try；baostock不能抓取9开头的股票，但是成功率高
            df = _fetch_akshare(codes) if codes.startswith("9") else _fetch_baostock(codes)
            last_date = str(df["日期"].max()) if len(df) else ""
            if last_date < MIN_LAST_DATE:
                raise ValueError(f"数据残缺，最后日期 {last_date or '空'}")
            all_data.append(df)
            replaced.add(codes)
            print(f" {codes} 完成 行数={len(df)}  ", flush=True)
            break
        except Exception as e:
            if attempt == 1:
                print(f"{codes} 失败 {type(e).__name__}: {str(e)[:60]}，重连后重试", flush=True)
                _reconnect()
            else:
                print(f"{codes} 二次失败，跳过（下次运行会再采）", flush=True)
                failed.append(codes)
    time.sleep(random.uniform(0.3, 0.5))

bs.logout()

if not all_data:
    print("本轮无新数据（全部失败），未写入文件", flush=True)
    if failed:
        print(f"失败 {len(failed)} 只：{' '.join(failed[:20])}...", flush=True)
    raise SystemExit(0)

new_df = pd.concat(all_data, ignore_index=True)
if old_df is not None:
    # 本轮重采成功的股票整只替换旧行；其余旧行原样保留
    keep_old = old_df[~old_df["_code"].isin(replaced)].drop(columns=["_code"])
    result = pd.concat([keep_old, new_df], ignore_index=True)
    print(f"合并：旧保留 {len(keep_old)} 行 + 新采 {len(new_df)} 行 = {len(result)} 行", flush=True)
else:
    result = new_df
result = result.drop_duplicates(subset=["股票代码", "日期"], keep="last")
result.to_csv(OUT_FILE, encoding="utf-8-sig", index=False)
print("完成", flush=True)
if failed:
    print(f"失败 {len(failed)} 只（下次运行会再采）：{' '.join(failed)}", flush=True)
