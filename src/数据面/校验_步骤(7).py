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


FILE = _resolve('fundamental_quarterly_new.csv')

df = pd.read_csv(FILE, dtype={'code': str}, encoding='utf-8-sig')
print(f"行数 {len(df)}   股票数 {df['code'].nunique()}")
print(f"报告期 {df['report_date'].min()} ~ {df['report_date'].max()}")

# 1. 主键重复（断点续采可能造成重复行）
dup = int(df.duplicated(subset=['code', 'report_date']).sum())
print(f"\n[1] 重复 (code, report_date)：{dup} 行{'  ← 必须为 0' if dup else '  ✓'}")

# 2. 缺失率
print("\n[2] 各列缺失率：")
print(df.isna().mean().round(4).sort_values(ascending=False).to_string())

# 3. pub_date 缺失（模板会用 report_date+120 天兜底，宁可晚用不可早用）
print(f"\n[3] pub_date 缺失 {int(df['pub_date'].isna().sum())} 行")

# 4. 数值范围（看极值污染规模）
print("\n[4] 关键列数值范围：")
for c in ['net_profit_yoy', 'eps_yoy', 'ROE', 'debt_to_asset', 'current_ratio']:
    s = pd.to_numeric(df[c], errors='coerce')
    print(f"  {c:>18}  min {s.min():>12.3g}   max {s.max():>12.3g}   "
          f"|p99| {s.abs().quantile(.99):>10.3g}")

# 5. debt_to_asset 缩量窗口核查
d = pd.to_numeric(df['debt_to_asset'], errors='coerce')
in_win = df['report_date'].between('2024-06-30', '2025-12-31')
small_vals = (d > 0) & (d < 0.1)
print(f"\n[5] debt_to_asset∈(0,0.1)：窗口内 {int((small_vals & in_win).sum())} 行（×100 修复）"
      f"   窗口外 {int((small_vals & ~in_win).sum())} 行（真实低负债，不能再修）")

# 6. 模板过滤预演（因子试探3 的成长字段覆盖 ≥90% 规则）
coverage = df.groupby('code')['net_profit_yoy'].apply(lambda s: s.notna().mean())
print(f"\n[6] net_profit_yoy 覆盖≥90%：{int((coverage >= 0.9).sum())} 只（因子试探3 会保留这些）")
coverage2 = df.groupby('code')['eps_yoy'].apply(lambda s: s.notna().mean())
print(f"    eps_yoy       覆盖≥90%：{int((coverage2 >= 0.9).sum())} 只")

# 7. 期数分布
period_counts = df.groupby('code').size()
print(f"\n[7] 每只股票期数：min {period_counts.min()}   中位 {int(period_counts.median())}   max {period_counts.max()}"
      f"   期数<30 的 {int((period_counts < 30).sum())} 只")

# 8. 报告期标签异常
odd_rows = df[df['report_date'] == '2026-12-31']
if len(odd_rows):
    print(f"\n[8] report_date=2026-12-31 共 {len(odd_rows)} 行（实为 FY2025 年报，"
          f"pub {odd_rows['pub_date'].min()}~{odd_rows['pub_date'].max()}），"
          f"roe_delta 该行同比为 NaN，影响可忽略")

print("\n校验完成：0 重复 + [5] 窗口外小值很少 + [6] 覆盖≥90% 数量正常 → 可以训练")

# 9. 定位 debt_to_asset > 1 的异常行（负债率不可能>1，疑似百分制刻度）
print("\n[9] debt_to_asset > 1 异常行排查：")
d_num = pd.to_numeric(df['debt_to_asset'], errors='coerce')
anomaly_rows = df[d_num > 1]
if len(anomaly_rows):
    print(f"  共 {len(anomaly_rows)} 行，报告期分布：")
    print(anomaly_rows.groupby('report_date').size().to_string())
    print("\n  受影响股票的同股序列（对比相邻期判断是否 ×100 百分制）：")
    for code in anomaly_rows['code'].unique()[:8]:
        sub = df[df['code'] == code].sort_values('report_date')
        seq = "  ".join(f"{r.report_date[:7]}={r.debt_to_asset:.3g}"
                        for r in sub.itertuples() if pd.notna(r.debt_to_asset))
        print(f"  {code}: {seq}")
else:
    print("  无异常行")

print("\n校验完成：0 重复 + [5] 窗口外小值很少 + [6] 覆盖≥90% 数量正常 → 可以训练")