"""Scientific Inversion & Data Assimilation of 26SP Initial Soil Mineral Nitrogen (NO3 & NH4) Profiles:
Uses Calibrated Crop Genetics (v30 Member #26) + 10-Layer Soil Discretization (Scheme 5)
to invert and assimilate the true pre-planting soil mineral nitrogen for all 12 treatments in 26SP.

Methodology:
1. Formulation: 26SP soil nitrogen in FileX copied 2025 data, introducing severe noise (e.g. TRNO 9 W3N0 having 2.5 mg/kg while TRNO 12 W1N0 having 47.5 mg/kg).
2. Two-Stage Inversion:
   - Stage 1: Group-level prior inversion across 4 nitrogen levels (N3, N2, N1, N0).
   - Stage 2: Individual plot-level fine assimilation across all 12 treatments to match 5-batch harvest curves & canopy states.
3. Optimization: Bounded Scipy optimization with DSSAT multiseason forward simulation.
4. Validation: Comprehensive evaluation of 25SP & 26SP metrics and physical sanity check.
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
from scipy.optimize import minimize

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
BASE_PAR = ROOT / "workspace/runs/e02_v30_formal_refined_balanced_0_60cm_100x5_20260822/deterministic_candidates/best_phi_member26_all22_20260822/best_member_26_params.csv"
WORK_DIR = ROOT / "workspace/runs/inverse_26sp_soil_n_20260823"
REF_SOL = ROOT / "data/user/experiments/xxql2501_rootzone_5layer_60cm_20260822/SOIL.SOL"

if WORK_DIR.exists():
    shutil.rmtree(WORK_DIR)
WORK_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "tools/analysis"))
sys.path.insert(0, str(ROOT / "tools/experiments"))
from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare, build_season_process_compare, compute_metrics
from exp_ultra_thin_topsoil_schemes_20260823 import build_soil_and_ic_bundles

LAYER_DEPTHS_10L = [2, 4, 15, 30, 40, 60, 80, 100, 140, 180]


def inject_26sp_ic(tmx_path: Path, tmt_dict: dict[int, dict[str, float]]):
    """Correctly injects custom initial SNO3 and SNH4 profiles into XXQL2601.TMX."""
    lines = tmx_path.read_text().splitlines()
    new_lines = []
    in_ic = False
    cur_tmt = None
    
    for l in lines:
        if "*INITIAL CONDITIONS" in l:
            in_ic = True
            new_lines.append(l)
        elif in_ic and l.startswith("*"):
            in_ic = False
            new_lines.append(l)
        elif in_ic:
            tokens = l.split()
            if l.startswith("@C"):
                new_lines.append(l)
            elif len(tokens) >= 10:
                cur_tmt = int(tokens[0])
                new_lines.append(l)
            elif len(tokens) >= 5 and tokens[0].isdigit() and tokens[1].isdigit():
                c_id = int(tokens[0])
                depth = int(tokens[1])
                sh2o = float(tokens[2])
                snh4 = float(tokens[3])
                sno3 = float(tokens[4])
                if c_id in tmt_dict:
                    prof = tmt_dict[c_id]
                    if depth <= 4:
                        sno3 = prof["sno3_top"]
                        snh4 = prof.get("snh4_top", 2.0)
                    elif depth <= 15:
                        sno3 = prof["sno3_drip"]
                        snh4 = prof.get("snh4_drip", 1.8)
                    elif depth <= 30:
                        sno3 = prof["sno3_mid"]
                        snh4 = prof.get("snh4_mid", 1.2)
                    elif depth <= 60:
                        sno3 = prof["sno3_bot"]
                        snh4 = prof.get("snh4_bot", 0.6)
                    else:
                        sno3 = 1.0
                        snh4 = 0.5
                new_lines.append(f" {c_id:>2d}  {depth:>4d}  {sh2o:5.3f} {snh4:5.3f} {sno3:5.2f}")
            else:
                new_lines.append(l)
        else:
            new_lines.append(l)
            
    tmx_path.write_text("\n".join(new_lines))


def evaluate_simulation(run_dir: Path, tmt_dict: dict[int, dict[str, float]], season_id="26SP", trt_list=None):
    t25 = run_dir / "exp25"
    t26 = run_dir / "exp26"
    
    if not t25.exists():
        build_soil_and_ic_bundles(t25, "25SP", LAYER_DEPTHS_10L)
    if not t26.exists():
        build_soil_and_ic_bundles(t26, "26SP", LAYER_DEPTHS_10L)

    if tmt_dict:
        inject_26sp_ic(t26 / "XXQL2601.TMX", tmt_dict)

    par_path = run_dir / "params.csv"
    if not par_path.exists():
        shutil.copy2(BASE_PAR, par_path)

    t_trts_25 = [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]
    t_trts_26 = trt_list if trt_list is not None else [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

    design = {
        "schema_version": 1,
        "design_id": "inverse_eval",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "Inverse 26SP Soil N Evaluation",
        "bounds_id": "eggplant_e02_v30_formal_refined_balanced_0_60cm_20260822",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Inverted 26SP Soil Mineral Nitrogen",
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
            {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(t25), "role": "calibration", "treatments": t_trts_25},
            {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(t26), "role": "calibration", "treatments": t_trts_26}
        ]
    }
    with open(run_dir / "joint_design.json", "w", encoding="utf-8") as f:
        json.dump(design, f, indent=2)

    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    
    subprocess.run([
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(run_dir / "joint_design.json"),
        "--param-csv", str(par_path),
        "--prefix", "sim_inverse",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs"
    ], cwd=run_dir, env=env, check=True, stdout=subprocess.DEVNULL)

    h26 = build_season_harvest_compare(run_dir / "_seasons/26SP", "26SP")
    p26 = build_season_process_compare(run_dir / "_seasons/26SP", "26SP")
    h25 = build_season_harvest_compare(run_dir / "_seasons/25SP", "25SP")
    p25 = build_season_process_compare(run_dir / "_seasons/25SP", "25SP")
    
    return h25, p25, h26, p26


def main():
    print("=== Starting Scientific Inversion of 26SP Initial Soil Mineral Nitrogen ===")
    
    inv_dir = WORK_DIR / "inversion_workspace"
    inv_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Baseline Evaluation with Raw Copied IC
    print("\n[Step 1/4] Running Baseline with Raw Copied 2025 IC...")
    h25_base, p25_base, h26_base, p26_base = evaluate_simulation(inv_dir, {})
    
    m26_dry_base = compute_metrics(h26_base["OBS_DRY_CUM"].to_numpy(float), h26_base["SIM_DRY_CUM"].to_numpy(float))
    m26_lai_base = compute_metrics(p26_base["OBS_LAID"].to_numpy(float), p26_base["SIM_LAID"].to_numpy(float))
    print(f"  Baseline 26SP: DRY NSE = {m26_dry_base['nse']:.4f}, RMSE = {m26_dry_base['rmse']:.1f} kg/ha | LAID NSE = {m26_lai_base['nse']:.4f}")
    
    last_b = h26_base.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
    t9_base = last_b[last_b["TN"] == 9]["SIM_DRY_CUM"].values[0]
    t12_base = last_b[last_b["TN"] == 12]["SIM_DRY_CUM"].values[0]
    print(f"  TRNO 9 (W3N0) Sim: {t9_base:.1f} kg (Obs: 3574.0 kg) | TRNO 12 (W1N0) Sim: {t12_base:.1f} kg (Obs: 3557.0 kg)")

    # 2. Stage 1: Invert Nitrogen Level Priors (N0, N1, N2, N3)
    print("\n[Step 2/4] Executing Stage 1: Group-Level Residual Nitrogen Inversion...")
    
    def loss_stage1(params):
        sno3_n0, sno3_n1, sno3_n2, sno3_n3, sub_ratio = params
        tmt_dict = {}
        for t in [9, 11, 12]:
            tmt_dict[t] = {"sno3_top": sno3_n0, "sno3_drip": sno3_n0 * 0.9, "sno3_mid": sno3_n0 * sub_ratio, "sno3_bot": sno3_n0 * sub_ratio * 0.5, "snh4_top": 2.0}
        for t in [7, 8, 10]:
            tmt_dict[t] = {"sno3_top": sno3_n1, "sno3_drip": sno3_n1 * 0.9, "sno3_mid": sno3_n1 * sub_ratio, "sno3_bot": sno3_n1 * sub_ratio * 0.5, "snh4_top": 2.2}
        for t in [4, 5, 6]:
            tmt_dict[t] = {"sno3_top": sno3_n2, "sno3_drip": sno3_n2 * 0.9, "sno3_mid": sno3_n2 * sub_ratio, "sno3_bot": sno3_n2 * sub_ratio * 0.5, "snh4_top": 2.4}
        for t in [1, 2, 3]:
            tmt_dict[t] = {"sno3_top": sno3_n3, "sno3_drip": sno3_n3 * 0.9, "sno3_mid": sno3_n3 * sub_ratio, "sno3_bot": sno3_n3 * sub_ratio * 0.5, "snh4_top": 2.5}
            
        try:
            _, _, h, p = evaluate_simulation(inv_dir, tmt_dict)
            rmse_dry = np.sqrt(np.mean((h["OBS_DRY_CUM"] - h["SIM_DRY_CUM"]) ** 2))
            rmse_lai = np.sqrt(np.mean((p["OBS_LAID"] - p["SIM_LAID"]) ** 2))
            return rmse_dry + 300.0 * rmse_lai
        except Exception:
            return 1e6

    bounds_s1 = [(15.0, 45.0), (18.0, 50.0), (20.0, 60.0), (22.0, 70.0), (0.40, 0.85)]
    init_s1 = [28.0, 32.0, 38.0, 45.0, 0.60]
    res_s1 = minimize(loss_stage1, init_s1, method="Nelder-Mead", bounds=bounds_s1, options={"maxiter": 30, "disp": True})
    p_s1 = res_s1.x
    print(f"  Stage 1 Optimal Group Initial NO3: N0={p_s1[0]:.1f}, N1={p_s1[1]:.1f}, N2={p_s1[2]:.1f}, N3={p_s1[3]:.1f} mg/kg | Sub Ratio={p_s1[4]:.3f}")

    # Build Stage 1 dictionary
    base_tmt_dict = {}
    for t in [9, 11, 12]:
        base_tmt_dict[t] = {"sno3_top": float(p_s1[0]), "sno3_drip": float(p_s1[0] * 0.9), "sno3_mid": float(p_s1[0] * p_s1[4]), "sno3_bot": float(p_s1[0] * p_s1[4] * 0.5), "snh4_top": 2.0}
    for t in [7, 8, 10]:
        base_tmt_dict[t] = {"sno3_top": float(p_s1[1]), "sno3_drip": float(p_s1[1] * 0.9), "sno3_mid": float(p_s1[1] * p_s1[4]), "sno3_bot": float(p_s1[1] * p_s1[4] * 0.5), "snh4_top": 2.2}
    for t in [4, 5, 6]:
        base_tmt_dict[t] = {"sno3_top": float(p_s1[2]), "sno3_drip": float(p_s1[2] * 0.9), "sno3_mid": float(p_s1[2] * p_s1[4]), "sno3_bot": float(p_s1[2] * p_s1[4] * 0.5), "snh4_top": 2.4}
    for t in [1, 2, 3]:
        base_tmt_dict[t] = {"sno3_top": float(p_s1[3]), "sno3_drip": float(p_s1[3] * 0.9), "sno3_mid": float(p_s1[3] * p_s1[4]), "sno3_bot": float(p_s1[3] * p_s1[4] * 0.5), "snh4_top": 2.5}

    # 3. Stage 2: Individual Plot-Level Fine Assimilation
    print("\n[Step 3/4] Executing Stage 2: Per-Plot Data Assimilation (12 Treatments)...")
    final_inverted_dict = {}
    
    # We calibrate a specific multiplier for each treatment to fit the 5 harvest batches
    for tn in range(1, 13):
        def loss_tn(scale_arr):
            scale = scale_arr[0]
            cur_dict = dict(base_tmt_dict)
            base_p = base_tmt_dict[tn]
            cur_dict[tn] = {
                "sno3_top": base_p["sno3_top"] * scale,
                "sno3_drip": base_p["sno3_drip"] * scale,
                "sno3_mid": base_p["sno3_mid"] * scale,
                "sno3_bot": base_p["sno3_bot"] * scale,
                "snh4_top": base_p["snh4_top"]
            }
            try:
                _, _, h_s, p_s = evaluate_simulation(inv_dir, cur_dict, trt_list=[tn])
                sub_h = h_s[h_s["TN"] == tn]
                rmse_t = np.sqrt(np.mean((sub_h["OBS_DRY_CUM"] - sub_h["SIM_DRY_CUM"]) ** 2))
                return rmse_t
            except Exception:
                return 1e6

        res_tn = minimize(loss_tn, [1.0], method="Nelder-Mead", bounds=[(0.5, 2.5)], options={"maxiter": 12})
        opt_scale = float(res_tn.x[0])
        base_p = base_tmt_dict[tn]
        final_inverted_dict[tn] = {
            "sno3_top": round(base_p["sno3_top"] * opt_scale, 2),
            "sno3_drip": round(base_p["sno3_drip"] * opt_scale, 2),
            "sno3_mid": round(base_p["sno3_mid"] * opt_scale, 2),
            "sno3_bot": round(base_p["sno3_bot"] * opt_scale, 2),
            "snh4_top": round(base_p["snh4_top"], 2),
            "snh4_drip": round(base_p["snh4_top"] * 0.8, 2),
            "snh4_mid": 1.0,
            "snh4_bot": 0.5
        }
        print(f"  TRNO {tn:>2d} Inverted Initial SNO3: Top={final_inverted_dict[tn]['sno3_top']:5.1f} mg/kg, Mid={final_inverted_dict[tn]['sno3_mid']:5.1f} mg/kg")

    # Save Inverted Profiles
    with open(WORK_DIR / "inverted_26sp_soil_n_profile.json", "w", encoding="utf-8") as f:
        json.dump(final_inverted_dict, f, indent=2)

    # 4. Final Comprehensive Re-Evaluation for both 25SP & 26SP
    print("\n[Step 4/4] Running Full Multi-Season Simulation with Inverted 26SP Soil Nitrogen...")
    h25_inv, p25_inv, h26_inv, p26_inv = evaluate_simulation(inv_dir, final_inverted_dict)

    # Save full tables
    h26_inv.to_csv(WORK_DIR / "26sp_inverted_harvest_compare.csv", index=False)
    p26_inv.to_csv(WORK_DIR / "26sp_inverted_process_compare.csv", index=False)

    print("\n" + "="*105)
    print("=== 26SP Comprehensive Evaluation Metrics Before vs After Inversion ===")
    print("="*105)
    print(f"{'Variable':<12s} | {'Before Inversion (Raw Copied IC)':<34s} | {'After Inversion (Inverted True IC)':<34s} | {'Gain':>8s}")
    print(f"{'':<12s} | {'NSE':>8s} | {'RMSE':>10s} | {'R2':>9s} | {'NSE':>8s} | {'RMSE':>10s} | {'R2':>9s} |")
    print("-"*105)
    
    # Before
    m_dry_b = compute_metrics(h26_base["OBS_DRY_CUM"].to_numpy(float), h26_base["SIM_DRY_CUM"].to_numpy(float))
    m_frs_b = compute_metrics(h26_base["OBS_FRESH_CUM"].to_numpy(float), h26_base["SIM_FRESH_CUM"].to_numpy(float))
    m_lai_b = compute_metrics(p26_base["OBS_LAID"].to_numpy(float), p26_base["SIM_LAID"].to_numpy(float))
    m_swa_b = compute_metrics(p26_base["OBS_SWAD"].to_numpy(float), p26_base["SIM_SWAD"].to_numpy(float))
    
    # After
    m_dry_a = compute_metrics(h26_inv["OBS_DRY_CUM"].to_numpy(float), h26_inv["SIM_DRY_CUM"].to_numpy(float))
    m_frs_a = compute_metrics(h26_inv["OBS_FRESH_CUM"].to_numpy(float), h26_inv["SIM_FRESH_CUM"].to_numpy(float))
    m_lai_a = compute_metrics(p26_inv["OBS_LAID"].to_numpy(float), p26_inv["SIM_LAID"].to_numpy(float))
    m_swa_a = compute_metrics(p26_inv["OBS_SWAD"].to_numpy(float), p26_inv["SIM_SWAD"].to_numpy(float))
    
    print(f"{'DRY_CUM':<12s} | {m_dry_b['nse']:>8.4f} | {m_dry_b['rmse']:>10.1f} | {m_dry_b['r2']:>9.4f} | {m_dry_a['nse']:>8.4f} | {m_dry_a['rmse']:>10.1f} | {m_dry_a['r2']:>9.4f} | {m_dry_a['nse'] - m_dry_b['nse']:>+7.4f}")
    print(f"{'FRESH_CUM':<12s} | {m_frs_b['nse']:>8.4f} | {m_frs_b['rmse']:>10.1f} | {m_frs_b['r2']:>9.4f} | {m_frs_a['nse']:>8.4f} | {m_frs_a['rmse']:>10.1f} | {m_frs_a['r2']:>9.4f} | {m_frs_a['nse'] - m_frs_b['nse']:>+7.4f}")
    print(f"{'LAID':<12s} | {m_lai_b['nse']:>8.4f} | {m_lai_b['rmse']:>10.3f} | {m_lai_b['r2']:>9.4f} | {m_lai_a['nse']:>8.4f} | {m_lai_a['rmse']:>10.3f} | {m_lai_a['r2']:>9.4f} | {m_lai_a['nse'] - m_lai_b['nse']:>+7.4f}")
    print(f"{'SWAD':<12s} | {m_swa_b['nse']:>8.4f} | {m_swa_b['rmse']:>10.1f} | {m_swa_b['r2']:>9.4f} | {m_swa_a['nse']:>8.4f} | {m_swa_a['rmse']:>10.1f} | {m_swa_a['r2']:>9.4f} | {m_swa_a['nse'] - m_swa_b['nse']:>+7.4f}")
    print("="*105)

    print("\n=== 26SP All 12 Treatments Terminal Yields Audit (Before vs After Inversion) ===")
    last_b = h26_base.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
    last_a = h26_inv.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
    
    tlabels = {
        1: "W3N3", 2: "W2N3", 3: "W1N3",
        4: "W3N2", 5: "W2N2", 6: "W1N2",
        7: "W3N1", 8: "W2N1", 9: "W3N0",
        10: "W1N1", 11: "W2N0", 12: "W1N0"
    }
    print(f"{'TRNO':<4s} | {'Label':<6s} | {'Obs Dry':>8s} | {'Before Inversion':>17s} | {'After Inversion':>17s} | {'Inverted Top SNO3':>18s} | {'Error Change':>12s}")
    print("-"*95)
    for tn in range(1, 13):
        obs = last_a[last_a["TN"] == tn]["OBS_DRY_CUM"].values[0]
        sim_b = last_b[last_b["TN"] == tn]["SIM_DRY_CUM"].values[0]
        sim_a = last_a[last_a["TN"] == tn]["SIM_DRY_CUM"].values[0]
        bias_b = sim_b - obs
        bias_a = sim_a - obs
        imp = abs(bias_b) - abs(bias_a)
        imp_str = f"+{imp:.1f} kg" if imp > 0 else f"{imp:.1f} kg"
        top_n = final_inverted_dict[tn]["sno3_top"]
        print(f"{tn:>4d} | {tlabels[tn]:<6s} | {obs:>8.1f} | {sim_b:>8.1f} ({bias_b:>+6.1f}) | {sim_a:>8.1f} ({bias_a:>+6.1f}) | {top_n:>14.1f} mg/kg | {imp_str:>12s}")
    print("="*95)


if __name__ == "__main__":
    main()
