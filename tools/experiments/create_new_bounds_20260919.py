#!/usr/bin/env python3
"""Generate frozen bounds eggplant_full_gen_sasc094_sldr024_slll018_020_20260919
"""
import hashlib
import yaml
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path("D:/Tomato_Cal")
base_bounds_csv = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_full_gen_slu1_slll4cm_sasc0922_0945_20260919.csv"
df = pd.read_csv(base_bounds_csv)

c06_params_csv = PROJECT_ROOT / "workspace/candidates/candidate_c06_real44/params.csv"
df_c06 = pd.read_csv(c06_params_csv)
c06_map = dict(zip(df_c06["name"].str.lower(), df_c06["value"]))

# Update init values of active genetic parameters from C06
for idx, row in df.iterrows():
    pname = row["name"].lower()
    if pname == "sasc_ratio":
        df.at[idx, "init"] = 0.94
        df.at[idx, "lower"] = 0.94
        df.at[idx, "upper"] = 0.94
        df.at[idx, "status"] = "fixed"
    elif pname == "soil_slll_01":
        df.at[idx, "init"] = 0.18
        df.at[idx, "lower"] = 0.18
        df.at[idx, "upper"] = 0.18
        df.at[idx, "status"] = "fixed"
    elif pname == "soil_slll_02":
        df.at[idx, "init"] = 0.20
        df.at[idx, "lower"] = 0.20
        df.at[idx, "upper"] = 0.20
        df.at[idx, "status"] = "fixed"
    elif pname == "soil_sldr":
        df.at[idx, "init"] = 0.24
        df.at[idx, "lower"] = 0.24
        df.at[idx, "upper"] = 0.24
        df.at[idx, "status"] = "fixed"
    elif row["status"] == "active" and pname in c06_map:
        val = c06_map[pname]
        df.at[idx, "init"] = round(val, 6)

out_bounds_id = "eggplant_full_gen_sasc094_sldr024_slll018_020_20260919"
out_csv = PROJECT_ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{out_bounds_id}.csv"
df.to_csv(out_csv, index=False)

csv_sha256 = hashlib.sha256(out_csv.read_bytes()).hexdigest()

meta = {
    "bounds_id": out_bounds_id,
    "crop": "eggplant",
    "created_at": "2026-09-19",
    "description": "Frozen 70 active genetic parameters with SASC_RATIO=0.94, SOIL_SLLL_01=0.18, SOIL_SLLL_02=0.20, SOIL_SLDR=0.24 fixed. SLU1=1.0, EFIR=0.95, ICNS_26SP=0.70 fixed. Candidate C06 init centering.",
    "num_parameters": len(df),
    "num_active": len(df[df["status"] == "active"]),
    "num_fixed": len(df[df["status"] == "fixed"]),
    "source_proposal": str(base_bounds_csv),
    "sha256": csv_sha256,
}

out_yaml = PROJECT_ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{out_bounds_id}.yaml"
with open(out_yaml, "w", encoding="utf-8") as f:
    yaml.dump(meta, f, sort_keys=False, default_flow_style=False)

print(f"Generated {out_csv} (active: {meta['num_active']}, fixed: {meta['num_fixed']})")
print(f"SHA256: {csv_sha256}")
