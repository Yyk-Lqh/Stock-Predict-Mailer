# -*- coding: utf-8 -*-
"""一键修正 5 个脚本里的旧路径，让 数据面2 成为完全自洽的工作目录。
运行一次即可，跑完可以删掉本文件。
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))

修正表 = [
    # (文件名, 旧字符串, 新字符串)
    ('股票爬虫（收集预测目录）步骤(1).py',
     'open("数据面/stock_data117.csv", "w", encoding="utf-8-sig", newline="") as f:',
     "open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stock_data117.csv'), \"w\", encoding=\"utf-8-sig\", newline=\"\") as f:"),
    ('历史股票数据爬虫_步骤(2).py',
     'with open("../数据面/stock_data117.csv", "r", encoding="utf-8-sig") as f:',
     'with open("stock_data117.csv", "r", encoding="utf-8-sig") as f:'),
    ('我已无力，不会有下一版的数据面_步骤(5).py',
     "DATA_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '数据面'))",
     'DATA_DIR = SCRIPT_DIR'),
    ('我已无力，不会有下一版的数据面_步骤(5).py',
     "LOG_FILE = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '重采进度.log'))",
     "LOG_FILE = os.path.join(SCRIPT_DIR, '重采进度.log')"),
    ('数据面清洗版_步骤(6).py',
     "OUT = os.path.normpath(os.path.join(BASE_DIR, '..', '数据面',\n"
     "                                    'fundamental_quarterly_cleaned.csv'))",
     "OUT = os.path.join(BASE_DIR, 'fundamental_quarterly_cleaned.csv')"),
    ('IC.py',
     "def _resolve(name):\n"
     "    \"\"\"优先用 数据面/ 的正本，避免 数据面2/ 副本陈旧\"\"\"\n"
     "    for cand in (os.path.join(ROOT_DIR, '数据面', name),\n"
     "                 os.path.join(BASE_DIR, name)):",
     "def _resolve(name):\n"
     "    \"\"\"数据面2 是唯一工作目录，优先本目录；上级 数据面/ 只作兜底\"\"\"\n"
     "    for cand in (os.path.join(BASE_DIR, name),\n"
     "                 os.path.normpath(os.path.join(ROOT_DIR, '数据面', name))):"),
]

for 文件名, 旧, 新 in 修正表:
    path = os.path.join(BASE, 文件名)
    if not os.path.exists(path):
        print(f'✗ {文件名}：文件不存在，跳过')
        continue
    with open(path, encoding='utf-8') as f:
        原文 = f.read()
    n = 原文.count(旧)
    if n == 1:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(原文.replace(旧, 新))
        print(f'✓ {文件名}：已修正')
    elif n == 0:
        print(f'— {文件名}：找不到旧路径（可能已改过），跳过')
    else:
        print(f'⚠ {文件名}：匹配到 {n} 处，未修改，请手动检查')

print('\n接着做：')
print('1. 把 数据面\\stock_data117.csv 拷到本目录（数据面2）')
print('2. 跑 校验_步骤(7).py，确认 0 重复')
print('3. 跑 因子试探3_步骤(8).py，结果应与 9 特征基线一致')
