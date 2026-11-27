"""验证底部名单：概率最低的 35 只，下周是否真的跑输全池"""
import glob
import os

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
预测文件 = max(glob.glob(os.path.join(BASE_DIR, '预测_涨_相对_*.csv')),
             key=os.path.getmtime)
预 = pd.read_csv(预测文件, encoding='utf-8-sig', dtype={'股票代码': str})
预['股票代码'] = 预['股票代码'].str.zfill(6)
预['日期'] = pd.to_datetime(预['日期'])

行 = []
for w, g in 预.groupby('周序'):
    n = max(3, int(len(g) * 0.1))
    行.append({
        '周序': w,
        '日期': g['日期'].iloc[0],
        'Top': g.nlargest(n, '概率')['下周收益'].mean(),
        'Bottom': g.nsmallest(n, '概率')['下周收益'].mean(),
        '全池': g['下周收益'].mean(),
    })
d = pd.DataFrame(行)
d['Top超额'] = d['Top'] - d['全池']
d['Bot超额'] = d['Bottom'] - d['全池']
d['多空'] = d['Top'] - d['Bottom']


def 报(name, s):
    t = s.mean() / (s.std(ddof=1) / np.sqrt(len(s)))
    print(f'  {name:<8} 周均 {s.mean():+.3%}  中位 {np.median(s):+.3%}  '
          f'正占 {(s > 0).mean():.0%}  t={t:.2f}')


print(f'周数 {len(d)}')
报('Top超额', d['Top超额'])
报('Bot超额', d['Bot超额'])
报('多空', d['多空'])

d['年'] = d['日期'].dt.year
print('\n  分年 Bot 超额：')
for y, g in d.groupby('年'):
    print(f'   {y}  {g["Bot超额"].mean():+.3%}')
