"""Quick check of 2025 spring yield data."""
import pandas as pd

df = pd.read_excel(r'D:\Tomato_Cal\data\user\ref\DSSAT文件\2025春\2025春产量数据集.xlsx', sheet_name='Sheet1')
print(f'Total rows: {len(df)}')
print(f'Columns: {list(df.columns)}')

# 行位置 values
positions = df['行位置'].dropna().astype(str).unique()
print(f'\n行位置 values: {sorted(positions)}')

# Plot count
plot_int = pd.to_numeric(df['小区号'], errors='coerce').dropna().astype(int)
print(f'\n小区数量: {plot_int.nunique()}, range: {plot_int.min()}-{plot_int.max()}')

# Dates
dates = pd.to_datetime(df['日期'], errors='coerce').dropna().dt.date.unique()
print(f'\n日期数: {len(dates)}')
print('日期:', sorted(dates))

# Treatment mapping
treat_map = df[['小区号', '水处理', '氮处理']].dropna().drop_duplicates().copy()
treat_map['小区号'] = pd.to_numeric(treat_map['小区号'], errors='coerce')
treat_map = treat_map.dropna().sort_values('小区号')
print('\n小区处理映射:')
print(treat_map.to_string())

# 加权小区产量 vs 小区产量 comparison
print('\n加权产量 vs 小区产量 sample (TRNO=1, first date):')
sample = df[(pd.to_numeric(df['小区号'], errors='coerce') == 1)].head(20)
print(sample[['日期', '小区号', '行位置', '产量', '小区产量', '加权小区产量']].to_string())

# Plot-level summary for first 3 plots
print('\n按小区汇总的最终累计产量:')
df['小区号_int'] = pd.to_numeric(df['小区号'], errors='coerce')
df['日期_dt'] = pd.to_datetime(df['日期'], errors='coerce')
# Take last harvest per plot
last_date = df.groupby('小区号_int')['日期_dt'].max().reset_index()
last_date.columns = ['小区号_int', '最后日期']
print(last_date.to_string())
