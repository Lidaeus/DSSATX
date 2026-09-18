"""Evaluate Clean Multi-Arm Exploratory Trials: Root Development, N Uptake, and Yields."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ARM_PREFIXES = [
    ("Arm A", "e02_clean_arm_a_High_LNREF_Measured_50x3_20260821"),
    ("Arm B", "e02_clean_arm_b_High_SLNF_13Layer_50x3_20260821"),
    ("Arm C", "e02_clean_arm_c_Enhanced_Early_Root_Foraging_50x3_20260821"),
    ("Arm D", "e02_clean_arm_d_Full_Synergy_Enhanced_Roots_50x3_20260821"),
]

sys.path.insert(0, str(ROOT / "tools/analysis"))
from render_arm_d_best17_diagnostics_20260820 import (
    build_season_harvest_compare,
    build_season_process_compare,
    compute_metrics,
)


def evaluate_arms():
    results = []
    
    for arm_label, case_name in ARM_PREFIXES:
        run_dir = ROOT / "workspace/runs" / case_name
        phi_file = run_dir / f"{case_name}.phi.actual.csv"
        par_files = sorted(run_dir.glob(f"{case_name}.*.par.csv"))
        
        if not phi_file.exists() or not par_files:
            print(f"Skipping {arm_label} ({case_name}): files not found")
            continue
            
        par_file = par_files[-1]
            
        phi_df = pd.read_csv(phi_file)
        last_row = phi_df.iloc[-1]
        members = [c for c in phi_df.columns if c not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]]
        best_mem = None
        min_phi = float("inf")
        for m in members:
            val = float(last_row[m])
            if val < min_phi:
                min_phi = val
                best_mem = m
                
        det_dir = run_dir / f"deterministic_best_{best_mem}"
        det_dir.mkdir(parents=True, exist_ok=True)
        
        par_df = pd.read_csv(par_file)
        real_col = par_df.columns[0]
        row_p = par_df.loc[par_df[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(str(best_mem))]
        
        params = []
        for col in par_df.columns[1:]:
            cl = str(col).lower()
            if not cl.startswith("ic_"):
                params.append({"name": cl, "value": float(row_p.iloc[0][col])})
        param_csv = det_dir / "best_params.csv"
        pd.DataFrame(params).to_csv(param_csv, index=False)
        
        # Replay
        design_path = run_dir / "joint_design.json"
        cmd_run = [
            sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
            "--design", str(design_path),
            "--param-csv", str(param_csv),
            "--prefix", f"det_best_{best_mem}",
            "--harvest-var", "CHPDT",
            "--keep-nitrogen-outputs",
        ]
        env = os.environ.copy()
        env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
        subprocess.run(cmd_run, cwd=det_dir, env=env, check=True)
        
        # Parse comparison
        h25 = build_season_harvest_compare(det_dir / "_seasons/25SP", "25SP")
        h26 = build_season_harvest_compare(det_dir / "_seasons/26SP", "26SP")
        
        # 25SP N0 (TN 5) & N3 (TN 2)
        n0_25_dry = h25[h25["TN"] == 5]["SIM_DRY_CUM"].iloc[-1] if 5 in h25["TN"].values else np.nan
        n3_25_dry = h25[h25["TN"] == 2]["SIM_DRY_CUM"].iloc[-1] if 2 in h25["TN"].values else np.nan
        n0_26_dry = h26[h26["TN"] == 11]["SIM_DRY_CUM"].iloc[-1] if 11 in h26["TN"].values else np.nan
        n3_26_dry = h26[h26["TN"] == 2]["SIM_DRY_CUM"].iloc[-1] if 2 in h26["TN"].values else np.nan
        
        # Extract root metrics from PlantGro.OUT
        pg25 = (det_dir / "_seasons/25SP/PlantGro.OUT").read_text(errors="ignore").splitlines()
        cur_tn = None
        n0_rdpd = np.nan
        n0_rlad = np.nan
        n0_rl_top = np.nan
        n0_rl_deep = np.nan
        for l in pg25:
            if l.startswith("*RUN"):
                m = re.search(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", l)
                if m:
                    cur_tn = int(m.group(2))
            elif cur_tn == 5 and l.strip() and not l.startswith("@") and not l.startswith("*"):
                parts = l.split()
                if len(parts) >= 45 and parts[0].isdigit():
                    n0_rdpd = float(parts[34])  # RDPD
                    n0_rlad = float(parts[35])  # RLAD
                    n0_rl_top = float(parts[36])  # RL1D
                    n0_rl_deep = float(parts[40]) # RL5D
                    
        # Extract N uptake from PlantN.OUT
        pn25 = (det_dir / "_seasons/25SP/PlantN.OUT").read_text(errors="ignore").splitlines()
        cur_tn = None
        n0_nupc = np.nan
        for l in pn25:
            if l.startswith("*RUN"):
                m = re.search(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", l)
                if m:
                    cur_tn = int(m.group(2))
            elif cur_tn == 5 and l.strip() and not l.startswith("@") and not l.startswith("*"):
                parts = l.split()
                if len(parts) >= 8 and parts[0].isdigit():
                    n0_nupc = float(parts[6])  # NUPC
                    
        results.append({
            "Arm": arm_label,
            "Best_Member": best_mem,
            "Min_Phi": min_phi,
            "25SP_N3_Dry": n3_25_dry,
            "25SP_N0_Dry": n0_25_dry,
            "26SP_N3_Dry": n3_26_dry,
            "26SP_N0_Dry": n0_26_dry,
            "N0_N_Uptake_kg_ha": n0_nupc,
            "N0_Root_Depth_m": n0_rdpd,
            "N0_Top_RLD_cm3": n0_rl_top,
            "N0_Deep_RLD_cm3": n0_rl_deep,
        })
        
    res_df = pd.DataFrame(results)
    out_csv = ROOT / "workspace/experiments/clean_multi_arm_evaluation_summary_20260821.csv"
    res_df.to_csv(out_csv, index=False)
    print("\n=======================================================")
    print("   Clean Multi-Arm Evaluation Summary (Pure Measured IC)")
    print("=======================================================")
    print(res_df.to_string(index=False))


if __name__ == "__main__":
    evaluate_arms()
