import pandas as pd
import numpy as np


# 创建特征
def create_feature(group):

    group['收益率'] = (group['收盘'] - group['开盘']) / group['开盘']

    # 均线只做中间变量，不落盘
    ma5 = group['收盘'].rolling(5).mean()
    group['均线偏移'] = (group['收盘'] - ma5) / ma5

    group['动量_20日'] = group['收盘'].pct_change(20)

    # min_periods 必须等于窗口，否则 2 个点算出 ±1 的伪相关
    group['量价相关_10日'] = (
        group['收盘'].rolling(10, min_periods=10)
        .corr(group['成交量'])
    )

    # 波动率只留长周期：选股不用，但组合中性化和仓位控制要用
    daily_return = group['收盘'].pct_change()
    group['波动率_20日'] = daily_return.rolling(20, min_periods=20).std() * np.sqrt(252)
    group['波动率_60日'] = daily_return.rolling(60, min_periods=40).std() * np.sqrt(252)
    group['波动率_120日'] = daily_return.rolling(120, min_periods=100).std() * np.sqrt(252)

    group['价格位置_20日'] = (group['收盘'] - group['收盘'].rolling(20).min()) / \
                             (group['收盘'].rolling(20).max() - group['收盘'].rolling(20).min() + 0.0001)

    return group


df = pd.read_csv('all_stock_history120_cleaned.csv', encoding='utf-8-sig')

df['日期'] = pd.to_datetime(df['日期'])
df = df.sort_values(['股票代码', '日期']).reset_index(drop=True)

# 估值分位：三者相关性 0.64，只留 IC 最强的 PB，PE/PS 不再生成
if '市净率' in df.columns:
    df['市净率'] = pd.to_numeric(df['市净率'], errors='coerce')
    # 负值无经济意义（资不抵债的 PB 为负），先置空再排名
    df.loc[df['市净率'] <= 0, '市净率'] = np.nan
    count = df.groupby('日期')['市净率'].transform('count')
    df['PB分位'] = df.groupby('日期')['市净率'].rank(pct=True).where(count >= 10)

df = df.drop(columns=[c for c in ['市盈率', '市净率', '市销率'] if c in df.columns])

print('估值分位缺失率：')
print(df[['PB分位']].isna().mean().round(3).to_string())

# 批量创建特征
stock_codes = df['股票代码'].copy()

df = df.groupby('股票代码', group_keys=False).apply(create_feature).reset_index(drop=True)
df.insert(0, '股票代码', stock_codes)

df.to_csv('all_stock_history120_deep_cleaned.csv', encoding='utf-8-sig', index=False)
print(f"特征工程完成：{len(df)} 行，{df.shape[1]} 列")
print(f"特征列：{[c for c in df.columns if c not in ('股票代码', '日期')]}")