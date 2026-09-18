#!/usr/bin/env python3
"""Generate updated frozen bounds for Formal Calibration v34 with smoothed nitrogen stress & broadened protein ranges.
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_BOUNDS = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v33_formal_8treat_fresh_bounds.csv"
OUT_BOUNDS = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v34_formal_nitrogen_smoothed_bounds.csv"

df = pd.read_csv(BASE_BOUNDS)

ADJUSTMENTS = {
    # 1. Broaden minimum protein bounds
    "PROLFF": {"lower": 0.050, "init": 0.075, "upper": 0.100, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PROSTF": {"lower": 0.025, "init": 0.038, "upper": 0.055, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PRORTF": {"lower": 0.020, "init": 0.032, "upper": 0.050, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PROLFG": {"lower": 0.180, "init": 0.220, "upper": 0.280, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PROSTG": {"lower": 0.100, "init": 0.136, "upper": 0.180, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PRORTG": {"lower": 0.080, "init": 0.119, "upper": 0.150, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PROLFI": {"lower": 0.220, "init": 0.270, "upper": 0.350, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PROSTI": {"lower": 0.150, "init": 0.188, "upper": 0.250, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PRORTI": {"lower": 0.110, "init": 0.144, "upper": 0.190, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},

    # 2. Enhanced N Mobilization Buffer
    "NMOBMX": {"lower": 0.100, "init": 0.160, "upper": 0.250, "status": "active"},
    "NVSMOB": {"lower": 0.450, "init": 0.600, "upper": 0.750, "status": "active"},
    "NRCVR": {"lower": 0.100, "init": 0.220, "upper": 0.350, "status": "active"},

    # 3. Smoothed Leaf N - Photosynthesis Curve & Expansion Sensitivity
    "FNPGN1": {"lower": 0.800, "init": 1.100, "upper": 1.600, "status": "active", "pargp": "SPE_Photo", "location": "SPE", "file": "TMGRO048.SPE"},
    "FNPGN2": {"lower": 3.000, "init": 3.500, "upper": 4.200, "status": "active", "pargp": "SPE_Photo", "location": "SPE", "file": "TMGRO048.SPE"},
    "LNREF": {"lower": 2.800, "init": 3.300, "upper": 4.200, "status": "active"},
    "NSLOPE": {"lower": 0.080, "init": 0.120, "upper": 0.200, "status": "active"},
    "NSTFAC": {"lower": 0.400, "init": 0.550, "upper": 0.750, "status": "active"},

    # 4. Root N uptake & partitioning
    "RTNO3": {"lower": 0.015, "init": 0.040, "upper": 0.050, "status": "active"},
    "RTNH4": {"lower": 0.008, "init": 0.025, "upper": 0.050, "status": "active"},
    "RTEXF": {"lower": 0.080, "init": 0.180, "upper": 0.300, "status": "active"},
    "NREXP": {"lower": 0.200, "init": 0.550, "upper": 0.900, "status": "active"},
    "NRMIN": {"lower": 0.300, "init": 0.650, "upper": 0.850, "status": "active"},

    # 5. Restored PGEFF and physiological params
    "PGEFF": {"lower": 0.047, "init": 0.0525, "upper": 0.058, "status": "active", "pargp": "SPE_Photosynthesis", "location": "SPE", "file": "TMGRO048.SPE"},
    "FINREF": {"lower": 150.0, "init": 175.0, "upper": 300.0, "status": "active"},
    "LNGSH": {"lower": 15.0, "init": 22.0, "upper": 45.0, "status": "active"},
    "SIZLF": {"lower": 280.0, "init": 345.0, "upper": 400.0, "status": "active"},
    "CMOBMX": {"lower": 0.020, "init": 0.050, "upper": 0.150, "status": "active"},
    "SFDUR": {"lower": 40.0, "init": 48.0, "upper": 65.0, "status": "active"},
    "WTFSD": {"lower": 0.400, "init": 0.480, "upper": 0.600, "status": "active"},
    "PORPT": {"lower": 0.220, "init": 0.300, "upper": 0.420, "status": "active"},
    "LFMAX": {"lower": 1.600, "init": 2.000, "upper": 2.400, "status": "active"},
    "PHTMAX": {"lower": 50.0, "init": 65.0, "upper": 80.0, "status": "active"},
}

existing_names = set(df["name"].str.upper().tolist())

# Update existing rows
for idx, row in df.iterrows():
    name = str(row["name"]).upper()
    if name in ADJUSTMENTS:
        adj = ADJUSTMENTS[name]
        for k, v in adj.items():
            df.at[idx, k] = v

# Add new parameters that were not in base table
new_rows = []
for name, adj in ADJUSTMENTS.items():
    if name not in existing_names:
        row_dict = {
            "name": name,
            "init": adj["init"],
            "lower": adj["lower"],
            "upper": adj["upper"],
            "status": adj["status"],
            "pargp": adj.get("pargp", "SPE_Photo"),
            "location": adj.get("location", "SPE"),
            "file": adj.get("file", "TMGRO048.SPE"),
            "cultivar": "",
            "ecotype": "",
            "mode": "",
        }
        new_rows.append(row_dict)

if new_rows:
    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)

df.to_csv(OUT_BOUNDS, index=False)
print(f"Written v34 bounds to {OUT_BOUNDS} with {len(df)} total parameters (active: {(df['status']=='active').sum()})")
