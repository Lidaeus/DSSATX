#!/usr/bin/env python3
"""Generate eggplant_e02_v45_nitrogen_synergy_bounds.csv
Inheriting from eggplant_e02_v41_nitrogen_10x_synergy_bounds.csv with targeted physiological constraints.
"""

from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
src_file = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v41_nitrogen_10x_synergy_bounds.csv"
dst_file = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v45_nitrogen_synergy_bounds.csv"

df = pd.read_csv(src_file)

# Parameter updates dict: name -> (init, lower, upper, status, notes)
updates = {
    "PROLFF": (0.200, 0.180, 0.220, "active", "v45: Leaf min protein floor to prevent N0 over-mining"),
    "PROSTF": (0.100, 0.080, 0.120, "active", "v45: Stem min protein floor"),
    "NVSMOB": (0.380, 0.320, 0.450, "active", "v45: Max mobilizable N fraction capped to 0.45"),
    "NMOBMX": (0.100, 0.080, 0.150, "active", "v45: Max daily N mobilization rate limited"),
    "FNPGN1": (1.250, 1.100, 1.450, "active", "v45: Critical leaf N for photosynthesis floor"),
    "FNPGN2": (4.250, 4.100, 4.450, "active", "v45: Min leaf N for max photosynthesis"),
    "SENRTE": (4.000, 3.000, 5.000, "active", "v45: N stress senescence acceleration"),
    "SENDAY": (0.050, 0.035, 0.070, "active", "v45: Daily leaf abscission fraction"),
    "NREXP": (0.850, 0.700, 0.950, "active", "v45: N stress sensitivity exponent"),
    "NSTFAC": (0.450, 0.300, 0.550, "active", "v45: N stress factor amplification"),
    "LFMAX": (2.000, 1.850, 2.200, "active", "v45: Max leaf photosynthesis rate"),
    "SFDUR": (37.00, 35.00, 42.00, "active", "v45: Fruit filling duration"),
    "KCAN": (0.450, 0.350, 0.550, "active", "v45: Canopy extinction coefficient"),
}

for idx, row in df.iterrows():
    name_u = str(row["name"]).upper()
    name_l = str(row["name"]).lower()
    match_key = None
    for k in updates:
        if name_u == k.upper() or name_l == k.lower():
            match_key = k
            break
    if match_key:
        init_v, low_v, up_v, stat_v, note_v = updates[match_key]
        df.at[idx, "init"] = init_v
        df.at[idx, "lower"] = low_v
        df.at[idx, "upper"] = up_v
        df.at[idx, "status"] = stat_v
        df.at[idx, "notes"] = note_v

dst_file.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(dst_file, index=False)
print(f"[OK] Generated v45 bounds at {dst_file} with {len(df)} rows.")

# Verify updated parameters
print("\nVerifying key updated parameters in v45 bounds:")
for k in updates:
    sub = df[df["name"].str.upper() == k.upper()]
    if not sub.empty:
        r = sub.iloc[0]
        print(f"  {r['name']:8s}: init={r['init']:7.3f}, lower={r['lower']:7.3f}, upper={r['upper']:7.3f}, status={r['status']}")
    else:
        print(f"  [WARNING] {k} not found in bounds CSV!")
