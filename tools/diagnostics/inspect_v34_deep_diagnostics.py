#!/usr/bin/env python3
"""Deep diagnostic script for Formal Calibration v34.
1. Computes per-treatment metrics for all 22 treatments across both seasons.
2. Analyzes parameter posterior distribution across top ensemble members and checks boundary proximity.
"""

from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = PROJECT_ROOT / "workspace/runs/e02_formal_v34_nitrogen_smoothed_200x6_20260829"
BOUNDS_CSV = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v34_formal_nitrogen_smoothed_bounds.csv"
BEST_MEMBER = "125"
DET_DIR = RUN_DIR / f"best_member_{BEST_MEMBER}_two_season_deterministic_20260829"

print("======================================================================")
print(" 1. PARAMETER POSTERIOR DISTRIBUTION & BOUNDARY PROXIMITY ANALYSIS ")
print("======================================================================")

bounds_df = pd.read_csv(BOUNDS_CSV)
active_bounds = bounds_df[bounds_df["status"] == "active"].set_index("name")

# Read final iteration parameter ensemble (iteration 6)
par_csv = RUN_DIR / "e02_formal_v34_n_smooth_20260829.6.par.csv"
if not par_csv.exists():
    par_csv = RUN_DIR / "e02_formal_v34_n_smooth_20260829.5.par.csv"

# Read phi to find top 20% members
phi_csv = RUN_DIR / "e02_formal_v34_n_smooth_20260829.phi.actual.csv"
phi_df = pd.read_csv(phi_csv, index_col=0)
last_iter = phi_df.index[-1]
phi_last = pd.to_numeric(phi_df.loc[last_iter], errors="coerce").dropna()
top_members = phi_last.nsmallest(40).index.tolist()  # Top 20%

best_params_csv = DET_DIR / f"best_member_{BEST_MEMBER}_params.csv"
best_p_df = pd.read_csv(best_params_csv).set_index("name")

param_records = []

if par_csv.exists():
    par_df = pd.read_csv(par_csv, index_col=0)
    valid_members = [m for m in top_members if m in par_df.index]
    if not valid_members:
        valid_members = par_df.index.tolist()
    sub_par = par_df.loc[valid_members]

    for pname, b_row in active_bounds.iterrows():
        pname_str = str(pname).upper()
        pname_match = None
        for col in par_df.columns:
            if col.upper() == pname_str:
                pname_match = col
                break
        if pname_match is None:
            continue

        vals = pd.to_numeric(sub_par[pname_match], errors="coerce").dropna()
        best_val = float(best_p_df.loc[pname_str, "value"]) if pname_str in best_p_df.index else vals.median()
        lb = float(b_row["lower"])
        ub = float(b_row["upper"])
        rng = ub - lb if ub > lb else 1.0

        p_min = vals.min()
        p_max = vals.max()
        p_mean = vals.mean()
        p_std = vals.std()

        dist_lb = (best_val - lb) / rng * 100.0
        dist_ub = (ub - best_val) / rng * 100.0
        
        status_tag = "OK"
        if dist_lb < 5.0 or (p_mean - lb) / rng < 0.05:
            status_tag = "TOUCH_LOWER"
        elif dist_ub < 5.0 or (ub - p_mean) / rng < 0.05:
            status_tag = "TOUCH_UPPER"
        elif p_std / rng < 0.01:
            status_tag = "COLLAPSED"

        param_records.append({
            "name": pname_str,
            "best_val": best_val,
            "mean": p_mean,
            "std": p_std,
            "lower": lb,
            "upper": ub,
            "dist_lb_%": dist_lb,
            "dist_ub_%": dist_ub,
            "tag": status_tag,
        })

df_par_diag = pd.DataFrame(param_records)
print(f"Total active parameters analyzed: {len(df_par_diag)}")

touching = df_par_diag[df_par_diag["tag"] != "OK"].sort_values("tag")
print(f"\n--- Touching / Constrained Parameters ({len(touching)}) ---")
print(touching[["name", "lower", "best_val", "upper", "dist_lb_%", "dist_ub_%", "tag"]].to_string(index=False))

print("\n======================================================================")
print(" 2. PER-TREATMENT OBSERVATION & SIMULATION PERFORMANCE ANALYSIS ")
print("======================================================================")

for season, t_list in [("25SP", [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]), ("26SP", list(range(1, 13)))]:
    s_dir = DET_DIR / "_seasons" / season
    tmt_grow_file = s_dir / "PestTmtGrow.OUT"
    harvest_file = s_dir / "PestHarvest.OUT"
    
    print(f"\n==================== Season {season} Per-Treatment ====================")
    
    # 1. Harvest analysis
    if harvest_file.exists():
        lines = harvest_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        header = None
        rows = []
        for l in lines:
            if "@" in l and header is None:
                header = l.replace("@", "").split()
            elif header and l.strip() and not l.startswith("*"):
                parts = l.split()
                if len(parts) >= len(header):
                    rows.append(parts[:len(header)])
        if header and rows:
            hdf = pd.DataFrame(rows, columns=header)
            hdf = hdf.apply(pd.to_numeric, errors="coerce")
            
            # Group by TRNO and compare observed vs simulated cumulative fresh yield
            # Look at available columns
            print("\n[Harvest Fresh Yield (kg/ha)]")
            print("TRNO | Obs Terminal | Sim Terminal | Bias (Sim-Obs) | Terminal RRMSE%")
            print("-------------------------------------------------------------------")
            for trno in sorted(hdf["TRNO"].unique()):
                sub = hdf[hdf["TRNO"] == trno].sort_values("DAP")
                # Look for HWAM (sim) and HWAM_OBS / observed
                # Let's inspect columns
                cols = [c for c in sub.columns if "HW" in c or "YI" in c or "CW" in c or "FW" in c]
                # In DSSAT harvest output: CWAD, HWAD, FWAD, or simulated harvest
                last_row = sub.iloc[-1]
                obs_val = last_row.get("HWAM_OBS", last_row.get("CWAD_OBS", np.nan))
                sim_val = last_row.get("HWAM", last_row.get("CWAD", np.nan))
                bias = sim_val - obs_val if pd.notna(obs_val) and pd.notna(sim_val) else np.nan
                rrmse = abs(bias) / obs_val * 100.0 if pd.notna(bias) and obs_val > 0 else np.nan
                role = "CALIB" if (season == "25SP" and trno in [2, 5, 10, 13]) or (season == "26SP" and trno in [1, 3, 9, 12]) else "VALID"
                print(f"TN{int(trno):02d} ({role:5s}) | {obs_val:12.1f} | {sim_val:12.1f} | {bias:+14.1f} | {rrmse:13.1f}%")

    # 2. Process state (LAID / SWAD / LWAD) analysis
    if tmt_grow_file.exists():
        lines = tmt_grow_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        header = None
        rows = []
        for l in lines:
            if "@" in l and header is None:
                header = l.replace("@", "").split()
            elif header and l.strip() and not l.startswith("*"):
                parts = l.split()
                if len(parts) >= len(header):
                    rows.append(parts[:len(header)])
        if header and rows:
            gdf = pd.DataFrame(rows, columns=header)
            gdf = gdf.apply(pd.to_numeric, errors="coerce")
            print(f"\n[Growth Process (LAID & SWAD) by Treatment in {season}]")
            print("TRNO | Max LAID Obs | Max LAID Sim | LAID Bias | Max SWAD Obs | Max SWAD Sim | SWAD Bias")
            print("------------------------------------------------------------------------------------")
            for trno in sorted(gdf["TRNO"].unique()):
                sub = gdf[gdf["TRNO"] == trno]
                obs_lai = sub.get("LAID_OBS", sub.get("LAID", pd.Series([np.nan]))).max()
                sim_lai = sub["LAID"].max() if "LAID" in sub.columns else np.nan
                obs_sw = sub.get("SWAD_OBS", sub.get("SWAD", pd.Series([np.nan]))).max()
                sim_sw = sub["SWAD"].max() if "SWAD" in sub.columns else np.nan
                role = "CALIB" if (season == "25SP" and trno in [2, 5, 10, 13]) or (season == "26SP" and trno in [1, 3, 9, 12]) else "VALID"
                print(f"TN{int(trno):02d} ({role:5s}) | {obs_lai:12.2f} | {sim_lai:12.2f} | {sim_lai-obs_lai:+9.2f} | {obs_sw:12.1f} | {sim_sw:12.1f} | {sim_sw-obs_sw:+9.1f}")
