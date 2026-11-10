"""Quick check of updated 2025春 growth data."""
import pandas as pd

df = pd.read_excel(r'D:\Tomato_Cal\data\user\ref\DSSAT文件\2025春\2025春作物生长指标集.xlsx', sheet_name='Sheet1')
print(f'Total rows: {len(df)}')
print(f'Columns: {list(df.columns)}')
print(f'果含水率 non-null: {df["果含水率"].notna().sum()}')
print(f'Dates: {sorted(df["日期"].dropna().dt.date.unique())}')
print(f'Plots: {sorted(df["小区号"].dropna().unique())}')

fruit = df[df['果含水率'].notna()]
print(f'\nFruit moisture rows: {len(fruit)}')
if not fruit.empty:
    print(f'果含水率 range: {fruit["果含水率"].min():.4f} - {fruit["果含水率"].max():.4f}')
    print(f'Dates with fruit moisture: {sorted(fruit["日期"].dt.date.unique())}')
    print(f'\nSample:')
    print(fruit[['日期', '小区号', '重复', '果含水率']].head(15).to_string())
