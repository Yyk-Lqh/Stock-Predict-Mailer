import pandas as pd

# 读取数据
df = pd.read_csv('all_stock_history119.csv', encoding='utf-8-sig')# 清洗股票代码前缀
df['股票代码'] = df['股票代码'].str.replace(r'^(sz|sh)\.', '', regex=True)


# 删除成交量为空的数据
df = df.dropna(subset=['成交量'])
df['成交量'] = df['成交量'].astype(int)


# 删除交易记录少于60天的股票
stock_counts = df['股票代码'].value_counts()
low_count_stocks = stock_counts[stock_counts < 60].index
if not low_count_stocks.empty:
    df = df[~df['股票代码'].isin(low_count_stocks)]

# 保存清洗后的数据
df.to_csv('all_stock_history120_cleaned.csv', encoding='utf-8-sig', index=False)
print('完成初步清洗')