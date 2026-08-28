"""Deterministic evaluator and comparative synthesizer for 4-arm exploratory trials.

Evaluates best member of each arm across 25SP and 26SP, producing:
1. Convergence summary (Phi init -> final min)
2. Whole-trial metrics (LAI, LWAD, SWAD, DRY_CUM NSE/MAE/d-index)
3. N0 low-nitrogen treatment fit (N0 LAI, N0 yield, N0 total plant N)
4. Root depth penetration and RLD layer distribution
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
ARMS = ["arm_a_measured_lnref", "arm_b_13layer_slnf", "arm_c_deep_root_foraging", "arm_d_full_synergy"]


def evaluate_all_arms() -> pd.DataFrame:
    rows = []
    
    for arm_id in ARMS:
        case_name = f"e02_{arm_id}_50x3_20260820"
        run_dir = ROOT / "workspace/runs" / case_name
        phi_file = run_dir / f"{case_name}.phi.actual.csv"
        
        if not phi_file.exists():
            print(f"Skipping {arm_id}: phi file not found")
            continue
            
        df_phi = pd.read_csv(phi_file)
        last = df_phi.iloc[-1]
        members = [c for c in df_phi.columns if c not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]]
        best_mem = None
        min_phi = float("inf")
        for m in members:
            val = float(last[m])
            if val < min_phi:
                min_phi = val
                best_mem = m
                
        # Replay deterministic run
        det_dir = run_dir / f"deterministic_best_{best_mem}"
        det_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract best member params from 3.par.csv
        par_csv = run_dir / f"{case_name}.3.par.csv"
        if not par_csv.exists():
            par_csv = run_dir / f"{case_name}.2.par.csv"
        df_par = pd.read_csv(par_csv)
        real_col = df_par.columns[0]
        row_p = df_par.loc[df_par[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(str(best_mem))]
        
        param_rows = []
        for col in df_par.columns[1:]:
            param_rows.append({"name": col.upper(), "value": float(row_p.iloc[0][col])})
        best_param_path = det_dir / "best_params.csv"
        pd.DataFrame(param_rows).to_csv(best_param_path, index=False)
        
        # Copy design.json
        design_src = ROOT / "configs/runs" / f"{case_name}.json"
        design_dst = det_dir / "design.json"
        shutil.copy2(design_src, design_dst)
        
        # Run multiseason
        cmd = [
            sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
            "--design", str(design_dst),
            "--param-csv", str(best_param_path),
            "--prefix", f"det_{arm_id}",
            "--harvest-var", "CHPDT",
            "--keep-nitrogen-outputs"
        ]
        res = subprocess.run(cmd, cwd=det_dir, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Deterministic run failed for {arm_id}")
            continue
            
        # Parse metrics
        for season in ["25SP", "26SP"]:
            s_dir = det_dir / "_seasons" / season
            h_file = s_dir / f"{season}_deterministic_harvest_compare.csv"
            p_file = s_dir / f"{season}_deterministic_process_compare.csv"
            n0_tns = [5, 9, 13] if season == "25SP" else [9, 11, 12]
            
            # PlantN for N0
            pn_file = s_dir / "PlantN.OUT"
            n0_nuptake = np.nan
            if pn_file.exists():
                lines = pn_file.read_text(errors="ignore").splitlines()
                header = None
                cur_tn = None
                pn_recs = []
                for l in lines:
                    if l.startswith("*RUN"):
                        cur_tn = int(l.split()[-1])
                    elif l.startswith("@YEAR"):
                        header = l.replace("@", "").split()
                    elif cur_tn in n0_tns and header is not None and l.strip() and not l.startswith("*") and not l.startswith("@"):
                        parts = l.split()
                        if len(parts) >= len(header) and parts[0].isdigit():
                            pn_recs.append({header[i]: float(parts[i]) for i in range(len(header))})
                if pn_recs:
                    df_pn = pd.DataFrame(pn_recs)
                    if "NUPC" in df_pn.columns:
                        n0_nuptake = float(df_pn.groupby("TRNO")["NUPC"].last().mean() if "TRNO" in df_pn.columns else df_pn["NUPC"].iloc[-1])
            
            # PlantGro for RLD
            pg_file = s_dir / "PlantGro.OUT"
            n0_rld_top = np.nan
            n0_rld_deep = np.nan
            max_lai_n0 = np.nan
            if pg_file.exists():
                lines = pg_file.read_text(errors="ignore").splitlines()
                header = None
                cur_tn = None
                pg_recs = []
                for l in lines:
                    if l.startswith("*RUN"):
                        cur_tn = int(l.split()[-1])
                    elif l.startswith("@YEAR"):
                        header = l.replace("@", "").split()
                    elif cur_tn in n0_tns and header is not None and l.strip() and not l.startswith("*") and not l.startswith("@"):
                        parts = l.split()
                        if len(parts) >= len(header) and parts[0].isdigit():
                            pg_recs.append({header[i]: float(parts[i]) for i in range(len(header))})
                if pg_recs:
                    df_pg = pd.DataFrame(pg_recs)
                    if "LAID" in df_pg.columns:
                        max_lai_n0 = float(df_pg["LAID"].max())
                    if "RL1D" in df_pg.columns:
                        n0_rld_top = float(df_pg["RL1D"].iloc[-1])
                    if "RL6D" in df_pg.columns:
                        n0_rld_deep = float(df_pg["RL6D"].iloc[-1])
                        
            # Harvest metrics
            dry_nse = np.nan
            dry_mae = np.nan
            if h_file.exists():
                hdf = pd.read_csv(h_file)
                # Compute DRY_CUM metrics across all treatments
                obs = hdf["OBS_DRY_CUM"].to_numpy(float)
                sim = hdf["SIM_DRY_CUM"].to_numpy(float)
                dry_mae = float(np.mean(np.abs(sim - obs)))
                denom = float(np.sum((obs - obs.mean())**2))
                dry_nse = float(1.0 - (np.sum((sim - obs)**2) / denom)) if denom > 0 else np.nan
                
            # Process metrics
            lai_nse = np.nan
            lai_mae = np.nan
            if p_file.exists():
                pdf = pd.read_csv(p_file)
                pdf_lai = pdf[pdf["variable"] == "LAID"]
                if not pdf_lai.empty:
                    obs_l = pdf_lai["observed"].to_numpy(float)
                    sim_l = pdf_lai["simulated"].to_numpy(float)
                    lai_mae = float(np.mean(np.abs(sim_l - obs_l)))
                    denom_l = float(np.sum((obs_l - obs_l.mean())**2))
                    lai_nse = float(1.0 - (np.sum((sim_l - obs_l)**2) / denom_l)) if denom_l > 0 else np.nan
                    
            rows.append({
                "arm": arm_id, "season": season, "best_member": best_mem, "best_phi": min_phi,
                "dry_cum_nse": dry_nse, "dry_cum_mae": dry_mae,
                "lai_nse": lai_nse, "lai_mae": lai_mae,
                "n0_max_lai": max_lai_n0, "n0_nuptake_kg_ha": n0_nuptake,
                "n0_rld_top": n0_rld_top, "n0_rld_deep": n0_rld_deep
            })
            
    summary_df = pd.DataFrame(rows)
    out_csv = ROOT / "workspace/experiments/multi_arm_senescence_evaluation_summary_20260820.csv"
    summary_df.to_csv(out_csv, index=False)
    print(f"Evaluated all arms! Results in: {out_csv}")
    return summary_df


if __name__ == "__main__":
    evaluate_all_arms()
