import time
import random
import baostock as bs
import baostock.common.context as bs_context
import akshare as ak
import csv
import pandas as pd

COLUMNS = ["日期", "股票代码", "开盘", "最高", "最低", "收盘", "成交量", "市盈率", "市净率", "市销率"]

bs.login()
if getattr(bs_context, "default_socket", None):
    bs_context.default_socket.settimeout(30)
all_data = []

with open("stock_data117.csv", "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    stock_codes = [row["股票代码"] for row in reader]

for codes in stock_codes:
    # akshare非常容易被禁ip发生错误，所以用try
    if codes.startswith("9"):
        prefix = "sh"
        try:
            df = ak.stock_zh_b_daily(symbol=f"{prefix}{codes}")
            df = df.rename(columns={"date": "日期", "open": "开盘", "high": "最高", "low": "最低",
                                    "close": "收盘", "volume": "成交量", "code": "股票代码"})
            for letter in ["市盈率", "市净率", "市销率"]:
                df[letter] = None
            all_data.append(df[["股票代码", "日期", "开盘", "收盘", "最高", "最低", "成交量", "市盈率", "市净率", "市销率"]])
            print(f" {codes} 完成 行数={len(df)}  ", flush=True)
        except Exception as e:
            print(f"{codes}返回失败{e}", flush=True)
    else:
        # baostock不能抓取9开头的股票,但是成功率高
        if codes.startswith("6"):
            prefix = "sh"
        else:
            prefix = "sz"
        try:
            rs = bs.query_history_k_data_plus(
                f"{prefix}.{codes}",
                "date,code,open,high,low,close,volume,peTTM,pbMRQ,psTTM",
                start_date="2009-10-23",
                end_date="2026-10-23",
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
            all_data.append(df)
            print(f" {codes} 完成 行数={len(df)}  ", flush=True)
        except Exception as e:
            print(f"{codes} 超时 {type(e).__name__}，跳过并重连", flush=True)
            try:
                bs_context.default_socket.close()
            except Exception:
                pass
            bs.login()
            if getattr(bs_context, "default_socket", None):
                bs_context.default_socket.settimeout(15)
    time.sleep(random.uniform(0.3, 0.5))

bs.logout()
result = pd.concat(all_data, ignore_index=True)
result.to_csv("all_stock_history119.csv", encoding="utf-8-sig", index=False)
print("完成")