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


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

prediction_file = max(glob.glob(os.path.join(BASE_DIR, '预测_涨_相对_*.csv')),
                      key=os.path.getmtime)
print(f'预测: {os.path.basename(prediction_file)}')

preds = pd.read_csv(prediction_file, encoding='utf-8-sig', dtype={'股票代码': str})
preds['股票代码'] = preds['股票代码'].str.zfill(6)
preds['日期'] = pd.to_datetime(preds['日期'])


def board_of(code):
    if code.startswith(('300', '301', '688')):
        return '创业科创'
    if code.startswith(('000', '001', '002', '003')):
        return '深主板'
    if code.startswith(('600', '601', '603', '605')):
        return '沪主板'
    return '其他'


preds['board'] = preds['股票代码'].map(board_of)
preds['year'] = preds['日期'].dt.year
main_boards = ('创业科创', '深主板', '沪主板')

print('\n【1】各板块覆盖（去重只数）')
for name in main_boards:
    g = preds[preds['board'] == name]
    print(f'   {name:<8} {g["股票代码"].nunique():>4} 只   '
          f'周均收益 {g["下周收益"].mean():+.3%}')

print('\n【2】组内 Top 10% 超额（相对本组均值）')
print('   板块      周数    组内超额     正占       t')
within_board = {}
for name in main_boards:
    g = preds[preds['board'] == name]
    weekly_excess = []
    for _, gg in g.groupby('周序'):
        n = max(3, int(len(gg) * 0.1))
        top = gg.nlargest(n, '概率')
        weekly_excess.append(top['下周收益'].mean() - gg['下周收益'].mean())
    weekly_excess = np.array(weekly_excess)
    t = weekly_excess.mean() / (weekly_excess.std(ddof=1) / np.sqrt(len(weekly_excess)))
    print(f'   {name:<8} {len(weekly_excess):>4} 周  {weekly_excess.mean():>+8.3%}  '
          f'{(weekly_excess > 0).mean():>5.0%}  {t:>6.2f}')
    within_board[name] = weekly_excess.mean()

print('\n【3】全池 Top35 的板块构成（按年，单位=只）')
rows = []
for _, g in preds.groupby('周序'):
    n = max(3, int(len(g) * 0.1))
    top = g.nlargest(n, '概率')
    rec = {'year': g['日期'].iloc[0].year, 'holdings': len(top)}
    rec.update({k: (top['board'] == k).sum() for k in main_boards})
    rows.append(rec)
composition = pd.DataFrame(rows)
by_year = composition.groupby('year').agg(
    weeks=('holdings', 'size'),
    avg_holdings=('holdings', 'mean'),
    **{f'{k}_count': (k, 'mean') for k in main_boards},
).round(1)
print(by_year.rename(columns={'weeks': '周数', 'avg_holdings': '平均持仓',
                              **{f'{k}_count': f'{k}只数' for k in main_boards}}).to_string())

print('\n【4】风格漂移：持/池 超配倍数')
print('   年份   创业科创 池/持/倍        深主板 池/持/倍        沪主板 池/持/倍')
for year, year_group in preds.groupby('year'):
    pool_share = year_group.drop_duplicates('股票代码')['board'].value_counts(normalize=True)
    weekly_shares = []
    for _, gg in year_group.groupby('周序'):
        n = max(3, int(len(gg) * 0.1))
        weekly_shares.append(gg.nlargest(n, '概率')['board'].value_counts(normalize=True))
    held_share = pd.concat(weekly_shares, axis=1).mean(axis=1)
    parts = []
    for k in main_boards:
        p = pool_share.get(k, 0.0)
        h = held_share.get(k, 0.0)
        multiple = h / p if p > 0.005 else np.nan
        parts.append(f'{p:>4.0%}/{h:>4.0%}/{multiple:>4.1f}x')
    print(f'   {year}   ' + '        '.join(parts))

print('\n【5】超额来源拆分')
universe_excess = []
for _, g in preds.groupby('周序'):
    n = max(3, int(len(g) * 0.1))
    top = g.nlargest(n, '概率')
    universe_excess.append(top['下周收益'].mean() - g['下周收益'].mean())
universe_excess = np.array(universe_excess)
stock_selection = np.mean(list(within_board.values()))
print(f'   全池 Top35 超额        {universe_excess.mean():+.3%}/周')
print(f'   三板块组内选股均值      {stock_selection:+.3%}/周')
print(f'   差额（板块配置贡献）    {universe_excess.mean() - stock_selection:+.3%}/周')
print(f'   选股占超额比例          {stock_selection / universe_excess.mean():.0%}')
