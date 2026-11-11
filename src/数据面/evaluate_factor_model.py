import os

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolve(name):
    for cand in (os.path.join(BASE_DIR, name),
                 os.path.normpath(os.path.join(BASE_DIR, '..', name))):
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError(f'找不到 {name}，已尝试 {BASE_DIR} 及其上级目录')


#0. 全局参数

position_ratio = 0.1        # 每月取概率最高的 10%
one_way_cost = 0.0015     # 佣金+印花税+滑点，双边约 0.3%
random_seed = 42
pos_threshold = 0.7        # 截面排名前 30% 为正类
WF_TEST_START = '2011-01'   # walk-forward 从此刻开始测试，之前的月份用于训练预热
WF_SEGMENT_LEN = 12              # 每段测试 12 个月；窗口按数据实际长度自动铺满全区间



def newey_west_t(series, lag=None):
    """Newey-West 调整 t 值：修正收益率序列的自相关，月度数据的标准做法"""
    x = np.asarray(series, dtype=float)
    n = len(x)
    if n < 3:
        return np.nan
    if lag is None:
        lag = max(1, int(np.floor(4 * (n / 100) ** (2 / 9))))
    demeaned = x - x.mean()
    γ0 = np.sum(demeaned ** 2) / n
    variance = γ0
    for k in range(1, lag + 1):
        weight = 1 - k / (lag + 1)
        γk = np.sum(demeaned[k:] * demeaned[:-k]) / n
        variance += 2 * weight * γk
    if variance <= 0:
        return np.nan
    return x.mean() / np.sqrt(variance / n)


def plain_t(series):
    x = np.asarray(series, dtype=float)
    if len(x) < 3 or x.std(ddof=1) == 0:
        return np.nan
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))


def max_drawdown(nav_series):
    nav = np.array(nav_series, dtype=float)
    if len(nav) == 0:
        return np.nan
    peaks = np.maximum.accumulate(nav)
    return float((nav / peaks - 1).min())


def intercept_test(y, x, lag=None):
    """y = α + β·x，检验截距 α 是否显著
    注意：不能对 OLS 残差做 t 检验（残差均值恒为 0），必须用截距标准误"""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    n = len(y)
    slope, intercept = np.polyfit(x, y, 1)
    residuals = y - (intercept + slope * x)
    if lag is None:
        lag = max(1, int(np.floor(4 * (n / 100) ** (2 / 9))))
    x̄ = x.mean()
    Sxx = np.sum((x - x̄) ** 2)
    residual_variance = np.sum(residuals ** 2) / n
    for k in range(1, lag + 1):
        weight = 1 - k / (lag + 1)
        residual_variance += 2 * weight * np.sum(residuals[k:] * residuals[:-k]) / n
    SE_α = np.sqrt(max(residual_variance, 1e-12) * (1 / n + x̄ ** 2 / max(Sxx, 1e-12)))
    return slope, intercept, SE_α, intercept / SE_α


# 1. 读数据

df = pd.read_csv(_resolve('all_stock_history120_deep_cleaned.csv'),
                 encoding='utf-8-sig', dtype={'股票代码': str})
df['股票代码'] = df['股票代码'].str.zfill(6)
# ... existing code ...
df['日期'] = pd.to_datetime(df['日期'])
df = df.sort_values(['股票代码', '日期']).reset_index(drop=True)


#2. 转月频
df['年月'] = df['日期'].dt.to_period('M')
monthly = df.groupby(['股票代码', '年月'], as_index=False).last()

monthly['下月收益'] = (monthly.groupby('股票代码')['收盘'].shift(-1)
                       / monthly['收盘'] - 1)

# 标签截面化：每月按收益排名前 30% 为正类
# 若用「下月收益 > 0」，正类率会随大盘在 27%~80% 间漂移，AUC 变成择时能力
monthly['目标'] = monthly.groupby('年月')['下月收益'].transform(
    lambda s: (s.rank(pct=True) > pos_threshold).astype(int))


# 2.5 合并基本面因子
monthly['月末'] = monthly['年月'].dt.to_timestamp('M')

fund = pd.read_csv(_resolve('fundamental_quarterly_cleaned.csv'),
                   dtype={'code': str}, encoding='utf-8-sig')
fund['report_dt'] = pd.to_datetime(fund['report_date'])
fund['pub_dt'] = pd.to_datetime(fund['pub_date'], errors='coerce')
# 公告日缺失时用报告期 +120 天兜底：宁可晚用，绝不可早用
fund['pub_dt'] = fund['pub_dt'].fillna(fund['report_dt'] + pd.Timedelta(days=120))
fund = fund.dropna(subset=['pub_dt']).sort_values(['code', 'pub_dt', 'report_dt'])
fund = fund.replace([np.inf, -np.inf], np.nan)

# 只保留成长字段覆盖 ≥90% 的股票：
# 排掉完全没采集的 100 只，也排掉只补了一部分的那几只
coverage = fund.groupby('code')['net_profit_yoy'].apply(lambda s: s.notna().mean())
keep_codes = set(coverage[coverage >= 0.9].index)
fund = fund[fund['code'].isin(keep_codes)]
print(f'基本面有效股票 {len(keep_codes)} 只')

# roe_delta = ROE 同比变化。差值型，分母不会接近 0，分布天然干净
ly = fund[['code', 'report_dt', 'ROE']].copy()
ly['report_dt'] = ly['report_dt'] + pd.DateOffset(years=1)
ly = ly.rename(columns={'ROE': 'ROE_ly'})
fund = fund.merge(ly, on=['code', 'report_dt'], how='left')
fund['roe_delta'] = fund['ROE'] - fund['ROE_ly']

fund_raw_cols = ['roe_delta', 'eps_yoy', 'net_profit_yoy']

fund = fund.rename(columns={'code': '股票代码'})

# 按公告日回溯对齐，杜绝用未公布财报做预测
monthly = pd.merge_asof(
    monthly.sort_values(['月末', '股票代码']),
    fund.sort_values(['pub_dt', '股票代码'])[['股票代码', 'pub_dt'] + fund_raw_cols],
    by='股票代码', left_on='月末', right_on='pub_dt',
    direction='backward', tolerance=pd.Timedelta(days=200))

# 截面分位化：net_profit_yoy 最大 266562 倍，原始值会带偏随机森林的分裂点

for col in fund_raw_cols:
    monthly[f'{col}_r'] = monthly.groupby('年月')[col].rank(pct=True)

# 三个基本面秩因子的共线性：>0.7 视为重复投票，只留 IC 强的一个
print('基本面秩因子相关性：')
print(monthly[['roe_delta_r', 'eps_yoy_r', 'net_profit_yoy_r']]
      .corr(method='spearman').round(2).to_string())


last_month = monthly['年月'].max()
monthly = monthly[monthly['年月'] < last_month].copy()
print(f"月频 {len(monthly)} 行   {monthly['股票代码'].nunique()} 只   "
      f"{monthly['年月'].nunique()} 个月")

#3. 特征（白名单，只保留有信号 + 风控必需）
# 已剔除：动量_10日/动量_60日（中位数/均值=0.13 纯噪声）
#         振幅/昨日收益率/成交量比率/波动率_10日（|t|<0.5 无信号）
#         PE分位/PS分位（与 PB 相关 0.64，重复投票）
# 注意：动量_20日/波动率_20日/价格位置_20日 单因子不稳定，但在组合里提供分散化，
#       不可删除（6 特征实验显示删除后单月超额 -30.42%，最大回撤 -41%）

FEATS = ['PB分位', '收益率', '均线偏移', '动量_20日',
         '量价相关_10日', '波动率_60日', '价格位置_20日',
         'roe_delta_r', 'eps_yoy_r']


missing_cols = [c for c in FEATS if c not in monthly.columns]
if missing_cols:
    raise KeyError(f"以下特征列不存在，请先跑 build_price_volume_features.py：{missing_cols}")


monthly = monthly.replace([np.inf, -np.inf], np.nan)
monthly = monthly.dropna(subset=FEATS + ['下月收益']).reset_index(drop=True)

# 截面从 282 只缩到 190 只，原来的「前 30%」是基于全池排的，
# 样本一变排名就失效，必须在最终样本上重算
monthly['目标'] = monthly.groupby('年月')['下月收益'].transform(
    lambda s: (s.rank(pct=True) > pos_threshold).astype(int))


segment_start = None
if segment_start:
    monthly = monthly[monthly['年月'] >= pd.Period(segment_start, 'M')].reset_index(drop=True)
    # 截断后截面变了，目标要再算一次
    monthly['目标'] = monthly.groupby('年月')['下月收益'].transform(
        lambda s: (s.rank(pct=True) > pos_threshold).astype(int))
    print(f'已限制到 {segment_start} 之后：{len(monthly)} 行  '
          f'{monthly["年月"].nunique()} 个月')



print(f"特征 {len(FEATS)} 个：{FEATS}")
print(f"清洗后 {len(monthly)} 行   实际起始月 {monthly['年月'].min()}   "
      f"结束月 {monthly['年月'].max()}")

# 4. 选股函数
def select_stocks(group, ratio=None):
    ratio = position_ratio if ratio is None else ratio
    return group.nlargest(max(5, int(len(group) * ratio)), 'proba')


def select_by_group(group, group_col, within_ratio=0.3):
    """组内中性化选股：每个分组内部各取概率前 组内比例"""
    pieces = []
    for _, h in group.groupby(group_col):
        if len(h) < 3:
            continue
        pieces.append(h.nlargest(max(1, int(len(h) * within_ratio)), 'proba'))
    return pd.concat(pieces) if pieces else group.iloc[0:0]


#5. 切分 训练



months = sorted(monthly['年月'].unique())
regime_split = months[len(months) // 2]        # regime 检验分界：取样本中位月
cut = months[int(len(months) * 0.8)]   # 训练/测试 80/20 切分
train = monthly[monthly['年月'] <= cut].copy()
test = monthly[monthly['年月'] > cut].copy()



model = RandomForestClassifier(
    n_estimators=300, max_depth=4,
    min_samples_split=40, min_samples_leaf=15,
    max_features='sqrt', random_state=random_seed, n_jobs=-1,
)
model.fit(train[FEATS], train['目标'])

train['proba'] = model.predict_proba(train[FEATS])[:, 1]
test['proba'] = model.predict_proba(test[FEATS])[:, 1]

auc = roc_auc_score(test['目标'], test['proba'])
auc_tr = roc_auc_score(train['目标'], train['proba'])
print(f"训练 AUC {auc_tr:.4f}   测试 AUC {auc:.4f}   衰减 {auc_tr - auc:+.4f}")

#6. 验证1：逐月 AUC
print("\n【验证1】逐月 AUC")
month_aucs = []
for m, g in test.groupby('年月'):
    if g['目标'].nunique() < 2:
        print(f"  {m}  {len(g):>3} 只  单一类别，跳过")
        continue
    a = roc_auc_score(g['目标'], g['proba'])
    ic, _ = spearmanr(g['proba'], g['下月收益'])
    month_aucs.append(a)
    print(f"  {m}  {len(g):>3} 只  正类 {g['目标'].mean():>4.0%}  "
          f"AUC {a:.3f}  IC {ic:+.3f}")

if month_aucs:
    print(f"  → AUC>0.55 的月份 {sum(1 for x in month_aucs if x > 0.55)}"
          f"/{len(month_aucs)}   均值 {np.mean(month_aucs):.3f}   "
          f"最差 {np.min(month_aucs):.3f}   最好 {np.max(month_aucs):.3f}   "
          f"标准差 {np.std(month_aucs):.3f}")

#7. 验证2：打乱标签对照
rng = np.random.default_rng(random_seed)
fake = np.array([roc_auc_score(rng.permutation(test['目标'].values),
                               test['proba'].values) for _ in range(200)])
print(f"\n【验证2】打乱测试标签 200 次")
print(f"  随机 AUC 均值 {fake.mean():.3f}   95% 分位 {np.percentile(fake, 95):.3f}")
print(f"  真实 AUC {auc:.3f} 的 p 值 = {(fake >= auc).mean():.4f}")

#8. 验证3：每月 Top 组合的实际收益
print("\n【验证3】每月 Top 组合的下月实际收益")
exs = []
for m, g in test.groupby('年月'):
    if len(g) < 5:
        continue
    top = select_stocks(g)
    ex = top['下月收益'].mean() - g['下月收益'].mean()
    exs.append(ex)
    print(f"  {m}  Top{len(top):>2} {top['下月收益'].mean():>+7.2%}   "
          f"全池 {g['下月收益'].mean():>+7.2%}   超额 {ex:>+7.2%}")

if exs:
    print(f"\n  月超额 均值 {np.mean(exs):+.2%}   中位数 {np.median(exs):+.2%}   "
          f"标准差 {np.std(exs):.2%}   正超额 {sum(1 for x in exs if x > 0)}/{len(exs)} 个月")
    print(f"  普通 t = {plain_t(exs):.2f}   Newey-West t = {newey_west_t(exs):.2f}"
          f"   ← 以后者为准")

#  9. 验证4：累计净值（含交易成本）
last_positions = set()
nav_p, nav_b, nav_net = 1.0, 1.0, 1.0
nav_gross, nav_net_hist, nav_bench = [1.0], [1.0], [1.0]
turnover_list = []
for m, g in test.groupby('年月'):
    if len(g) < 5:
        continue
    this_month = select_stocks(g)
    this_month_codes = set(this_month['股票代码'])
    turnover = 0.0 if not last_positions else 1 - len(this_month_codes & last_positions) / len(this_month_codes)
    turnover_list.append(turnover)

    gross_ret = this_month['下月收益'].mean()
    nav_p *= (1 + gross_ret)
    nav_b *= (1 + g['下月收益'].mean())
    nav_net *= (1 + gross_ret - turnover * one_way_cost * 2)
    nav_gross.append(nav_p)
    nav_net_hist.append(nav_net)
    nav_bench.append(nav_b)
    last_positions = this_month_codes

print(f"\n【验证4】{test['年月'].nunique()} 个月累计")
print(f"  Top 组合(毛)  {nav_p - 1:+.2%}   最大回撤 {max_drawdown(nav_gross):.2%}")
print(f"  Top 组合(净)  {nav_net - 1:+.2%}   最大回撤 {max_drawdown(nav_net_hist):.2%}")
print(f"  全池          {nav_b - 1:+.2%}   最大回撤 {max_drawdown(nav_bench):.2%}")
print(f"  相对全池(净)  {nav_net / nav_b - 1:+.2%}   ← 复利口径，别用相减")
if turnover_list:
    print(f"  月均换手 {np.mean(turnover_list):.1%}   年化成本约 {np.mean(turnover_list) * one_way_cost * 2 * 12:.2%}")

#  10. 验证5：分档单调性 + 多空组合
print("\n【验证5】按概率分 5 档，看单调性（多空组合 β≈0，能直接看 alpha）")
quintiles = {k: [] for k in range(5)}
for m, g in test.groupby('年月'):
    if len(g) < 25:
        continue
    g = g.copy()
    g['档位'] = pd.qcut(g['proba'].rank(method='first'), 5, labels=False)
    for k in range(5):
        quintiles[k].append(g.loc[g['档位'] == k, '下月收益'].mean())

for k in range(5):
    print(f"  D{k + 1}  月均 {np.mean(quintiles[k]):+.2%}   正收益月 "
          f"{sum(1 for v in quintiles[k] if v > 0)}/{len(quintiles[k])}")
long_short = np.array(quintiles[4]) - np.array(quintiles[0])
print(f"  多空(D5-D1) 月均 {long_short.mean():+.2%}   正收益 "
      f"{sum(1 for v in long_short if v > 0)}/{len(long_short)}")
print(f"  多空 普通t = {plain_t(long_short):.2f}   Newey-West t = {newey_west_t(long_short):.2f}")

#11. 特征重要性
imp = pd.Series(model.feature_importances_, index=FEATS).sort_values(ascending=False)
print(f"\n特征重要性:\n{imp.round(4).to_string()}")
vol_family = [c for c in FEATS if '波动' in c]
print(f"  波动类特征合计占比 {imp[vol_family].sum():.1%}   "
      f"（>40% 说明模型本质在做多高波动）")

#12. 诊断A：训练期 vs 测试期超额
print("\n【诊断A】训练期(模型见过) vs 测试期(没见过)")
train_exs = []
for m, g in train.groupby('年月'):
    if len(g) < 5:
        continue
    train_exs.append(select_stocks(g)['下月收益'].mean() - g['下月收益'].mean())

print(f"  训练期  月超额均值 {np.mean(train_exs):+.2%}   "
      f"中位数 {np.median(train_exs):+.2%}   正超额 "
      f"{sum(1 for x in train_exs if x > 0)}/{len(train_exs)}")
print(f"  测试期  月超额均值 {np.mean(exs):+.2%}   "
      f"中位数 {np.median(exs):+.2%}   正超额 "
      f"{sum(1 for x in exs if x > 0)}/{len(exs)}")

#13. 诊断B：留一股票
print("\n【诊断B】留一股票（训练时排除该股，再预测它）")
codes_all = monthly['股票代码'].unique()
rng2 = np.random.default_rng(0)
pick = rng2.choice(codes_all, size=min(12, len(codes_all)), replace=False)

oos_aucs = []
for code in pick:
    tr = monthly[monthly['股票代码'] != code]
    te = monthly[monthly['股票代码'] == code]
    if te['目标'].nunique() < 2 or len(te) < 20:
        continue
    m = RandomForestClassifier(
        n_estimators=100, max_depth=4, min_samples_split=40,
        min_samples_leaf=15, max_features='sqrt',
        random_state=random_seed, n_jobs=-1,
    )
    m.fit(tr[FEATS], tr['目标'])
    p = m.predict_proba(te[FEATS])[:, 1]
    a = roc_auc_score(te['目标'], p)
    oos_aucs.append(a)
    print(f"  {code}  {len(te):>2} 个月  AUC {a:.3f}")

loo_mean = np.mean(oos_aucs) if oos_aucs else np.nan
if oos_aucs:
    print(f"\n  留一 AUC 均值 {loo_mean:.3f}   "
          f"(in-sample {auc_tr:.3f}, 原测试 {auc:.3f})")
    print(f"  → 若明显低于原测试，说明测试分数里含「同月其他股票」的 beta 转移")

#14. 诊断C：月内打乱标签
print("\n【诊断C】月内打乱标签 200 次（保持每月正类率不变）")
fake2 = []
for _ in range(200):
    y_shuf = test.groupby('年月')['目标'].transform(
        lambda x: rng.permutation(x.values))
    fake2.append(roc_auc_score(y_shuf, test['proba']))
fake2 = np.array(fake2)
print(f"  月内随机 AUC 均值 {fake2.mean():.3f}   95% 分位 {np.percentile(fake2, 95):.3f}")
print(f"  真实 {auc:.3f} 的 p 值 = {(fake2 >= auc).mean():.4f}")

# 15. 诊断D：Walk-forward（覆盖全部区间）
# 窗口按数据实际月份动态生成：从 WF_测试起始 开始，每 WF_段长 个月一段，铺满到最新月
start_period = pd.Period(WF_TEST_START, 'M')
testable_months = [mm for mm in months if mm >= start_period]
WINDOWS = []
i = 0
while i + WF_SEGMENT_LEN <= len(testable_months):
    WINDOWS.append((str(testable_months[i]), str(testable_months[i + WF_SEGMENT_LEN - 1])))
    i += WF_SEGMENT_LEN

print(f"\n【诊断D】Walk-forward（每段训练完，测未来 {WF_SEGMENT_LEN} 个月）")
print(f"  共 {len(WINDOWS)} 段，覆盖 {testable_months[0]} ~ {testable_months[min(len(testable_months), WF_SEGMENT_LEN * len(WINDOWS)) - 1]}"
      f"（测试起始 {WF_TEST_START}，之前用于训练预热）")
print(f"{'测试区间':>18}{'训练行数':>10}{'训练月数':>10}{'测试样本':>10}"
      f"{'AUC':>8}{'月超额':>10}{'正超额':>10}")

wf_results = []
for ts_str, te_str in WINDOWS:
    ts = pd.Period(ts_str, 'M')
    te_p = pd.Period(te_str, 'M')

    tr = monthly[monthly['年月'] < ts]
    te = monthly[(monthly['年月'] >= ts) & (monthly['年月'] <= te_p)]
    if len(tr) < 300 or te['目标'].nunique() < 2 or len(te) < 100:
        print(f"  {ts_str}~{te_str}  样本不足，跳过")
        continue

    m = RandomForestClassifier(
        n_estimators=200, max_depth=4, min_samples_split=40,
        min_samples_leaf=15, max_features='sqrt',
        random_state=random_seed, n_jobs=-1,
    )
    m.fit(tr[FEATS], tr['目标'])
    te = te.copy()
    te['proba'] = m.predict_proba(te[FEATS])[:, 1]

    a = roc_auc_score(te['目标'], te['proba'])
    ex_list = []
    for mm, g in te.groupby('年月'):
        if len(g) < 5:
            continue
        ex_list.append(select_stocks(g)['下月收益'].mean() - g['下月收益'].mean())

    avg_ex = np.mean(ex_list) if ex_list else np.nan
    positive_ratio = sum(1 for x in ex_list if x > 0)
    wf_results.append((ts_str, te_str, a, avg_ex, ex_list))
    print(f"  {ts_str}~{te_str}  {len(tr):>9}  {tr['年月'].nunique():>9}  "
          f"{len(te):>9}  {a:>7.3f}  {avg_ex:>+9.2%}  {positive_ratio:>5}/{len(ex_list)}")

aucs_wf, exs_wf, all_seg_excess = [], [], []
if wf_results:
    aucs_wf = [r[2] for r in wf_results]
    exs_wf = [r[3] for r in wf_results]
    all_seg_excess = [v for r in wf_results for v in r[4]]
    print(f"\n  各段 AUC：{['%.3f' % x for x in aucs_wf]}   均值 {np.mean(aucs_wf):.3f}")
    print(f"  各段超额：{['%+.2f%%' % (x * 100) for x in exs_wf]}   均值 {np.mean(exs_wf):+.2%}")
    print(f"  合计 {len(all_seg_excess)} 个月  月均超额 {np.mean(all_seg_excess):+.2%}   "
          f"正超额 {sum(1 for x in all_seg_excess if x > 0)}/{len(all_seg_excess)}")
    print(f"  普通 t = {plain_t(all_seg_excess):.2f}   Newey-West t = {newey_west_t(all_seg_excess):.2f}")

    print(f"\n  {'区间':>18}{'月均超额':>12}{'判定':>10}")
    for r in wf_results:
        verdict = '有效' if r[3] > 0.005 else ('失效' if r[3] < -0.005 else '无效')
        print(f"  {r[0]}~{r[1]}  {r[3]:>+11.2%}  {verdict:>10}")

#16. 风格归因：超额到底是不是 beta
print("\n【风格归因】Top 组合收益 = β × 全池收益 + α")
attribution = []
for m, g in test.groupby('年月'):
    if len(g) < 5:
        continue
    attribution.append((select_stocks(g)['下月收益'].mean(), g['下月收益'].mean()))

attribution = np.array(attribution)
y, x = attribution[:, 0], attribution[:, 1]
β, α, SE_α, t_α = intercept_test(y, x)
R2 = np.corrcoef(x, y)[0, 1] ** 2
print(f"  β = {β:.2f}   R² = {R2:.3f}   α = {α:+.2%}/月   "
      f"SE(α) = {SE_α:.2%}   t(α) = {t_α:.2f}")
print(f"  → R²>0.7 说明超额大部分是市场杠杆；t(α)<2 说明选股能力不显著")
print(f"  → 注意：不能对 OLS 残差做 t 检验（残差均值恒为 0），必须检验截距本身")

#17. 波动率中性化
print("\n【中性化】每月按波动率三组内各选 Top30%")
neutralized_result = {}
for seg_name, seg in [('训练', train), ('测试', test)]:
    ex = []
    for m, g in seg.groupby('年月'):
        if len(g) < 30:
            continue
        g = g.copy()
        g['波动组'] = pd.qcut(g['波动率_60日'], 3, labels=False, duplicates='drop')
        if g['波动组'].nunique() < 3:
            continue
        picked = select_by_group(g, '波动组', 0.3)
        ex.append(picked['下月收益'].mean() - g['下月收益'].mean())
    if ex:
        neutralized_result[seg_name] = (np.mean(ex), newey_west_t(ex), len(ex))
        print(f"  {seg_name}期  中性化后月超额 {np.mean(ex):+.2%}   标准差 {np.std(ex):.2%}   "
              f"正超额 {sum(1 for v in ex if v > 0)}/{len(ex)}   NW-t {newey_west_t(ex):.2f}")
print(f"  → 中性化后超额大幅缩水 = 收益来自波动率暴露，不是选股")

#18. 波动率目标化（含仓位相关性诊断）
print("\n【波动率目标化】按组合波动率动态降仓")
nav_vt, nav_vt_b = 1.0, 1.0
nav_target, nav_target_bench = [1.0], [1.0]
ex_vt, pos_record, ret_record = [], [], []
for m, g in test.groupby('年月'):
    if len(g) < 5:
        continue
    top = select_stocks(g)
    port_vol = top['波动率_60日'].mean()
    pool_vol = g['波动率_60日'].median()
    position = float(np.clip(pool_vol / port_vol, 0.2, 1.0)) if port_vol > 0 else 1.0
    raw_ret = top['下月收益'].mean()
    period_ret = position * raw_ret
    pos_record.append(position)
    ret_record.append(raw_ret)
    ex_vt.append(period_ret - g['下月收益'].mean())
    nav_vt *= (1 + period_ret)
    nav_vt_b *= (1 + g['下月收益'].mean())
    nav_target.append(nav_vt)
    nav_target_bench.append(nav_vt_b)

pos_ret_corr = np.corrcoef(pos_record, ret_record)[0, 1] if len(pos_record) > 2 else np.nan
print(f"  月均仓位 {np.mean(pos_record):.0%}   仓位与本期收益相关性 {pos_ret_corr:+.2f}"
      f"   （|r|<0.2 说明仓位调整与收益无关，只是随机降仓）")
print(f"  累计(目标化) {nav_vt - 1:+.2%}   最大回撤 {max_drawdown(nav_target):.2%}")
print(f"  全池         {nav_vt_b - 1:+.2%}   最大回撤 {max_drawdown(nav_target_bench):.2%}")
print(f"  相对全池     {nav_vt / nav_vt_b - 1:+.2%}")
print(f"  月超额 均值 {np.mean(ex_vt):+.2%}   标准差 {np.std(ex_vt):.2%}   "
      f"正超额 {sum(1 for v in ex_vt if v > 0)}/{len(ex_vt)}")
print(f"  普通 t = {plain_t(ex_vt):.2f}   Newey-West t = {newey_west_t(ex_vt):.2f}")
IR_raw = np.mean(exs) / np.std(exs) if np.std(exs) > 0 else np.nan
IR_target = np.mean(ex_vt) / np.std(ex_vt) if np.std(ex_vt) > 0 else np.nan
print(f"  月度 IR：原始 {IR_raw:.3f} → 目标化 {IR_target:.3f}   "
      f"（若基本持平，说明只是线性缩放，没有新增信息）")

# 19. 单因子截面 IC
print("\n【单因子 IC】逐月 Spearman，稳健 t")
rows = []
for f in FEATS:
    monthly_ics = []
    for m, g in monthly.groupby('年月'):
        if g[f].nunique() < 20:
            continue
        ic, _ = spearmanr(g[f], g['下月收益'])
        monthly_ics.append(ic)
    monthly_ics = pd.Series(monthly_ics).dropna()
    t = monthly_ics.mean() / (monthly_ics.std() / np.sqrt(len(monthly_ics)))
    pos_ratio = (monthly_ics > 0).mean()
    rows.append((f, monthly_ics.mean(), t, pos_ratio, len(monthly_ics)))

ic_df = pd.DataFrame(rows, columns=['因子', 'IC均值', 't值', '正IC占比', '月份数'])
ic_df = ic_df.reindex(ic_df['IC均值'].abs().sort_values(ascending=False).index)
print(ic_df.round(3).to_string(index=False))
ic_means = dict(zip(ic_df['因子'], ic_df['IC均值']))

#20. 单因子组合
print("\n【单因子组合】方向取 IC 符号，每月 Top10%，分训练/测试期")
print(f"{'因子':>14}{'训练期月超额':>14}{'正超额月':>10}{'测试期月超额':>14}{'正超额月':>10}")
for f in FEATS:
    if abs(ic_means[f]) < 0.02:
        continue
    direction = 1 if ic_means[f] > 0 else -1
    seg_results = []
    for mask in [monthly['年月'] <= cut, monthly['年月'] > cut]:
        seg = monthly[mask]
        ex = []
        for m, g in seg.groupby('年月'):
            if g[f].nunique() < 20:
                continue
            ranks = (g[f] * direction).rank(pct=True)
            top = g.loc[ranks >= 1 - position_ratio]
            if len(top) < 3:
                continue
            ex.append(top['下月收益'].mean() - g['下月收益'].mean())
        seg_results.append((np.mean(ex) if ex else np.nan,
                       f"{sum(1 for x in ex if x > 0)}/{len(ex)}"))
    print(f"{f:>14}{seg_results[0][0]:>+13.2%}{seg_results[0][1]:>10}"
          f"{seg_results[1][0]:>+13.2%}{seg_results[1][1]:>10}")

#21. 估值因子（PE/PS 已因共线删除）
print("\n【估值因子】只保留 IC 最强的 PB分位")
monthly_ics = []
for m, g in monthly.groupby('年月'):
    if g['PB分位'].nunique() > 20:
        monthly_ics.append(spearmanr(g['PB分位'], g['下月收益'])[0])
monthly_ics = pd.Series(monthly_ics).dropna()
t = monthly_ics.mean() / (monthly_ics.std() / np.sqrt(len(monthly_ics)))
print(f"PB分位  IC {monthly_ics.mean():+.3f}  t {t:+.2f}  正IC {(monthly_ics > 0).mean():.0%}  "
      f"月份数 {len(monthly_ics)}")
print("  → PE/PS 与 PB 相关性 0.64 且 IC 均不显著，已删除，避免重复投票")

# 22. regime 检验：因子方向有没有翻号
print(f"\n【regime 检验】单因子 IC 以 {regime_split} 为界分两段")
print(f"{'因子':>14}{'前段IC':>10}{'前段t':>8}{'前段月':>8}"
      f"{'后段IC':>10}{'后段t':>8}{'后段月':>8}{'翻号':>6}")

flip_count = 0
regime_detail = []
for f in FEATS:
    seg_data = []
    for mask in [monthly['年月'] < regime_split, monthly['年月'] >= regime_split]:
        monthly_ics = []
        for m, g in monthly[mask].groupby('年月'):
            if g[f].nunique() < 20:
                continue
            monthly_ics.append(spearmanr(g[f], g['下月收益'])[0])
        monthly_ics = pd.Series(monthly_ics).dropna()
        t = monthly_ics.mean() / (monthly_ics.std() / np.sqrt(len(monthly_ics))) if len(monthly_ics) > 2 else np.nan
        seg_data.append((monthly_ics.mean(), t, len(monthly_ics)))

    front, back = seg_data[0], seg_data[1]
    flipped = "是" if front[0] * back[0] < 0 else ""
    if flipped:
        flip_count += 1
    regime_detail.append((f, front[0], front[1], front[2], back[0], back[1], back[2], flipped))

regime_detail.sort(key=lambda r: -abs(r[1] - r[4]))
for f, front_ic, front_t, front_n, back_ic, back_t, back_n, flipped in regime_detail:
    print(f"{f:>14}{front_ic:>+10.3f}{front_t:>+8.2f}{front_n:>8}"
          f"{back_ic:>+10.3f}{back_t:>+8.2f}{back_n:>8}{flipped:>6}")

print(f"\n  翻号因子 {flip_count}/{len(FEATS)} 个")
if flip_count <= len(FEATS) * 0.3:
    print("  → 多数因子方向一致，只是强度不同：属样本量问题，扩股票池可改善")
else:
    print("  → 大量因子翻号：市场结构已变，扩池子无用，必须换因子或做 regime 切换")

# 23. 极端值依赖 + 稳健性比值
print("\n【极端值依赖】剔除 IC 最极端的月份后，信号还剩多少")
print(f"{'因子':>14}{'均值':>9}{'中位数':>9}{'比值':>7}{'偏度':>7}"
      f"{'剔10%后':>9}{'剔10%t':>9}{'剔20%后':>9}{'剔20%t':>9}")

robust_pool = []
for f in FEATS:
    monthly_ics = []
    for m, g in monthly.groupby('年月'):
        if g[f].nunique() < 20:
            continue
        monthly_ics.append(spearmanr(g[f], g['下月收益'])[0])
    monthly_ics = pd.Series(monthly_ics).dropna()
    ic = monthly_ics.values
    n = len(ic)
    ic_mean = ic.mean()
    ic_median = np.median(ic)
    med_mean_ratio = abs(ic_median / ic_mean) if ic_mean != 0 else 0
    ic_skew = pd.Series(ic).skew()

    trimmed_stats = []
    for trim_ratio in [0.1, 0.2]:
        trim_n = max(1, int(n * trim_ratio))
        keep_idx = np.argsort(np.abs(ic - ic_mean))[:-trim_n]
        remaining = ic[keep_idx]
        t_remaining = remaining.mean() / (remaining.std(ddof=1) / np.sqrt(len(remaining)))
        trimmed_stats.append((remaining.mean(), t_remaining))

    print(f"{f:>14}{ic_mean:>+9.4f}{ic_median:>+9.4f}{med_mean_ratio:>7.2f}{ic_skew:>+7.2f}"
          f"{trimmed_stats[0][0]:>+9.4f}{trimmed_stats[0][1]:>+9.2f}"
          f"{trimmed_stats[1][0]:>+9.4f}{trimmed_stats[1][1]:>+9.2f}")

    # 稳健判定：中位数/均值 > 0.6 且 |t| > 1.2
    t_val = ic_mean / (monthly_ics.std() / np.sqrt(n))
    if med_mean_ratio > 0.6 and abs(t_val) > 1.2 :
        robust_pool.append(f)

print(f"\n  稳健因子 {len(robust_pool)} 个：{robust_pool}")
print("  → 比值<0.6 说明信号靠少数极端月份撑着，不可交易")

#24. 稳健因子等权合成
print(f"\n【因子合成】{len(robust_pool)} 个稳健因子等权合成")
composite_factors = robust_pool if len(robust_pool) >= 2 else []

if composite_factors:
    print("  合成前相关性：")
    print(monthly[composite_factors].corr().round(2).to_string())

    # 截面标准化后按 IC 符号统一方向
    z = monthly.groupby('年月')[composite_factors].transform(
        lambda s: (s - s.mean()) / (s.std() + 1e-9))
    direction = np.array([-1 if ic_means[f] < 0 else 1 for f in composite_factors])
    monthly['合成分'] = (z * direction).mean(axis=1)

    monthly_ics = []
    for m, g in monthly.groupby('年月'):
        if g['合成分'].nunique() < 20:
            continue
        monthly_ics.append(spearmanr(g['合成分'], g['下月收益'])[0])
    monthly_ics = pd.Series(monthly_ics).dropna()
    t = monthly_ics.mean() / (monthly_ics.std() / np.sqrt(len(monthly_ics)))
    print(f"\n  合成 IC {monthly_ics.mean():+.4f}   中位数 {np.median(monthly_ics):+.4f}   "
          f"t {t:.2f}   正IC {(monthly_ics > 0).mean():.0%}")
    print(f"  → 若 t 仍 < 2，说明这批因子合起来也不够强，需换维度")

    # 合成因子直接选股（不用模型），Top10%
    print(f"\n  {'区间':>22}{'月超额':>10}{'正超额月':>10}{'NW-t':>8}")
    for seg_name, mask in [('全样本', monthly['年月'].notna()),
                        (f'前段 {monthly["年月"].min()}~{regime_split - 1}', monthly['年月'] < regime_split),
                        (f'后段 {regime_split}~{monthly["年月"].max()}', monthly['年月'] >= regime_split)]:
        seg = monthly[mask]
        ex = []
        for m, g in seg.groupby('年月'):
            top = g.loc[g['合成分'].rank(pct=True) >= 1 - position_ratio]
            if len(top) < 3:
                continue
            ex.append(top['下月收益'].mean() - g['下月收益'].mean())
        if ex:
            print(f"  {seg_name:>22}{np.mean(ex):>+9.2%}"
                  f"{sum(1 for v in ex if v > 0):>7}/{len(ex):<3}{newey_west_t(ex):>8.2f}")
else:
    print("  稳健因子不足 2 个，跳过合成")

#25. 结论汇总
print("\n" + "=" * 66)
print("【结论汇总】")
print(f"  1. 测试 AUC {auc:.3f}   留一 AUC {loo_mean:.3f}（跨股票泛化）")
print(f"  2. 风格归因 β={β:.2f}  R²={R2:.3f}  α={α:+.2%}/月  t(α)={t_α:.2f}")
if '训练' in neutralized_result and '测试' in neutralized_result:
    print(f"  3. 中性化后超额  训练 {neutralized_result['训练'][0]:+.2%}(NW-t {neutralized_result['训练'][1]:.2f})   "
          f"测试 {neutralized_result['测试'][0]:+.2%}(NW-t {neutralized_result['测试'][1]:.2f})")
if all_seg_excess:
    print(f"  4. WF {len(wf_results)} 段  均值 AUC {np.mean(aucs_wf):.3f}   "
          f"月超额 {np.mean(all_seg_excess):+.2%}   NW-t {newey_west_t(all_seg_excess):.2f}")
print(f"  5. 月度 IR  原始 {IR_raw:.3f} → 目标化 {IR_target:.3f}")
print(f"  6. 波动族特征占比 {imp[vol_family].sum():.1%}")
print(f"  7. regime 翻号 {flip_count}/{len(FEATS)}   稳健因子 {len(robust_pool)}/{len(FEATS)}")
print("-" * 66)
print("  判定标准：")
print("    NW-t > 2  且  熊市段超额 > 0  且  regime 翻号 < 30%  才考虑实盘")
print("=" * 66)

#26. 中性化版本的 Walk-forward
print("\n【诊断E】中性化选股的 Walk-forward（这才是可实盘的形态）")
print(f"{'测试区间':>18}{'AUC':>8}{'中性化月超额':>14}{'标准差':>9}"
      f"{'正超额':>9}{'NW-t':>8}")

neutral_wf = []
for ts_str, te_str in WINDOWS:
    ts = pd.Period(ts_str, 'M')
    te_p = pd.Period(te_str, 'M')
    tr = monthly[monthly['年月'] < ts]
    te = monthly[(monthly['年月'] >= ts) & (monthly['年月'] <= te_p)]
    if len(tr) < 300 or te['目标'].nunique() < 2 or len(te) < 100:
        continue

    m = RandomForestClassifier(
        n_estimators=200, max_depth=4, min_samples_split=40,
        min_samples_leaf=15, max_features='sqrt',
        random_state=random_seed, n_jobs=-1,
    )
    m.fit(tr[FEATS], tr['目标'])
    te = te.copy()
    te['proba'] = m.predict_proba(te[FEATS])[:, 1]

    a = roc_auc_score(te['目标'], te['proba'])
    ex = []
    for mm, g in te.groupby('年月'):
        if len(g) < 30:
            continue
        g = g.copy()
        g['波动组'] = pd.qcut(g['波动率_60日'], 3, labels=False, duplicates='drop')
        if g['波动组'].nunique() < 3:
            continue
        picked = select_by_group(g, '波动组', 0.3)
        ex.append(picked['下月收益'].mean() - g['下月收益'].mean())

    if ex:
        neutral_wf.append(ex)
        print(f"  {ts_str}~{te_str}  {a:>7.3f}  {np.mean(ex):>+13.2%}  "
              f"{np.std(ex):>8.2%}  {sum(1 for v in ex if v > 0):>5}/{len(ex):<3}"
              f"{newey_west_t(ex):>8.2f}")

if neutral_wf:
    all_neutral = [v for seg in neutral_wf for v in seg]
    print(f"\n  合计 {len(all_neutral)} 个月   月均超额 {np.mean(all_neutral):+.2%}   "
          f"标准差 {np.std(all_neutral):.2%}   IR {np.mean(all_neutral) / np.std(all_neutral):.3f}")
    print(f"  正超额 {sum(1 for v in all_neutral if v > 0)}/{len(all_neutral)}   "
          f"NW-t {newey_west_t(all_neutral):.2f}")
    print(f"  → 熊市段（如 2011、2015 股灾、2018 全年下跌）若超额为正，中性化版本才值得上实盘")
# ... existing code ...
    print(f"  → 熊市段（如 2011、2015 股灾、2018 全年下跌）若超额为正，中性化版本才值得上实盘")

#  27. 规避型 alpha 验证：剔除底部后再选 Top
# 动机：合成因子 IC 显著（t≈3.3）但直接选 Top10% 亏钱，说明信息在「底部（躲开差票）」而非顶部
# 假设：每月先按合成分剔掉最差的一批，再在剩余里选高分，或能把规避型 alpha 转成多头超额
print("\n【规避型 alpha】先剔除合成分底部，再选 Top")

def composite_cross_section(data, factor_cols, dir_map):
    data = data.copy()
    z = data.groupby('年月')[factor_cols].transform(
        lambda s: (s - s.mean()) / (s.std() + 1e-9))
    data['合成分'] = sum(z[f] * dir_map[f] for f in factor_cols) / len(factor_cols)
    return data

def avoid_bottom_excess(data, trim_ratio, hold_ratio):
    ex = []
    for m, g in data.groupby('年月'):
        if g['合成分'].nunique() < 20:
            continue
        rank_pct = g['合成分'].rank(pct=True)
        candidates = g[rank_pct > trim_ratio]                   # 去掉底部 剔除比
        take_n = max(3, int(len(g) * hold_ratio))        # 持仓规模按整月计，保证各档可比
        top = candidates.nlargest(take_n, '合成分')
        if len(top) < 3:
            continue
        ex.append(top['下月收益'].mean() - g['下月收益'].mean())
    return ex

if composite_factors:
    dir_map_all = {f: (-1 if ic_means[f] < 0 else 1) for f in composite_factors}
    full_data = composite_cross_section(monthly, composite_factors, dir_map_all)

    # —— 合成分五分位：确认信号到底在顶部还是底部 ——
    print("\n  合成分五分位月均收益（看单调性来自哪一端）")
    quintiles2 = {k: [] for k in range(5)}
    for m, g in full_data.groupby('年月'):
        if g['合成分'].nunique() < 25:
            continue
        gg = g.copy()
        gg['档'] = pd.qcut(gg['合成分'].rank(method='first'), 5, labels=False)
        for k in range(5):
            quintiles2[k].append(gg.loc[gg['档'] == k, '下月收益'].mean())
    for k in range(5):
        print(f"    Q{k + 1}  月均 {np.mean(quintiles2[k]):+.2%}   正收益月 "
              f"{sum(1 for v in quintiles2[k] if v > 0)}/{len(quintiles2[k])}")
    D5_D1 = np.array(quintiles2[4]) - np.array(quintiles2[0])
    D4_D1 = np.array(quintiles2[3]) - np.array(quintiles2[0])
    D5_D2 = np.array(quintiles2[4]) - np.array(quintiles2[1])
    print(f"    Q5-Q1 {D5_D1.mean():+.2%} (NW-t {newey_west_t(D5_D1):.2f})   "
          f"Q4-Q1 {D4_D1.mean():+.2%} (NW-t {newey_west_t(D4_D1):.2f})   "
          f"Q5-Q2 {D5_D2.mean():+.2%} (NW-t {newey_west_t(D5_D2):.2f})")
    print("    → 若 Q5-Q2 明显小于 Q4-Q1/Q5-Q1，说明 alpha 主要靠「躲开 Q1」，做多 Q5 增益有限")

    # —— 不同剔除比例下的多头超额（全样本，in-sample，先看形态）——
    print(f"\n  {'剔除底部':>8}{'持仓':>8}{'月超额':>10}{'正超额月':>10}{'IR':>7}{'NW-t':>8}")
    for trim_ratio in [0.0, 0.2, 0.3, 0.4, 0.5]:
        ex = avoid_bottom_excess(full_data, trim_ratio, position_ratio)
        if ex:
            ir = np.mean(ex) / np.std(ex) if np.std(ex) > 0 else np.nan
            print(f"  {trim_ratio:>7.0%}{position_ratio:>8.0%}{np.mean(ex):>+9.2%}"
                  f"{sum(1 for v in ex if v > 0):>7}/{len(ex):<3}{ir:>7.3f}{newey_west_t(ex):>8.2f}")
    print("  ↑ 剔除底部=0% 即原来的「直接选 Top10%」，用来做基准对照")

    # —— 严格 out-of-sample：每段 WF 只用训练月定因子方向 ——
    print(f"\n  【WF 口径】方向仅用各段训练月估计，测未来 12 个月，剔除底部 30%")
    print(f"  {'测试区间':>18}{'月超额':>10}{'正超额月':>10}{'NW-t':>8}")
    wf_ex_avoid = []
    for ts_str, te_str in WINDOWS:
        ts = pd.Period(ts_str, 'M')
        te_p = pd.Period(te_str, 'M')
        tr = monthly[monthly['年月'] < ts]
        te = monthly[(monthly['年月'] >= ts) & (monthly['年月'] <= te_p)]
        if len(tr) < 300 or len(te) < 100:
            continue
        dir_map = {}
        ok = True
        for f in composite_factors:
            m_ics = []
            for m, g in tr.groupby('年月'):
                if g[f].nunique() < 20:
                    continue
                m_ics.append(spearmanr(g[f], g['下月收益'])[0])
            m_ics = pd.Series(m_ics).dropna()
            if len(m_ics) == 0:
                ok = False
                break
            dir_map[f] = -1 if m_ics.mean() < 0 else 1
        if not ok:
            continue
        te2 = composite_cross_section(te, composite_factors, dir_map)
        ex = avoid_bottom_excess(te2, 0.3, position_ratio)
        if ex:
            wf_ex_avoid.append(ex)
            print(f"  {ts_str}~{te_str}  {np.mean(ex):>+9.2%}"
                  f"{sum(1 for v in ex if v > 0):>7}/{len(ex):<3}{newey_west_t(ex):>8.2f}")
    if wf_ex_avoid:
        all_ex = [v for seg in wf_ex_avoid for v in seg]
        ir = np.mean(all_ex) / np.std(all_ex) if np.std(all_ex) > 0 else np.nan
        print(f"\n  合计 {len(all_ex)} 个月   月均超额 {np.mean(all_ex):+.2%}   "
              f"标准差 {np.std(all_ex):.2%}   IR {ir:.3f}")
        print(f"  正超额 {sum(1 for v in all_ex if v > 0)}/{len(all_ex)}   "
              f"NW-t {newey_west_t(all_ex):.2f}")
        print("  → NW-t>2 且 熊市段(2011/2014/2018/2021/2023)超额为正，规避型 alpha 才真能变现")
    print("  注：上方全样本口径为 in-sample，仅供参考；能否变现以 WF 口径为准")
else:
    print("  稳健因子不足 2 个，跳过规避型验证")
