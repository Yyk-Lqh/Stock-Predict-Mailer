import os

import pandas as pd


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolve(name):

    for cand in (os.path.join(BASE_DIR, name),
                 os.path.normpath(os.path.join(BASE_DIR, '..', '数据面', name)),
                 os.path.normpath(os.path.join(BASE_DIR, '..', name))):
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError(f'找不到 {name}，已尝试 {BASE_DIR} 及 数据面/')


SRC = _resolve('fundamental_quarterly_new.csv')

OUT = os.path.join(BASE_DIR, 'fundamental_quarterly_cleaned.csv')


df = pd.read_csv(SRC, dtype={'code': str}, encoding='utf-8-sig')
n0 = len(df)

# 1) 2024Q2~2025Q4 源数据整体缩小 100 倍 → 乘回
d = pd.to_numeric(df['debt_to_asset'], errors='coerce')
in_win = df['report_date'].between('2024-06-30', '2025-12-31')
shrunk= (d > 0) & (d < 0.1) & in_win
df.loc[shrunk, 'debt_to_asset'] = d[shrunk] * 100

# 2) 2018Q1~Q3 部分股票被放大 100 倍（34~70 实为 0.34~0.70）→ 除回
d = pd.to_numeric(df['debt_to_asset'], errors='coerce')
percent_format = d > 3
df.loc[percent_format, 'debt_to_asset'] = d[percent_format] / 100
# 注：(1,3] 不动——000792 的 2.29、600115 的 1.15、600221 的 1.02~1.15 是真实资不抵债

# 3) report_date=2026-12-31 实为 FY2025 年报（pub 均早于 2026-12）
#    有真实 2025-12-31 行的股票丢弃该行，否则改标为 2025-12-31，恢复 roe_delta 同比
mis = df['report_date'] == '2026-12-31'
has_25 = set(df.loc[df['report_date'] == '2025-12-31', 'code'])
df = df[~(mis & df['code'].isin(has_25))].copy()
mis = df['report_date'] == '2026-12-31'
df.loc[mis, 'report_date'] = '2025-12-31'

# 4) 校验后落盘
dup = int(df.duplicated(subset=['code', 'report_date']).sum())
d3 = pd.to_numeric(df['debt_to_asset'], errors='coerce')
print(f"原始 {n0} 行 → 清洗后 {len(df)} 行（丢弃冲突 {n0 - len(df)} 行）")
print(f"缩量 ×100：{int(shrunk.sum())} 行    百分制 ÷100：{int(percent_format.sum())} 行")
print(f"报告期改标：{int(mis.sum())} 行    重复键：{dup}（必须为 0）")
print(f"debt_to_asset 范围 {d3.min():.4f} ~ {d3.max():.4f}，"
      f">1 剩 {int((d3 > 1).sum())} 行（真实资不抵债，保留原值）")

df = df.sort_values(['code', 'report_date'])
df.to_csv(OUT, encoding='utf-8-sig', index=False)
print(f"已保存 → {OUT}")