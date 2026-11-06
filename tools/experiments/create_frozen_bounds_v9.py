#!/usr/bin/env python3
"""Generate frozen bounds CSV and YAML for V9 calibration:
eggplant_full_gen_slu1_slll4cm_sasc0922_0945_20260919.

Changes relative to eggplant_full_gen_p22_sasc0945_sldr015_035_20260919:
1. SASC_RATIO: active, range [0.922, 0.945], init 0.933
2. soil_slll_01 (0-2cm): active, range [0.120, 0.240], init 0.180
3. soil_slll_02 (2-4cm): active, range [0.120, 0.240], init 0.180
4. SOIL_SLDR: active, range [0.15, 0.35], init 0.25
5. ICNS_26SP: fixed at 0.70
6. All other 70 genetic parameters: active from champion iter5_real13 / baseline.
"""
from pathlib import Path
import hashlib
import yaml
import pandas as pd

PROJECT_ROOT = Path("D:/Tomato_Cal")
SRC_CSV = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_full_gen_p22_sasc0945_sldr015_035_20260919.csv"

BOUNDS_ID = "eggplant_full_gen_slu1_slll4cm_sasc0922_0945_20260919"
OUT_CSV = PROJECT_ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv"
OUT_YAML = PROJECT_ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.yaml"

df = pd.read_csv(SRC_CSV)

# Update SASC_RATIO
mask_sasc = df["name"].str.upper() == "SASC_RATIO"
df.loc[mask_sasc, "status"] = "active"
df.loc[mask_sasc, "lower"] = 0.922
df.loc[mask_sasc, "upper"] = 0.945
df.loc[mask_sasc, "init"] = 0.933

# Update soil_slll_01
mask_slll1 = df["name"].str.upper() == "SOIL_SLLL_01"
df.loc[mask_slll1, "status"] = "active"
df.loc[mask_slll1, "lower"] = 0.120
df.loc[mask_slll1, "upper"] = 0.240
df.loc[mask_slll1, "init"] = 0.180

# Update soil_slll_02
mask_slll2 = df["name"].str.upper() == "SOIL_SLLL_02"
df.loc[mask_slll2, "status"] = "active"
df.loc[mask_slll2, "lower"] = 0.120
df.loc[mask_slll2, "upper"] = 0.240
df.loc[mask_slll2, "init"] = 0.180

# Ensure SOIL_SLDR is active in [0.15, 0.35]
mask_sldr = df["name"].str.upper() == "SOIL_SLDR"
df.loc[mask_sldr, "status"] = "active"
df.loc[mask_sldr, "lower"] = 0.15
df.loc[mask_sldr, "upper"] = 0.35
df.loc[mask_sldr, "init"] = 0.25

# Ensure ICNS_26SP is fixed at 0.70
mask_icns = df["name"].str.upper() == "ICNS_26SP"
df.loc[mask_icns, "status"] = "fixed"
df.loc[mask_icns, "lower"] = 0.70
df.loc[mask_icns, "upper"] = 0.70
df.loc[mask_icns, "init"] = 0.70

# Save CSV
df.to_csv(OUT_CSV, index=False)
print(f"Saved {OUT_CSV}")

# Print active parameters summary
active_df = df[df["status"] == "active"]
print(f"Total parameters: {len(df)}, Active: {len(active_df)}, Fixed: {len(df[df['status'] == 'fixed'])}")

# Calculate SHA256
sha256 = hashlib.sha256(OUT_CSV.read_bytes()).hexdigest()

# Metadata YAML
meta = {
    "bounds_id": BOUNDS_ID,
    "crop": "eggplant",
    "created_at": "2026-09-19T07:05:00Z",
    "csv_file": f"{BOUNDS_ID}.csv",
    "csv_sha256": sha256,
    "description": (
        "Full genetic suite (70 params) + SOIL_SLDR [0.15, 0.35] + SOIL_SLLL_01 [0.12, 0.24] "
        "+ SOIL_SLLL_02 [0.12, 0.24] + SASC_RATIO [0.922, 0.945] with SLU1=1.0 and EFIR=0.95."
    ),
    "total_params": len(df),
    "active_params": len(active_df),
    "fixed_params": len(df[df["status"] == "fixed"]),
    "parent_bounds_id": "eggplant_full_gen_p22_sasc0945_sldr015_035_20260919",
}

with open(OUT_YAML, "w", encoding="utf-8") as f:
    yaml.dump(meta, f, sort_keys=False)
print(f"Saved {OUT_YAML}")
