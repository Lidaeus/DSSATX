"""Analyze v29 Focused Core Calibration Results, extract Best Member, run deterministic evaluation on ALL 22 treatments, and render complete diagnostic metrics.
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

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
CASE_NAME = "e02_v29_formal_focused_core28_0_60cm_100x5_20260822"
RUN_DIR = ROOT / "workspace/runs" / CASE_NAME
MAPPING_SRC = ROOT / "workspace/runs/e02_arm_d_full_synergy_50x3_20260820/deterministic_best_17/two_season_water_n_mapping_from_filex.csv"
REGISTRY_SRC = RUN_DIR / f"{CASE_NAME}_observation_registry.csv"

EXP_25_5L = ROOT / "data/user/experiments/xxql2501_rootzone_5layer_60cm_20260822"
EXP_26_5L = ROOT / "data/user/experiments/xxql2601_rootzone_5layer_60cm_20260822"

ALL_TMTS_25SP = [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]
ALL_TMTS_26SP = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]


def main():
    # 1. Inspect Phi convergence
    phi_csv = RUN_DIR / f"{CASE_NAME}.phi.actual.csv"
    df_phi = pd.read_csv(phi_csv)
    print("=== v29 Focused Core Calibration Objective Function (Phi) Iteration Summary ===")
    print(df_phi[["iteration", "total_runs", "min", "mean", "standard_deviation", "max"]].to_string(index=False))

    last_row = df_phi.iloc[-1]
    members = [c for c in df_phi.columns if c not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]]
    valid_phi = [(m, float(last_row[m])) for m in members if pd.notna(last_row[m])]
    valid_phi.sort(key=lambda x: x[1])
    best_member, best_phi = valid_phi[0]
    print(f"\nBest Candidate Member in Iteration 5: #{best_member} with Phi = {best_phi:.2f}")

    # 2. Extract best member parameters
    par_csv = RUN_DIR / f"{CASE_NAME}.5.par.csv"
    df_par = pd.read_csv(par_csv)
    row_best = df_par[df_par[df_par.columns[0]].astype(str) == str(best_member)].iloc[0]

    par_rows = []
    for c in df_par.columns[1:]:
        par_rows.append({"name": c.lower(), "value": float(row_best[c])})
    df_best_par = pd.DataFrame(par_rows)

    det_cand_dir = RUN_DIR / "deterministic_candidates" / f"best_phi_member{best_member}_all22_20260822"
    if det_cand_dir.exists():
        shutil.rmtree(det_cand_dir)
    det_cand_dir.mkdir(parents=True, exist_ok=True)

    best_par_path = det_cand_dir / f"best_member_{best_member}_params.csv"
    df_best_par.to_csv(best_par_path, index=False)
    print(f"Saved Best Member #{best_member} parameters to {best_par_path}")

    # 3. Create deterministic all-22-treatment evaluation run
    t25 = det_cand_dir / "exp25"
    t26 = det_cand_dir / "exp26"
    shutil.copytree(EXP_25_5L, t25)
    shutil.copytree(EXP_26_5L, t26)

    design = {
        "schema_version": 1,
        "design_id": f"{CASE_NAME}_best{best_member}_all22",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": f"v29 Best Member {best_member} Deterministic Run (All 22 Treatments)",
        "bounds_id": "eggplant_e02_v29_formal_focused_core28_0_60cm_20260822",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "5-layer 0-60cm deep plow soil",
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
            {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(t25), "role": "calibration", "treatments": ALL_TMTS_25SP},
            {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(t26), "role": "calibration", "treatments": ALL_TMTS_26SP}
        ]
    }
    with open(det_cand_dir / "joint_design.json", "w", encoding="utf-8") as f:
        json.dump(design, f, indent=2)

    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    print(f"Running deterministic multi-season simulation for ALL 22 Treatments with Member #{best_member}...")
    subprocess.run([
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(det_cand_dir / "joint_design.json"),
        "--param-csv", str(best_par_path),
        "--prefix", f"sim_v29_best{best_member}",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs"
    ], cwd=det_cand_dir, env=env, check=True)

    # 4. Calculate metrics across all 22 treatments
    sys.path.insert(0, str(ROOT / "tools/analysis"))
    from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare, build_season_process_compare, compute_metrics

    df_map = pd.read_csv(MAPPING_SRC)
    tmt_dict_25 = dict(zip(df_map[df_map["season_id"] == "25SP"]["treatment"], df_map[df_map["season_id"] == "25SP"]["water_level"] + df_map[df_map["season_id"] == "25SP"]["nitrogen_level"]))
    tmt_dict_26 = dict(zip(df_map[df_map["season_id"] == "26SP"]["treatment"], df_map[df_map["season_id"] == "26SP"]["water_level"] + df_map[df_map["season_id"] == "26SP"]["nitrogen_level"]))

    metrics_rows = []
    treatment_results = []
    for season, tdict, tmts in [("25SP", tmt_dict_25, ALL_TMTS_25SP), ("26SP", tmt_dict_26, ALL_TMTS_26SP)]:
        sdir = det_cand_dir / "_seasons" / season
        h_compare = build_season_harvest_compare(sdir, season)
        for vcol in ["DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM"]:
            obs_c = f"OBS_{vcol}"
            sim_c = f"SIM_{vcol}"
            if obs_c in h_compare.columns and sim_c in h_compare.columns:
                m = compute_metrics(h_compare[obs_c].to_numpy(float), h_compare[sim_c].to_numpy(float))
                m.update({"season": season, "kind": "harvest", "variable": vcol, "n": len(h_compare)})
                metrics_rows.append(m)

        p_compare = build_season_process_compare(sdir, season)
        for var in ["LAID", "LWAD", "SWAD", "CHTD"]:
            obs_c = f"OBS_{var}"
            sim_c = f"SIM_{var}"
            if obs_c in p_compare.columns and sim_c in p_compare.columns:
                m = compute_metrics(p_compare[obs_c].to_numpy(float), p_compare[sim_c].to_numpy(float))
                m.update({"season": season, "kind": "process", "variable": var, "n": len(p_compare)})
                metrics_rows.append(m)

        last_h = h_compare.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
        for idx, row in last_h.iterrows():
            tn = int(row["TN"])
            tlabel = tdict.get(tn, f"TN{tn}")
            treatment_results.append({
                "season": season,
                "treatment": tn,
                "treatment_label": tlabel,
                "obs_dry": row["OBS_DRY_CUM"],
                "sim_dry": row["SIM_DRY_CUM"],
                "obs_fresh": row["OBS_FRESH_CUM"],
                "sim_fresh": row["SIM_FRESH_CUM"],
                "bias_dry_pct": (row["SIM_DRY_CUM"] - row["OBS_DRY_CUM"]) / row["OBS_DRY_CUM"] * 100.0,
            })

    metrics_df = pd.DataFrame(metrics_rows)
    metrics_path = det_cand_dir / "metrics_by_season_variable.csv"
    metrics_df.to_csv(metrics_path, index=False)

    tmt_df = pd.DataFrame(treatment_results)
    tmt_df.to_csv(det_cand_dir / "all_22_treatments_terminal_yields.csv", index=False)

    # 5. Render diagnostic figures
    out_fig_dir = ROOT / "figture" / f"e02_v29_formal_focused_core28_best{best_member}_all22_treatments_20260822"
    out_fig_dir.mkdir(parents=True, exist_ok=True)
    if MAPPING_SRC.exists():
        shutil.copy2(MAPPING_SRC, det_cand_dir / "two_season_water_n_mapping_from_filex.csv")

    cmd_plot = [
        sys.executable, str(ROOT / "tools/calibration/plot_dynamics.py"),
        "--det-root", str(det_cand_dir),
        "--out-root", str(out_fig_dir),
        "--seasons", "25SP,26SP",
        "--registry-csv", str(REGISTRY_SRC),
        "--include-all-treatments",
        "--mapping-csv", str(det_cand_dir / "two_season_water_n_mapping_from_filex.csv")
    ]
    print(f"Rendering all 22-treatment diagnostic plots to {out_fig_dir}...")
    subprocess.run(cmd_plot, cwd=ROOT, check=True)
    print(f"Plotting completed successfully!")

    # 6. Print summary tables
    print("\n" + "="*95)
    print(f"{'Season':<6s} | {'TRNO':<4s} | {'Label':<6s} | {'Obs Dry':>8s} | {'Sim Dry':>8s} | {'Bias (kg)':>10s} | {'Bias (%)':>10s}")
    print("="*95)
    for idx, row in tmt_df.iterrows():
        bias_kg = row['sim_dry'] - row['obs_dry']
        print(f"{row['season']:<6s} | {int(row['treatment']):>4d} | {row['treatment_label']:<6s} | {row['obs_dry']:>8.1f} | {row['sim_dry']:>8.1f} | {bias_kg:>+9.1f} kg | {row['bias_dry_pct']:>+9.1f}%")
    print("="*95)

    print(f"\n=== Comprehensive Metrics Summary (Best Member #{best_member}) ===")
    for season in ["25SP", "26SP"]:
        print(f"\n--- Season: {season} ---")
        df_s = metrics_df[metrics_df["season"] == season]
        print(df_s[["variable", "n", "rmse", "mae", "nse", "d_index", "r2"]].to_string(index=False))


if __name__ == "__main__":
    main()
