"""Ultra-Fast & High-Precision Scientific Inversion of 26SP Initial Soil Nitrogen:
Directly drives DSSAT runner on 26SP bundle (0.8s per evaluation) to invert
the true initial mineral nitrogen (NO3 and NH4) profiles across all 12 treatments in 26SP.
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
WORK_DIR = ROOT / "workspace/runs/fast_inverse_26sp_soil_n_20260823"

if WORK_DIR.exists():
    shutil.rmtree(WORK_DIR)
WORK_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "tools/analysis"))
sys.path.insert(0, str(ROOT / "tools/experiments"))
from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare, build_season_process_compare, compute_metrics
from exp_ultra_thin_topsoil_schemes_20260823 import build_soil_and_ic_bundles

LAYER_DEPTHS_10L = [2, 4, 15, 30, 40, 60, 80, 100, 140, 180]


def inject_26sp_ic_lines(lines: list[str], tmt_dict: dict[int, dict[str, float]]) -> list[str]:
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
    return new_lines


def run_direct_dssat_26sp(dir_26: Path, par_csv: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    subprocess.run([
        sys.executable, str(ROOT / "src/dssat/run_dssat.py"),
        "--param-csv", str(par_csv),
        "--batch", "DSSBatch.v48",
        "--harvest-var", "CHPDT"
    ], cwd=dir_26, env=env, check=True, stdout=subprocess.DEVNULL)
    
    h = build_season_harvest_compare(dir_26, "26SP")
    p = build_season_process_compare(dir_26, "26SP")
    return h, p


def main():
    print("=== Direct High-Speed Scientific Inversion of 26SP Soil Nitrogen ===")
    
    t26_dir = WORK_DIR / "exp26"
    t26_dir.mkdir(parents=True, exist_ok=True)
    build_soil_and_ic_bundles(t26_dir, "26SP", LAYER_DEPTHS_10L)
    
    par_csv = WORK_DIR / "params.csv"
    shutil.copy2(BASE_PAR, par_csv)

    # 1. Baseline Evaluation
    print("\n[Step 1/3] Running Baseline 26SP (Raw Copied 2025 IC)...")
    h_base, p_base = run_direct_dssat_26sp(t26_dir, par_csv)
    m_dry_base = compute_metrics(h_base["OBS_DRY_CUM"].to_numpy(float), h_base["SIM_DRY_CUM"].to_numpy(float))
    m_lai_base = compute_metrics(p_base["OBS_LAID"].to_numpy(float), p_base["SIM_LAID"].to_numpy(float))
    print(f"  Baseline 26SP: DRY NSE = {m_dry_base['nse']:.4f}, RMSE = {m_dry_base['rmse']:.1f} kg/ha | LAID NSE = {m_lai_base['nse']:.4f}")
    
    last_b = h_base.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
    for tn in [9, 11, 12, 1, 2]:
        sim_val = last_b[last_b["TN"] == tn]["SIM_DRY_CUM"].values[0]
        obs_val = last_b[last_b["TN"] == tn]["OBS_DRY_CUM"].values[0]
        print(f"  TRNO {tn:>2d}: Sim={sim_val:6.1f} kg vs Obs={obs_val:6.1f} kg (Error={sim_val - obs_val:+6.1f} kg)")

    # Read base TMX lines
    tmx_path = t26_dir / "XXQL2601.TMX"
    orig_tmx_lines = tmx_path.read_text().splitlines()

    # 2. Stage 1: Group-Level Inversion (N0, N1, N2, N3)
    print("\n[Step 2/3] Performing Group-Level Residual Soil Nitrogen Inversion...")
    
    def loss_group(params):
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
            
        mod_lines = inject_26sp_ic_lines(orig_tmx_lines, tmt_dict)
        tmx_path.write_text("\n".join(mod_lines))
        
        try:
            h_s, p_s = run_direct_dssat_26sp(t26_dir, par_csv)
            rmse_dry = np.sqrt(np.mean((h_s["OBS_DRY_CUM"] - h_s["SIM_DRY_CUM"]) ** 2))
            rmse_lai = np.sqrt(np.mean((p_s["OBS_LAID"] - p_s["SIM_LAID"]) ** 2))
            return rmse_dry + 200.0 * rmse_lai
        except Exception:
            return 1e6

    bounds_s1 = [(15.0, 50.0), (18.0, 60.0), (20.0, 70.0), (25.0, 85.0), (0.40, 0.85)]
    init_s1 = [32.0, 38.0, 48.0, 58.0, 0.65]
    res_s1 = minimize(loss_group, init_s1, method="Nelder-Mead", bounds=bounds_s1, options={"maxiter": 40, "disp": True})
    p_s1 = res_s1.x
    print(f"  Stage 1 Optimal Group Initial NO3: N0={p_s1[0]:.1f}, N1={p_s1[1]:.1f}, N2={p_s1[2]:.1f}, N3={p_s1[3]:.1f} mg/kg | Sub Ratio={p_s1[4]:.3f}")

    base_tmt_dict = {}
    for t in [9, 11, 12]:
        base_tmt_dict[t] = {"sno3_top": float(p_s1[0]), "sno3_drip": float(p_s1[0] * 0.9), "sno3_mid": float(p_s1[0] * p_s1[4]), "sno3_bot": float(p_s1[0] * p_s1[4] * 0.5), "snh4_top": 2.0}
    for t in [7, 8, 10]:
        base_tmt_dict[t] = {"sno3_top": float(p_s1[1]), "sno3_drip": float(p_s1[1] * 0.9), "sno3_mid": float(p_s1[1] * p_s1[4]), "sno3_bot": float(p_s1[1] * p_s1[4] * 0.5), "snh4_top": 2.2}
    for t in [4, 5, 6]:
        base_tmt_dict[t] = {"sno3_top": float(p_s1[2]), "sno3_drip": float(p_s1[2] * 0.9), "sno3_mid": float(p_s1[2] * p_s1[4]), "sno3_bot": float(p_s1[2] * p_s1[4] * 0.5), "snh4_top": 2.4}
    for t in [1, 2, 3]:
        base_tmt_dict[t] = {"sno3_top": float(p_s1[3]), "sno3_drip": float(p_s1[3] * 0.9), "sno3_mid": float(p_s1[3] * p_s1[4]), "sno3_bot": float(p_s1[3] * p_s1[4] * 0.5), "snh4_top": 2.5}

    # 3. Stage 2: Individual Plot-Level Fine Assimilation (12 treatments)
    print("\n[Step 3/3] Performing Per-Plot Fine Assimilation for all 12 Treatments...")
    final_inverted_dict = dict(base_tmt_dict)

    for tn in range(1, 13):
        base_p = base_tmt_dict[tn]
        
        def loss_single_plot(s_val):
            val = s_val[0]
            cur_d = dict(final_inverted_dict)
            cur_d[tn] = {
                "sno3_top": val,
                "sno3_drip": val * 0.9,
                "sno3_mid": val * p_s1[4],
                "sno3_bot": val * p_s1[4] * 0.5,
                "snh4_top": base_p["snh4_top"]
            }
            mod_l = inject_26sp_ic_lines(orig_tmx_lines, cur_d)
            tmx_path.write_text("\n".join(mod_l))
            h_cur, p_cur = run_direct_dssat_26sp(t26_dir, par_csv)
            sub_h = h_cur[h_cur["TN"] == tn]
            return np.sqrt(np.mean((sub_h["OBS_DRY_CUM"] - sub_h["SIM_DRY_CUM"]) ** 2))

        res_plot = minimize(loss_single_plot, [base_p["sno3_top"]], method="Nelder-Mead", bounds=[(10.0, 95.0)], options={"maxiter": 15})
        opt_sno3 = float(res_plot.x[0])
        final_inverted_dict[tn] = {
            "sno3_top": round(opt_sno3, 2),
            "sno3_drip": round(opt_sno3 * 0.9, 2),
            "sno3_mid": round(opt_sno3 * p_s1[4], 2),
            "sno3_bot": round(opt_sno3 * p_s1[4] * 0.5, 2),
            "snh4_top": round(base_p["snh4_top"], 2),
            "snh4_drip": round(base_p["snh4_top"] * 0.8, 2),
            "snh4_mid": 1.0,
            "snh4_bot": 0.5
        }
        print(f"  TRNO {tn:>2d} Inverted Initial SNO3: Top={opt_sno3:5.1f} mg/kg (0-4cm), Mid={opt_sno3 * p_s1[4]:5.1f} mg/kg (15-30cm)")

    # Final Execution & Table Generation
    mod_final_lines = inject_26sp_ic_lines(orig_tmx_lines, final_inverted_dict)
    tmx_path.write_text("\n".join(mod_final_lines))
    h_final, p_final = run_direct_dssat_26sp(t26_dir, par_csv)

    with open(WORK_DIR / "inverted_26sp_soil_n_profile.json", "w", encoding="utf-8") as f:
        json.dump(final_inverted_dict, f, indent=2)

    h_final.to_csv(WORK_DIR / "26sp_inverted_harvest_compare.csv", index=False)
    p_final.to_csv(WORK_DIR / "26sp_inverted_process_compare.csv", index=False)

    print("\n" + "="*110)
    print("=== 26SP Comprehensive Evaluation Metrics Before vs After Inversion ===")
    print("="*110)
    print(f"{'Variable':<12s} | {'Before Inversion (Raw Copied IC)':<34s} | {'After Inversion (Inverted True IC)':<34s} | {'Gain':>8s}")
    print(f"{'':<12s} | {'NSE':>8s} | {'RMSE':>10s} | {'R2':>9s} | {'NSE':>8s} | {'RMSE':>10s} | {'R2':>9s} |")
    print("-"*110)
    
    m_dry_b = compute_metrics(h_base["OBS_DRY_CUM"].to_numpy(float), h_base["SIM_DRY_CUM"].to_numpy(float))
    m_frs_b = compute_metrics(h_base["OBS_FRESH_CUM"].to_numpy(float), h_base["SIM_FRESH_CUM"].to_numpy(float))
    m_lai_b = compute_metrics(p_base["OBS_LAID"].to_numpy(float), p_base["SIM_LAID"].to_numpy(float))
    m_swa_b = compute_metrics(p_base["OBS_SWAD"].to_numpy(float), p_base["SIM_SWAD"].to_numpy(float))
    
    m_dry_a = compute_metrics(h_final["OBS_DRY_CUM"].to_numpy(float), h_final["SIM_DRY_CUM"].to_numpy(float))
    m_frs_a = compute_metrics(h_final["OBS_FRESH_CUM"].to_numpy(float), h_final["SIM_FRESH_CUM"].to_numpy(float))
    m_lai_a = compute_metrics(p_final["OBS_LAID"].to_numpy(float), p_final["SIM_LAID"].to_numpy(float))
    m_swa_a = compute_metrics(p_final["OBS_SWAD"].to_numpy(float), p_final["SIM_SWAD"].to_numpy(float))
    
    print(f"{'DRY_CUM':<12s} | {m_dry_b['nse']:>8.4f} | {m_dry_b['rmse']:>10.1f} | {m_dry_b['r2']:>9.4f} | {m_dry_a['nse']:>8.4f} | {m_dry_a['rmse']:>10.1f} | {m_dry_a['r2']:>9.4f} | {m_dry_a['nse'] - m_dry_b['nse']:>+7.4f}")
    print(f"{'FRESH_CUM':<12s} | {m_frs_b['nse']:>8.4f} | {m_frs_b['rmse']:>10.1f} | {m_frs_b['r2']:>9.4f} | {m_frs_a['nse']:>8.4f} | {m_frs_a['rmse']:>10.1f} | {m_frs_a['r2']:>9.4f} | {m_frs_a['nse'] - m_frs_b['nse']:>+7.4f}")
    print(f"{'LAID':<12s} | {m_lai_b['nse']:>8.4f} | {m_lai_b['rmse']:>10.3f} | {m_lai_b['r2']:>9.4f} | {m_lai_a['nse']:>8.4f} | {m_lai_a['rmse']:>10.3f} | {m_lai_a['r2']:>9.4f} | {m_lai_a['nse'] - m_lai_b['nse']:>+7.4f}")
    print(f"{'SWAD':<12s} | {m_swa_b['nse']:>8.4f} | {m_swa_b['rmse']:>10.1f} | {m_swa_b['r2']:>9.4f} | {m_swa_a['nse']:>8.4f} | {m_swa_a['rmse']:>10.1f} | {m_swa_a['r2']:>9.4f} | {m_swa_a['nse'] - m_swa_b['nse']:>+7.4f}")
    print("="*110)

    print("\n=== 26SP All 12 Treatments Terminal Yields Audit (Before vs After Inversion) ===")
    last_b = h_base.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
    last_a = h_final.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
    
    tlabels = {
        1: "W3N3", 2: "W2N3", 3: "W1N3",
        4: "W3N2", 5: "W2N2", 6: "W1N2",
        7: "W3N1", 8: "W2N1", 9: "W3N0",
        10: "W1N1", 11: "W2N0", 12: "W1N0"
    }
    print(f"{'TRNO':<4s} | {'Label':<6s} | {'Obs Dry':>8s} | {'Before Inversion':>17s} | {'After Inversion':>17s} | {'Inverted Top SNO3':>18s} | {'Error Reduction':>15s}")
    print("-"*105)
    for tn in range(1, 13):
        obs = last_a[last_a["TN"] == tn]["OBS_DRY_CUM"].values[0]
        sim_b = last_b[last_b["TN"] == tn]["SIM_DRY_CUM"].values[0]
        sim_a = last_a[last_a["TN"] == tn]["SIM_DRY_CUM"].values[0]
        bias_b = sim_b - obs
        bias_a = sim_a - obs
        imp = abs(bias_b) - abs(bias_a)
        imp_str = f"+{imp:6.1f} kg" if imp > 0 else f"{imp:6.1f} kg"
        top_n = final_inverted_dict[tn]["sno3_top"]
        print(f"{tn:>4d} | {tlabels[tn]:<6s} | {obs:>8.1f} | {sim_b:>8.1f} ({bias_b:>+6.1f}) | {sim_a:>8.1f} ({bias_a:>+6.1f}) | {top_n:>14.1f} mg/kg | {imp_str:>15s}")
    print("="*105)


if __name__ == "__main__":
    main()
