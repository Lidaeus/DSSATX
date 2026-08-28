"""Exhaustive Evaluation of ALL 12 Soil Discretization Schemes under STRICT RAW INITIAL SOIL NITROGEN (不统一土壤初始背景氮).

Evaluates 12 schemes across 22 treatments in 25SP & 26SP:
1. Scheme 0: Baseline 5L Single 60cm [60, 80, 100, 140, 180]
2. Scheme 1: Dual-Plow 5L [10, 30, 60, 100, 180]
3. Scheme 2: 2cm Skin 6L [2, 6, 20, 60, 100, 180]
4. Scheme 3: 3cm Skin 6L [3, 15, 35, 60, 100, 180]
5. Scheme 4: Exponential 8L [2, 5, 12, 25, 45, 60, 100, 180]
6. Scheme 5: 2cm+2cm Crust 10L [2, 4, 15, 30, 40, 60, 80, 100, 140, 180]
7. Scheme 6: 2cm+1cm Skin 10L [2, 3, 15, 30, 40, 60, 80, 100, 140, 180]
8. Scheme 7: 1cm+2cm Ultra-Skin 10L [1, 3, 8, 15, 30, 60, 80, 100, 140, 180]
9. Scheme 8: Balanced Doubling 12L [1, 2, 4, 8, 15, 25, 40, 60, 80, 100, 140, 180]
10. Scheme 9: Logarithmic Power 14L [1, 2, 3, 5, 8, 12, 18, 25, 35, 50, 65, 85, 120, 180]
11. Scheme 10: Geometric Multi-Scale 16L [1, 2, 3, 4, 6, 8, 10, 12, 14, 16, 22, 28, 34, 40, 60, 180]
12. Scheme 11: User Proposal Max 20L [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 30, 40, 50, 60, 80, 120, 180]
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
WORK_DIR = ROOT / "workspace/runs/exp_all_12_soil_schemes_raw_ic_20260823"
REF_SOL = ROOT / "data/user/experiments/xxql2501_rootzone_5layer_60cm_20260822/SOIL.SOL"

if WORK_DIR.exists():
    shutil.rmtree(WORK_DIR)
WORK_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "tools/analysis"))
sys.path.insert(0, str(ROOT / "tools/experiments"))
from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare, build_season_process_compare, compute_metrics
from exp_ultra_thin_topsoil_schemes_20260823 import build_soil_and_ic_bundles


def run_scheme_raw_ic(scheme_id: str, desc: str, layer_depths: list[int]):
    s_dir = WORK_DIR / scheme_id
    s_dir.mkdir(parents=True, exist_ok=True)
    t25 = s_dir / "exp25"
    t26 = s_dir / "exp26"
    
    # Builds bundles preserving 100% raw measured plot-specific initial conditions
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
        "initial_condition_policy": "100% Raw Unmodified Measured Initial Conditions",
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
        m_dry.update({"scheme": scheme_id, "season": s, "variable": "DRY_CUM", "runtime_s": runtime, "nl": len(layer_depths)})
        metrics_list.append(m_dry)

        p = build_season_process_compare(s_dir / f"_seasons/{s}", s)
        for var in ["LAID", "LWAD", "SWAD"]:
            if f"OBS_{var}" in p.columns and f"SIM_{var}" in p.columns:
                m_v = compute_metrics(p[f"OBS_{var}"].to_numpy(float), p[f"SIM_{var}"].to_numpy(float))
                m_v.update({"scheme": scheme_id, "season": s, "variable": var, "runtime_s": runtime, "nl": len(layer_depths)})
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
    print("=== Exhaustive Testing of 12 Soil Layer Schemes under Raw Measured Initial Nitrogen ===")
    
    all_schemes = [
        ("Scheme_0_5L_Base", "5L Single 60cm Plow Layer", [60, 80, 100, 140, 180]),
        ("Scheme_1_5L_DualPlow", "5L Dual-Plow Active Grid", [10, 30, 60, 100, 180]),
        ("Scheme_2_6L_Skin2cm", "6L 2cm Micro-Skin Grid", [2, 6, 20, 60, 100, 180]),
        ("Scheme_3_6L_Skin3cm", "6L 3cm Micro-Skin Grid", [3, 15, 35, 60, 100, 180]),
        ("Scheme_4_8L_Exp", "8L Exponential Grid", [2, 5, 12, 25, 45, 60, 100, 180]),
        ("Scheme_5_10L_2cm2cm", "10L 2cm+2cm Crust Grid", [2, 4, 15, 30, 40, 60, 80, 100, 140, 180]),
        ("Scheme_6_10L_2cm1cm", "10L 2cm+1cm Skin Grid", [2, 3, 15, 30, 40, 60, 80, 100, 140, 180]),
        ("Scheme_7_10L_1cm2cm", "10L 1cm+2cm Ultra-Skin Grid", [1, 3, 8, 15, 30, 60, 80, 100, 140, 180]),
        ("Scheme_8_12L_Doubling", "12L Balanced Doubling Grid", [1, 2, 4, 8, 15, 25, 40, 60, 80, 100, 140, 180]),
        ("Scheme_9_14L_LogPower", "14L Logarithmic Power Grid", [1, 2, 3, 5, 8, 12, 18, 25, 35, 50, 65, 85, 120, 180]),
        ("Scheme_10_16L_Geom", "16L Geometric Multi-Scale Grid", [1, 2, 3, 4, 6, 8, 10, 12, 14, 16, 22, 28, 34, 40, 60, 180]),
        ("Scheme_11_20L_UserMax", "20L User Proposal Max Grid", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 30, 40, 50, 60, 80, 120, 180]),
    ]

    all_metrics = []
    all_yields = []

    for sid, desc, layers in all_schemes:
        print(f"Running {sid:<24s} ({len(layers):2d} layers): {desc}...")
        try:
            m_df, y_df = run_scheme_raw_ic(sid, desc, layers)
            all_metrics.append(m_df)
            all_yields.append(y_df)
        except Exception as e:
            print(f"  Error in {sid}: {e}")

    df_metrics = pd.concat(all_metrics, ignore_index=True)
    df_yields = pd.concat(all_yields, ignore_index=True)

    df_metrics.to_csv(WORK_DIR / "all_12_schemes_raw_ic_metrics.csv", index=False)
    df_yields.to_csv(WORK_DIR / "all_12_schemes_raw_ic_yields.csv", index=False)

    print("\n" + "="*135)
    print(f"{'Scheme Name':<24s} | {'NL':<2s} | {'25SP Dry NSE':>12s} | {'25SP RMSE':>9s} | {'25SP LAI NSE':>12s} | {'26SP Dry NSE':>12s} | {'26SP LAI NSE':>12s} | {'26SP SWAD NSE':>13s}")
    print("="*135)
    
    table_rows = []
    for sid, desc, layers in all_schemes:
        sub25 = df_metrics[(df_metrics["scheme"] == sid) & (df_metrics["season"] == "25SP")]
        sub26 = df_metrics[(df_metrics["scheme"] == sid) & (df_metrics["season"] == "26SP")]
        
        nse_dry25 = sub25[sub25["variable"] == "DRY_CUM"]["nse"].values[0] if len(sub25[sub25["variable"] == "DRY_CUM"]) > 0 else np.nan
        rmse_dry25 = sub25[sub25["variable"] == "DRY_CUM"]["rmse"].values[0] if len(sub25[sub25["variable"] == "DRY_CUM"]) > 0 else np.nan
        nse_lai25 = sub25[sub25["variable"] == "LAID"]["nse"].values[0] if len(sub25[sub25["variable"] == "LAID"]) > 0 else np.nan
        
        nse_dry26 = sub26[sub26["variable"] == "DRY_CUM"]["nse"].values[0] if len(sub26[sub26["variable"] == "DRY_CUM"]) > 0 else np.nan
        nse_lai26 = sub26[sub26["variable"] == "LAID"]["nse"].values[0] if len(sub26[sub26["variable"] == "LAID"]) > 0 else np.nan
        nse_swad26 = sub26[sub26["variable"] == "SWAD"]["nse"].values[0] if len(sub26[sub26["variable"] == "SWAD"]) > 0 else np.nan
        
        print(f"{sid:<24s} | {len(layers):<2d} | {nse_dry25:>12.4f} | {rmse_dry25:>9.1f} | {nse_lai25:>12.4f} | {nse_dry26:>12.4f} | {nse_lai26:>12.4f} | {nse_swad26:>13.4f}")
        table_rows.append({
            "sid": sid, "desc": desc, "nl": len(layers),
            "nse_dry25": nse_dry25, "rmse_dry25": rmse_dry25, "nse_lai25": nse_lai25,
            "nse_dry26": nse_dry26, "nse_lai26": nse_lai26, "nse_swad26": nse_swad26
        })
    print("="*135)

    print("\n=== Critical Treatment Yields Audit (Under Strict Raw Initial Nitrogen) ===")
    print(f"{'Scheme Name':<24s} | {'NL':<2s} | {'25SP W1N0 (T13)':>15s} | {'25SP W3N0 (T5)':>14s} | {'25SP W2N0 (T9)':>14s} | {'25SP W3N3 (T2)':>14s} | {'26SP W1N0 (T12)':>15s} | {'26SP W3N0 (T9)':>14s}")
    print(f"{'Field Real Targets':<24s} | {'-':<2s} | {'1958.0 kg':>15s} | {'2882.0 kg':>14s} | {'2834.0 kg':>14s} | {'3637.0 kg':>14s} | {'3557.0 kg':>15s} | {'3574.0 kg':>14s}")
    print("-" * 135)
    for sid, desc, layers in all_schemes:
        sub_y = df_yields[df_yields["scheme"] == sid]
        y_25_t13 = sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 13)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 13)]) > 0 else np.nan
        y_25_t5 = sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 5)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 5)]) > 0 else np.nan
        y_25_t9 = sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 9)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 9)]) > 0 else np.nan
        y_25_t2 = sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 2)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 2)]) > 0 else np.nan
        y_26_t12 = sub_y[(sub_y["season"] == "26SP") & (sub_y["tn"] == 12)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "26SP") & (sub_y["tn"] == 12)]) > 0 else np.nan
        y_26_t9 = sub_y[(sub_y["season"] == "26SP") & (sub_y["tn"] == 9)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "26SP") & (sub_y["tn"] == 9)]) > 0 else np.nan
        print(f"{sid:<24s} | {len(layers):<2d} | {y_25_t13:>12.1f} kg | {y_25_t5:>11.1f} kg | {y_25_t9:>11.1f} kg | {y_25_t2:>11.1f} kg | {y_26_t12:>12.1f} kg | {y_26_t9:>11.1f} kg")
    print("=" * 135)


if __name__ == "__main__":
    main()
