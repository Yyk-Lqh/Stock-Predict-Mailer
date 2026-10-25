import pandas as pd

df = pd.read_csv('all_stock_history2.csv')

df['股票代码'] = df['股票代码'].str.replace('sz.', '', regex=False)
df['股票代码'] = df['股票代码'].str.replace('sh.', '', regex=False)

df['日期'] = df['日期'].str.replace('-', '', regex=False)

precision = ['开盘', '最高', '最低', '收盘']
for i in precision:
    df[i] = df[i].round(2)

df = df.dropna(subset=['成交量'])
df['成交量'] = df['成交量'].astype(int)

select_data = df['股票代码'].value_counts()
delect_data = select_data[select_data < 60].index

if len(delect_data) > 0:
    df = df[~df['股票代码'].isin(delect_data)]

df.to_csv('all_stock_history2_cleaned.csv', encoding='utf-8-sig', index=False)
print('完成清洗')
