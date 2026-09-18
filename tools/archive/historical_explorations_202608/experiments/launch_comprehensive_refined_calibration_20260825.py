"""Comprehensive Refined Calibration and 22-Treatment Full Evaluation Launcher.

Workflow:
1. Builds PST with refined bounds `eggplant_calib_refined_comprehensive_20260825`
2. Runs 6-agent parallel PEST++ IES calibration (80 reals x 5 iters)
3. Extracts best posterior parameter set and runs deterministic simulation on all 22 treatments across 25SP and 26SP
4. Renders full 22-treatment diagnostic plots in figture/eval_22treat_refined_best_20260825/
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
import pandas as pd
import numpy as np
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CASE_NAME = "calib_25sp_refined_full_20260825"
BOUNDS_ID = "eggplant_calib_refined_comprehensive_20260825"
RUN_DIR = ROOT / "workspace/runs" / CASE_NAME
OUT_FIG_DIR = ROOT / "figture/eval_22treat_refined_best_20260825"

N_REALS = 80
NOPTMAX = 5
N_AGENTS = 6
SEED = 20260825

EXP_BUNDLE_25 = ROOT / "data/user/experiments/xxql2501_best_env_10layer_20260825"
EXP_BUNDLE_26 = ROOT / "data/user/experiments/xxql2601_best_env_10layer_20260825"
OFFICIAL_SPE = Path(r"C:\DSSAT48\Genotype\TMGRO048.SPE")
MAPPING_SRC = ROOT / "workspace/runs/e02_arm_d_full_synergy_50x3_20260820/deterministic_best_17/two_season_water_n_mapping_from_filex.csv"

# Import comparison builders
sys.path.insert(0, str(ROOT / "tools/analysis"))
from render_arm_d_best17_diagnostics_20260820 import (
    build_season_harvest_compare,
    build_season_process_compare,
    compute_metrics,
)


def run_pipeline():
    print(f"\n====================================================================")
    print(f"   [Comprehensive Refined Calibration & 22-Treatment Evaluation]")
    print(f"   Case: {CASE_NAME} | Bounds: {BOUNDS_ID}")
    print(f"   Calibration Treatments: 25SP [2, 3, 5, 10, 11, 13] (W3N3, W3N2, W3N0, W1N3, W1N2, W1N0)")
    print(f"   Configuration: {N_REALS} reals x {NOPTMAX} iters x {N_AGENTS} agents")
    print(f"====================================================================\n")

    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR, ignore_errors=True)
    time.sleep(0.5)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Write Multi-Season Design JSON
    design_path = ROOT / "configs/runs" / f"{CASE_NAME}.json"
    design_content = {
        "schema_version": 1,
        "design_id": CASE_NAME,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "Comprehensive Refined Calibration with Expanded Boundaries and Nitrogen Dynamics",
        "bounds_id": BOUNDS_ID,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "diagnostic_single_season": True,
        "initial_condition_policy": "10-layer micro-grid soil with vigorous transplant and cleaned soil N",
        "nitrogen_response_objective": {"enabled": False},
        "water_response_objective": {"enabled": False},
        "harvest_dry_objective": {
            "enabled": True,
            "mode": "increment_plus_terminal",
            "variable": "CHPDT",
            "process_lambda_per_season": 200.0,
            "terminal_lambda_per_season": 300.0
        },
        "process_state_objective": {
            "enabled": True,
            "mode": "signed_difference_plus_terminal",
            "variables": ["LAID", "LWAD", "SWAD"]
        },
        "seasons": [
            {
                "season_id": "25SP",
                "experiment_code": "XXQL2501",
                "bundle_path": str(EXP_BUNDLE_25),
                "role": "calibration",
                "treatments": [2, 3, 4, 10, 11, 12]
            }
        ],
        "pest_ies": {
            "num_reals": N_REALS,
            "noptmax": NOPTMAX,
            "par_sigma_range": 4.0,
            "lambda_mults": [0.1, 1.0, 10.0],
            "subreg": True,
            "subreg_how": "par_sigma_range"
        }
    }
    with open(design_path, "w", encoding="utf-8") as f:
        json.dump(design_content, f, indent=2)

    # 2. Build PST via build_pest.py
    print(f"[1/5] Building PST via build_pest.py...")
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = str(OFFICIAL_SPE.resolve())
    policy_path = ROOT / "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv"

    cmd_build = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(design_path),
        "--input-dir", str(EXP_BUNDLE_25),
        "--bounds-id", BOUNDS_ID,
        "--bounds-crop", "eggplant",
        "--prefix", CASE_NAME,
        "--noptmax", str(NOPTMAX),
        "--ies-num-reals", str(N_REALS),
        "--random-seed", str(SEED),
        "--bad-phi-sigma", "1e300",
        "--batch", "DSSBatch.v48",
        "--harvest-var", "CHPDT",
        "--include-soil",
        "--out-dir", str(RUN_DIR),
        "--param-review-mode", "off",
        "--bounds-review-mode", "off",
        "--observation-policy-csv", str(policy_path),
        "--initial-ensemble-method", "sobol",
        "--no-include-n-uptake",
    ]
    subprocess.run(cmd_build, cwd=str(ROOT), env=env, check=True)

    pst_file = RUN_DIR / f"{CASE_NAME}.pst"
    pst = pyemu.Pst(str(pst_file))
    n_adj = (pst.parameter_data["partrans"] == "none").sum()
    n_obs = len(pst.observation_data)
    nnz_obs = (pst.observation_data["weight"] > 0).sum()
    print(f"  PST verification: Total Params={len(pst.parameter_data)}, Active={n_adj}, Total Obs={n_obs}, Weighted Obs={nnz_obs}")

    # 3. Launch Parallel PEST++ IES
    print(f"\n[2/5] Launching {N_AGENTS}-Agent Parallel PEST++ IES...")
    cmd_parallel = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(RUN_DIR),
        "--case", CASE_NAME,
        "--mode", "ies",
        "--n-agents", str(N_AGENTS),
        "--wait"
    ]
    subprocess.run(cmd_parallel, cwd=str(ROOT), check=True)
    print(f"\n[3/5] Calibration Execution Finished!")

    # 4. Extract best parameters
    par_file = RUN_DIR / f"{CASE_NAME}.{NOPTMAX}.par.csv"
    phi_file = RUN_DIR / f"{CASE_NAME}.phi.actual.csv"
    df_phi = pd.read_csv(phi_file)
    print("\nPhi Summary:")
    print(df_phi[["iteration", "total_runs", "mean", "min", "max"]])

    last_row = df_phi.iloc[-1]
    members = [c for c in df_phi.columns if c not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]]
    best_mem = None
    min_phi = float("inf")
    for m in members:
        val = float(last_row[m])
        if val < min_phi:
            min_phi = val
            best_mem = m
    print(f"\nOptimal Posterior Individual: #{best_mem} with Phi = {min_phi:.2f}")

    df_par = pd.read_csv(par_file)
    real_col = df_par.columns[0]
    row_p = df_par.loc[df_par[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(str(best_mem))]

    det_dir = RUN_DIR / "deterministic_best_base"
    det_dir.mkdir(parents=True, exist_ok=True)
    params = []
    for col in df_par.columns[1:]:
        params.append({"name": str(col).lower(), "value": float(row_p.iloc[0][col])})
    param_csv = det_dir / "best_params.csv"
    pd.DataFrame(params).to_csv(param_csv, index=False)
    print(f"Saved best parameters to: {param_csv}")

    # 5. Replay simulation on all 22 treatments (25SP 10 + 26SP 12)
    print(f"\n[4/5] Running Deterministic Simulation on all 22 Treatments...")
    eval_design_path = det_dir / "joint_22treat_design.json"
    eval_design_dict = {
        "schema_version": 1,
        "design_id": "eval_22treat_refined",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "Full 22 Treatments Evaluation with Refined Best Parameters",
        "bounds_id": BOUNDS_ID,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "diagnostic_single_season": False,
        "harvest_dry_objective": {"enabled": True, "mode": "increment_plus_terminal", "variable": "CHPDT"},
        "process_state_objective": {"enabled": True, "mode": "signed_difference_plus_terminal", "variables": ["LAID", "LWAD", "SWAD"]},
        "seasons": [
            {
                "season_id": "25SP",
                "experiment_code": "XXQL2501",
                "bundle_path": str(EXP_BUNDLE_25),
                "role": "calibration",
                "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]
            },
            {
                "season_id": "26SP",
                "experiment_code": "XXQL2601",
                "bundle_path": str(EXP_BUNDLE_26),
                "role": "calibration",
                "treatments": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
            }
        ]
    }
    with open(eval_design_path, "w", encoding="utf-8") as f:
        json.dump(eval_design_dict, f, indent=2)

    cmd_eval = [
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(eval_design_path),
        "--param-csv", str(param_csv),
        "--prefix", "eval_det",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    subprocess.run(cmd_eval, cwd=str(det_dir), env=env, check=True)

    # Compute metrics
    metrics_rows = []
    for season in ["25SP", "26SP"]:
        sdir = det_dir / "_seasons" / season
        h_compare = build_season_harvest_compare(sdir, season)
        h_compare.to_csv(sdir / "compare_harvest.csv", index=False)
        for vcol in ["DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM"]:
            obs_c = f"OBS_{vcol}"
            sim_c = f"SIM_{vcol}"
            if obs_c in h_compare.columns and sim_c in h_compare.columns:
                m = compute_metrics(h_compare[obs_c].to_numpy(float), h_compare[sim_c].to_numpy(float))
                m.update({"season": season, "kind": "harvest", "variable": vcol, "n": len(h_compare)})
                metrics_rows.append(m)

        p_compare = build_season_process_compare(sdir, season)
        p_compare.to_csv(sdir / "compare_process.csv", index=False)
        for var in ["LAID", "LWAD", "SWAD", "CHTD"]:
            obs_c = f"OBS_{var}"
            sim_c = f"SIM_{var}"
            if obs_c in p_compare.columns and sim_c in p_compare.columns:
                m = compute_metrics(p_compare[obs_c].to_numpy(float), p_compare[sim_c].to_numpy(float))
                m.update({"season": season, "kind": "process", "variable": var, "n": len(p_compare)})
                metrics_rows.append(m)

    metrics_df = pd.DataFrame(metrics_rows)
    metrics_path = det_dir / "metrics_by_season_variable.csv"
    metrics_df.to_csv(metrics_path, index=False)
    print("\n=== Refined 22-Treatment Metrics Summary ===")
    print(metrics_df[["season", "kind", "variable", "n", "rmse", "rrmse_pct", "nse", "d_index", "r2"]].to_string(index=False))

    # 6. Render full 22-treatment diagnostic plots
    print(f"\n[5/5] Rendering Full 22-Treatment Diagnostic Plots to {OUT_FIG_DIR}...")
    if MAPPING_SRC.exists():
        shutil.copy2(MAPPING_SRC, det_dir / "two_season_water_n_mapping_from_filex.csv")
    OUT_FIG_DIR.mkdir(parents=True, exist_ok=True)
    reg_csv = RUN_DIR / f"{CASE_NAME}_observation_registry.csv"

    cmd_plot = [
        sys.executable, str(ROOT / "tools/calibration/plot_dynamics.py"),
        "--det-root", str(det_dir),
        "--out-root", str(OUT_FIG_DIR),
        "--seasons", "25SP,26SP",
        "--include-all-treatments",
        "--mapping-csv", str(det_dir / "two_season_water_n_mapping_from_filex.csv")
    ]
    if reg_csv.exists():
        cmd_plot.extend(["--registry-csv", str(reg_csv)])

    subprocess.run(cmd_plot, cwd=str(ROOT), check=True)
    print(f"\nAll 22 treatments diagnostic plots successfully generated in: {OUT_FIG_DIR}!")


if __name__ == "__main__":
    run_pipeline()
