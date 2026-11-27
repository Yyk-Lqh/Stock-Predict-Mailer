"""周频涨跌模型

设计：
- 频率 = 周频（每自然周最后一个交易日），信息利用率是月频的 4 倍
- 标签 = 下周收益 > 0（绝对涨跌，暂缓）；对照 = 截面前 30%（相对强弱，主力）
- 特征 = 日频快照 + 周频反转 + 市场状态
- 模型 = RandomForest，每 STEP 周滚动重训，只用最近 训练窗口 周训练
- 组合 = 固定 Top10% 与 Buffer 版（留 15% / 买 5%）对照
- 缓存 = 周度特征表 + walk-forward 预测结果，改评估逻辑不用重训
"""
import hashlib
import os
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

warnings.filterwarnings('ignore', category=FutureWarning)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE_DIR, '周度特征缓存.csv')
随机种子 = 42
START = 104      # 前 104 周（2 年）只做训练预热
STEP = 8         # 每 8 周重训一次
训练窗口 = 0   # 只用最近 156 周（3 年）训练，0 = 用全部历史
强制重训 = False  # True 时忽略预测缓存，强制重跑 walk-forward
正类阈值 = 0.7   # 相对标签：截面前 30%
单边成本 = 0.0015


def _resolve(name):
    for cand in (os.path.join(BASE_DIR, name),
                 os.path.normpath(os.path.join(BASE_DIR, '..', '数据面（大股池）', name))):
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError(f'找不到 {name}')


def 造周度表():
    print('[1/4] 读取日频数据（大文件，约 1~2 分钟）…')
    df = pd.read_csv(_resolve('all_stock_history120_deep_cleaned.csv'),
                     encoding='utf-8-sig', dtype={'股票代码': str})
    df['股票代码'] = df['股票代码'].str.zfill(6)
    df['日期'] = pd.to_datetime(df['日期'])
    df = df.sort_values(['股票代码', '日期']).reset_index(drop=True)
    df['周'] = df['日期'].dt.to_period('W')
    print(f'  {len(df)} 行  {df["股票代码"].nunique()} 只')

    print('[2/4] 转周频 + 造特征…')
    周度 = df.groupby(['股票代码', '周'], as_index=False).last()
    周度['周序'] = 周度['周'].apply(lambda p: p.ordinal)
    周度 = 周度.sort_values(['股票代码', '周序']).reset_index(drop=True)

    周度['周收益'] = 周度.groupby('股票代码')['收盘'].pct_change()
    # 停牌周：周序不连续，周收益作废
    周度['周间隔'] = 周度.groupby('股票代码')['周序'].diff()
    周度.loc[周度['周间隔'] != 1, '周收益'] = np.nan

    # 短期反转类特征
    周度['过去4周收益'] = 周度.groupby('股票代码')['周收益'].transform(
        lambda s: s.rolling(4, min_periods=3).sum())
    周度['过去12周收益'] = 周度.groupby('股票代码')['周收益'].transform(
        lambda s: s.rolling(12, min_periods=9).sum())

    # 市场状态（预测绝对涨跌必须给模型大盘信息）
    市场周 = 周度.groupby('周序').agg(
        市场周收益=('周收益', 'mean'),
        上涨占比=('周收益', lambda s: (s > 0).mean()),
        周收益离散=('周收益', 'std'),
    )
    市场周['市场动量4'] = 市场周['市场周收益'].rolling(4, min_periods=3).mean()
    市场周['市场动量12'] = 市场周['市场周收益'].rolling(12, min_periods=9).mean()
    周度 = 周度.merge(市场周, on='周序', how='left')

    # 标签：下周收益
    周度['下周收益'] = 周度.groupby('股票代码')['周收益'].shift(-1)
    周度['下周间隔'] = 周度.groupby('股票代码')['周序'].shift(-1) - 周度['周序']
    周度.loc[周度['下周间隔'] != 1, '下周收益'] = np.nan

    周度['涨'] = (周度['下周收益'] > 0).astype(int)
    周度['涨_相对'] = 周度.groupby('周序')['下周收益'].transform(
        lambda s: (s.rank(pct=True) > 正类阈值).astype(int))

    周度 = 周度.drop(columns=['周'])
    周度.to_csv(CACHE, encoding='utf-8-sig', index=False)
    print(f'  已缓存 → {CACHE}')
    return 周度


if os.path.exists(CACHE):
    print('[1/4] 复用周度缓存…')
    周度 = pd.read_csv(CACHE, encoding='utf-8-sig', dtype={'股票代码': str})
    周度['股票代码'] = 周度['股票代码'].str.zfill(6)
else:
    周度 = 造周度表()

FEATS = ['收益率', '均线偏移', '动量_20日', '波动率_60日', '价格位置_20日',
         '过去4周收益', '过去12周收益',
         '市场周收益', '上涨占比', '周收益离散', '市场动量4', '市场动量12']

周度 = 周度.replace([np.inf, -np.inf], np.nan)
周度 = 周度.dropna(subset=FEATS + ['下周收益']).reset_index(drop=True)
print(f'[3/4] 可用样本 {len(周度)} 行  {周度["股票代码"].nunique()} 只  '
      f'{周度["周序"].nunique()} 周')
print(f'  绝对标签正类率 {周度["涨"].mean():.1%}   '
      f'相对标签正类率 {周度["涨_相对"].mean():.1%}')

# ========== walk-forward ==========
print(f'[4/4] walk-forward（每 {STEP} 周重训，窗口 {训练窗口} 周）…')
全部周 = np.sort(周度['周序'].unique())
模型参数 = dict(n_estimators=120, max_depth=6, min_samples_leaf=100,
               max_features='sqrt', random_state=随机种子, n_jobs=-1)


def 跑一遍(标签列):
    特征签名 = hashlib.md5('|'.join(FEATS).encode()).hexdigest()[:6]
    预测缓存 = os.path.join(
        BASE_DIR, f'预测_{标签列}_{训练窗口}w_{STEP}s_{特征签名}.csv')
    if os.path.exists(预测缓存) and not 强制重训:
        print(f'  复用预测缓存 {os.path.basename(预测缓存)}')
        d = pd.read_csv(预测缓存, encoding='utf-8-sig', dtype={'股票代码': str})
        d['股票代码'] = d['股票代码'].str.zfill(6)
        return d

    结果 = []
    for i in range(START, len(全部周), STEP):
        测试周 = 全部周[i:i + STEP]
        起点 = 全部周[max(0, i - 训练窗口)] if 训练窗口 else 全部周[0]
        训练 = 周度[(周度['周序'] >= 起点) & (周度['周序'] < 测试周[0])]
        测试 = 周度[周度['周序'].isin(测试周)].copy()
        if len(训练) < 5000 or 测试[标签列].nunique() < 2:
            continue
        模型 = RandomForestClassifier(**模型参数)
        模型.fit(训练[FEATS], 训练[标签列])
        测试['概率'] = 模型.predict_proba(测试[FEATS])[:, 1]
        结果.append(测试)

    if not 结果:
        return None
    出 = pd.concat(结果, ignore_index=True)
    出.to_csv(预测缓存, encoding='utf-8-sig', index=False)
    print(f'  预测已缓存 → {os.path.basename(预测缓存)}')
    return 出


def 组合统计(结果, 标签列, 用buffer):
    """用buffer=True 时：持仓未跌出前 15% 不卖，新票进前 5% 才买"""
    周列, 周收益列, 命中列, 换手列, 持仓列 = [], [], [], [], []
    持仓 = set()
    for w, g in 结果.groupby('周序'):
        n = max(3, int(len(g) * 0.1))
        g = g.copy()
        g['分位'] = g['概率'].rank(pct=True, ascending=False)
        if 用buffer:
            可留 = set(g[g['分位'] <= 0.15]['股票代码'])
            可买 = set(g[g['分位'] <= 0.05]['股票代码'])
            新持仓 = (持仓 & 可留) | 可买
            if len(新持仓) > 2 * n:
                新持仓 = set(g[g['股票代码'].isin(新持仓)]
                             .nlargest(2 * n, '概率')['股票代码'])
        else:
            新持仓 = set(g.nlargest(n, '概率')['股票代码'])
        if not 新持仓:
            continue
        明细 = g[g['股票代码'].isin(新持仓)]
        周列.append(w)
        周收益列.append(明细['下周收益'].mean())
        命中列.append(明细[标签列].mean())
        持仓列.append(len(新持仓))
        if 持仓:
            换手列.append(len(新持仓 - 持仓) / max(1, len(新持仓)))
        持仓 = 新持仓
    return (np.array(周列), np.array(周收益列), np.array(命中列),
            np.array(换手列), np.array(持仓列))


def 打印组合(结果, 标签列, 模式, 用buffer):
    全池 = 结果.groupby('周序')['下周收益'].mean()
    周列, 组收益, 命中, 换手, 持仓 = 组合统计(结果, 标签列, 用buffer)
    超 = 组收益 - 全池.loc[周列].values
    成本 = 2 * np.mean(换手) * 单边成本
    净 = 超 - 成本
    t = 超.mean() / (超.std(ddof=1) / np.sqrt(len(超)))
    print(f'  [{模式}] 持仓 {持仓.mean():.0f} 只  换手 {np.mean(换手):.1%}/周  '
          f'命中 {命中.mean():.1%}（基线 {结果[标签列].mean():.1%}）')
    print(f'        超额 {超.mean():+.3%}/周（中位 {np.median(超):+.3%}，'
          f'正超额 {(超 > 0).mean():.1%}）  t={t:.2f}')
    print(f'        成本 {成本:.3%}/周  净 {净.mean():+.3%}/周  '
          f'年化 {净.mean() * 52:+.2%}')


def 评估(结果, 标签列, 名称):
    print(f'\n===== {名称} =====')
    周auc = []
    for _, g in 结果.groupby('周序'):
        if g[标签列].nunique() < 2:
            continue
        周auc.append(roc_auc_score(g[标签列], g['概率']))
    周auc = np.array(周auc)
    print(f'  逐周 AUC 均值 {周auc.mean():.4f}  中位 {np.median(周auc):.4f}  '
          f'标准差 {周auc.std():.4f}  >0.55 占 {(周auc > 0.55).mean():.1%}')
    print(f'  全样本 AUC {roc_auc_score(结果[标签列], 结果["概率"]):.4f}')

    # 打乱标签（每周内打乱，保持正类率）
    随机 = []
    for k in range(30):
        打乱 = 结果.copy()
        打乱[标签列] = 打乱.groupby('周序')[标签列].transform(
            lambda s: s.sample(frac=1, random_state=k).values)
        随机.append(roc_auc_score(打乱[标签列], 打乱['概率']))
    随机 = np.array(随机)
    print(f'  打乱标签 AUC 均值 {随机.mean():.4f}  '
          f'95% 分位 {np.percentile(随机, 95):.4f}')

    打印组合(结果, 标签列, '固定Top10%', 用buffer=False)
    打印组合(结果, 标签列, 'Buffer 15/5', 用buffer=True)


# 绝对涨跌已验证为弱信号（AUC 0.5341、扣成本后为负），暂缓；
# 需要时取消注释即可，预测会走独立缓存
# 绝对 = 跑一遍('涨')
# 评估(绝对, '涨', '绝对涨跌（下周收益 > 0）')

相对 = 跑一遍('涨_相对')
评估(相对, '涨_相对', '相对强弱（截面前 30%）')