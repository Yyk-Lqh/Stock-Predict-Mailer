"""验证：模型是风格暴露还是真截面能力

1. 组内 Top 10% 超额（相对本组均值）→ 判断有无真 alpha
2. 按年板块构成 → 看持仓结构变化
3. 持/池 超配倍数 → 看风格是否在漂移
4. 板块配置 vs 组内选股 的贡献拆分
"""
import glob
import os

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
预测文件 = max(glob.glob(os.path.join(BASE_DIR, '预测_涨_相对_*.csv')),
             key=os.path.getmtime)
print(f'预测: {os.path.basename(预测文件)}')

预 = pd.read_csv(预测文件, encoding='utf-8-sig', dtype={'股票代码': str})
预['股票代码'] = 预['股票代码'].str.zfill(6)
预['日期'] = pd.to_datetime(预['日期'])


def 板块(c):
    if c.startswith(('300', '301', '688')):
        return '创业科创'
    if c.startswith(('000', '001', '002', '003')):
        return '深主板'
    if c.startswith(('600', '601', '603', '605')):
        return '沪主板'
    return '其他'


预['板块'] = 预['股票代码'].map(板块)
预['年'] = 预['日期'].dt.year
主板块 = ('创业科创', '深主板', '沪主板')

print('\n【1】各板块覆盖（去重只数）')
for 名 in 主板块:
    g = 预[预['板块'] == 名]
    print(f'   {名:<8} {g["股票代码"].nunique():>4} 只   '
          f'周均收益 {g["下周收益"].mean():+.3%}')

print('\n【2】组内 Top 10% 超额（相对本组均值）')
print('   板块      周数    组内超额     正占       t')
组内 = {}
for 名 in 主板块:
    g = 预[预['板块'] == 名]
    周超 = []
    for _, gg in g.groupby('周序'):
        n = max(3, int(len(gg) * 0.1))
        top = gg.nlargest(n, '概率')
        周超.append(top['下周收益'].mean() - gg['下周收益'].mean())
    周超 = np.array(周超)
    t = 周超.mean() / (周超.std(ddof=1) / np.sqrt(len(周超)))
    print(f'   {名:<8} {len(周超):>4} 周  {周超.mean():>+8.3%}  '
          f'{(周超 > 0).mean():>5.0%}  {t:>6.2f}')
    组内[名] = 周超.mean()

print('\n【3】全池 Top35 的板块构成（按年，单位=只）')
行 = []
for w, g in 预.groupby('周序'):
    n = max(3, int(len(g) * 0.1))
    top = g.nlargest(n, '概率')
    rec = {'年': g['日期'].iloc[0].year, '持仓': len(top)}
    rec.update({k: (top['板块'] == k).sum() for k in 主板块})
    行.append(rec)
构 = pd.DataFrame(行)
按年 = 构.groupby('年').agg(
    周数=('持仓', 'size'),
    平均持仓=('持仓', 'mean'),
    **{f'{k}只数': (k, 'mean') for k in 主板块},
).round(1)
print(按年.to_string())

print('\n【4】风格漂移：持/池 超配倍数')
print('   年份   创业科创 池/持/倍        深主板 池/持/倍        沪主板 池/持/倍')
for 年, g年 in 预.groupby('年'):
    池计 = g年.drop_duplicates('股票代码')['板块'].value_counts(normalize=True)
    每周 = []
    for _, gg in g年.groupby('周序'):
        n = max(3, int(len(gg) * 0.1))
        每周.append(gg.nlargest(n, '概率')['板块'].value_counts(normalize=True))
    持计 = pd.concat(每周, axis=1).mean(axis=1)
    片段 = []
    for k in 主板块:
        p = 池计.get(k, 0.0)
        h = 持计.get(k, 0.0)
        倍 = h / p if p > 0.005 else np.nan
        片段.append(f'{p:>4.0%}/{h:>4.0%}/{倍:>4.1f}x')
    print(f'   {年}   ' + '        '.join(片段))

print('\n【5】超额来源拆分')
全池超 = []
for _, g in 预.groupby('周序'):
    n = max(3, int(len(g) * 0.1))
    top = g.nlargest(n, '概率')
    全池超.append(top['下周收益'].mean() - g['下周收益'].mean())
全池超 = np.array(全池超)
选股 = np.mean(list(组内.values()))
print(f'   全池 Top35 超额        {全池超.mean():+.3%}/周')
print(f'   三板块组内选股均值      {选股:+.3%}/周')
print(f'   差额（板块配置贡献）    {全池超.mean() - 选股:+.3%}/周')
print(f'   选股占超额比例          {选股 / 全池超.mean():.0%}')
