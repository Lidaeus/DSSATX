"""Generate, simulate, compute metrics, and render full diagnostic plots for:
1. Soil Profile 0-40 cm Single Plow Layer (SLB = 40, 60, 80, 100, 140, 180 cm)
2. Soil Profile 0-60 cm Single Deep Plow Layer (SLB = 60, 80, 100, 140, 180 cm)
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
BEST_PARAMS_V25 = ROOT / "workspace/runs/e02_v25_full_root_state_9layer_80x5_20260822/deterministic_candidates/best_phi_member50_two_season_20260822/best_member_50_params.csv"
MAPPING_SRC = ROOT / "workspace/runs/e02_arm_d_full_synergy_50x3_20260820/deterministic_best_17/two_season_water_n_mapping_from_filex.csv"
REGISTRY_SRC = ROOT / "workspace/runs/e02_v25_full_root_state_9layer_80x5_20260822/e02_v25_full_root_state_9layer_80x5_20260822_observation_registry.csv"

EXP_25_BASE = ROOT / "data/user/experiments/xxql2501_rootzone_9layer_30cm_20260822"
EXP_26_BASE = ROOT / "data/user/experiments/xxql2601_rootzone_9layer_30cm_20260822"


def generate_soil_sol_40cm(src_soil_path: Path, dst_soil_path: Path):
    text = src_soil_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    
    # 0-40, 40-60, 60-80, 80-100, 100-140, 140-180 (6 layers)
    layer_def = """@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC
    40     1  .145  .318  .460  .950  0.23  1.47  0.80  35.0  30.0   -99  0.07   8.1   -99   -99   -99
    60     3  .172  .330  .440  .450  0.24  1.53  0.31  35.0  30.0   -99  0.03   8.0   -99   -99   -99
    80     4  .157  .330  .460  .250  0.24  1.50  0.18  35.0  30.0   -99   -99   -99   -99   -99   -99
   100     5  .166  .340  .510  .150  0.24  1.49  0.10  35.0  30.0   -99   -99   -99   -99   -99   -99
   140     6  .173  .305  .400  .080  0.24  1.53  0.07  35.0  30.0   -99   -99   -99   -99   -99   -99
   180     6  .176  .290  .350  .030  0.24  1.55  0.05  35.0  30.0   -99   -99   -99   -99   -99   -99"""

    new_lines = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if l.startswith("*IBTM910017"):
            new_lines.append(l)
            i += 1
            while i < len(lines) and not lines[i].startswith("@  SLB"):
                new_lines.append(lines[i])
                i += 1
            new_lines.append(layer_def)
            while i < len(lines) and not lines[i].startswith("*IBPP910015"):
                i += 1
        else:
            new_lines.append(l)
            i += 1
            
    dst_soil_path.write_text("\n".join(new_lines), encoding="utf-8")


def generate_soil_sol_60cm(src_soil_path: Path, dst_soil_path: Path):
    text = src_soil_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    
    # 0-60, 60-80, 80-100, 100-140, 140-180 (5 layers)
    layer_def = """@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC
    60     1  .150  .320  .450  .900  0.23  1.50  0.65  35.0  30.0   -99  0.05   8.0   -99   -99   -99
    80     4  .157  .330  .460  .250  0.24  1.50  0.18  35.0  30.0   -99   -99   -99   -99   -99   -99
   100     5  .166  .340  .510  .150  0.24  1.49  0.10  35.0  30.0   -99   -99   -99   -99   -99   -99
   140     6  .173  .305  .400  .080  0.24  1.53  0.07  35.0  30.0   -99   -99   -99   -99   -99   -99
   180     6  .176  .290  .350  .030  0.24  1.55  0.05  35.0  30.0   -99   -99   -99   -99   -99   -99"""

    new_lines = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if l.startswith("*IBTM910017"):
            new_lines.append(l)
            i += 1
            while i < len(lines) and not lines[i].startswith("@  SLB"):
                new_lines.append(lines[i])
                i += 1
            new_lines.append(layer_def)
            while i < len(lines) and not lines[i].startswith("*IBPP910015"):
                i += 1
        else:
            new_lines.append(l)
            i += 1
            
    dst_soil_path.write_text("\n".join(new_lines), encoding="utf-8")


def run_and_render_soil_setup(soil_type: str, out_fig_dir: Path) -> dict:
    case_name = f"eval_soil_layer_{soil_type}_plow_20260822"
    run_dir = ROOT / "workspace/runs" / case_name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    
    t25 = run_dir / "exp25"
    t26 = run_dir / "exp26"
    shutil.copytree(EXP_25_BASE, t25)
    shutil.copytree(EXP_26_BASE, t26)
    
    if soil_type == "0_40cm":
        generate_soil_sol_40cm(EXP_25_BASE / "SOIL.SOL", t25 / "SOIL.SOL")
        generate_soil_sol_40cm(EXP_26_BASE / "SOIL.SOL", t26 / "SOIL.SOL")
    else:
        generate_soil_sol_60cm(EXP_25_BASE / "SOIL.SOL", t25 / "SOIL.SOL")
        generate_soil_sol_60cm(EXP_26_BASE / "SOIL.SOL", t26 / "SOIL.SOL")
        
    design = {
        "schema_version": 1, "design_id": case_name, "cultivar_identity": "TM0008",
        "shared_parameter_scope": case_name, "bounds_id": "eggplant_e02_v25_full_root_state_9layer_20260822",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": f"Soil plow layer {soil_type}",
        "nitrogen_response_objective": {"enabled": False}, "water_response_objective": {"enabled": False},
        "harvest_dry_objective": {"enabled": True, "mode": "increment_plus_terminal", "variable": "CHPDT", "process_lambda_per_season": 200.0, "terminal_lambda_per_season": 300.0},
        "process_state_objective": {"enabled": True, "mode": "signed_difference_plus_terminal", "variables": ["LAID", "LWAD", "SWAD"]},
        "seasons": [
            {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(t25), "role": "calibration", "treatments": [2, 5, 10, 13]},
            {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(t26), "role": "calibration", "treatments": [2, 11, 3, 12]}
        ]
    }
    with open(run_dir / "joint_design.json", "w", encoding="utf-8") as f:
        json.dump(design, f, indent=2)
        
    # Prepare parameter file with balanced physiological parameters (LFMAX=1.70, XFRT=0.74, SOIL_SLNF=3.20)
    df_p = pd.read_csv(BEST_PARAMS_V25)
    df_p.loc[df_p["name"] == "lfmax", "value"] = 1.70
    df_p.loc[df_p["name"] == "xfrt", "value"] = 0.74
    df_p.loc[df_p["name"] == "soil_slnf", "value"] = 3.20
    param_csv = run_dir / "params_balanced_lfmax170.csv"
    df_p.to_csv(param_csv, index=False)
    
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    print(f"Running simulation for Soil Profile {soil_type}...")
    subprocess.run([
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(run_dir / "joint_design.json"),
        "--param-csv", str(param_csv),
        "--prefix", f"sim_{soil_type}", "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs"
    ], cwd=run_dir, env=env, check=True)
    
    sys.path.insert(0, str(ROOT / "tools/analysis"))
    from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare, build_season_process_compare, compute_metrics

    metrics_rows = []
    treatment_results = {}
    for season, tmt_map in [("25SP", {2: "W3N3", 10: "W1N3", 5: "W3N0", 13: "W1N0"}),
                            ("26SP", {2: "W3N3", 3: "W1N3", 11: "W3N0", 12: "W1N0"})]:
        sdir = run_dir / "_seasons" / season
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
            tlabel = tmt_map[tn]
            treatment_results[(season, tlabel)] = {
                "Obs_Dry": row["OBS_DRY_CUM"],
                "Sim_Dry": row["SIM_DRY_CUM"],
                "Obs_Fresh": row["OBS_FRESH_CUM"],
                "Sim_Fresh": row["SIM_FRESH_CUM"],
                "Bias_Dry_Pct": (row["SIM_DRY_CUM"] - row["OBS_DRY_CUM"]) / row["OBS_DRY_CUM"] * 100.0,
            }

    metrics_df = pd.DataFrame(metrics_rows)
    metrics_path = run_dir / "metrics_by_season_variable.csv"
    metrics_df.to_csv(metrics_path, index=False)

    # Render Diagnostic plots
    if MAPPING_SRC.exists():
        shutil.copy2(MAPPING_SRC, run_dir / "two_season_water_n_mapping_from_filex.csv")
    out_fig_dir.mkdir(parents=True, exist_ok=True)
    cmd_plot = [
        sys.executable, str(ROOT / "tools/calibration/plot_dynamics.py"),
        "--det-root", str(run_dir),
        "--out-root", str(out_fig_dir),
        "--seasons", "25SP,26SP",
        "--registry-csv", str(REGISTRY_SRC),
        "--include-all-treatments",
        "--mapping-csv", str(run_dir / "two_season_water_n_mapping_from_filex.csv")
    ]
    print(f"Rendering all diagnostic plots for {soil_type} to {out_fig_dir}...")
    subprocess.run(cmd_plot, cwd=ROOT, check=True)
    print(f"Plotting completed for {soil_type}!")
    
    return {
        "metrics_df": metrics_df,
        "treatment_results": treatment_results
    }


def main():
    dir_40 = ROOT / "figture/soil_layer_0_40cm_plow_all_treatments_20260822"
    dir_60 = ROOT / "figture/soil_layer_0_60cm_plow_all_treatments_20260822"
    
    print("=== Processing Soil Profile 1: 0-40 cm Single Plow Layer ===")
    res_40 = run_and_render_soil_setup("0_40cm", dir_40)
    
    print("\n=== Processing Soil Profile 2: 0-60 cm Single Deep Plow Layer ===")
    res_60 = run_and_render_soil_setup("0_60cm", dir_60)
    
    print("\n" + "="*95)
    print(f"{'Season':<6s} | {'Treatment':<8s} | {'Obs Dry':>8s} | {'0-40cm Plow Yield':>22s} | {'0-60cm Plow Yield':>22s}")
    print("="*95)
    
    for season in ["25SP", "26SP"]:
        for tlabel in ["W3N3", "W1N3", "W3N0", "W1N0"]:
            a = res_40["treatment_results"].get((season, tlabel), {})
            b = res_60["treatment_results"].get((season, tlabel), {})
            print(f"{season:<6s} | {tlabel:<8s} | {a.get('Obs_Dry', 0):>8.1f} | {a.get('Sim_Dry', 0):>7.1f} kg ({a.get('Bias_Dry_Pct', 0):>+5.1f}%) | {b.get('Sim_Dry', 0):>7.1f} kg ({b.get('Bias_Dry_Pct', 0):>+5.1f}%)")
        print("-" * 95)

    print("\n=== Key Metrics Comparison ===")
    for season in ["25SP", "26SP"]:
        print(f"\n--- Season: {season} ---")
        df40 = res_40["metrics_df"][res_40["metrics_df"]["season"] == season]
        df60 = res_60["metrics_df"][res_60["metrics_df"]["season"] == season]
        merged = pd.merge(df40[["variable", "nse", "d_index", "r2"]],
                          df60[["variable", "nse", "d_index", "r2"]],
                          on="variable", suffixes=("_0_40cm", "_0_60cm"))
        print(merged.to_string(index=False))


if __name__ == "__main__":
    main()
