"""Scientific Inversion of 26SP Initial Soil Nitrogen Constrained in the Neighborhood of 25FA Measured Data:

Uses 25FA pre-planting outlier-filtered soil nitrate & ammonium measurements
(from data/user/ref/26SP和25FA硝态氮铵态氮参考.xlsx) as the prior baseline and confidence bounds.
Employs the optimal 10-layer soil discretization (Scheme 5: [2, 4, 15, 30, 40, 60, 80, 100, 140, 180] cm)
and calibrated genetic parameters (Member #26) to invert the true 26SP initial mineral nitrogen profile.
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
WORK_DIR = ROOT / "workspace/runs/inverse_26sp_soil_n_near_25fa_20260824"
EXCEL_PATH = ROOT / "data/user/ref/26SP和25FA硝态氮铵态氮参考.xlsx"

if WORK_DIR.exists():
    shutil.rmtree(WORK_DIR)
WORK_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "tools/analysis"))
sys.path.insert(0, str(ROOT / "tools/experiments"))
from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare, build_season_process_compare, compute_metrics
from exp_ultra_thin_topsoil_schemes_20260823 import build_soil_and_ic_bundles

LAYER_DEPTHS_10L = [2, 4, 15, 30, 40, 60, 80, 100, 140, 180]


def load_25fa_reference_priors() -> dict[int, dict]:
    """Load 25FA clean outlier-removed data and repeat bounds for all 12 plots."""
    df_clean = pd.read_excel(EXCEL_PATH, sheet_name="剔异常平均版")
    df_raw = pd.read_excel(EXCEL_PATH, sheet_name="三重复与判定")
    
    priors = {}
    for plot in range(1, 13):
        sub_c = df_clean[df_clean["小区"] == plot]
        sub_r = df_raw[df_raw["小区"] == plot]
        
        plot_dict = {
            "plot": plot,
            "trt": sub_c.iloc[0]["末期"],
            "irr": sub_c.iloc[0]["灌水"],
            "fert": sub_c.iloc[0]["施氮"],
        }
        
        for idx in range(len(sub_c)):
            rc = sub_c.iloc[idx]
            rr = sub_r.iloc[idx]
            layer = rc["土层"]
            
            # NO3
            no3_mean = float(rc["硝态氮纯氮-剔异常平均"])
            no3_rep = [float(rr["硝态氮纯氮-R1"]), float(rr["硝态氮纯氮-R2"]), float(rr["硝态氮纯氮-R3"])]
            if pd.notna(rr["硝态氮异常重复"]):
                no3_rep.pop(int(rr["硝态氮异常重复"]) - 1)
            no3_min, no3_max = min(no3_rep), max(no3_rep)
            
            # NH4
            nh4_mean = float(rc["铵态氮-剔异常平均"])
            nh4_rep = [float(rr["铵态氮-R1"]), float(rr["铵态氮-R2"]), float(rr["铵态氮-R3"])]
            if pd.notna(rr["铵态氮异常重复"]):
                nh4_rep.pop(int(rr["铵态氮异常重复"]) - 1)
            nh4_min, nh4_max = min(nh4_rep), max(nh4_rep)
            
            key_prefix = "l1" if layer == "0-20" else ("l2" if layer == "20-40" else "l3")
            plot_dict[f"{key_prefix}_no3_mean"] = no3_mean
            plot_dict[f"{key_prefix}_no3_min"] = no3_min
            plot_dict[f"{key_prefix}_no3_max"] = no3_max
            plot_dict[f"{key_prefix}_no3_sd"] = float(np.std(no3_rep)) if len(no3_rep) > 1 else 1.0
            
            plot_dict[f"{key_prefix}_nh4_mean"] = nh4_mean
            plot_dict[f"{key_prefix}_nh4_min"] = nh4_min
            plot_dict[f"{key_prefix}_nh4_max"] = nh4_max
            plot_dict[f"{key_prefix}_nh4_sd"] = float(np.std(nh4_rep)) if len(nh4_rep) > 1 else 0.5
            
        priors[plot] = plot_dict
    return priors


def inject_10layer_ic_from_dict(lines: list[str], tmt_profiles: dict[int, dict]) -> list[str]:
    """Inject 10-layer SNO3 and SNH4 into XXQL2601.TMX *INITIAL CONDITIONS block."""
    new_lines = []
    in_ic = False
    
    for l in lines:
        if "*INITIAL CONDITIONS" in l:
            in_ic = True
            new_lines.append(l)
        elif in_ic and l.startswith("*"):
            in_ic = False
            new_lines.append(l)
        elif in_ic:
            tokens = l.split()
            if l.startswith("@C") or len(tokens) >= 10:
                new_lines.append(l)
            elif len(tokens) >= 5 and tokens[0].isdigit() and tokens[1].isdigit():
                c_id = int(tokens[0])
                depth = int(tokens[1])
                sh2o = float(tokens[2])
                snh4 = float(tokens[3])
                sno3 = float(tokens[4])
                if c_id in tmt_profiles:
                    p = tmt_profiles[c_id]
                    if depth == 2:
                        sno3 = p.get("sno3_2", sno3)
                        snh4 = p.get("snh4_2", snh4)
                    elif depth == 4:
                        sno3 = p.get("sno3_4", sno3)
                        snh4 = p.get("snh4_4", snh4)
                    elif depth == 15:
                        sno3 = p.get("sno3_15", sno3)
                        snh4 = p.get("snh4_15", snh4)
                    elif depth == 30:
                        sno3 = p.get("sno3_30", sno3)
                        snh4 = p.get("snh4_30", snh4)
                    elif depth == 40:
                        sno3 = p.get("sno3_40", sno3)
                        snh4 = p.get("snh4_40", snh4)
                    elif depth == 60:
                        sno3 = p.get("sno3_60", sno3)
                        snh4 = p.get("snh4_60", snh4)
                    elif depth == 80:
                        sno3 = p.get("sno3_80", 1.0)
                        snh4 = p.get("snh4_80", 0.5)
                    elif depth == 100:
                        sno3 = p.get("sno3_100", 1.0)
                        snh4 = p.get("snh4_100", 0.5)
                    elif depth == 140:
                        sno3 = p.get("sno3_140", 1.0)
                        snh4 = p.get("snh4_140", 0.5)
                    elif depth == 180:
                        sno3 = p.get("sno3_180", 1.0)
                        snh4 = p.get("snh4_180", 0.5)
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


def map_prior_to_10l_profile(prior: dict, k_l1: float = 1.0, k_l2: float = 1.0, k_l3: float = 1.0, g_surf: float = 1.0, k_nh4: float = 1.0) -> dict:
    """Map 3-layer 25FA prior measurements to 10-layer profile with adjustment factors."""
    no3_1 = max(1.0, prior["l1_no3_mean"] * k_l1)
    no3_2 = max(1.0, prior["l2_no3_mean"] * k_l2)
    no3_3 = max(1.0, prior["l3_no3_mean"] * k_l3)
    
    nh4_1 = max(0.5, prior["l1_nh4_mean"] * k_nh4)
    nh4_2 = max(0.5, prior["l2_nh4_mean"] * k_nh4)
    nh4_3 = max(0.5, prior["l3_nh4_mean"] * k_nh4)
    
    return {
        "sno3_2": round(no3_1 * g_surf, 2),
        "sno3_4": round(no3_1 * g_surf, 2),
        "sno3_15": round(no3_1, 2),
        "sno3_30": round(no3_2, 2),
        "sno3_40": round(no3_2, 2),
        "sno3_60": round(no3_3, 2),
        "sno3_80": 1.0,
        "sno3_100": 1.0,
        "sno3_140": 1.0,
        "sno3_180": 1.0,
        "snh4_2": round(nh4_1 * g_surf, 2),
        "snh4_4": round(nh4_1 * g_surf, 2),
        "snh4_15": round(nh4_1, 2),
        "snh4_30": round(nh4_2, 2),
        "snh4_40": round(nh4_2, 2),
        "snh4_60": round(nh4_3, 2),
        "snh4_80": 0.5,
        "snh4_100": 0.5,
        "snh4_140": 0.5,
        "snh4_180": 0.5,
    }


def main():
    print("=" * 115)
    print("=== 26SP Initial Soil Nitrogen Inversion Constrained Around 25FA Clean Reference Data ===")
    print("=" * 115)
    
    # 1. Load 25FA Reference Priors
    priors = load_25fa_reference_priors()
    print(f"\n[Step 1/4] Loaded 25FA pre-planting outlier-removed reference data for all 12 plots from Excel.")
    for p in range(1, 13):
        pd_info = priors[p]
        print(f"  Plot {p:>2d} ({pd_info['trt']}, {pd_info['irr']}{pd_info['fert']}): "
              f"L1(0-20) NO3={pd_info['l1_no3_mean']:5.2f} [{pd_info['l1_no3_min']:5.2f}, {pd_info['l1_no3_max']:5.2f}], "
              f"L2(20-40) NO3={pd_info['l2_no3_mean']:5.2f} [{pd_info['l2_no3_min']:5.2f}, {pd_info['l2_no3_max']:5.2f}], "
              f"L3(40-60) NO3={pd_info['l3_no3_mean']:5.2f} [{pd_info['l3_no3_min']:5.2f}, {pd_info['l3_no3_max']:5.2f}]")

    # 2. Setup 10-layer sandbox
    t26_dir = WORK_DIR / "exp26"
    t26_dir.mkdir(parents=True, exist_ok=True)
    build_soil_and_ic_bundles(t26_dir, "26SP", LAYER_DEPTHS_10L)
    
    par_csv = WORK_DIR / "params.csv"
    shutil.copy2(BASE_PAR, par_csv)
    
    tmx_path = t26_dir / "XXQL2601.TMX"
    orig_tmx_lines = tmx_path.read_text().splitlines()

    # 3. Evaluate Direct 25FA Baseline (uncalibrated reference mapped directly to 10 layers)
    print("\n[Step 2/4] Evaluating Uncalibrated Baseline (25FA clean data directly mapped to 10-layer grid)...")
    base_profiles = {p: map_prior_to_10l_profile(priors[p], 1.0, 1.0, 1.0, 1.0, 1.0) for p in range(1, 13)}
    base_lines = inject_10layer_ic_from_dict(orig_tmx_lines, base_profiles)
    tmx_path.write_text("\n".join(base_lines))
    
    h_base, p_base = run_direct_dssat_26sp(t26_dir, par_csv)
    m_dry_base = compute_metrics(h_base["OBS_DRY_CUM"].to_numpy(float), h_base["SIM_DRY_CUM"].to_numpy(float))
    m_lai_base = compute_metrics(p_base["OBS_LAID"].to_numpy(float), p_base["SIM_LAID"].to_numpy(float))
    m_swa_base = compute_metrics(p_base["OBS_SWAD"].to_numpy(float), p_base["SIM_SWAD"].to_numpy(float))
    print(f"  Direct 25FA Baseline Metrics: DRY NSE = {m_dry_base['nse']:.4f}, RMSE = {m_dry_base['rmse']:.1f} kg/ha | LAID NSE = {m_lai_base['nse']:.4f} | SWAD NSE = {m_swa_base['nse']:.4f}")

    # 4. Stage 1: Macro Shift & Surface Gradient Inversion (Macro Search)
    print("\n[Step 3/4] Optimizing Macro Inter-Season Shift & Surface Gradient within 25FA Neighborhood...")
    
    def loss_macro(params):
        k_top, k_sub, g_surf, k_nh4 = params
        cur_prof = {}
        for p in range(1, 13):
            cur_prof[p] = map_prior_to_10l_profile(priors[p], k_l1=k_top, k_l2=k_sub, k_l3=k_sub, g_surf=g_surf, k_nh4=k_nh4)
        
        mod_l = inject_10layer_ic_from_dict(orig_tmx_lines, cur_prof)
        tmx_path.write_text("\n".join(mod_l))
        try:
            h_s, p_s = run_direct_dssat_26sp(t26_dir, par_csv)
            rmse_dry = np.sqrt(np.mean((h_s["OBS_DRY_CUM"] - h_s["SIM_DRY_CUM"]) ** 2))
            rmse_lai = np.sqrt(np.mean((p_s["OBS_LAID"] - p_s["SIM_LAID"]) ** 2))
            # Regularization penalty to stay close to 1.0 (25FA reference)
            reg = 50.0 * ((k_top - 1.0)**2 + (k_sub - 1.0)**2 + (g_surf - 1.0)**2 + (k_nh4 - 1.0)**2)
            return rmse_dry + 150.0 * rmse_lai + reg
        except Exception:
            return 1e6

    # Macro search bounds strictly around 1.0 ([0.70, 1.40])
    bounds_macro = [(0.70, 1.40), (0.65, 1.35), (0.80, 1.25), (0.80, 1.25)]
    init_macro = [1.0, 1.0, 1.0, 1.0]
    res_macro = minimize(loss_macro, init_macro, method="Nelder-Mead", bounds=bounds_macro, options={"maxiter": 35, "disp": True})
    opt_k_top, opt_k_sub, opt_g_surf, opt_k_nh4 = res_macro.x
    print(f"  Optimal Macro Shift Factors: Topsoil NO3 k={opt_k_top:.3f}, Subsoil NO3 k={opt_k_sub:.3f}, Surface Grad g={opt_g_surf:.3f}, NH4 k={opt_k_nh4:.3f}")

    macro_profiles = {p: map_prior_to_10l_profile(priors[p], opt_k_top, opt_k_sub, opt_k_sub, opt_g_surf, opt_k_nh4) for p in range(1, 13)}

    # 5. Stage 2: Plot-Level Bounded Fine Assimilation
    print("\n[Step 4/4] Performing Per-Plot Constrained Neighborhood Assimilation for all 12 Treatments...")
    final_inverted_profiles = dict(macro_profiles)
    
    for plot in range(1, 13):
        pr = priors[plot]
        base_p = macro_profiles[plot]
        
        # Determine strict confidence bounds from 25FA repeats and clean data
        # Lower bound: max(1.0, min(pr['l1_no3_min'], pr['l1_no3_mean'] * 0.65))
        # Upper bound: max(pr['l1_no3_max'], pr['l1_no3_mean'] * 1.35)
        l1_min = max(1.0, min(pr["l1_no3_min"] * 0.75, pr["l1_no3_mean"] * 0.65))
        l1_max = max(pr["l1_no3_max"] * 1.25, pr["l1_no3_mean"] * 1.35)
        
        l2_min = max(1.0, min(pr["l2_no3_min"] * 0.75, pr["l2_no3_mean"] * 0.65))
        l2_max = max(pr["l2_no3_max"] * 1.25, pr["l2_no3_mean"] * 1.35)
        
        def loss_plot(p_vars):
            s_top, s_mid = p_vars
            cur_p = dict(final_inverted_profiles)
            cur_p[plot] = {
                "sno3_2": round(s_top * opt_g_surf, 2),
                "sno3_4": round(s_top * opt_g_surf, 2),
                "sno3_15": round(s_top, 2),
                "sno3_30": round(s_mid, 2),
                "sno3_40": round(s_mid, 2),
                "sno3_60": round(s_mid * (pr["l3_no3_mean"] / (pr["l2_no3_mean"] + 1e-4)), 2),
                "sno3_80": 1.0,
                "sno3_100": 1.0,
                "sno3_140": 1.0,
                "sno3_180": 1.0,
                "snh4_2": base_p["snh4_2"],
                "snh4_4": base_p["snh4_4"],
                "snh4_15": base_p["snh4_15"],
                "snh4_30": base_p["snh4_30"],
                "snh4_40": base_p["snh4_40"],
                "snh4_60": base_p["snh4_60"],
                "snh4_80": 0.5,
                "snh4_100": 0.5,
                "snh4_140": 0.5,
                "snh4_180": 0.5,
            }
            mod_l = inject_10layer_ic_from_dict(orig_tmx_lines, cur_p)
            tmx_path.write_text("\n".join(mod_l))
            h_cur, p_cur = run_direct_dssat_26sp(t26_dir, par_csv)
            sub_h = h_cur[h_cur["TN"] == plot]
            rmse_h = np.sqrt(np.mean((sub_h["OBS_DRY_CUM"] - sub_h["SIM_DRY_CUM"]) ** 2))
            
            # Prior regularization
            reg_top = 10.0 * ((s_top - pr["l1_no3_mean"] * opt_k_top) / (pr["l1_no3_sd"] + 1.0)) ** 2
            reg_mid = 10.0 * ((s_mid - pr["l2_no3_mean"] * opt_k_sub) / (pr["l2_no3_sd"] + 1.0)) ** 2
            return rmse_h + reg_top + reg_mid

        init_plot = [base_p["sno3_15"], base_p["sno3_30"]]
        res_plot = minimize(loss_plot, init_plot, method="Nelder-Mead", bounds=[(l1_min, l1_max), (l2_min, l2_max)], options={"maxiter": 20})
        opt_s_top, opt_s_mid = res_plot.x
        
        final_inverted_profiles[plot] = {
            "sno3_2": round(opt_s_top * opt_g_surf, 2),
            "sno3_4": round(opt_s_top * opt_g_surf, 2),
            "sno3_15": round(opt_s_top, 2),
            "sno3_30": round(opt_s_mid, 2),
            "sno3_40": round(opt_s_mid, 2),
            "sno3_60": round(opt_s_mid * (pr["l3_no3_mean"] / (pr["l2_no3_mean"] + 1e-4)), 2),
            "sno3_80": 1.0,
            "sno3_100": 1.0,
            "sno3_140": 1.0,
            "sno3_180": 1.0,
            "snh4_2": base_p["snh4_2"],
            "snh4_4": base_p["snh4_4"],
            "snh4_15": base_p["snh4_15"],
            "snh4_30": base_p["snh4_30"],
            "snh4_40": base_p["snh4_40"],
            "snh4_60": base_p["snh4_60"],
            "snh4_80": 0.5,
            "snh4_100": 0.5,
            "snh4_140": 0.5,
            "snh4_180": 0.5,
        }
        print(f"  Plot {plot:>2d} ({pr['trt']}, {pr['irr']}{pr['fert']}) Inverted NO3: "
              f"0-4cm={final_inverted_profiles[plot]['sno3_2']:5.2f} (25FA ref={pr['l1_no3_mean']:5.2f}), "
              f"15-30cm={final_inverted_profiles[plot]['sno3_30']:5.2f} (25FA ref={pr['l2_no3_mean']:5.2f}), "
              f"40-60cm={final_inverted_profiles[plot]['sno3_60']:5.2f} (25FA ref={pr['l3_no3_mean']:5.2f})")

    # Final Verification & Output Generation
    final_lines = inject_10layer_ic_from_dict(orig_tmx_lines, final_inverted_profiles)
    tmx_path.write_text("\n".join(final_lines))
    h_final, p_final = run_direct_dssat_26sp(t26_dir, par_csv)

    # Save artifacts
    with open(WORK_DIR / "inverted_26sp_soil_n_near_25fa_profile.json", "w", encoding="utf-8") as f:
        json.dump(final_inverted_profiles, f, indent=2)

    h_final.to_csv(WORK_DIR / "26sp_inverted_near_25fa_harvest_compare.csv", index=False)
    p_final.to_csv(WORK_DIR / "26sp_inverted_near_25fa_process_compare.csv", index=False)

    print("\n" + "=" * 115)
    print("=== 26SP Evaluation Metrics Before vs After Constrained Inversion (25FA Neighborhood) ===")
    print("=" * 115)
    print(f"{'Variable':<12s} | {'Before Inversion (Raw 25FA Direct)':<34s} | {'After Inversion (25FA Constrained)':<34s} | {'Gain':>8s}")
    print(f"{'':<12s} | {'NSE':>8s} | {'RMSE':>10s} | {'R2':>9s} | {'NSE':>8s} | {'RMSE':>10s} | {'R2':>9s} |")
    print("-" * 115)
    
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
    print("=" * 115)

    print("\n=== 26SP All 12 Treatments Terminal Yields Audit ===")
    last_b = h_base.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
    last_a = h_final.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
    
    tlabels = {
        1: "W3N3", 2: "W2N3", 3: "W1N3",
        4: "W3N2", 5: "W2N2", 6: "W1N2",
        7: "W3N1", 8: "W2N1", 9: "W3N0",
        10: "W1N1", 11: "W2N0", 12: "W1N0"
    }
    print(f"{'TRNO':<4s} | {'Label':<6s} | {'Obs Dry':>8s} | {'Raw 25FA Sim':>17s} | {'Inverted 26SP':>17s} | {'25FA Top SNO3':>14s} | {'26SP Top SNO3':>14s} | {'Bias Change':>13s}")
    print("-" * 115)
    for tn in range(1, 13):
        obs = last_a[last_a["TN"] == tn]["OBS_DRY_CUM"].values[0]
        sim_b = last_b[last_b["TN"] == tn]["SIM_DRY_CUM"].values[0]
        sim_a = last_a[last_a["TN"] == tn]["SIM_DRY_CUM"].values[0]
        bias_b = sim_b - obs
        bias_a = sim_a - obs
        imp = abs(bias_b) - abs(bias_a)
        imp_str = f"{imp:+6.1f} kg"
        ref_top = priors[tn]["l1_no3_mean"]
        top_n = final_inverted_profiles[tn]["sno3_2"]
        print(f"{tn:>4d} | {tlabels[tn]:<6s} | {obs:>8.1f} | {sim_b:>8.1f} ({bias_b:>+6.1f}) | {sim_a:>8.1f} ({bias_a:>+6.1f}) | {ref_top:>10.2f} mg/kg | {top_n:>10.2f} mg/kg | {imp_str:>13s}")
    print("=" * 115)


if __name__ == "__main__":
    main()
