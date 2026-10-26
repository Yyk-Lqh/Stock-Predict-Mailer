
import requests
import time
import random

url = "https://push2.eastmoney.com/api/qt/clist/get"

params = {
    "pn": 1,
    "pz": 20,
    "po": 1,
    "fid": "f3",
    "fs": "m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2",
    "fields": "f12,f13,f14,f1,f2,f4,f3,f152,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f23",
    "np": 1,
    "fltt": 1,
    "invt": 2,
    "ut": "fa5fd1943c7b386f172d6893dbfba10b",
}

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

session = requests.Session()
session.headers.update(headers)

max_retries = 3
for attempt in range(max_retries):
    try:
        session.get("https://quote.eastmoney.com/", timeout=10)
        time.sleep(random.uniform(1, 3))
        response = session.get(url, params=params, timeout=30)
        data = response.json()
        break
    except Exception as e:
        print(f"第 {attempt + 1} 次请求失败: {e}")
        if attempt == max_retries - 1:
            print("多次重试仍失败，请稍后再运行")
            exit()
        time.sleep(random.uniform(60, 120))


print(f"共 {data['data']['total']} 只股票\n")

for item in data["data"]["diff"]:
    code = item["f12"]
    name = item["f14"]
    price = item["f2"]
    change_pct = item["f3"]
    volume = item["f5"]
    amount = item["f6"]

    p = price / 100 if isinstance(price, (int, float)) else price
    c = change_pct / 100 if isinstance(change_pct, (int, float)) else change_pct
    v = volume / 100 if isinstance(volume, (int, float)) else volume
    a = amount

    print(f"{code} {name:>8} | 价格:{p:>8} | 涨跌幅:{c:>6}% | 成交额:{a:>8}")












