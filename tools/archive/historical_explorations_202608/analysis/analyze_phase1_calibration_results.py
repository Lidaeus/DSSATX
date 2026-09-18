"""Post-process and Analyze Phase 1 25SP 6-Treatment Calibration Results:
1. Extract minimum-Phi ensemble member from PEST++ IES posterior.
2. Run deterministic simulation on the 6 treatments in 25SP.
3. Compute metrics (RMSE, NSE, R2, d-index) for DRY_CUM, FRESH_CUM, LAID, LWAD, SWAD.
4. Audit parameter hits/proximity to lower and upper bounds for Phase 2 bounds adjustment.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def analyze_run(case_name: str, run_dir: Path, design_json: Path):
    print(f"\n====================================================================")
    print(f"   Analyzing Calibration Results for {case_name}")
    print(f"   Directory: {run_dir}")
    print(f"====================================================================\n")

    phi_file = run_dir / f"{case_name}.phi.actual.csv"
    if not phi_file.exists():
        print(f"Error: {phi_file} not found!")
        return None

    df_phi = pd.read_csv(phi_file)
    print(f"Phi Actual Summary (total {len(df_phi)} iterations/entries):")
    print(df_phi.tail(5).to_string())

    # Find best iteration and realization
    # Find all par.csv files in run_dir
    par_files = sorted(list(run_dir.glob(f"{case_name}.*.par.csv")), key=lambda p: int(p.stem.split(".")[1]) if p.stem.split(".")[1].isdigit() else -1)
    if not par_files:
        print("Error: No par.csv files found!")
        return None

    last_par_file = par_files[-1]
    last_iter = int(last_par_file.stem.split(".")[1])
    print(f"Reading final parameter ensemble from iteration {last_iter}: {last_par_file.name}")
    df_par = pd.read_csv(last_par_file, index_col=0)

    # Find best member from obs file or phi file
    obs_files = sorted(list(run_dir.glob(f"{case_name}.*.obs.csv")), key=lambda p: int(p.stem.split(".")[1]) if p.stem.split(".")[1].isdigit() else -1)
    
    # Read PST to get bounds and weights
    pst_file = run_dir / f"{case_name}.pst"
    pst = pyemu.Pst(str(pst_file))
    
    # Identify best member (minimum phi in final iteration)
    # We can evaluate phi for each realization in df_par
    best_real = df_par.index[0]
    # Check if 'base' is in index
    if "base" in df_par.index:
        best_real = "base"
    
    # If .phi.group.csv or realization phi exists
    phi_group_file = run_dir / f"{case_name}.{last_iter}.phi.group.csv"
    if phi_group_file.exists():
        df_pg = pd.read_csv(phi_group_file, index_col=0)
        if "total" in df_pg.columns:
            best_real = df_pg["total"].idxmin()
            print(f"Best member by final group total Phi: {best_real} (Phi = {df_pg.loc[best_real, 'total']:.2f})")
    else:
        # Check phi actual
        min_phi_val = df_phi["mean"].min()
        print(f"Best iteration mean Phi: {min_phi_val:.2f}")

    best_params_series = df_par.loc[best_real]
    out_best_dir = run_dir / f"deterministic_best_{best_real}"
    if out_best_dir.exists():
        shutil.rmtree(out_best_dir)
    out_best_dir.mkdir(parents=True, exist_ok=True)

    # Save best parameters CSV
    best_param_rows = []
    for pname in pst.parameter_data.index:
        key = str(pname).lower()
        val = float(best_params_series[pname]) if pname in best_params_series.index else float(pst.parameter_data.at[pname, "parval1"])
        lb = float(pst.parameter_data.at[pname, "parlbnd"])
        ub = float(pst.parameter_data.at[pname, "parubnd"])
        status = pst.parameter_data.at[pname, "partrans"]
        pargp = pst.parameter_data.at[pname, "pargp"]
        best_param_rows.append({
            "name": pname, "value": val, "lower": lb, "upper": ub,
            "status": "active" if status == "none" else "fixed", "pargp": pargp
        })
    df_best_params = pd.DataFrame(best_param_rows)
    best_params_csv = out_best_dir / "best_params.csv"
    df_best_params.to_csv(best_params_csv, index=False)
    print(f"Saved best parameters to: {best_params_csv}")

    # 2. Run Deterministic DSSAT Simulation
    print("\nRunning deterministic simulation with best parameters...")
    det_season_dir = out_best_dir / "_seasons" / "25SP"
    det_season_dir.mkdir(parents=True, exist_ok=True)

    cmd_det = [
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_json),
        "--param-csv", str(best_params_csv),
        "--harvest-var", "CHPDT",
        "--prefix", case_name,
        "--observation-transform-config", str(run_dir / f"{case_name}.observation_transforms.json")
    ]
    subprocess.run(cmd_det, cwd=str(out_best_dir), check=True)
    print("Deterministic simulation completed successfully!")

    # 3. Compute Metrics for the 6 Treatments
    sys.path.insert(0, str(ROOT / "tools/analysis"))
    from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare, build_season_process_compare, compute_metrics

    h_comp = build_season_harvest_compare(det_season_dir, "25SP")
    p_comp = build_season_process_compare(det_season_dir, "25SP")

    metrics_rows = []
    # Harvest Dry Yield (CHPDT)
    if not h_comp.empty and "OBS_DRY_CUM" in h_comp.columns:
        valid_h = h_comp.dropna(subset=["OBS_DRY_CUM", "SIM_DRY_CUM"])
        m_dry = compute_metrics(valid_h["OBS_DRY_CUM"].to_numpy(), valid_h["SIM_DRY_CUM"].to_numpy())
        metrics_rows.append({"Variable": "DRY_CUM (kg/ha)", "n": len(valid_h), **m_dry})

    # Harvest Fresh Yield (CHFPW)
    if not h_comp.empty and "OBS_FRESH_CUM" in h_comp.columns:
        valid_hf = h_comp.dropna(subset=["OBS_FRESH_CUM", "SIM_FRESH_CUM"])
        m_fresh = compute_metrics(valid_hf["OBS_FRESH_CUM"].to_numpy(), valid_hf["SIM_FRESH_CUM"].to_numpy())
        metrics_rows.append({"Variable": "FRESH_CUM (kg/ha)", "n": len(valid_hf), **m_fresh})

    # Process variables: LAID, LWAD, SWAD
    for var in ["LAID", "LWAD", "SWAD"]:
        if not p_comp.empty and f"OBS_{var}" in p_comp.columns and f"SIM_{var}" in p_comp.columns:
            sub_p = p_comp.dropna(subset=[f"OBS_{var}", f"SIM_{var}"])
            sub_p = sub_p[sub_p[f"OBS_{var}"] > 0]
            if len(sub_p) > 2:
                m_v = compute_metrics(sub_p[f"OBS_{var}"].to_numpy(), sub_p[f"SIM_{var}"].to_numpy())
                metrics_rows.append({"Variable": var, "n": len(sub_p), **m_v})

    df_metrics = pd.DataFrame(metrics_rows)
    metrics_csv = out_best_dir / "deterministic_metrics_summary.csv"
    df_metrics.to_csv(metrics_csv, index=False)
    print(f"\nDeterministic Metrics Summary for 25SP (6 treatments):")
    print(df_metrics.to_string(index=False))

    # 4. Parameter Bound Hits Audit
    bound_audit_rows = []
    for idx, r in df_best_params[df_best_params["status"] == "active"].iterrows():
        pname = r["name"]
        val = float(r["value"])
        lb = float(r["lower"])
        ub = float(r["upper"])
        rng = ub - lb
        if rng > 1e-9:
            ratio = (val - lb) / rng
            if ratio <= 0.03:
                tag = "HIT_LOWER"
            elif ratio >= 0.97:
                tag = "HIT_UPPER"
            elif ratio <= 0.08:
                tag = "NEAR_LOWER"
            elif ratio >= 0.92:
                tag = "NEAR_UPPER"
            else:
                tag = "INTERIOR"
            bound_audit_rows.append({
                "Parameter": pname, "Value": val, "Lower": lb, "Upper": ub,
                "Position_Pct": ratio * 100.0, "Tag": tag, "pargp": r["pargp"]
            })
    df_bound_audit = pd.DataFrame(bound_audit_rows).sort_values("Position_Pct")
    audit_csv = out_best_dir / "parameter_bound_hits_audit.csv"
    df_bound_audit.to_csv(audit_csv, index=False)

    print(f"\nParameter Bound Hits Audit Summary:")
    hit_counts = df_bound_audit["Tag"].value_counts()
    print(hit_counts.to_string())
    print("\nParameters Hitting or Near Lower/Upper Bounds:")
    hits_df = df_bound_audit[df_bound_audit["Tag"] != "INTERIOR"]
    print(hits_df.to_string(index=False))

    return {
        "best_real": best_real,
        "metrics": df_metrics,
        "bound_audit": df_bound_audit,
        "best_params_csv": best_params_csv,
        "out_dir": out_best_dir
    }


if __name__ == "__main__":
    analyze_run(
        "calib_25sp_6treat_phase1_20260825",
        ROOT / "workspace/runs/calib_25sp_6treat_phase1_20260825",
        ROOT / "configs/runs/calib_25sp_6treat_phase1_20260825.json"
    )
