"""Verify the improved weight scheme in the new PST."""
import pyemu
import pandas as pd
import numpy as np

pst_path = 'd:/Tomato_Cal/workspace/eggplant_stage2_v14_improved.pst'
pst = pyemu.Pst(pst_path)
obs = pst.observation_data

print('PST obs_data columns:', obs.columns.tolist())
print(f'Total observations: {len(obs)}')
print()
print('First 5 rows:')
print(obs[['obsnme', 'weight']].head(5).to_string())
print()

if 'obgnme' in obs.columns:
    print('Weight by obgnme:')
    grouped = obs.groupby('obgnme').agg(
        count=('weight', 'count'),
        mean_weight=('weight', 'mean'),
        min_weight=('weight', 'min'),
        max_weight=('weight', 'max')
    ).round(6)
    for g, row in grouped.iterrows():
        print(f'  {g}: n={int(row["count"]):3d}, mean={row["mean_weight"]:.6f}')
else:
    print('obgnme not in columns, checking other names...')
    name_cols = [c for c in obs.columns if 'name' in c.lower() or 'grp' in c.lower()]
    print(f'Possible name/group columns: {name_cols}')
    print(obs.head(3).to_string())

print()
print('Legacy comparison:')
try:
    pst_legacy = pyemu.Pst('d:/Tomato_Cal/workspace/eggplant_stage2_v14_full.pst')
    obs_legacy = pst_legacy.observation_data
    print(f'Legacy obs_data columns: {obs_legacy.columns.tolist()}')
    print(f'Legacy first 5 obs: {obs_legacy[["obsnme", "weight"]].head(5).to_string()}')
except Exception as e:
    print(f'Could not load legacy PST: {e}')
