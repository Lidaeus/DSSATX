"""Check specific data issues for DSSAT FileA/FileT generation."""
import pandas as pd
from pathlib import Path

ROOT = Path(r'D:\Tomato_Cal\data\user\ref\DSSAT文件')

# 1. 2025春: plot count, treatment mapping, harvest dates
print('='*80)
print('1. 2025春 产量数据集: 小区/处理/日期')
print('='*80)
y = pd.read_excel(ROOT / '2025春' / '2025春产量数据集.xlsx', sheet_name='Sheet1')
y['日期'] = pd.to_datetime(y['日期'], errors='coerce')
print(f'Total rows: {len(y)}')
print(f'Plots (小区号): {sorted(y["小区号"].dropna().unique())}')
print(f'Harvest dates: {sorted(y["日期"].dropna().dt.date.unique())}')
trt = y[['小区号','水处理','氮处理']].drop_duplicates().sort_values('小区号')
print(f'\nTreatment mapping ({len(trt)} plots):')
print(trt.to_string(index=False))

# 2. 2025秋: quality data - 半果含水率 coverage
print('\n' + '='*80)
print('2. 2025秋 品质指标集: 半果含水率 coverage')
print('='*80)
q = pd.read_excel(ROOT / '2025秋' / '25年秋季2号棚品质指标集.xlsx', sheet_name='Sheet1')
print(f'Total rows: {len(q)}')
print(f'半果含水率 non-null: {q["半果含水率"].notna().sum()} / {len(q)}')
print(f'Dates: {sorted(q["测定日期"].dropna().dt.date.unique())}')
if q['半果含水率'].notna().any():
    print(f'半果含水率 range: {q["半果含水率"].min():.4f} - {q["半果含水率"].max():.4f}')

# 3. 2025秋: growth data - 果含水率 vs 果干重
print('\n' + '='*80)
print('3. 2025秋 生长指标集: 果干重/果含水率')
print('='*80)
g = pd.read_excel(ROOT / '2025秋' / '2025年秋季茄子生长指标集.xlsx', sheet_name='Sheet1')
print(f'Total rows: {len(g)}')
print(f'果干重 > 0: {(g["果干重"] > 0).sum()} rows')
print(f'果含水率 non-null: {g["果含水率"].notna().sum()} rows')
print(f'Dates: {sorted(g["日期"].dropna().dt.date.unique())}')
fruit_data = g[g['果干重'] > 0].copy()
if not fruit_data.empty:
    fruit_data['DMFR'] = fruit_data['果干重'] / (fruit_data['果干重'] / (1 - fruit_data['果含水率']))
    print(f'\n果干重>0 rows: {len(fruit_data)}')
    print(f'DMFR (from 果干重/果鲜重) range: {fruit_data["DMFR"].min():.4f} - {fruit_data["DMFR"].max():.4f}')

# 4. 2026春: growth sheets overview
print('\n' + '='*80)
print('4. 2026春 生长指标集: all sheets')
print('='*80)
xls = pd.ExcelFile(ROOT / '2026春' / '2026春生长指标集.xlsx')
for sheet in xls.sheet_names:
    df = pd.read_excel(ROOT / '2026春' / '2026春生长指标集.xlsx', sheet_name=sheet)
    has_lai = 'LAI' in df.columns
    has_fruit = any('果' in str(c) and '鲜' in str(c) for c in df.columns)
    print(f'  Sheet "{sheet}": {len(df)} rows, {df.shape[1]} cols, LAI={has_lai}, 果鲜重={has_fruit}')
    # Identify plot column
    plot_col = [c for c in df.columns if '小区' in str(c) or '处理' in str(c)]
    print(f'    Plot col: {plot_col}')

# 5. 2026春: quality data - 半果含水率
print('\n' + '='*80)
print('5. 2026春 品质指标集: 半果含水率')
print('='*80)
q26 = pd.read_excel(ROOT / '2026春' / '2026春品质指标集.xlsx', sheet_name='Sheet1')
print(f'Total rows: {len(q26)}')
print(f'半果含水率 non-null: {q26["半果含水率"].notna().sum()} / {len(q26)}')
print(f'Dates: {sorted(q26["日期"].unique())}')
print(f'Plots: {sorted(q26["小区号"].unique())}')

# 6. Check 2025春 yield units
print('\n' + '='*80)
print('6. 2025春 产量数据集: units check')
print('='*80)
y2 = pd.read_excel(ROOT / '2025春' / '2025春产量数据集.xlsx', sheet_name='Sheet1')
sample = y2[y2['小区号'] == 1].head(3)
print('Sample rows (小区1):')
for _, r in sample.iterrows():
    print(f'  日期={r["日期"].date()}, 行号={r["行号"]}, 果实总重={r["果实总重"]}, 产量={r["产量"]}, 小区产量={r["小区产量"]}, 加权小区产量={r["加权小区产量"]}')
# Check if 小区产量 is already kg/ha (should be ~5000-10000 for eggplant)
print(f'\n小区产量 range: {y2["小区产量"].min():.1f} - {y2["小区产量"].max():.1f}')
print(f'加权小区产量 range: {y2["加权小区产量"].min():.1f} - {y2["加权小区产量"].max():.1f}')

# 7. 2025秋: treatment mapping
print('\n' + '='*80)
print('7. 2025秋 treatment mapping')
print('='*80)
yf = pd.read_excel(ROOT / '2025秋' / '2025秋季产量集.xlsx', sheet_name='2025秋季产量集')
trt_f = yf[['小区号','水处理','氮处理']].drop_duplicates().sort_values('小区号')
print(f'Plots: {sorted(yf["小区号"].unique())}')
print(trt_f.to_string(index=False))

# 8. 2026春: treatment mapping
print('\n' + '='*80)
print('8. 2026春 treatment mapping')
print('='*80)
y26 = pd.read_excel(ROOT / '2026春' / '2026春产量集.xlsx', sheet_name='Sheet1')
trt_26 = y26[['小区号','水处理','氮处理']].drop_duplicates().sort_values('小区号')
print(f'Plots: {sorted(y26["小区号"].unique())}')
print(trt_26.to_string(index=False))
