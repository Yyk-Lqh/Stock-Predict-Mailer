import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix



df = pd.read_csv('all_stock_history2_cleaned.csv', dtype={'股票代码': str})



df['日期'] = pd.to_datetime(df['日期'], format='%Y%m%d')
df = df.sort_values(['股票代码', '日期']).reset_index(drop=True)

# ========== 特征工程 ==========

# 1. 日收益率
df['日收益率'] = df.groupby('股票代码')['收盘'].pct_change()

# 2. 移动平均线
for window in [5, 10, 20]:
    df[f'MA{window}'] = df.groupby('股票代码')['收盘'].rolling(window).mean().reset_index(level=0, drop=True)
    df[f'MA{window}_偏离'] = (df['收盘'] - df[f'MA{window}']) / df[f'MA{window}']

# 3. 成交量变化率
df['成交量变化'] = df.groupby('股票代码')['成交量'].pct_change()

# 4. 振幅
df['振幅'] = (df['最高'] - df['最低']) / df['收盘']

# 5. 价格区间位置
df['价格位置'] = (df['收盘'] - df['最低']) / (df['最高'] - df['最低'])

# 6. 过去N天涨跌
for n in [1, 3, 5]:
    df[f'过去{n}天涨跌'] = df.groupby('股票代码')['收盘'].pct_change(n)

# 7. 过去5天平均成交量 / 过去20天平均成交量
df['量比5_20'] = (
    df.groupby('股票代码')['成交量'].rolling(5).mean().reset_index(level=0, drop=True)
    / df.groupby('股票代码')['成交量'].rolling(20).mean().reset_index(level=0, drop=True)
)

# ========== 目标变量：5天后收盘是否比今天高 ==========
df['5天后收盘'] = df.groupby('股票代码')['收盘'].shift(-5)
df['目标'] = (df['5天后收盘'] > df['收盘']).astype(int)
df = df.drop(columns=['5天后收盘'])

# ========== 删除空值 ==========
feature_cols = ['日收益率', '成交量变化', '振幅', '价格位置',
                'MA5_偏离', 'MA10_偏离', 'MA20_偏离',
                '过去1天涨跌', '过去3天涨跌', '过去5天涨跌',
                '量比5_20']

df = df.dropna(subset=feature_cols + ['目标'])

print(f"特征数量: {len(feature_cols)}")
print(f"样本数量: {len(df)}")
print(f"\n目标分布:")
print(df['目标'].value_counts())

# ========== 划分训练集和测试集 ==========

X = df[feature_cols]
y = df['目标']

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

print(f"\n训练集: {len(X_train)} 条")
print(f"测试集: {len(X_test)} 条")

# ========== 训练模型 ==========

model = RandomForestClassifier(
    n_estimators=200,
    max_depth=10,
    min_samples_split=10,
    min_samples_leaf=5,
    random_state=42,
    n_jobs=-1
)

model.fit(X_train, y_train)

# ========== 评估 ==========

y_pred = model.predict(X_test)

print(f"\n准确率: {accuracy_score(y_test, y_pred):.4f}")
print(f"\n分类报告:")
print(classification_report(y_test, y_pred, target_names=['跌(0)', '涨(1)']))
print(f"混淆矩阵:")
print(confusion_matrix(y_test, y_pred))

# ========== 特征重要性 ==========

importance = pd.DataFrame({
    '特征': feature_cols,
    '重要性': model.feature_importances_
}).sort_values('重要性', ascending=False)

print(f"\n特征重要性排名:")
print(importance.to_string(index=False))

# ========== 预测示例 ==========

latest = df[df['股票代码'] == '688322'].iloc[-1]
print(f"\n最新数据: {latest['股票代码']} 日期:{latest['日期'].strftime('%Y-%m-%d')}")
sample = pd.DataFrame([{col: latest[col] for col in feature_cols}])
pred = model.predict(sample)[0]
prob = model.predict_proba(sample)[0]
print(f"预测未来5天方向: {'涨' if pred == 1 else '跌'}")
print(f"概率: 跌={prob[0]:.2%}, 涨={prob[1]:.2%}")