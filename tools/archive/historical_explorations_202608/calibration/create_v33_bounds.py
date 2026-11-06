#!/usr/bin/env python3
"""Generate updated frozen bounds for 8-treatment fresh-weight formal calibration (v33).
"""

from __future__ import annotations

import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_BOUNDS = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v32_formal_final_champion_bounds.csv"
OUT_BOUNDS = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v33_formal_8treat_fresh_bounds.csv"

df = pd.read_csv(BASE_BOUNDS)

# Adjustments map: param -> (lower, init, upper, status, pargp)
ADJUSTMENTS = {
    "PGEFF": {"lower": 0.047, "init": 0.0525, "upper": 0.058, "status": "active", "pargp": "SPE_Photosynthesis", "location": "SPE", "file": "TMGRO048.SPE"},
    "LNREF": {"lower": 2.50, "init": 3.50, "upper": 6.00, "status": "active"},
    "NSLOPE": {"lower": 0.08, "init": 0.12, "upper": 0.35, "status": "active"},
    "NSTFAC": {"lower": 0.60, "init": 0.95, "upper": 1.00, "status": "active"},
    "NMOBMX": {"lower": 0.02, "init": 0.06, "upper": 0.20, "status": "active"},
    "NVSMOB": {"lower": 0.20, "init": 0.55, "upper": 0.70, "status": "active"},
    "NRCVR": {"lower": 0.05, "init": 0.22, "upper": 0.35, "status": "active"},
    "RTNO3": {"lower": 0.010, "init": 0.040, "upper": 0.050, "status": "active"},
    "RTNH4": {"lower": 0.005, "init": 0.025, "upper": 0.050, "status": "active"},
    "RTEXF": {"lower": 0.08, "init": 0.18, "upper": 0.30, "status": "active"},
    "NREXP": {"lower": 0.10, "init": 0.50, "upper": 1.00, "status": "active"},
    "NRMIN": {"lower": 0.20, "init": 0.70, "upper": 0.90, "status": "active"},
    "SFDUR": {"lower": 40.0, "init": 48.0, "upper": 65.0, "status": "active"},
    "WTFSD": {"lower": 0.40, "init": 0.48, "upper": 0.60, "status": "active"},
    "PORPT": {"lower": 0.22, "init": 0.30, "upper": 0.42, "status": "active"},
    "CMOBMX": {"lower": 0.02, "init": 0.05, "upper": 0.15, "status": "active"},
    "LFMAX": {"lower": 1.60, "init": 2.00, "upper": 2.40, "status": "active"},
    "PHTMAX": {"lower": 50.0, "init": 65.0, "upper": 80.0, "status": "active"},
    "FINREF": {"lower": 150.0, "init": 175.0, "upper": 300.0, "status": "active"},
    "LNGSH": {"lower": 15.0, "init": 22.0, "upper": 45.0, "status": "active"},
    "SIZLF": {"lower": 280.0, "init": 345.0, "upper": 400.0, "status": "active"},
}

# Update existing rows
for idx, row in df.iterrows():
    name = str(row["name"]).upper()
    if name in ADJUSTMENTS:
        adj = ADJUSTMENTS[name]
        for k, v in adj.items():
            df.at[idx, k] = v

# Add PGEFF if not present
if "pgeff" not in df["name"].str.lower().tolist():
    pgeff_dict = {
        "name": "PGEFF",
        "init": 0.0525,
        "lower": 0.047,
        "upper": 0.058,
        "status": "active",
        "pargp": "SPE_Photosynthesis",
        "location": "SPE",
        "file": "TMGRO048.SPE",
        "cultivar": "",
        "ecotype": "",
        "mode": "",
    }
    df = pd.concat([df, pd.DataFrame([pgeff_dict])], ignore_index=True)

df.to_csv(OUT_BOUNDS, index=False)
print(f"Written updated bounds to {OUT_BOUNDS} with {len(df)} parameters (active: {(df['status']=='active').sum()})")
