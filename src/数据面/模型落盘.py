
"""数据面2 流程：训练随机森林模型并落盘

口径说明：
- 特征工程、训练参数与 因子试探_步骤(8).py 完全一致（9 特征 + 截面排名前 30% 为正类）
- 先按 80/20 切分做验证对照（输出训练/测试 AUC，可与步骤8 输出比对）
- 再用全部可用月份训练最终模型（生产口径）并保存
前置：all_stock_history120_deep_cleaned.csv（步骤4 产出）、
      fundamental_quarterly_cleaned.csv（步骤6 产出）已位于 数据面2/
产出：随机森林_数据面2模型.pkl（模型 + 特征列表 + 训练元数据）
"""
import os
import pickle
from datetime import datetime

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def 找文件(名称):
    for 候选 in (os.path.join(BASE_DIR, 名称),
                 os.path.normpath(os.path.join(BASE_DIR, '..', 名称))):
        if os.path.exists(候选):
            return 候选
    raise FileNotFoundError(f'找不到 {名称}，已尝试 {BASE_DIR} 及其上级目录')


# ========== 全局参数（与 因子试探_步骤(8).py 完全一致） ==========
随机种子 = 42
正类阈值 = 0.7          # 截面排名前 30% 为正类
FEATS = ['PB分位', '收益率', '均线偏移', '动量_20日',
         '量价相关_10日', '波动率_60日', '价格位置_20日',
         'roe_delta_r', 'eps_yoy_r']
模型文件 = os.path.join(BASE_DIR, '随机森林_数据面2模型.pkl')

# ========== 1. 量价数据 → 月频 ==========
print('[1/6] 读取量价数据（大文件，约 1~2 分钟）…')
df = pd.read_csv(找文件('all_stock_history120_deep_cleaned.csv'),
                 encoding='utf-8-sig', dtype={'股票代码': str})
df['股票代码'] = df['股票代码'].str.zfill(6)
df['日期'] = pd.to_datetime(df['日期'])
df = df.sort_values(['股票代码', '日期']).reset_index(drop=True)
df['年月'] = df['日期'].dt.to_period('M')
月度 = df.groupby(['股票代码', '年月'], as_index=False).last()
月度['下月收益'] = 月度.groupby('股票代码')['收盘'].shift(-1) / 月度['收盘'] - 1
月度['目标'] = 月度.groupby('年月')['下月收益'].transform(
    lambda s: (s.rank(pct=True) > 正类阈值).astype(int))
月度['月末'] = 月度['年月'].dt.to_timestamp('M')

# ========== 2. 基本面合并（公告日回溯对齐，宁可晚用不可早用） ==========
print('[2/6] 合并基本面因子…')
基本面 = pd.read_csv(找文件('fundamental_quarterly_cleaned.csv'),
                     dtype={'code': str}, encoding='utf-8-sig')
基本面['report_dt'] = pd.to_datetime(基本面['report_date'])
基本面['pub_dt'] = pd.to_datetime(基本面['pub_date'], errors='coerce')
基本面['pub_dt'] = 基本面['pub_dt'].fillna(基本面['report_dt'] + pd.Timedelta(days=120))
基本面 = 基本面.dropna(subset=['pub_dt']).sort_values(['code', 'pub_dt', 'report_dt'])
基本面 = 基本面.replace([np.inf, -np.inf], np.nan)

覆盖 = 基本面.groupby('code')['net_profit_yoy'].apply(lambda s: s.notna().mean())
保留股票 = set(覆盖[覆盖 >= 0.9].index)
基本面 = 基本面[基本面['code'].isin(保留股票)]
print(f'  基本面有效股票 {len(保留股票)} 只')

去年ROE = 基本面[['code', 'report_dt', 'ROE']].copy()
去年ROE['report_dt'] = 去年ROE['report_dt'] + pd.DateOffset(years=1)
去年ROE = 去年ROE.rename(columns={'ROE': 'ROE_ly'})
基本面 = 基本面.merge(去年ROE, on=['code', 'report_dt'], how='left')
基本面['roe_delta'] = 基本面['ROE'] - 基本面['ROE_ly']

基本面原值 = ['roe_delta', 'eps_yoy', 'net_profit_yoy']
基本面 = 基本面.rename(columns={'code': '股票代码'})

月度 = pd.merge_asof(
    月度.sort_values(['月末', '股票代码']),
    基本面.sort_values(['pub_dt', '股票代码'])[['股票代码', 'pub_dt'] + 基本面原值],
    by='股票代码', left_on='月末', right_on='pub_dt',
    direction='backward', tolerance=pd.Timedelta(days=200))

# 截面分位化：原始值会带偏随机森林的分裂点
for col in 基本面原值:
    月度[f'{col}_r'] = 月度.groupby('年月')[col].rank(pct=True)

# ========== 3. 清洗 + 重算目标 ==========
print('[3/6] 特征清洗与标签截面化…')
最后月 = 月度['年月'].max()
月度 = 月度[月度['年月'] < 最后月].copy()

缺失列 = [c for c in FEATS if c not in 月度.columns]
if 缺失列:
    raise KeyError(f'特征列不存在，请先跑 特征工程2_步骤(4).py：{缺失列}')

月度 = 月度.replace([np.inf, -np.inf], np.nan)
月度 = 月度.dropna(subset=FEATS + ['下月收益']).reset_index(drop=True)
# 样本缩水后截面变了，目标必须在最终样本上重算
月度['目标'] = 月度.groupby('年月')['下月收益'].transform(
    lambda s: (s.rank(pct=True) > 正类阈值).astype(int))
print(f'  清洗后 {len(月度)} 行   {月度["股票代码"].nunique()} 只   '
      f'{月度["年月"].nunique()} 个月   '
      f'{月度["年月"].min()} ~ {月度["年月"].max()}')

# ========== 4. 80/20 验证对照 ==========
print('[4/6] 80/20 切分验证（与 因子试探_步骤(8).py 同口径）…')
月份 = sorted(月度['年月'].unique())
切点 = 月份[int(len(月份) * 0.8)]
训练 = 月度[月度['年月'] <= 切点].copy()
测试 = 月度[月度['年月'] > 切点].copy()

模型参数 = dict(n_estimators=300, max_depth=4, min_samples_split=40,
               min_samples_leaf=15, max_features='sqrt',
               random_state=随机种子, n_jobs=-1)

验证模型 = RandomForestClassifier(**模型参数)
验证模型.fit(训练[FEATS], 训练['目标'])
auc_训练 = roc_auc_score(训练['目标'], 验证模型.predict_proba(训练[FEATS])[:, 1])
auc_测试 = roc_auc_score(测试['目标'], 验证模型.predict_proba(测试[FEATS])[:, 1])
print(f'  训练 AUC {auc_训练:.4f}   测试 AUC {auc_测试:.4f}   衰减 {auc_训练 - auc_测试:+.4f}')

# ========== 5. 全量训练最终模型（生产口径） ==========
print('[5/6] 全量训练最终模型（300 棵树，约 1~3 分钟）…')
模型 = RandomForestClassifier(**模型参数)
模型.fit(月度[FEATS], 月度['目标'])
print('  训练完成')

# ========== 6. 落盘前校验 + 保存 ==========
print('[6/6] 落盘前校验并保存…')
assert len(模型.feature_importances_) == len(FEATS), '特征重要性数量与特征列表不一致'
assert len(月度) > 0, '训练样本为空'
assert auc_测试 > 0.5, f'测试 AUC {auc_测试:.3f} 未超过 0.5，模型无预测力，中止落盘'

包 = {
    'model': 模型,
    'FEATS': FEATS,
    '训练截止月': str(月度['年月'].max()),
    '训练样本数': len(月度),
    '训练股票数': 月度['股票代码'].nunique(),
    '训练月份数': 月度['年月'].nunique(),
    '验证_AUC_训练': round(auc_训练, 4),
    '验证_AUC_测试': round(auc_测试, 4),
    '参数': 模型参数,
    'sklearn版本': sklearn.__version__,
    '训练时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    '口径': '特征工程与 因子试探_步骤(8).py 一致；最终模型用全部可用月份训练',
}
with open(模型文件, 'wb') as f:
    pickle.dump(包, f)
print(f'\n已保存 → {模型文件}')

print('\n以后加载模型：')
print('    import pickle')
print('    with open(r\'数据面2\\随机森林_数据面2模型.pkl\', \'rb\') as f:')
print('        包 = pickle.load(f)')
print('    概率 = 包["model"].predict_proba(本月[包["FEATS"]])[:, 1]')
