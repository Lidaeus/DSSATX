"""Explore initial mineral N (SNH4/SNO3) scaling for N0 treatments under fixed member 174 parameters.

Scans initial N multipliers (alpha in [0.2, 0.5, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 2.2, 2.5])
for N0 treatments in 25SP (TN 5, 9, 13) and 26SP (TN 9, 11, 12) while keeping depth profiles
proportional and Member #174 genetic/soil parameters 100% fixed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "workspace/runs/e02_v19_nitrogen_solution_official_200x6_20260820"
DET_DIR = RUN_DIR / "deterministic_candidates/best_phi_member174_two_season_20260820"
PARAM_CSV = DET_DIR / "best_member_174_params.csv"
WORK_DIR = ROOT / "workspace/experiments/explore_n0_mineral_n_20260820"


def run_exploration() -> pd.DataFrame:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    multipliers = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.5]
    
    params_df = pd.read_csv(PARAM_CSV)
    results = []
    
    for alpha in multipliers:
        print(f"--- Testing N0 Mineral N Multiplier alpha = {alpha:.2f} ---", flush=True)
        run_name = f"alpha_{alpha:.2f}".replace(".", "p")
        case_dir = WORK_DIR / run_name
        if case_dir.exists():
            shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(DET_DIR / "design.json", case_dir / "design.json")
        
        cur_params = params_df.copy()
        for idx, row in cur_params.iterrows():
            name = str(row["name"])
            is_n0_25sp = any(f"XXQL2501_TN{tn:02d}" in name for tn in [5, 9, 13])
            is_n0_26sp = any(f"XXQL2601_TN{tn:02d}" in name for tn in [9, 11, 12])
            if (name.startswith("IC_SNH4_") or name.startswith("IC_SNO3_")) and (is_n0_25sp or is_n0_26sp):
                cur_params.at[idx, "value"] = float(row["value"]) * alpha
        
        cur_param_path = case_dir / "params.csv"
        cur_params.to_csv(cur_param_path, index=False)
        
        cmd = [
            sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
            "--design", str(case_dir / "design.json"),
            "--param-csv", str(cur_param_path),
            "--prefix", f"n0_scan_{run_name}",
            "--harvest-var", "CHPDT",
            "--keep-nitrogen-outputs"
        ]
        res = subprocess.run(cmd, cwd=case_dir, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"FAILED for alpha={alpha:.2f}", flush=True)
            continue
        
        for season in ["25SP", "26SP"]:
            s_dir = case_dir / "_seasons" / season
            h_file = s_dir / f"{season}_deterministic_harvest_compare.csv"
            p_file = s_dir / f"{season}_deterministic_process_compare.csv"
            
            n0_tns = [5, 9, 13] if season == "25SP" else [9, 11, 12]
            
            if h_file.exists():
                hdf = pd.read_csv(h_file)
                hdf_n0 = hdf[hdf["treatment"].isin(n0_tns) & (hdf["variable"] == "DRY_CUM")].copy()
                if not hdf_n0.empty:
                    obs = hdf_n0["observed"].values
                    sim = hdf_n0["simulated"].values
                    rmse = np.sqrt(np.mean((sim - obs) ** 2))
                    mae = np.mean(np.abs(sim - obs))
                    bias = np.mean(sim - obs)
                    rrmse = (rmse / np.mean(obs)) * 100.0 if np.mean(obs) != 0 else np.nan
                    results.append({
                        "alpha": alpha, "season": season, "variable": "DRY_CUM",
                        "rmse": rmse, "mae": mae, "bias": bias, "rrmse_pct": rrmse,
                        "mean_obs": np.mean(obs), "mean_sim": np.mean(sim)
                    })
            if p_file.exists():
                pdf = pd.read_csv(p_file)
                for var in ["LAID", "LWAD", "SWAD"]:
                    pdf_n0 = pdf[pdf["treatment"].isin(n0_tns) & (pdf["variable"] == var)].copy()
                    if not pdf_n0.empty:
                        obs = pdf_n0["observed"].values
                        sim = pdf_n0["simulated"].values
                        rmse = np.sqrt(np.mean((sim - obs) ** 2))
                        mae = np.mean(np.abs(sim - obs))
                        bias = np.mean(sim - obs)
                        results.append({
                            "alpha": alpha, "season": season, "variable": var,
                            "rmse": rmse, "mae": mae, "bias": bias, "rrmse_pct": np.nan,
                            "mean_obs": np.mean(obs), "mean_sim": np.mean(sim)
                        })
        
        # Incremental save
        df_res = pd.DataFrame(results)
        df_res.to_csv(WORK_DIR / "n0_exploration_summary.csv", index=False)
        print(f"Saved results for alpha = {alpha:.2f}", flush=True)

    df_res = pd.DataFrame(results)
    out_csv = WORK_DIR / "n0_exploration_summary.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\nExploration completed! Results written to: {out_csv}", flush=True)
    return df_res


if __name__ == "__main__":
    run_exploration()
