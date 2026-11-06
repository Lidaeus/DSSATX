#!/usr/bin/env python3
"""Generate V4 parameter bounds proposal:
- Leaf senescence tuning to simulate manual greenhouse pruning (SENRTE, SENPOR_LATE)
- Organ phosphorus refinement based on measured plant samples (OPTLFP_FS, OPTSTP_FS, OPTSDP_FS)
- Inherits V3 champion parameter values
"""

import csv
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V3_BOUNDS_CSV = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_full_genetic_98pct_v3_20260915.csv"
V3_CHAMPION_CSV = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_98pct_v3_20260915" / "full_gen98_v3_best_parameters_fixed.csv"
OUT_CSV = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_proposals" / "eggplant_full_genetic_98pct_v4_20260915.csv"

df_bounds = pd.read_csv(V3_BOUNDS_CSV)
champ_df = pd.read_csv(V3_CHAMPION_CSV)
champ_dict = dict(zip(champ_df["name"], champ_df["value"]))

rows = []
for _, r in df_bounds.iterrows():
    row = r.to_dict()
    name = row["name"]
    status = str(row["status"]).strip().lower()
    
    # 1. Leaf senescence tuning (SENRTE)
    if name.lower() == "senrte":
        row["init"] = 6.50
        row["lower"] = 4.00
        row["upper"] = 8.50
        row["status"] = "active"
        
    # 2. Organ phosphorus tuning
    elif name.lower() == "optlfp_fs":
        row["init"] = 0.00340
        row["lower"] = 0.00280
        row["upper"] = 0.00420
        row["status"] = "active"
    elif name.lower() == "optstp_fs":
        row["init"] = 0.00285
        row["lower"] = 0.00220
        row["upper"] = 0.00350
        row["status"] = "active"
    elif name.lower() == "optsdp_fs":
        row["init"] = 0.00475
        row["lower"] = 0.00400
        row["upper"] = 0.00520
        row["status"] = "active"
    else:
        if status == "active" and name in champ_dict:
            val = float(champ_dict[name])
            lb = float(row["lower"])
            ub = float(row["upper"])
            row["init"] = round(max(lb, min(ub, val)), 6)
        elif status == "fixed":
            # Keep exact equality for fixed parameters
            row["init"] = row["lower"]
            row["upper"] = row["lower"]
            
    rows.append(row)

# 3. Add SENPOR_LATE if not already present
if not any(r["name"].lower() == "senpor_late" for r in rows):
    rows.append({
        "name": "SENPOR_LATE",
        "init": 0.19,
        "lower": 0.15,
        "upper": 0.25,
        "status": "active",
        "pargp": "SPE_Senescence",
        "location": "SPE",
        "file": "TMGRO048.SPE",
        "cultivar": "TM0008",
        "ecotype": "DFAULT",
        "mode": "none"
    })

df_out = pd.DataFrame(rows)
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
df_out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
print(f"Generated V4 proposal with {len(df_out)} parameters at {OUT_CSV}")
