
import requests
import csv
import time
import random

stock_code = "002664"
market = 0  # 0=深圳, 1=上海

url = (
    f"http://push2his.eastmoney.com/api/qt/stock/kline/get?"
    f"secid={market}.{stock_code}"
    f"&fields1=f1,f2,f3,f4,f5,f6"
    f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
    f"&klt=101"
    f"&fqt=1"
    f"&beg=20261001"
    f"&end=20261022"
)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/"
}

all_data = []


def fetch_stock_data():
    try:
        response = requests.get(url, headers=headers, timeout=60)
        response.encoding = "utf-8"
        data = response.json()

        if data.get("data") and data["data"].get("klines"):
            klines = data["data"]["klines"]
            for line in klines:
                fields = line.split(",")
                stock_info = {
                    "日期": fields[0],
                    "开盘价": fields[1],
                    "收盘价": fields[2],
                    "最高价": fields[3],
                    "最低价": fields[4],
                    "成交量": fields[5],
                    "成交额": fields[6],
                    "振幅": fields[7],
                    "涨跌幅": fields[8],
                    "涨跌额": fields[9],
                    "换手率": fields[10],
                }
                all_data.append(stock_info)
                print(f"{stock_info['日期']} | 开:{stock_info['开盘价']} 高:{stock_info['最高价']} 低:{stock_info['最低价']} 收:{stock_info['收盘价']} 量:{stock_info['成交量']}")
        else:
            print("未获取到数据，请检查股票代码或日期范围")

    except Exception as e:
        print(f"请求失败: {e}")


def save_to_csv():
    if not all_data:
        print("没有数据可保存")
        return
    with open(f"stock_{stock_code}.csv", "w", newline="", encoding="utf-8") as f:
        fieldnames = ["日期", "开盘价", "收盘价", "最高价", "最低价", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_data)
        print(f"已保存到 stock_{stock_code}.csv，共 {len(all_data)} 条数据")


def main():
    print(f"正在爬取股票 {stock_code} 的行情数据...")
    time.sleep(random.uniform(1, 2))
    fetch_stock_data()
    time.sleep(random.uniform(1, 2))
    save_to_csv()


main()