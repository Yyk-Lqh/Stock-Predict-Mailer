import requests
import time
import random
import json
import os
import csv


json_data="cache_stock_data.json"
b=False




if b and os.path.exists(json_data):
    with open(json_data,"r",encoding="utf-8") as f:
        data=json.load(f)
        print("打开了缓存文件")



else:
    data={
  "rc": 0,
  "rt": 6,
  "svr": 180606409,
  "lt": 1,
  "full": 1,
  "dlmkts": "",
  "dsc": "0",
  "data": {
    "total": 5581,
    "diff": [
      {
        "f1": 2,
        "f2": 7299,
        "f3": 17154,
        "f4": 4611,
        "f5": 271287,
        "f6": 2187703775.42,
        "f7": 6789,
        "f8": 7848,
        "f9": 5967,
        "f10": "-",
        "f12": "301718",
        "f13": 0,
        "f14": "N通则",
        "f15": 8885,
        "f16": 7060,
        "f17": 7800,
        "f18": 2688,
        "f23": 654,
        "f152": 2
      }
    ]
  }
}
    with open(json_data,"w",encoding="utf-8") as f:
        json.dump(data,f,ensure_ascii=False,indent=2)
        print("创建了缓存文件")
