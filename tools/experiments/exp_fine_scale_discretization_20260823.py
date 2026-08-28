"""Comprehensive Fine-Scale Soil Discretization Experiments (Exploring 10 to 20 Layer Boundaries):
Scheme 1 (User Proposal 20-Layer Max): 0-10cm every 1cm [1,2,3,4,5,6,7,8,9,10,15,20,25,30,40,50,60,80,120,180]
Scheme 2 (Geometric Multi-Scale 16-Layer): 1cm top + 2cm drip [1,2,3,4,6,8,10,12,14,16,22,28,34,40,60,180]
Scheme 3 (Logarithmic Power Grid 14-Layer): [1,2,3,5,8,12,18,25,35,50,65,85,120,180]
Scheme 4 (Balanced Doubling Grid 12-Layer): [1,2,4,8,15,25,40,60,80,100,140,180]
Scheme Ref (Baseline 10-Layer): [2,4,15,30,40,60,80,100,140,180]

Evaluates:
- 25SP & 26SP DRY_CUM NSE, RMSE, MAE, R2
- LAID NSE, LWAD NSE, SWAD NSE
- Specific audit on 25SP W1N0 (T13), 25SP W3N0 (T5), 26SP W1N0 (T12), 26SP W3N3 (T1)
- Numerical execution runtime and stability
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
import pandas as pd
import numpy as np

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
BASE_PAR = ROOT / "workspace/runs/e02_v30_formal_refined_balanced_0_60cm_100x5_20260822/deterministic_candidates/best_phi_member26_all22_20260822/best_member_26_params.csv"
WORK_DIR = ROOT / "workspace/runs/exp_fine_scale_discretization_20260823"
REF_SOL = ROOT / "data/user/experiments/xxql2501_rootzone_5layer_60cm_20260822/SOIL.SOL"

if WORK_DIR.exists():
    shutil.rmtree(WORK_DIR)
WORK_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "tools/analysis"))
sys.path.insert(0, str(ROOT / "tools/experiments"))
from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare, build_season_process_compare, compute_metrics
from exp_ultra_thin_topsoil_schemes_20260823 import build_soil_and_ic_bundles


def run_fine_scheme(scheme_id: str, desc: str, layer_depths: list[int]):
    s_dir = WORK_DIR / scheme_id
    s_dir.mkdir(parents=True, exist_ok=True)
    t25 = s_dir / "exp25"
    t26 = s_dir / "exp26"
    
    build_soil_and_ic_bundles(t25, "25SP", layer_depths)
    build_soil_and_ic_bundles(t26, "26SP", layer_depths)

    par_path = s_dir / "params.csv"
    shutil.copy2(BASE_PAR, par_path)

    design = {
        "schema_version": 1,
        "design_id": scheme_id,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": desc,
        "bounds_id": "eggplant_e02_v30_formal_refined_balanced_0_60cm_20260822",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": desc,
        "nitrogen_response_objective": {"enabled": False},
        "water_response_objective": {"enabled": False},
        "harvest_dry_objective": {
            "enabled": True, "mode": "increment_plus_terminal", "variable": "CHPDT",
            "process_lambda_per_season": 200.0, "terminal_lambda_per_season": 300.0
        },
        "process_state_objective": {
            "enabled": True, "mode": "signed_difference_plus_terminal", "variables": ["LAID", "LWAD", "SWAD"]
        },
        "seasons": [
            {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(t25), "role": "calibration", "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]},
            {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(t26), "role": "calibration", "treatments": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]}
        ]
    }
    with open(s_dir / "joint_design.json", "w", encoding="utf-8") as f:
        json.dump(design, f, indent=2)

    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    
    t0 = time.time()
    subprocess.run([
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(s_dir / "joint_design.json"),
        "--param-csv", str(par_path),
        "--prefix", f"sim_{scheme_id}",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs"
    ], cwd=s_dir, env=env, check=True, stdout=subprocess.DEVNULL)
    runtime = time.time() - t0

    # Collect metrics & terminal yields
    metrics_list = []
    yields_list = []
    for s in ["25SP", "26SP"]:
        h = build_season_harvest_compare(s_dir / f"_seasons/{s}", s)
        m_dry = compute_metrics(h["OBS_DRY_CUM"].to_numpy(float), h["SIM_DRY_CUM"].to_numpy(float))
        m_dry.update({"scheme": scheme_id, "season": s, "variable": "DRY_CUM", "runtime_s": runtime, "layers": len(layer_depths)})
        metrics_list.append(m_dry)

        p = build_season_process_compare(s_dir / f"_seasons/{s}", s)
        for var in ["LAID", "LWAD", "SWAD"]:
            if f"OBS_{var}" in p.columns and f"SIM_{var}" in p.columns:
                m_v = compute_metrics(p[f"OBS_{var}"].to_numpy(float), p[f"SIM_{var}"].to_numpy(float))
                m_v.update({"scheme": scheme_id, "season": s, "variable": var, "runtime_s": runtime, "layers": len(layer_depths)})
                metrics_list.append(m_v)

        last_h = h.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
        for idx, r in last_h.iterrows():
            yields_list.append({
                "scheme": scheme_id,
                "season": s,
                "tn": int(r["TN"]),
                "obs": r["OBS_DRY_CUM"],
                "sim": r["SIM_DRY_CUM"],
                "bias_pct": (r["SIM_DRY_CUM"] - r["OBS_DRY_CUM"]) / r["OBS_DRY_CUM"] * 100.0
            })
    return pd.DataFrame(metrics_list), pd.DataFrame(yields_list)


def main():
    print("=== Exploring Fine-Scale Discretization Thresholds (10 to 20 Layers) ===")
    
    schemes = [
        ("Scheme_Ref_10L", "Baseline 10-Layer Grid [2,4,15,30,40,60,80,100,140,180]", [2, 4, 15, 30, 40, 60, 80, 100, 140, 180]),
        ("Scheme_4_12L_Doubling", "Balanced Doubling 12-Layer Grid [1,2,4,8,15,25,40,60,80,100,140,180]", [1, 2, 4, 8, 15, 25, 40, 60, 80, 100, 140, 180]),
        ("Scheme_3_14L_LogPower", "Logarithmic Power 14-Layer Grid [1,2,3,5,8,12,18,25,35,50,65,85,120,180]", [1, 2, 3, 5, 8, 12, 18, 25, 35, 50, 65, 85, 120, 180]),
        ("Scheme_2_16L_Geometric", "Geometric Multi-Scale 16-Layer Grid [1,2,3,4,6,8,10,12,14,16,22,28,34,40,60,180]", [1, 2, 3, 4, 6, 8, 10, 12, 14, 16, 22, 28, 34, 40, 60, 180]),
        ("Scheme_1_20L_UserMax", "User Proposal Max 20-Layer Grid [1..10, 15, 20, 25, 30, 40, 50, 60, 80, 120, 180]", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 30, 40, 50, 60, 80, 120, 180]),
    ]

    all_metrics = []
    all_yields = []

    for sid, desc, layers in schemes:
        print(f"\nRunning {sid} ({len(layers)} layers): {desc}...")
        try:
            m_df, y_df = run_fine_scheme(sid, desc, layers)
            all_metrics.append(m_df)
            all_yields.append(y_df)
            print(f"  {sid} completed successfully.")
        except Exception as e:
            print(f"  Error in {sid}: {e}")

    df_metrics = pd.concat(all_metrics, ignore_index=True)
    df_yields = pd.concat(all_yields, ignore_index=True)

    df_metrics.to_csv(WORK_DIR / "fine_scale_schemes_metrics_summary.csv", index=False)
    df_yields.to_csv(WORK_DIR / "fine_scale_schemes_yields_summary.csv", index=False)

    print("\n" + "="*120)
    print(f"{'Scheme Description':<30s} | {'NL':<3s} | {'Season':<6s} | {'DRY NSE':>10s} | {'DRY RMSE':>10s} | {'LAID NSE':>10s} | {'SWAD NSE':>10s} | {'Runtime':>8s}")
    print("="*120)
    for sid, desc, layers in schemes:
        for s in ["25SP", "26SP"]:
            sub = df_metrics[(df_metrics["scheme"] == sid) & (df_metrics["season"] == s)]
            nse_dry = sub[sub["variable"] == "DRY_CUM"]["nse"].values[0] if len(sub[sub["variable"] == "DRY_CUM"]) > 0 else np.nan
            rmse_dry = sub[sub["variable"] == "DRY_CUM"]["rmse"].values[0] if len(sub[sub["variable"] == "DRY_CUM"]) > 0 else np.nan
            nse_laid = sub[sub["variable"] == "LAID"]["nse"].values[0] if len(sub[sub["variable"] == "LAID"]) > 0 else np.nan
            nse_swad = sub[sub["variable"] == "SWAD"]["nse"].values[0] if len(sub[sub["variable"] == "SWAD"]) > 0 else np.nan
            rt = sub["runtime_s"].values[0] if len(sub) > 0 else np.nan
            print(f"{sid:<30s} | {len(layers):<3d} | {s:<6s} | {nse_dry:>10.4f} | {rmse_dry:>10.1f} | {nse_laid:>10.4f} | {nse_swad:>10.4f} | {rt:>7.1f}s")
        print("-" * 120)

    print("\n=== Specific Treatment Yields & Water/Nitrogen Response Audit ===")
    print(f"{'Scheme Description':<30s} | {'NL':<3s} | {'25SP W1N0 (T13)':>16s} | {'25SP W3N0 (T5)':>15s} | {'26SP W1N0 (T12)':>16s} | {'26SP W3N3 (T1)':>15s}")
    print(f"{'Observed Real Target':<30s} | {'-':<3s} | {'1958.0 kg':>16s} | {'2882.0 kg':>15s} | {'3557.0 kg':>16s} | {'3967.0 kg':>15s}")
    print("-" * 120)
    for sid, desc, layers in schemes:
        sub_y = df_yields[df_yields["scheme"] == sid]
        y_25_t13 = sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 13)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 13)]) > 0 else np.nan
        y_25_t5 = sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 5)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 5)]) > 0 else np.nan
        y_26_t12 = sub_y[(sub_y["season"] == "26SP") & (sub_y["tn"] == 12)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "26SP") & (sub_y["tn"] == 12)]) > 0 else np.nan
        y_26_t1 = sub_y[(sub_y["season"] == "26SP") & (sub_y["tn"] == 1)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "26SP") & (sub_y["tn"] == 1)]) > 0 else np.nan
        print(f"{sid:<30s} | {len(layers):<3d} | {y_25_t13:>13.1f} kg | {y_25_t5:>12.1f} kg | {y_26_t12:>13.1f} kg | {y_26_t1:>12.1f} kg")
    print("=" * 120)


if __name__ == "__main__":
    main()
