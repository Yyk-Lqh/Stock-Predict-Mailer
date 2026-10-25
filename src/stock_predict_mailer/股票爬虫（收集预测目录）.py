import requests
import time
import random
import json
import os
import csv


#运行完成后，不要在删除了缓存的json文件下的10分钟内再次运行，否则IP封禁1小时左右


DEBUG =True#如果缓存了返回的数据，就接着用（改成False会强制更新数据）
CACHE_FILE = "cache_stock_data.json"

url = "https://push2.eastmoney.com/api/qt/clist/get"
# 请求参数
params = {
    "pn": 1,
    "pz": 50,
    "po": 1,
    "fid": "f3",
    "fs": "m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2",
    "fields": "f12,f13,f14,f1,f2,f4,f3,f152,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f23",
    "np": 1,
    "fltt": 1,
    "invt": 2,
    "ut": "fa5fd1943c7b386f172d6893dbfba10b",
}
# 请求头
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}
session=requests.Session()
session.headers.update(headers)

# 设置最大重试次数
max_time=3

if DEBUG and os.path.exists(CACHE_FILE):
    print(f"[DEBUG] 读取本地缓存: {CACHE_FILE}")
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
else:
    for i in range(max_time):
        try:
            try:
                session.get("https://quote.eastmoney.com/", timeout=10)
            except Exception :
                pass
            time.sleep(random.uniform(5, 10))
            response = session.get(url, params=params, timeout=30)
            data = response.json()
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[缓存] 数据已保存到 {CACHE_FILE}")
            print(f"\n")
            break
        except Exception as e:
            print(f"第 {i + 1} 次请求失败: {e}")
            if i == max_time - 1:
                print("多次重试仍失败，请稍后再运行")
                exit()
            time.sleep(random.uniform(60, 120))

# 遍历股票数据
for i in data["data"]["diff"]:
    stock_code=i["f12"]#股票代码
    stock_name=i["f14"]#股票名称
    stock_max_price=i["f15"]#最高价
    stock_min_price=i["f16"]#最低价
    stock_open_price=i["f17"]#开盘价
    stock_yesterday_close_price=i["f18"]#昨日收盘价
    stock_now_price=i["f2"]#现价
    stock_deal_volume=i["f5"]#成交量

#测试用
    stock_max_price1 = stock_max_price / 100 if isinstance(stock_max_price, (int, float)) else stock_max_price
    stock_min_price1=stock_min_price / 100 if isinstance(stock_min_price, (int, float)) else stock_min_price
    stock_open_price1=stock_open_price / 100 if isinstance(stock_open_price, (int, float)) else stock_open_price
    stock_yesterday_close_price1=stock_yesterday_close_price / 100 if isinstance(stock_yesterday_close_price, (int, float)) else stock_yesterday_close_price
    stock_now_price1=stock_now_price / 100 if isinstance(stock_now_price, (int, float)) else stock_now_price
    print(f"{stock_code} {stock_name:>8s}  现价:{stock_now_price1}  最高:{stock_max_price1}  最低:{stock_min_price1}  开盘:{stock_open_price1}  昨收:{stock_yesterday_close_price1    }  成交量:{stock_deal_volume}")
#   写入CSV文件

with open("stock_data2.csv", "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["股票代码", "股票名称", "现价", "最高", "最低", "开盘", "昨收", "成交量"])
    for i in data["data"]["diff"]:
        code = i["f12"]
        name = i["f14"]
        now = i["f2"] / 100 if isinstance(i["f2"], (int, float)) else i["f2"]
        high = i["f15"] / 100 if isinstance(i["f15"], (int, float)) else i["f15"]
        low = i["f16"] / 100 if isinstance(i["f16"], (int, float)) else i["f16"]
        open_p = i["f17"] / 100 if isinstance(i["f17"], (int, float)) else i["f17"]
        yclose = i["f18"] / 100 if isinstance(i["f18"], (int, float)) else i["f18"]
        vol = i["f5"]
        writer.writerow([code, name, now, high, low, open_p, yclose, vol])
print("\n[完成] 数据已保存到 stock_data2.csv")




