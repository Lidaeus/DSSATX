"""Quick inspection of 2025 fall and 2026 spring data structure."""
import pandas as pd
from pathlib import Path

ROOT = Path(r'D:\Tomato_Cal\data\user\ref\DSSAT文件')

print('='*80)
print('2025 秋季')
print('='*80)

# 2025秋 yield
y = pd.read_excel(ROOT / '2025秋' / '2025秋季产量集.xlsx', sheet_name='2025秋季产量集')
print(f'\n[产量集] rows={len(y)}, cols={list(y.columns)}')
print(f'  小区: {sorted(y["小区号"].dropna().unique())}')
y['日期'] = pd.to_datetime(y['日期'], errors='coerce')
print(f'  日期: {sorted(y["日期"].dropna().dt.date.unique())}')
print(f'  sample:')
print(y.head(3).to_string())

# 2025秋 growth
g = pd.read_excel(ROOT / '2025秋' / '2025年秋季茄子生长指标集.xlsx', sheet_name='Sheet1')
print(f'\n[生长集] rows={len(g)}, cols={list(g.columns)}')
g['日期'] = pd.to_datetime(g['日期'], errors='coerce')
print(f'  日期: {sorted(g["日期"].dropna().dt.date.unique())}')
print(f'  果含水率 non-null: {g["果含水率"].notna().sum() if "果含水率" in g.columns else "N/A"}')

# 2025秋 nutrient
n = pd.read_excel(ROOT / '2025秋' / '2025年秋季茄子植株样氮磷钾测定.xlsx', sheet_name='Sheet1')
print(f'\n[养分集] rows={len(n)}, cols={list(n.columns)}')
print(f'  取样部位: {sorted(n["取样部位"].dropna().unique())}')

# 2025秋 quality
q = pd.read_excel(ROOT / '2025秋' / '25年秋季2号棚品质指标集.xlsx', sheet_name='Sheet1')
print(f'\n[品质集] rows={len(q)}, cols={list(q.columns)}')
print(f'  半果含水率 non-null: {q["半果含水率"].notna().sum() if "半果含水率" in q.columns else "N/A"}')

print('\n' + '='*80)
print('2026 春季')
print('='*80)

# 2026春 yield
y26 = pd.read_excel(ROOT / '2026春' / '2026春产量集.xlsx', sheet_name='Sheet1')
print(f'\n[产量集] rows={len(y26)}, cols={list(y26.columns)}')
y26['日期'] = pd.to_datetime(y26['日期'], errors='coerce')
y26['小区号_num'] = pd.to_numeric(y26['小区号'], errors='coerce')
print(f'  小区: {sorted(y26["小区号_num"].dropna().astype(int).unique())}')
print(f'  日期: {sorted(y26["日期"].dropna().dt.date.unique())}')
print(f'  sample:')
print(y26.head(3).to_string())

# 2026春 quality
xls26q = pd.ExcelFile(ROOT / '2026春' / '2026春品质指标集.xlsx')
for sheet in xls26q.sheet_names:
    q26 = pd.read_excel(xls26q, sheet_name=sheet)
    print(f'\n[品质集/{sheet}] rows={len(q26)}, cols={list(q26.columns)}')
    moisture_col = '半果含水率' if '半果含水率' in q26.columns else ('含水率' if '含水率' in q26.columns else None)
    if moisture_col:
        print(f'  {moisture_col} non-null: {q26[moisture_col].notna().sum()}')
    if '日期' in q26.columns:
        q26['日期'] = pd.to_datetime(q26['日期'], errors='coerce')
        print(f'  日期: {sorted(q26["日期"].dropna().dt.date.unique())}')

# 2026春 growth
xls26g = pd.ExcelFile(ROOT / '2026春' / '2026春生长指标集.xlsx')
for sheet in xls26g.sheet_names:
    g26 = pd.read_excel(xls26g, sheet_name=sheet)
    print(f'\n[生长集/{sheet}] rows={len(g26)}, cols={list(g26.columns)}')
