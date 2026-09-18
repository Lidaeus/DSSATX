#!/usr/bin/env python3
"""Deep diagnostic script for Formal Calibration v34.
Matches observations and simulations per treatment across 25SP and 26SP.
"""

from __future__ import annotations

import re
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = PROJECT_ROOT / "workspace/runs/e02_formal_v34_nitrogen_smoothed_200x6_20260829"
BOUNDS_CSV = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v34_formal_nitrogen_smoothed_bounds.csv"
BEST_MEMBER = "125"
DET_DIR = RUN_DIR / f"best_member_{BEST_MEMBER}_two_season_deterministic_20260829"

# Load observation registry
obs_reg_file = RUN_DIR / "e02_formal_v34_n_smooth_20260829_observation_registry.csv"
obs_df = pd.read_csv(obs_reg_file)

# Parse simulated outputs from DET_DIR
sim_records = []

for season in ["25SP", "26SP"]:
    s_dir = DET_DIR / "_seasons" / season
    
    # 1. Harvest
    ph_file = s_dir / "PestHarvest.OUT"
    if ph_file.exists():
        for line in ph_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            m_meta = re.search(r"TN\s+(\d+)\s+HNO\s+(\d+)\s+DATE\s+(\d+)", line)
            if m_meta:
                tn = int(m_meta.group(1))
                hno = int(m_meta.group(2))
                date_code = int(m_meta.group(3))
                for var in ["CHFPWS", "CHPDTS", "HPODWS", "PWADS"]:
                    m_val = re.search(rf"@{var}@\s+([-\d\.]+)", line)
                    if m_val:
                        val = float(m_val.group(1))
                        # Match observation name pattern: 25sp_chfpwm_t02_h01
                        base_v = var.replace("S", "").lower()
                        obs_name_pattern = f"{season.lower()}_{base_v}m_t{tn:02d}_h{hno:02d}"
                        sim_records.append({
                            "season": season,
                            "trno": tn,
                            "obs_name": obs_name_pattern.upper(),
                            "sim_token": var,
                            "sim": val,
                            "date_code": date_code,
                            "hno": hno,
                        })

    # 2. Process growth
    pt_file = s_dir / "PestTmtGrow.OUT"
    if pt_file.exists():
        for line in pt_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            m_meta = re.search(r"TN\s+(\d+)\s+DATE\s+(\d+)", line)
            if m_meta:
                tn = int(m_meta.group(1))
                date_code = int(m_meta.group(2))
                for var in ["LAIDS", "LWADS", "SWADS", "CHTDS", "CWADS"]:
                    m_val = re.search(rf"@{var}@\s+([-\d\.]+)", line)
                    if m_val:
                        val = float(m_val.group(1))
                        base_v = var.replace("S", "").lower()
                        obs_name_pattern = f"{season.lower()}_{base_v}m_t{tn:02d}_d{date_code}"
                        sim_records.append({
                            "season": season,
                            "trno": tn,
                            "obs_name": obs_name_pattern.upper(),
                            "sim_token": var,
                            "sim": val,
                            "date_code": date_code,
                            "hno": 0,
                        })

sim_df = pd.DataFrame(sim_records)

# Merge observations and simulations
obs_sub = obs_df[["obsnme", "obsval", "raw_obsval", "treatment", "season_id", "sim_token", "dataset_role"]].copy()
obs_sub["obs_name"] = obs_sub["obsnme"].str.upper()

merged = pd.merge(obs_sub, sim_df, on=["obs_name", "sim_token"], how="inner")
merged["observed"] = merged["raw_obsval"].fillna(merged["obsval"])
merged["error"] = merged["sim"] - merged["observed"]
merged["sq_error"] = merged["error"] ** 2

print("======================================================================")
print(" 1. PER-TREATMENT HARVEST FRESH YIELD PERFORMANCE (CHFPW) ")
print("======================================================================")

chf_df = merged[merged["sim_token"] == "CHFPWS"].copy()
if not chf_df.empty:
    for season in ["25SP", "26SP"]:
        sub_s = chf_df[chf_df["season_id"] == season]
        print(f"\n--- Season {season} Cumulative Fresh Yield (CHFPW kg/ha) by Treatment ---")
        print("TRNO | Role  | Obs Term | Sim Term | Bias (kg/ha) | RRMSE(%) | Traj RMSE (kg/ha) | Traj R2")
        print("-----------------------------------------------------------------------------------------")
        for trno in sorted(sub_s["treatment"].unique()):
            sub_t = sub_s[sub_s["treatment"] == trno].sort_values("hno")
            role = "CALIB" if (season == "25SP" and trno in [2, 5, 10, 13]) or (season == "26SP" and trno in [1, 3, 9, 12]) else "VALID"
            obs_last = sub_t["observed"].iloc[-1]
            sim_last = sub_t["sim"].iloc[-1]
            bias = sim_last - obs_last
            term_rrmse = abs(bias) / obs_last * 100.0 if obs_last > 0 else 0
            traj_rmse = np.sqrt(sub_t["sq_error"].mean())
            r2 = np.corrcoef(sub_t["observed"], sub_t["sim"])[0, 1] ** 2 if len(sub_t) > 2 and sub_t["observed"].std() > 0 and sub_t["sim"].std() > 0 else np.nan
            print(f"TN{int(trno):02d} | {role:5s} | {obs_last:8.1f} | {sim_last:8.1f} | {bias:+12.1f} | {term_rrmse:7.1f}% | {traj_rmse:17.1f} | {r2:7.3f}")

print("\n======================================================================")
print(" 2. PER-TREATMENT CANOPY LAI (LAID) PERFORMANCE ")
print("======================================================================")
lai_df = merged[merged["sim_token"] == "LAIDS"].copy()
if not lai_df.empty:
    for season in ["25SP", "26SP"]:
        sub_s = lai_df[lai_df["season_id"] == season]
        print(f"\n--- Season {season} Canopy LAI (LAID m2/m2) by Treatment ---")
        print("TRNO | Role  | Obs Max  | Sim Max  | Peak Bias | RMSE   | Mean Bias | NSE")
        print("-------------------------------------------------------------------------")
        for trno in sorted(sub_s["treatment"].unique()):
            sub_t = sub_s[sub_s["treatment"] == trno]
            role = "CALIB" if (season == "25SP" and trno in [2, 5, 10, 13]) or (season == "26SP" and trno in [1, 3, 9, 12]) else "VALID"
            obs_max = sub_t["observed"].max()
            sim_max = sub_t["sim"].max()
            rmse = np.sqrt(sub_t["sq_error"].mean())
            mean_bias = sub_t["error"].mean()
            ss_tot = ((sub_t["observed"] - sub_t["observed"].mean()) ** 2).sum()
            ss_res = sub_t["sq_error"].sum()
            nse = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
            print(f"TN{int(trno):02d} | {role:5s} | {obs_max:8.2f} | {sim_max:8.2f} | {sim_max-obs_max:+9.2f} | {rmse:6.3f} | {mean_bias:+9.3f} | {nse:6.3f}")

print("\n======================================================================")
print(" 3. PER-TREATMENT STEM BIOMASS (SWAD) PERFORMANCE ")
print("======================================================================")
sw_df = merged[merged["sim_token"] == "SWADS"].copy()
if not sw_df.empty:
    for season in ["25SP", "26SP"]:
        sub_s = sw_df[sw_df["season_id"] == season]
        print(f"\n--- Season {season} Stem Biomass (SWAD kg/ha) by Treatment ---")
        print("TRNO | Role  | Obs Max  | Sim Max  | Peak Bias | RMSE (kg/ha) | Mean Bias | NSE")
        print("---------------------------------------------------------------------------------")
        for trno in sorted(sub_s["treatment"].unique()):
            sub_t = sub_s[sub_s["treatment"] == trno]
            role = "CALIB" if (season == "25SP" and trno in [2, 5, 10, 13]) or (season == "26SP" and trno in [1, 3, 9, 12]) else "VALID"
            obs_max = sub_t["observed"].max()
            sim_max = sub_t["sim"].max()
            rmse = np.sqrt(sub_t["sq_error"].mean())
            mean_bias = sub_t["error"].mean()
            ss_tot = ((sub_t["observed"] - sub_t["observed"].mean()) ** 2).sum()
            ss_res = sub_t["sq_error"].sum()
            nse = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
            print(f"TN{int(trno):02d} | {role:5s} | {obs_max:8.1f} | {sim_max:8.1f} | {sim_max-obs_max:+9.1f} | {rmse:12.1f} | {mean_bias:+9.1f} | {nse:6.3f}")
