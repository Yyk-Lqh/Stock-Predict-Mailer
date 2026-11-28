"""验证底部名单：概率最低的 35 只，下周是否真的跑输全池"""
import glob
import os

import numpy as np
import pandas as pd


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

prediction_file = max(glob.glob(os.path.join(BASE_DIR, '预测_涨_相对_*.csv')),
                      key=os.path.getmtime)
preds = pd.read_csv(prediction_file, encoding='utf-8-sig', dtype={'股票代码': str})
preds['股票代码'] = preds['股票代码'].str.zfill(6)
preds['日期'] = pd.to_datetime(preds['日期'])

rows = []
for w, g in preds.groupby('周序'):
    n = max(3, int(len(g) * 0.1))
    rows.append({
        '周序': w,
        '日期': g['日期'].iloc[0],
        'Top': g.nlargest(n, '概率')['下周收益'].mean(),
        'Bottom': g.nsmallest(n, '概率')['下周收益'].mean(),
        'universe': g['下周收益'].mean(),
    })
d = pd.DataFrame(rows)
d['top_excess'] = d['Top'] - d['universe']
d['bot_excess'] = d['Bottom'] - d['universe']
d['long_short'] = d['Top'] - d['Bottom']


def report_stat(label, series):
    t = series.mean() / (series.std(ddof=1) / np.sqrt(len(series)))
    print(f'  {label:<8} 周均 {series.mean():+.3%}  中位 {np.median(series):+.3%}  '
          f'正占 {(series > 0).mean():.0%}  t={t:.2f}')


print(f'周数 {len(d)}')
report_stat('Top超额', d['top_excess'])
report_stat('Bot超额', d['bot_excess'])
report_stat('多空', d['long_short'])

d['year'] = d['日期'].dt.year
print('\n  分年 Bot 超额：')
for y, g in d.groupby('year'):
    print(f'   {y}  {g["bot_excess"].mean():+.3%}')
