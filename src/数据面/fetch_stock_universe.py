import requests
import time
import random
import json
import os
import csv


#运行完成后，不要在删除了缓存的json文件下的10分钟内再次运行，否则IP封禁1小时左右


DEBUG =True#如果缓存了返回的数据，就接着用（改成False会强制更新数据）
CACHE_FILE = "../sessions/cache_stock_data.json"

url = "https://pushguest.eastmoney.com/api/qt/clist/get"
# 请求参数
params = {
    "timil": 1,
    "np": 1,
    "fltt": 2,          # 2 = 返回 ×100 整数；1 = 原始浮点（那时不用 /100）
    "invt": 2,
    "fs": "b:bk0500+f:!50",
    "fields": "f12,f13,f14,f1,f2,f4,f3,f152,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f23",
    "fid": "f3",                  # 按涨跌幅排序
    "pn": 1,                      # 页码
    "pz": 100,                     # 每页条数
    "po": 1,                      # 1 = 降序
    "dect": 1,
    "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    "wbp2u": "|0|0|0|web",
    "_": int(time.time() * 1000) ,
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





            if data.get("data"):
                diff = data["data"].get("diff") or []
                if isinstance(diff, dict):  # 只有 1 条时返回 dict
                    diff = list(diff.values())
                total = data["data"].get("total", 0)
                pn = params.get("pn", 1)  # 用局部变量，不动 params
                while total and len(diff) < total:
                    pn += 1
                    p = {**params, "pn": pn, "_": int(time.time() * 1000)}
                    time.sleep(random.uniform(1.5, 3))
                    try:
                        d2 = session.get(url, params=p, timeout=30).json().get("data") or {}
                    except Exception as e:
                        print(f"  补第 {pn} 页失败: {e}，保留已拿到的 {len(diff)} 条")
                        break
                    part = d2.get("diff") or []
                    if isinstance(part, dict):
                        part = list(part.values())
                    if not part:
                        break
                    diff.extend(part)
                    print(f"  补第 {pn} 页 {len(part)} 条   累计 {len(diff)} / {total}")
                # 按代码去重（盘中 fid=f3 排序会变，可能重复）
                data["data"]["diff"] = list({str(i["f12"]): i for i in diff}.values())








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

with open("stock_data117.csv", "w", encoding="utf-8-sig", newline="") as f:
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
print("\n[完成] 数据已保存到 stock_data117.csv")