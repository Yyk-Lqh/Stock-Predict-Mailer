import os

import numpy as np
import pandas as pd

# ... existing code ...
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)


def _resolve(name):
    """数据面2 是唯一工作目录，优先本目录；上级 数据面/ 只作兜底"""
    for cand in (os.path.join(BASE_DIR, name),
                 os.path.normpath(os.path.join(ROOT_DIR, '数据面', name))):
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError(f'找不到 {name}，已尝试 数据面/ 与 {BASE_DIR}')


FUND_FILE = _resolve('fundamental_quarterly_cleaned.csv')
PRICE_FILE = _resolve('all_stock_history120_deep_cleaned.csv')
# ... existing code ...

# ========== 1. 基本面：构造代理 ==========
def load_fundamental(path):
    f = pd.read_csv(path, dtype={'code': str}, encoding='utf-8-sig')
    f['report_dt'] = pd.to_datetime(f['report_date'])
    f['pub_dt'] = pd.to_datetime(f['pub_date'], errors='coerce')
    # 公告日缺失时用报告期 +120 天兜底，宁可晚用，不可早用
    f['pub_dt'] = f['pub_dt'].fillna(f['report_dt'] + pd.Timedelta(days=120))
    f = f.dropna(subset=['pub_dt']).sort_values(['code', 'pub_dt', 'report_dt'])

    # 去年同期对齐：比 shift(4) 可靠，缺季度不会错位
    ly = f[['code', 'report_dt', 'eps_ttm', 'net_margin', 'ROE']].copy()
    ly['report_dt'] = ly['report_dt'] + pd.DateOffset(years=1)
    ly = ly.rename(columns={'eps_ttm': 'eps_ttm_ly',
                            'net_margin': 'net_margin_ly',
                            'ROE': 'ROE_ly'})
    f = f.merge(ly, on=['code', 'report_dt'], how='left')

    def yoy(cur, prev):
        return (cur - prev) / prev.abs().replace(0, np.nan)

    f['eps_growth'] = yoy(f['eps_ttm'], f['eps_ttm_ly'])          # 代理 eps_yoy
    f['margin_growth'] = yoy(f['net_margin'], f['net_margin_ly'])  # 代理 net_profit_yoy
    f['roe_delta'] = f['ROE'] - f['ROE_ly']

    # ... existing code ...
    # 修正 2024Q2~2025Q4 被缩小 100 倍的负债率
    # 只修该窗口：2026 年起源数据已恢复正常刻度，
    # 真实低负债股(0.07~0.1)若再全局 ×100 会被误放大
    # ... existing code ...
    # 兜底防御（对 cleaned 文件为幂等无操作，防有人直接喂原始文件）
    if 'debt_to_asset' in f.columns:
        f['debt_to_asset'] = pd.to_numeric(f['debt_to_asset'], errors='coerce')
        d = f['debt_to_asset']
        bad = ((d > 0) & (d < 0.1)
               & f['report_dt'].between(pd.Timestamp('2024-06-30'),
                                        pd.Timestamp('2025-12-31')))
        f.loc[bad, 'debt_to_asset'] = d[bad] * 100
        # >3 才是百分制错误（2018Q1~Q3 的 34~70）；
        # (1,3] 是真实资不抵债（盐湖 2.29、海航/东航 1.02~1.15），不能动
        d = f['debt_to_asset']
        f.loc[d > 3, 'debt_to_asset'] = d[d > 3] / 100
        f['leverage'] = f['debt_to_asset']


    f = f.replace([np.inf, -np.inf], np.nan)
    keep = ['code', 'pub_dt', 'eps_growth', 'margin_growth', 'roe_delta',
            'leverage', 'ROE', 'eps_ttm',
            'net_profit_yoy', 'attrib_net_profit_yoy', 'eps_yoy']
    return f[[c for c in keep if c in f.columns]]


# ========== 2. 量价：月频 + 下月收益 ==========
def load_monthly(path):
    d = pd.read_csv(path, encoding='utf-8-sig', dtype={'股票代码': str})
    d['股票代码'] = d['股票代码'].str.zfill(6)
    d['日期'] = pd.to_datetime(d['日期'])
    d['年月'] = d['日期'].dt.to_period('M')
    m = d.groupby(['股票代码', '年月'], as_index=False).last()
    m['下月收益'] = m.groupby('股票代码')['收盘'].shift(-1) / m['收盘'] - 1
    m['月末'] = m['年月'].dt.to_timestamp('M')
    return m.rename(columns={'股票代码': 'code'})


# ========== 3. 按公告日对齐，杜绝未来信息 ==========
def attach(monthly, fund):
    left = monthly.sort_values(['月末', 'code'])
    right = fund.sort_values(['pub_dt', 'code'])
    return pd.merge_asof(left, right, by='code',
                         left_on='月末', right_on='pub_dt',
                         direction='backward',
                         tolerance=pd.Timedelta(days=200))


# ========== 4. 单因子截面 Rank IC ==========
def rank_ic(df, factor, ret='下月收益', min_n=20):
    vals = []
    for _, g in df.groupby('年月'):
        v = g[[factor, ret]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(v) < min_n or v[factor].nunique() < 5:
            continue
        vals.append(v[factor].corr(v[ret], method='spearman'))
    if len(vals) < 3:
        return None
    s = pd.Series(vals, dtype=float)
    sd = s.std(ddof=1)
    return {'IC均值': s.mean(),
            'IR': s.mean() / sd if sd > 0 else np.nan,
            't值': s.mean() / (sd / np.sqrt(len(s))) if sd > 0 else np.nan,
            '胜率': (s > 0).mean(),
            '月份数': len(s)}


def main():
    for p in (FUND_FILE, PRICE_FILE):
        if not os.path.exists(p):
            raise SystemExit(f'找不到文件: {p}')

    print(f'基本面: {FUND_FILE}')
    print(f'量价:   {PRICE_FILE}\n')

    fund = load_fundamental(FUND_FILE)
    monthly = load_monthly(PRICE_FILE)
    data = attach(monthly, fund).dropna(subset=['下月收益'])
    print(f'对齐后 {len(data)} 行  {data["code"].nunique()} 只  '
          f'{data["年月"].nunique()} 个月\n')

    cols = [c for c in ('eps_growth', 'margin_growth') if c in data.columns]
    if cols:
        print('代理因子分布（min/max 与 1% 分位的差距就是极值污染的规模）：')
        print(data[cols].describe(percentiles=[.01, .5, .99]).round(2).to_string())
        print()

    factors = ['margin_growth', 'eps_growth', 'roe_delta', 'leverage',
               'ROE', 'net_profit_yoy', 'attrib_net_profit_yoy', 'eps_yoy']
    factors = [f for f in factors if f in data.columns]

    print('【全部样本】单因子 Rank IC')
    rows = {}
    for f in factors:
        r = rank_ic(data, f)
        if r:
            rows[f] = r
    if rows:
        print(pd.DataFrame(rows).T.round(3).to_string())

    if 'net_profit_yoy' in data.columns:
        sub = data.dropna(subset=['net_profit_yoy'])
        print(f'\n【同一子集，有真值的 {sub["code"].nunique()} 只】代理 vs 真值')
        rows2 = {}
        for f in ['net_profit_yoy', 'margin_growth', 'eps_yoy', 'eps_growth']:
            if f in sub.columns:
                r = rank_ic(sub, f)
                if r:
                    rows2[f] = r
        if rows2:
            print(pd.DataFrame(rows2).T.round(3).to_string())


if __name__ == '__main__':
    main()