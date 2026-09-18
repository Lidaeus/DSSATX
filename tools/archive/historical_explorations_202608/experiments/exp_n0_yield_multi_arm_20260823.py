"""Multi-Arm Small Experiment to Diagnose & Validate N0 Yield Behavior:
Arm 0: Baseline Control (Member #26)
Arm 1: Uniform Mean Initial Soil Nitrogen across N0 Plots (testing initial N spatial spike)
Arm 2: Moderated Soil Mineralization Factor (SOIL_SLNF = 2.70 vs 2.50)
Arm 3: Water Stress Calibration for Deficit Irrigation (W1) via SLLL (+0.020) and RWUMX (0.038)
Arm 4: Combined Multi-Factor Synergy (Uniform N0 IC + SLNF 2.80 + Water Stress)
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
BASE_PAR = ROOT / "workspace/runs/e02_v30_formal_refined_balanced_0_60cm_100x5_20260822/deterministic_candidates/best_phi_member26_all22_20260822/best_member_26_params.csv"
EXP_25_5L = ROOT / "data/user/experiments/xxql2501_rootzone_5layer_60cm_20260822"
EXP_26_5L = ROOT / "data/user/experiments/xxql2601_rootzone_5layer_60cm_20260822"
WORK_DIR = ROOT / "workspace/runs/exp_n0_yield_multi_arm_20260823"

if WORK_DIR.exists():
    shutil.rmtree(WORK_DIR)
WORK_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "tools/analysis"))
from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare, compute_metrics


def run_arm(arm_id: str, desc: str, mod_fn, param_mods: dict = None):
    arm_dir = WORK_DIR / arm_id
    arm_dir.mkdir(parents=True, exist_ok=True)
    t25 = arm_dir / "exp25"
    t26 = arm_dir / "exp26"
    shutil.copytree(EXP_25_5L, t25)
    shutil.copytree(EXP_26_5L, t26)

    # Apply FileX modifications
    mod_fn(t25, t26)

    # Prepare parameter CSV
    df_p = pd.read_csv(BASE_PAR)
    if param_mods:
        for k, v in param_mods.items():
            idx_p = df_p.index[df_p["name"] == k.lower()].tolist()
            if idx_p:
                df_p.loc[idx_p[0], "value"] = v
            else:
                df_p = pd.concat([df_p, pd.DataFrame([{"name": k.lower(), "value": v}])], ignore_index=True)
    par_path = arm_dir / "params.csv"
    df_p.to_csv(par_path, index=False)

    design = {
        "schema_version": 1,
        "design_id": arm_id,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": desc,
        "bounds_id": "eggplant_e02_v30_formal_refined_balanced_0_60cm_20260822",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "5-layer 0-60cm deep plow soil",
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
    with open(arm_dir / "joint_design.json", "w", encoding="utf-8") as f:
        json.dump(design, f, indent=2)

    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    subprocess.run([
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(arm_dir / "joint_design.json"),
        "--param-csv", str(par_path),
        "--prefix", f"sim_{arm_id}",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs"
    ], cwd=arm_dir, env=env, check=True, stdout=subprocess.DEVNULL)

    # Collect results
    res = []
    for s in ["25SP", "26SP"]:
        h = build_season_harvest_compare(arm_dir / f"_seasons/{s}", s)
        last_h = h.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
        for idx, r in last_h.iterrows():
            res.append({
                "arm": arm_id,
                "season": s,
                "tn": int(r["TN"]),
                "obs": r["OBS_DRY_CUM"],
                "sim": r["SIM_DRY_CUM"],
                "bias_pct": (r["SIM_DRY_CUM"] - r["OBS_DRY_CUM"]) / r["OBS_DRY_CUM"] * 100.0
            })
    return pd.DataFrame(res)


def no_mod(t25, t26):
    pass


def mod_uniform_n0_ic(t25, t26):
    # For 25SP: copy TRNO 5 lines into TRNO 13 in *INITIAL CONDITIONS
    p25 = t25 / "XXQL2501.TMX"
    txt25 = p25.read_text()
    old_block_25 = (
        "13    20  .238 .8803 44.38\n"
        "13    40  .296 .6725 10.28\n"
        "13    60  .305  .732 4.111\n"
        "13    80  .365    .5     1\n"
        "13   100  .356    .5     1"
    )
    new_block_25 = (
        "13    20  .202 1.267  19.9\n"
        "13    40   .26  .817 11.59\n"
        "13    60  .281 .6185 4.188\n"
        "13    80  .299    .5     1\n"
        "13   100  .255    .5     1"
    )
    txt25 = txt25.replace(old_block_25, new_block_25)
    p25.write_text(txt25)

    # For 26SP: copy TRNO 11 lines into TRNO 12 in *INITIAL CONDITIONS
    p26 = t26 / "XXQL2601.TMX"
    txt26 = p26.read_text()
    old_block_26 = (
        "12    20   .21 1.861 47.57\n"
        "12    40  .298 .7317 42.37\n"
        "12    60   .27 .8497 10.21\n"
        "12    80   .28    .5     1\n"
        "12   100   .34    .5     1"
    )
    new_block_26 = (
        "12    20  .202 2.126 15.00\n"
        "12    40  .273 .8951 9.565\n"
        "12    60  .253 .7771 6.431\n"
        "12    80  .296    .5     1\n"
        "12   100  .343    .5     1"
    )
    txt26 = txt26.replace(old_block_26, new_block_26)
    p26.write_text(txt26)


def main():
    print("=== Launching Multi-Arm Small Experiments for N0 Yield Investigation ===")
    
    # Arm 0: Control
    print("\nRunning Arm 0: Baseline Control (Member #26)...")
    df_arm0 = run_arm("Arm_0_Control", "Arm 0 Baseline Control", no_mod)

    # Arm 1: Uniform Mean Initial Soil Nitrogen
    print("\nRunning Arm 1: Uniform Background Initial Soil N in N0 plots (eliminating 44+ mg/kg spatial spike)...")
    df_arm1 = run_arm("Arm_1_Uniform_N0_IC", "Arm 1 Uniform Background N0 IC", mod_uniform_n0_ic)

    # Arm 2: Moderated Soil Mineralization Factor (SOIL_SLNF = 2.70 vs 2.40)
    print("\nRunning Arm 2: Moderated Soil Mineralization (SOIL_SLNF = 2.60)...")
    df_arm2 = run_arm("Arm_2_SLNF_2_60", "Arm 2 SOIL_SLNF = 2.60", no_mod, param_mods={"soil_slnf": 2.60})

    # Arm 3: Water Stress Calibration on W1 via RWUMX & SWFAC sensitivity
    print("\nRunning Arm 3: Water Stress Calibration on Deficit Irrigation (RWUMX = 0.038, SWBAR = 0.35)...")
    df_arm3 = run_arm("Arm_3_Water_Stress_W1", "Arm 3 Water Stress Calibration", no_mod, param_mods={"rwumx": 0.038, "soil_slll_01": 0.165, "soil_slll_02": 0.170})

    # Arm 4: Combined Multi-Factor Synergy (Uniform N0 IC + SLNF 2.70 + Water Stress Calibration)
    print("\nRunning Arm 4: Combined Multi-Factor Synergy (Uniform N0 IC + SLNF 2.70 + RWUMX 0.038)...")
    df_arm4 = run_arm("Arm_4_Combined_Synergy", "Arm 4 Combined Synergy", mod_uniform_n0_ic, param_mods={"soil_slnf": 2.70, "rwumx": 0.038, "soil_slll_01": 0.165, "soil_slll_02": 0.170})

    df_all = pd.concat([df_arm0, df_arm1, df_arm2, df_arm3, df_arm4], ignore_index=True)
    df_all.to_csv(WORK_DIR / "multi_arm_n0_experiment_results.csv", index=False)

    print("\n" + "="*115)
    print(f"{'Arm Description':<28s} | {'Season':<6s} | {'TRNO (Tmt)':<10s} | {'Obs Dry':>8s} | {'Sim Dry':>8s} | {'Bias (%)':>10s}")
    print("="*115)
    
    n0_tmts = [("25SP", 5, "W3N0"), ("25SP", 9, "W2N0"), ("25SP", 13, "W1N0"), ("26SP", 9, "W3N0"), ("26SP", 11, "W2N0"), ("26SP", 12, "W1N0")]
    for arm_name in ["Arm_0_Control", "Arm_1_Uniform_N0_IC", "Arm_2_SLNF_2_60", "Arm_3_Water_Stress_W1", "Arm_4_Combined_Synergy"]:
        df_a = df_all[df_all["arm"] == arm_name]
        for s, tn, tlabel in n0_tmts:
            row = df_a[(df_a["season"] == s) & (df_a["tn"] == tn)]
            if len(row) > 0:
                r = row.iloc[0]
                print(f"{arm_name:<28s} | {s:<6s} | {tn:>2d} ({tlabel:<4s}) | {r['obs']:>8.1f} | {r['sim']:>8.1f} | {r['bias_pct']:>+9.1f}%")
        print("-" * 115)


if __name__ == "__main__":
    main()
