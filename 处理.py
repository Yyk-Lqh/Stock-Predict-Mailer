import pandas as pd

# 读取数据
df = pd.read_csv('all_stock_history2.csv', encoding='utf-8-sig')

# 清洗股票代码前缀
df['股票代码'] = df['股票代码'].str.replace(r'^(sz|sh)\.', '', regex=True)

# 日期格式处理
df['日期'] = df['日期'].str.replace('-', '', regex=False)

# 价格保留两位小数
price_cols = ['开盘', '最高', '最低', '收盘']
for col in price_cols:
    df[col] = df[col].round(2)

# 删除成交量为空的数据
df = df.dropna(subset=['成交量'])
df['成交量'] = df['成交量'].astype(int)

# 删除交易记录少于60天的股票
stock_counts = df['股票代码'].value_counts()
low_count_stocks = stock_counts[stock_counts < 60].index
if not low_count_stocks.empty:
    df = df[~df['股票代码'].isin(low_count_stocks)]

# 保存清洗后的数据
df.to_csv('all_stock_history2_cleaned.csv', encoding='utf-8-sig', index=False)
print('完成清洗')
