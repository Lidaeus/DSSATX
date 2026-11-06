"""Evaluate v23 4-Arm Trials and Extract Root Dynamics, Soil Leaching, N Uptake, and Yields."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/analysis"))
from render_arm_d_best17_diagnostics_20260820 import (
    build_season_harvest_compare,
    build_season_process_compare,
    compute_metrics,
)

ARMS = [
    ("ArmA", "hydraulic_retention", "e02_v23_arm_arma_hydraulic_retention_40x3_20260821"),
    ("ArmB", "deep_interception_foraging", "e02_v23_arm_armb_deep_interception_foraging_40x3_20260821"),
    ("ArmC", "greenhouse_mineralization_boost", "e02_v23_arm_armc_greenhouse_mineralization_boost_40x3_20260821"),
    ("ArmD", "full_eco_hydraulic_synergy", "e02_v23_arm_armd_full_eco_hydraulic_synergy_40x3_20260821"),
]


def evaluate_arm(arm_id: str, arm_name: str, case_name: str) -> dict:
    run_dir = ROOT / "workspace/runs" / case_name
    phi_csv = run_dir / f"{case_name}.phi.actual.csv"
    par_csv = run_dir / f"{case_name}.3.par.csv"
    design_path = run_dir / "joint_design.json"
    
    if not phi_csv.exists() or not par_csv.exists():
        print(f"[{arm_id}] Incomplete run files in {run_dir}")
        return {"arm_id": arm_id, "status": "incomplete"}
        
    df_phi = pd.read_csv(phi_csv)
    last_row = df_phi.iloc[-1]
    members = [c for c in df_phi.columns if c not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]]
    
    best_mem = None
    min_phi = float("inf")
    for m in members:
        val = float(last_row[m])
        if val < min_phi:
            min_phi = val
            best_mem = m
            
    print(f"\n>>> [{arm_id}: {arm_name}] Lowest Phi Member: #{best_mem} (Phi = {min_phi:.2f}) <<<")
    
    det_dir = run_dir / f"deterministic_best_{best_mem}"
    det_dir.mkdir(parents=True, exist_ok=True)
    
    # Extract params
    df_par = pd.read_csv(par_csv)
    real_col = df_par.columns[0]
    row_p = df_par.loc[df_par[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(str(best_mem))]
    
    params = []
    for col in df_par.columns[1:]:
        params.append({"name": str(col).lower(), "value": float(row_p.iloc[0][col])})
    param_path = det_dir / f"best_member_{best_mem}_params.csv"
    pd.DataFrame(params).to_csv(param_path, index=False)
    
    # Run deterministic replay
    cmd_run = [
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_path),
        "--param-csv", str(param_path),
        "--prefix", f"best{best_mem}_det",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    subprocess.run(cmd_run, cwd=det_dir, env=env, check=True)
    
    # Extract root & yield metrics
    metrics_summary = {"arm_id": arm_id, "arm_name": arm_name, "best_mem": best_mem, "min_phi": min_phi}
    
    for season in ["25SP", "26SP"]:
        sdir = det_dir / "_seasons" / season
        pg_file = sdir / "PlantGro.OUT"
        pn_file = sdir / "PlantN.OUT"
        sni_file = sdir / "SoilNi.OUT"
        
        n3_tn = 2
        n0_tn = 5 if season == "25SP" else 11
        
        # Parse PlantGro
        pg_lines = pg_file.read_text(errors="ignore").splitlines()
        header, cur_tn, recs = None, None, []
        for l in pg_lines:
            if l.startswith("*RUN"):
                m = re.search(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", l)
                if m: cur_tn = int(m.group(2))
            elif l.startswith("@YEAR"):
                header = l.replace("@", "").split()
            elif cur_tn in [n3_tn, n0_tn] and header and l.strip() and not l.startswith("*") and not l.startswith("@"):
                parts = l.split()
                if len(parts) >= len(header) and parts[0].isdigit():
                    r = {header[i]: float(parts[i]) for i in range(len(header))}
                    r["TN"] = cur_tn
                    recs.append(r)
        df_pg = pd.DataFrame(recs)
        
        # Parse PlantN
        pn_lines = pn_file.read_text(errors="ignore").splitlines()
        header_n, cur_tn, recs_n = None, None, []
        for l in pn_lines:
            if l.startswith("*RUN"):
                m = re.search(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", l)
                if m: cur_tn = int(m.group(2))
            elif l.startswith("@YEAR"):
                header_n = l.replace("@", "").split()
            elif cur_tn in [n3_tn, n0_tn] and header_n and l.strip() and not l.startswith("*") and not l.startswith("@"):
                parts = l.split()
                if len(parts) >= len(header_n) and parts[0].isdigit():
                    r = {header_n[i]: float(parts[i]) for i in range(len(header_n))}
                    r["TN"] = cur_tn
                    recs_n.append(r)
        df_pn = pd.DataFrame(recs_n)
        
        # Harvest yield compare
        h_compare = build_season_harvest_compare(sdir, season)
        for tn, tname in [(n3_tn, "N3"), (n0_tn, "N0")]:
            sub_pg = df_pg[df_pg["TN"] == tn]
            sub_pn = df_pn[df_pn["TN"] == tn]
            sub_h = h_compare[h_compare["TN"] == tn]
            
            last_pg = sub_pg.iloc[-1] if not sub_pg.empty else {}
            last_pn = sub_pn.iloc[-1] if not sub_pn.empty else {}
            last_h = sub_h.iloc[-1] if not sub_h.empty else {}
            
            metrics_summary[f"{season}_{tname}_yield_dry"] = last_h.get("SIM_DRY_CUM", np.nan)
            metrics_summary[f"{season}_{tname}_root_wt"] = last_pg.get("RWAD", np.nan)
            metrics_summary[f"{season}_{tname}_root_depth"] = last_pg.get("RDPD", np.nan)
            metrics_summary[f"{season}_{tname}_rld_top"] = last_pg.get("RL1D", np.nan)
            metrics_summary[f"{season}_{tname}_rld_deep"] = last_pg.get("RL5D", np.nan)
            metrics_summary[f"{season}_{tname}_n_uptake"] = last_pn.get("NUPC", np.nan)
            metrics_summary[f"{season}_{tname}_leaf_n"] = last_pn.get("LN%D", np.nan)
            
    return metrics_summary


def main():
    results = []
    for aid, aname, cname in ARMS:
        res = evaluate_arm(aid, aname, cname)
        results.append(res)
        
    df_res = pd.DataFrame(results)
    out_csv = ROOT / "workspace/runs/e02_v23_4arm_comparison_20260821.csv"
    df_res.to_csv(out_csv, index=False)
    
    print("\n==========================================================================================")
    print("                 v23 4-Arm Exploration Comprehensive Comparison")
    print("==========================================================================================")
    cols_show = [
        "arm_id", "min_phi",
        "25SP_N3_yield_dry", "25SP_N0_yield_dry", "25SP_N0_root_wt", "25SP_N0_rld_deep", "25SP_N0_n_uptake",
        "26SP_N3_yield_dry", "26SP_N0_yield_dry", "26SP_N0_root_wt", "26SP_N0_rld_deep", "26SP_N0_n_uptake",
    ]
    cols_present = [c for c in cols_show if c in df_res.columns]
    print(df_res[cols_present].to_string(index=False))


if __name__ == "__main__":
    main()
