"""周频模型三检验：分年 / 成本敏感性 / 月度调仓

只读缓存，不做训练。自动匹配最新的 预测_涨_相对_*.csv
"""
import glob
import os

import numpy as np
import pandas as pd


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

label_col = '涨_相对'
one_way_cost = 0.0015

prediction_candidates = glob.glob(os.path.join(BASE_DIR, '预测_涨_相对_*.csv'))
if not prediction_candidates:
    raise SystemExit('找不到预测缓存，先跑一次 周频跌涨模型.py')
prediction_file = max(prediction_candidates, key=os.path.getmtime)
print(f'预测: {os.path.basename(prediction_file)}')

preds = pd.read_csv(prediction_file, encoding='utf-8-sig', dtype={'股票代码': str})
preds['股票代码'] = preds['股票代码'].str.zfill(6)
preds['日期'] = pd.to_datetime(preds['日期'])

weekly = pd.read_csv(os.path.join(BASE_DIR, '周度特征缓存.csv'),
                     encoding='utf-8-sig', dtype={'股票代码': str})
weekly['股票代码'] = weekly['股票代码'].str.zfill(6)
weekly = weekly.sort_values(['股票代码', '周序'])

# 未来 4 周累计收益：位置 t 取 t+1 ~ t+4
weekly['future_4w_return'] = (weekly.groupby('股票代码')['周收益']
                              .transform(lambda s: s.rolling(4, min_periods=3).sum().shift(-4)))
lower, upper = weekly['future_4w_return'].quantile([0.005, 0.995])
weekly['future_4w_return'] = weekly['future_4w_return'].clip(lower, upper)
print(f'  4周收益 中位 {weekly["future_4w_return"].median():.2%}  '
      f'0.5%分位 {lower:.2%}  99.5%分位 {upper:.2%}（已截断）')

duplicates = weekly.duplicated(['股票代码', '周序']).sum()
if duplicates:
    raise SystemExit(f'周度表有 {duplicates} 条重复索引，join 会膨胀')

preds = preds.join(weekly.set_index(['股票代码', '周序'])[['future_4w_return']],
                   on=['股票代码', '周序'])


def portfolio_series(return_col='下周收益', use_buffer=True):
    rows = []
    holdings = set()
    for w, g in preds.groupby('周序'):
        n = max(3, int(len(g) * 0.1))
        g = g.copy()
        g['pct_rank'] = g['概率'].rank(pct=True, ascending=False)
        if use_buffer:
            new_holdings = ((holdings & set(g[g['pct_rank'] <= 0.15]['股票代码']))
                            | set(g[g['pct_rank'] <= 0.05]['股票代码']))
            if len(new_holdings) > 2 * n:
                new_holdings = set(g[g['股票代码'].isin(new_holdings)]
                                   .nlargest(2 * n, '概率')['股票代码'])
        else:
            new_holdings = set(g.nlargest(n, '概率')['股票代码'])
        if not new_holdings:
            continue
        selected = g[g['股票代码'].isin(new_holdings)]
        rows.append({'周序': w,
                     '日期': g['日期'].iloc[0],
                     'portfolio': selected[return_col].mean(),
                     'universe': g[return_col].mean(),
                     'turnover': len(new_holdings - holdings) / max(1, len(new_holdings)) if holdings else np.nan,
                     'holdings': len(new_holdings)})
        holdings = new_holdings
    frame = pd.DataFrame(rows)
    frame['excess'] = frame['portfolio'] - frame['universe']
    return frame


series = portfolio_series()
series['year'] = series['日期'].dt.year

print('\n【1】分年（Buffer 15/5）')
print('   年份    周数    周均超额    正超额    净年化')
for y, g in series.groupby('year'):
    net_annual = g['excess'].mean() * 52 - 2 * g['turnover'].mean() * one_way_cost * 52
    print(f'   {y}  {len(g):>4} 周  {g["excess"].mean():>+8.3%}  '
          f'{(g["excess"] > 0).mean():>5.0%}  {net_annual:>+8.2%}')
best_year = series.groupby('year')['excess'].mean().idxmax()
contribution = series[series['year'] == best_year]['excess'].sum() / series['excess'].sum()
print(f'   → 最强年 {best_year} 贡献总超额的 {contribution:.0%}')

print('\n【2】成本敏感性（Buffer 15/5）')
print('   单边成本     周净       年化')
for c in (0.0005, 0.0008, 0.00105, 0.0015, 0.002, 0.0025, 0.003):
    net = series['excess'].mean() - 2 * series['turnover'].mean() * c
    print(f'   {c:>7.3%}  {net:>+7.3%}  {net * 52:>+8.2%}')

print('\n【3】每月最后一周持仓，持有 4 周（模拟月频调仓）')
monthly_series = portfolio_series(return_col='future_4w_return', use_buffer=False)
monthly_series['month'] = monthly_series['日期'].dt.to_period('M')
month_end = monthly_series.loc[monthly_series.groupby('month')['周序'].idxmax()]
month_end = month_end.dropna(subset=['excess'])
print(f'   月数 {len(month_end)}   4周均超额 {month_end["excess"].mean():+.3%}   '
      f'正超额 {(month_end["excess"] > 0).mean():.0%}')
t_month = month_end['excess'].mean() / (month_end['excess'].std(ddof=1) / np.sqrt(len(month_end)))
print(f'   t 值 {t_month:.2f}')
by_year = month_end.groupby(month_end['日期'].dt.year)['excess'].mean()
print('   分年：' + '   '.join(f'{y}:{v:+.2%}' for y, v in by_year.items()))
retention = month_end['excess'].mean() / (4 * series['excess'].mean())
print(f'   信号保留率 {retention:.0%}   '
      f'（100% = 月频调仓不损失；<60% = 必须周频操作）')
