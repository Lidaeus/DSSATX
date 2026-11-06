#!/usr/bin/env python3
"""Generate updated frozen bounds for Formal Calibration v35 with boundary relaxed nitrogen & physiological parameters.
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_BOUNDS = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v34_formal_nitrogen_smoothed_bounds.csv"
OUT_BOUNDS = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v35_formal_nitrogen_relaxed_bounds.csv"

df = pd.read_csv(BASE_BOUNDS)

ADJUSTMENTS = {
    # 1. Relaxed N Mobilization & Buffer
    "NMOBMX": {"lower": 0.100, "init": 0.260, "upper": 0.450, "status": "active"},
    "NVSMOB": {"lower": 0.450, "init": 0.700, "upper": 0.850, "status": "active"},
    "NRCVR": {"lower": 0.100, "init": 0.220, "upper": 0.350, "status": "active"},

    # 2. Relaxed N Stress Sensitivity & Curve
    "NSTFAC": {"lower": 0.150, "init": 0.350, "upper": 0.600, "status": "active"},
    "FNPGN1": {"lower": 0.500, "init": 0.800, "upper": 1.400, "status": "active", "pargp": "SPE_Photo", "location": "SPE", "file": "TMGRO048.SPE"},
    "FNPGN2": {"lower": 2.800, "init": 3.500, "upper": 4.200, "status": "active", "pargp": "SPE_Photo", "location": "SPE", "file": "TMGRO048.SPE"},
    "LNREF": {"lower": 2.500, "init": 3.300, "upper": 4.200, "status": "active"},
    "NSLOPE": {"lower": 0.060, "init": 0.120, "upper": 0.200, "status": "active"},

    # 3. Relaxed Organ Protein Bounds
    "PROSTI": {"lower": 0.150, "init": 0.250, "upper": 0.320, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PRORTG": {"lower": 0.080, "init": 0.150, "upper": 0.200, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PROLFG": {"lower": 0.130, "init": 0.175, "upper": 0.250, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PROLFF": {"lower": 0.050, "init": 0.095, "upper": 0.130, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PROSTF": {"lower": 0.025, "init": 0.038, "upper": 0.060, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PRORTF": {"lower": 0.020, "init": 0.032, "upper": 0.050, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PROLFI": {"lower": 0.200, "init": 0.270, "upper": 0.350, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},
    "PRORTI": {"lower": 0.110, "init": 0.144, "upper": 0.190, "status": "active", "pargp": "SPE_Compo", "location": "SPE", "file": "TMGRO048.SPE"},

    # 4. Relaxed Photosynthesis & Carbon Dynamics
    "PGEFF": {"lower": 0.042, "init": 0.0475, "upper": 0.056, "status": "active", "pargp": "SPE_Photosynthesis", "location": "SPE", "file": "TMGRO048.SPE"},
    "CMOBMX": {"lower": 0.005, "init": 0.020, "upper": 0.100, "status": "active"},
    "DSWBAR": {"lower": 2.000, "init": 5.000, "upper": 20.000, "status": "active"},
    "KC_SLOPE": {"lower": 0.003, "init": 0.010, "upper": 0.050, "status": "active"},
    "RHGHT": {"lower": 0.400, "init": 0.700, "upper": 1.200, "status": "active"},
    "RWDTH": {"lower": 0.350, "init": 0.500, "upper": 1.800, "status": "active"},
    "XFRT": {"lower": 0.550, "init": 0.720, "upper": 0.900, "status": "active"},
    "TM3": {"lower": 35.0, "init": 45.0, "upper": 48.0, "status": "active"},
    "CSDL": {"lower": 11.50, "init": 12.07, "upper": 13.00, "status": "active"},

    # 5. Root N Uptake & Translocation
    "RTNO3": {"lower": 0.015, "init": 0.041, "upper": 0.050, "status": "active"},
    "RTNH4": {"lower": 0.008, "init": 0.025, "upper": 0.050, "status": "active"},
    "RTEXF": {"lower": 0.080, "init": 0.190, "upper": 0.300, "status": "active"},
    "NREXP": {"lower": 0.200, "init": 0.550, "upper": 0.900, "status": "active"},
    "NRMIN": {"lower": 0.300, "init": 0.650, "upper": 0.850, "status": "active"},
}

existing_names = set(df["name"].str.upper().tolist())

# Update existing rows
for idx, row in df.iterrows():
    name = str(row["name"]).upper()
    if name in ADJUSTMENTS:
        adj = ADJUSTMENTS[name]
        for k, v in adj.items():
            df.at[idx, k] = v

# Add new parameters if any
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
print(f"Written v35 bounds to {OUT_BOUNDS} with {len(df)} total parameters (active: {(df['status']=='active').sum()})")
