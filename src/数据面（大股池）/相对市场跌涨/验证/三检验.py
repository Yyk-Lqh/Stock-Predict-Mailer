"""周频模型三检验：分年 / 成本敏感性 / 月度调仓

只读缓存，不做训练。自动匹配最新的 预测_涨_相对_*.csv
"""
import glob
import os

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
标签列 = '涨_相对'
单边成本 = 0.0015

预测候选 = glob.glob(os.path.join(BASE_DIR, '预测_涨_相对_*.csv'))
if not 预测候选:
    raise SystemExit('找不到预测缓存，先跑一次 周频跌涨模型.py')
预测文件 = max(预测候选, key=os.path.getmtime)
print(f'预测: {os.path.basename(预测文件)}')

预 = pd.read_csv(预测文件, encoding='utf-8-sig', dtype={'股票代码': str})
预['股票代码'] = 预['股票代码'].str.zfill(6)
预['日期'] = pd.to_datetime(预['日期'])

周 = pd.read_csv(os.path.join(BASE_DIR, '周度特征缓存.csv'),
                 encoding='utf-8-sig', dtype={'股票代码': str})
周['股票代码'] = 周['股票代码'].str.zfill(6)
周 = 周.sort_values(['股票代码', '周序'])

# 未来 4 周累计收益：位置 t 取 t+1 ~ t+4
周['未来4周收益'] = (周.groupby('股票代码')['周收益']
                  .transform(lambda s: s.rolling(4, min_periods=3).sum().shift(-4)))
下界, 上界 = 周['未来4周收益'].quantile([0.005, 0.995])
周['未来4周收益'] = 周['未来4周收益'].clip(下界, 上界)
print(f'  4周收益 中位 {周["未来4周收益"].median():.2%}  '
      f'0.5%分位 {下界:.2%}  99.5%分位 {上界:.2%}（已截断）')

重复 = 周.duplicated(['股票代码', '周序']).sum()
if 重复:
    raise SystemExit(f'周度表有 {重复} 条重复索引，join 会膨胀')

预 = 预.join(周.set_index(['股票代码', '周序'])[['未来4周收益']],
            on=['股票代码', '周序'])


def 组合序列(收益列='下周收益', 用buffer=True):
    行 = []
    持仓 = set()
    for w, g in 预.groupby('周序'):
        n = max(3, int(len(g) * 0.1))
        g = g.copy()
        g['分位'] = g['概率'].rank(pct=True, ascending=False)
        if 用buffer:
            新持仓 = ((持仓 & set(g[g['分位'] <= 0.15]['股票代码']))
                      | set(g[g['分位'] <= 0.05]['股票代码']))
            if len(新持仓) > 2 * n:
                新持仓 = set(g[g['股票代码'].isin(新持仓)]
                             .nlargest(2 * n, '概率')['股票代码'])
        else:
            新持仓 = set(g.nlargest(n, '概率')['股票代码'])
        if not 新持仓:
            continue
        明细 = g[g['股票代码'].isin(新持仓)]
        行.append({'周序': w,
                   '日期': g['日期'].iloc[0],
                   '组合': 明细[收益列].mean(),
                   '全池': g[收益列].mean(),
                   '换手': len(新持仓 - 持仓) / max(1, len(新持仓)) if 持仓 else np.nan,
                   '持仓': len(新持仓)})
        持仓 = 新持仓
    d = pd.DataFrame(行)
    d['超额'] = d['组合'] - d['全池']
    return d


序 = 组合序列()
序['年'] = 序['日期'].dt.year

print('\n【1】分年（Buffer 15/5）')
print('   年份    周数    周均超额    正超额    净年化')
for y, g in 序.groupby('年'):
    净年化 = g['超额'].mean() * 52 - 2 * g['换手'].mean() * 单边成本 * 52
    print(f'   {y}  {len(g):>4} 周  {g["超额"].mean():>+8.3%}  '
          f'{(g["超额"] > 0).mean():>5.0%}  {净年化:>+8.2%}')
最强年 = 序.groupby('年')['超额'].mean().idxmax()
贡献 = 序[序['年'] == 最强年]['超额'].sum() / 序['超额'].sum()
print(f'   → 最强年 {最强年} 贡献总超额的 {贡献:.0%}')

print('\n【2】成本敏感性（Buffer 15/5）')
print('   单边成本     周净       年化')
for c in (0.0005, 0.0008, 0.00105, 0.0015, 0.002, 0.0025, 0.003):
    净 = 序['超额'].mean() - 2 * 序['换手'].mean() * c
    print(f'   {c:>7.3%}  {净:>+7.3%}  {净 * 52:>+8.2%}')

print('\n【3】每月最后一周持仓，持有 4 周（模拟月频调仓）')
序月 = 组合序列(收益列='未来4周收益', 用buffer=False)
序月['月'] = 序月['日期'].dt.to_period('M')
月末 = 序月.loc[序月.groupby('月')['周序'].idxmax()]
月末 = 月末.dropna(subset=['超额'])
print(f'   月数 {len(月末)}   4周均超额 {月末["超额"].mean():+.3%}   '
      f'正超额 {(月末["超额"] > 0).mean():.0%}')
t月 = 月末['超额'].mean() / (月末['超额'].std(ddof=1) / np.sqrt(len(月末)))
print(f'   t 值 {t月:.2f}')
按年 = 月末.groupby(月末['日期'].dt.year)['超额'].mean()
print('   分年：' + '   '.join(f'{y}:{v:+.2%}' for y, v in 按年.items()))
保留率 = 月末['超额'].mean() / (4 * 序['超额'].mean())
print(f'   信号保留率 {保留率:.0%}   '
      f'（100% = 月频调仓不损失；<60% = 必须周频操作）')