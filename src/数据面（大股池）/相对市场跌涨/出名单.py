"""出名单：训练最终模型（带 pkl 缓存），预测最新一周，输出买入/回避名单

pkl 失效条件：特征变了、训练数据行数变了、训练截止日变了。任一触发就重训。

数据目录默认与脚本同级；用 --data-dir 或环境变量
STOCK_PREDICT_MAILER_DATAMART_BIG_DIR 可指向其他目录。
"""
import argparse
import glob
import hashlib
import os
import pickle

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
解析 = argparse.ArgumentParser(description='用周度特征缓存输出买入/回避名单')
解析.add_argument('--data-dir', help='周度特征缓存.csv 与 pkl 所在目录，默认脚本同级')
参数 = 解析.parse_args()
DATA_DIR = os.path.abspath(参数.data_dir
                         or os.environ.get('STOCK_PREDICT_MAILER_DATAMART_BIG_DIR')
                         or BASE_DIR)
CACHE = os.path.join(DATA_DIR, '周度特征缓存.csv')
MODEL_PATH = os.path.join(DATA_DIR, '周频模型_相对强弱.pkl')
FEATS = ['收益率', '均线偏移', '动量_20日', '波动率_60日', '价格位置_20日',
         '过去4周收益', '过去12周收益',
         '市场周收益', '上涨占比', '周收益离散', '市场动量4', '市场动量12']
模型参数 = dict(n_estimators=120, max_depth=6, min_samples_leaf=100,
               max_features='sqrt', random_state=42, n_jobs=-1)
TOP_N = 35
强制重训 = False

if not os.path.exists(CACHE):
    raise SystemExit(f'找不到 {CACHE}\n'
                     '用 --data-dir 指向 周度特征缓存.csv 所在目录')

周 = pd.read_csv(CACHE, encoding='utf-8-sig', dtype={'股票代码': str})
周['股票代码'] = 周['股票代码'].str.zfill(6)
周['日期'] = pd.to_datetime(周['日期'])
周 = 周.replace([np.inf, -np.inf], np.nan)

训练集 = 周.dropna(subset=FEATS + ['下周收益'])
最新周序 = 周['周序'].max()
预测集 = 周[周['周序'] == 最新周序].dropna(subset=FEATS).copy()
if 预测集.empty:
    raise SystemExit(f'最新周 {最新周序} 没有可用特征')
截止日 = 预测集['日期'].max()
训练截止 = 训练集['日期'].max()
print(f'训练样本 {len(训练集)} 行  训练截止 {训练截止.date()}   '
      f'预测周 {截止日.date()}   {len(预测集)} 只')

特征签名 = hashlib.md5('|'.join(FEATS).encode()).hexdigest()[:8]


def 取模型():
    if os.path.exists(MODEL_PATH) and not 强制重训:
        try:
            with open(MODEL_PATH, 'rb') as f:
                打包 = pickle.load(f)
        except Exception as e:
            print(f'  pkl 读取失败（{e}），重训')
            打包 = None
        if 打包 is not None:
            if 打包.get('特征签名') != 特征签名:
                print('  特征变了，旧 pkl 作废')
            elif (打包.get('训练行数') != len(训练集)
                  or 打包.get('训练截止') != 训练截止):
                print(f'  数据变了（pkl 截止 {打包.get("训练截止")}），重训')
            else:
                print(f'  复用 pkl  训练至 {打包["训练截止"].date()}  '
                      f'存盘于 {打包["存盘时间"]:%Y-%m-%d %H:%M}')
                return 打包['模型']

    print('  训练中…')
    模型 = RandomForestClassifier(**模型参数)
    模型.fit(训练集[FEATS], 训练集['涨_相对'])
    with open(MODEL_PATH, 'wb') as f:
        pickle.dump({
            '模型': 模型,
            'FEATS': FEATS,
            '特征签名': 特征签名,
            '正类阈值': 0.7,
            '训练行数': len(训练集),
            '训练截止': 训练截止,
            '训练起始': 训练集['日期'].min(),
            '模型参数': 模型参数,
            '存盘时间': pd.Timestamp.now(),
        }, f)
    print(f'  已存 pkl → {MODEL_PATH}')
    return 模型


模型 = 取模型()
预测集['概率'] = 模型.predict_proba(预测集[FEATS])[:, 1]
预测集 = 预测集.sort_values('概率', ascending=False).reset_index(drop=True)

买 = 预测集.head(TOP_N)
避 = 预测集.tail(TOP_N).sort_values('概率')

print(f'\n===== {截止日.date()} 收盘，预测下周 =====')
print(f'\n【买入选池 Top {TOP_N}】')
print('   代码     概率    本周涨跌')
for _, r in 买.iterrows():
    print(f'   {r["股票代码"]}   {r["概率"]:.3f}   {r["周收益"]:>+7.2%}')

print(f'\n【回避名单 Bottom {TOP_N}】')
print('   代码     概率    本周涨跌')
for _, r in 避.iterrows():
    print(f'   {r["股票代码"]}   {r["概率"]:.3f}   {r["周收益"]:>+7.2%}')

名单文件 = os.path.join(DATA_DIR, f'名单_{截止日:%Y%m%d}.csv')
预测集[['股票代码', '日期', '概率', '周收益']].to_csv(
    名单文件, encoding='utf-8-sig', index=False)
print(f'\n全量名单已存 → {名单文件}')

旧名单 = sorted(p for p in glob.glob(os.path.join(DATA_DIR, '名单_*.csv'))
              if os.path.abspath(p) != os.path.abspath(名单文件))
if 旧名单:
    上期 = pd.read_csv(旧名单[-1], encoding='utf-8-sig', dtype={'股票代码': str})
    上期['股票代码'] = 上期['股票代码'].str.zfill(6)
    上期持 = set(上期.head(TOP_N)['股票代码'])
    可留 = set(预测集.head(int(len(预测集) * 0.15))['股票代码'])
    可买 = set(预测集.head(int(len(预测集) * 0.05))['股票代码'])
    最终持 = (上期持 & 可留) | 可买
    if len(最终持) > 2 * TOP_N:
        最终持 = set(预测集[预测集['股票代码'].isin(最终持)]
                    .head(2 * TOP_N)['股票代码'])
    print(f'\n【Buffer 调仓建议（对比 {os.path.basename(旧名单[-1])}）】')
    print(f'   上期持仓 {len(上期持)} 只  继续持有 {len(最终持 & 上期持)} 只')
    print(f'   卖出 {sorted(上期持 - 最终持)}')
    print(f'   买入 {sorted(最终持 - 上期持)}')
    print(f'   本期目标 {len(最终持)} 只')
else:
    print('\n【无上期名单，首次运行：直接按 Top 35 建仓】')
