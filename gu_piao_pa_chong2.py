import os
import time
import random
import baostock as bs
import csv
import pandas as pd


all_data = []

with open("stock_data.csv", "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    stock_codes = [row["股票代码"] for row in reader]
for codes in stock_codes:
    df = bs.stock_zh_a_hist(symbol=codes, period="daily", start_date="20251023", end_date="20261023", adjust="qfq")
    all_data.append(df[["股票代码", "日期", "开盘", "收盘", "最高", "最低", "成交量"]])
    time.sleep(random.uniform(6, 9))

result=pd.concat(all_data, ignore_index=True)
result.to_csv("all_stock_history.csv", encoding="utf-8-sig", index=False)
print("全部完成")
