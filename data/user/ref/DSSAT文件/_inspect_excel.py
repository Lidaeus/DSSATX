"""Inspect new Excel data files for DSSAT FileA/FileT generation."""
import pandas as pd
from pathlib import Path

ROOT = Path(r'D:\Tomato_Cal\data\user\ref\DSSAT文件')

SEASONS = {
    '2025春': [
        '2025春产量数据集.xlsx',
        '2025春作物生长指标集.xlsx',
        '2025春土壤数据集.xlsx',
        '2025年春季茄子植株样氮磷钾测定.xlsx',
    ],
    '2025秋': [
        '2025秋季产量集.xlsx',
        '2025年秋季茄子生长指标集.xlsx',
        '20251002_2号棚取土.xlsx',
        '2025年秋季茄子植株样氮磷钾测定.xlsx',
        '25年秋季2号棚品质指标集.xlsx',
    ],
    '2026春': [
        '2026春产量集.xlsx',
        '2026春品质指标集.xlsx',
        '2026春土壤数据集.xlsx',
        '2026春生长指标集.xlsx',
    ],
}

for season, files in SEASONS.items():
    for fname in files:
        fpath = ROOT / season / fname
        if not fpath.exists():
            print(f'!!! NOT FOUND: {season}/{fname}')
            continue
        print(f'{"="*80}')
        print(f'=== {season} / {fname} ===')
        print(f'{"="*80}')
        xls = pd.ExcelFile(fpath)
        for sheet in xls.sheet_names:
            df = pd.read_excel(fpath, sheet_name=sheet, nrows=5)
            print(f'\n  Sheet: "{sheet}" ({df.shape[1]} cols)')
            print(f'  Columns: {list(df.columns)}')
            print(f'  First rows:')
            for _, row in df.iterrows():
                print(f'    {list(row.values)}')
        print()
