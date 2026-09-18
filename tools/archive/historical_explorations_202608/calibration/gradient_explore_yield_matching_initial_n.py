#!/usr/bin/env python3
"""Yield-Matching Gradient Exploration for 25SP Initial Soil Nitrogen (0-60cm SNO3 & SNH4).

Objective:
Directly minimize |Simulated_Fresh_Yield - Observed_Fresh_Yield| for each of the 10 treatments in 25SP:
TN 2 (W3N3), TN 3 (W3N2), TN 4 (W3N1), TN 5 (W3N0),
TN 9 (W2N0), TN 10 (W1N3), TN 11 (W1N2), TN 12 (W1N1), TN 13 (W1N0), TN 14 (CKN2).

Performs a dense gradient scan (s in [0.05, 8.00]) to identify the optimal scale factor
that brings simulated yield closest to observed yield for every treatment.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PYTHON = sys.executable

RUN_DIR_BASE = PROJECT_ROOT / "workspace/runs/e02_small_v41_nresp10x_scheme4_60x3_20260830/best_member_13_two_season_deterministic_20260830"
BASE_PARAMS_PATH = RUN_DIR_BASE / "best_member_13_params.csv"
OUT_DIR = PROJECT_ROOT / "workspace/reports/yield_matching_initial_n_exploration_20260830"
OUT_DIR.mkdir(parents=True, exist_ok=True)

from tools.calibration.explore_soil_layering_for_nitrogen_response import patch_filex_mesol
from src.reporting.analyze_results import _read_tmt_harvest_obs

TREATMENTS_25SP = [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]


def parse_original_25sp_ic(tmx_path: Path):
    text = tmx_path.read_text(encoding="utf-8", errors="ignore")
    ic_match = re.search(r"\*INITIAL CONDITIONS.*?\n(.*?)(?:\n\*[A-Z]|\Z)", text, re.DOTALL)
    ic_data = {}
    if ic_match:
        current_ic = None
        for line in ic_match.group(1).splitlines():
            if line.startswith("@C") or not line.strip() or line.strip().startswith("*"):
                continue
            parts = line.split()
            if len(parts) >= 10:
                try: current_ic = int(parts[0])
                except: pass
            elif len(parts) >= 4 and current_ic is not None:
                floats = re.findall(r"[-+]?(?:\d*\.\d+|\d+)", line)
                if len(floats) >= 5:
                    c = int(floats[0])
                    icbl = float(floats[1])
                    sh2o = float(floats[2])
                    snh4 = float(floats[3])
                    sno3 = float(floats[4])
                    ic_data.setdefault(c, []).append({
                        "icbl": icbl, "sh2o": sh2o, "snh4": snh4, "sno3": sno3
                    })
    return ic_data


def write_scaled_filex_25sp(orig_tmx_path: Path, target_tmx_path: Path, scale_dict: dict[int, float], orig_ic_data: dict[int, list[dict]]):
    lines = orig_tmx_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    new_lines = []
    in_ic = False
    skip_current = False
    
    for l in lines:
        if l.startswith("*INITIAL CONDITIONS"):
            new_lines.append(l)
            in_ic = True
            continue
        elif l.startswith("*") and in_ic:
            in_ic = False
            new_lines.append(l)
            continue
            
        if in_ic:
            if l.startswith("@C") and "PCR" in l:
                new_lines.append(l)
                skip_current = False
            elif l.startswith("@C") and "ICBL" in l:
                new_lines.append(l)
            elif l.strip() and len(l.split()) >= 10:
                c = int(l.split()[0])
                new_lines.append(l)
                if c in scale_dict and c in orig_ic_data:
                    s_factor = scale_dict[c]
                    for layer in orig_ic_data[c]:
                        d = layer["icbl"]
                        sh2o = layer["sh2o"]
                        if d <= 60.0:
                            snh4 = max(0.1, layer["snh4"] * s_factor)
                            sno3 = max(0.2, layer["sno3"] * s_factor)
                        else:
                            snh4 = layer["snh4"]
                            sno3 = layer["sno3"]
                        new_lines.append(f" {c:2d} {d:5.0f} {sh2o:5.3f} {snh4:5.1f} {sno3:5.1f}")
                    skip_current = True
            elif l.strip() and len(l.split()) <= 6:
                if not skip_current:
                    new_lines.append(l)
            else:
                new_lines.append(l)
        else:
            new_lines.append(l)
            
    target_tmx_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    patch_filex_mesol(target_tmx_path)


def run_candidate_scale_sweep(work_dir: Path) -> pd.DataFrame:
    orig_tmx = PROJECT_ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830/XXQL2501.TMX"
    orig_ic = parse_original_25sp_ic(orig_tmx)
    obs_dict = _read_tmt_harvest_obs(PROJECT_ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830/XXQL2501.TMT")
    base_design_tpl = json.loads((PROJECT_ROOT / "configs/runs/e02_small_v41_nresp10x_scheme4_60x3_20260830.json").read_text())
    
    # Dense scan ladder
    candidate_scales = [
        0.05, 0.10, 0.20, 0.35, 0.50, 0.70, 1.00, 1.30, 1.60, 2.00, 2.50, 3.00, 4.00, 5.00, 6.00, 7.00, 8.00
    ]
    
    sweep_records = []
    print(f"==================== RUNNING DENSE SCALE SWEEP ({len(candidate_scales)} LEVELS) ====================")
    
    for s in candidate_scales:
        step_dir = work_dir / f"sweep_s_{s:.2f}"
        step_dir.mkdir(parents=True, exist_ok=True)
        bdir25 = step_dir / "25SP_bundle"
        bdir26 = step_dir / "26SP_bundle"
        if not bdir25.exists(): shutil.copytree(PROJECT_ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830", bdir25)
        if not bdir26.exists(): shutil.copytree(PROJECT_ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830", bdir26)
        
        filex25 = next(bdir25.glob("*.TMX"))
        filex26 = next(bdir26.glob("*.TMX"))
        write_scaled_filex_25sp(orig_tmx, filex25, {tn: s for tn in TREATMENTS_25SP}, orig_ic)
        patch_filex_mesol(filex25)
        patch_filex_mesol(filex26)
        
        base_design = dict(base_design_tpl)
        base_design["design_id"] = f"sweep_{s:.2f}"
        base_design["seasons"] = [
            {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(bdir25.resolve()), "role": "calibration", "treatments": TREATMENTS_25SP},
            {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(bdir26.resolve()), "role": "calibration", "treatments": list(range(1, 13))},
        ]
        base_design["diagnostic_only"] = {"25SP": [], "26SP": []}
        
        df_file = step_dir / "design.json"
        df_file.write_text(json.dumps(base_design, indent=2))
        param_csv = step_dir / "params.csv"
        shutil.copy2(BASE_PARAMS_PATH, param_csv)
        
        cmd = [
            PYTHON, str((PROJECT_ROOT / "src/calibration/run_multiseason.py").resolve()),
            "--design", str(df_file.resolve()),
            "--param-csv", str(param_csv.resolve()),
            "--prefix", "det",
            "--harvest-var", "CHPDT",
            "--keep-nitrogen-outputs",
        ]
        subprocess.run(cmd, cwd=str(step_dir.resolve()), capture_output=True, text=True)
        
        pest_h = step_dir / "_seasons/25SP/PestHarvest.OUT"
        if not pest_h.exists(): continue
        
        lines = pest_h.read_text().splitlines()
        for l in lines:
            parts = l.split()
            d = {}
            for i in range(0, len(parts)-1, 2):
                d[parts[i].strip("@")] = parts[i+1]
            if "HNO" in d and int(float(d["HNO"])) == 10 and "TN" in d:
                tn = int(float(d["TN"]))
                if tn in TREATMENTS_25SP:
                    sim_f = float(d["CHFPWS"])
                    sim_d = float(d["CHPDTS"])
                    obs_f = obs_dict[tn][-1]["OBS_FRESH_CUM"]
                    obs_d = obs_dict[tn][-1]["OBS_DRY_CUM"]
                    sweep_records.append({
                        "scale": s, "TN": tn,
                        "SIM_Fresh": sim_f, "OBS_Fresh": obs_f, "Fresh_Diff": abs(sim_f - obs_f),
                        "SIM_Dry": sim_d, "OBS_Dry": obs_d, "Dry_Diff": abs(sim_d - obs_d),
                    })
        print(f"  Completed scale s={s:5.2f}")
        
    df_sweep = pd.DataFrame(sweep_records)
    df_sweep.to_csv(work_dir / "dense_scale_sweep_raw.csv", index=False)
    return df_sweep


def select_best_yield_matching_scales(df_sweep: pd.DataFrame) -> dict[int, float]:
    """For each treatment, pick the scale factor that minimizes |SIM_Fresh - OBS_Fresh|."""
    best_scales = {}
    print("\n==================== BEST YIELD-MATCHING SCALE PER TREATMENT ====================")
    for tn in TREATMENTS_25SP:
        sub = df_sweep[df_sweep["TN"] == tn]
        if sub.empty:
            best_scales[tn] = 1.0
            continue
        best_row = sub.loc[sub["Fresh_Diff"].idxmin()]
        best_s = float(best_row["scale"])
        best_scales[tn] = best_s
        print(f"TN {tn:2d}: Best scale s={best_s:5.2f} -> Sim Fresh={best_row['SIM_Fresh']:7.1f} | Obs Fresh={best_row['OBS_Fresh']:7.1f} | Error={best_row['SIM_Fresh'] - best_row['OBS_Fresh']:+7.1f} kg/ha (PBIAS: {100.0*(best_row['SIM_Fresh']-best_row['OBS_Fresh'])/best_row['OBS_Fresh']:+.2f}%)")
    return best_scales


def replay_and_generate_final_report(optimal_scales: dict[int, float], work_dir: Path):
    print("\n==================== REPLAYING FULL 22-TREATMENT RUN WITH YIELD-MATCHED SCALES ====================")
    final_dir = work_dir / "yield_matched_final_replay"
    final_dir.mkdir(parents=True, exist_ok=True)
    
    bdir25 = final_dir / "25SP_bundle"
    bdir26 = final_dir / "26SP_bundle"
    if bdir25.exists(): shutil.rmtree(bdir25)
    if bdir26.exists(): shutil.rmtree(bdir26)
    shutil.copytree(PROJECT_ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830", bdir25)
    shutil.copytree(PROJECT_ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830", bdir26)
    
    orig_tmx = PROJECT_ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830/XXQL2501.TMX"
    orig_ic = parse_original_25sp_ic(orig_tmx)
    filex25 = next(bdir25.glob("*.TMX"))
    filex26 = next(bdir26.glob("*.TMX"))
    write_scaled_filex_25sp(orig_tmx, filex25, optimal_scales, orig_ic)
    patch_filex_mesol(filex25)
    patch_filex_mesol(filex26)
    
    base_design_tpl = json.loads((PROJECT_ROOT / "configs/runs/e02_small_v41_nresp10x_scheme4_60x3_20260830.json").read_text())
    base_design = dict(base_design_tpl)
    base_design["design_id"] = "yield_matched_replay"
    base_design["seasons"] = [
        {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(bdir25.resolve()), "role": "calibration", "treatments": TREATMENTS_25SP},
        {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(bdir26.resolve()), "role": "calibration", "treatments": list(range(1, 13))},
    ]
    base_design["diagnostic_only"] = {"25SP": [], "26SP": []}
    
    df_file = final_dir / "design.json"
    df_file.write_text(json.dumps(base_design, indent=2))
    param_csv = final_dir / "params.csv"
    shutil.copy2(BASE_PARAMS_PATH, param_csv)
    
    cmd = [
        PYTHON, str((PROJECT_ROOT / "src/calibration/run_multiseason.py").resolve()),
        "--design", str(df_file.resolve()),
        "--param-csv", str(param_csv.resolve()),
        "--prefix", "det_matched",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    subprocess.run(cmd, cwd=str(final_dir.resolve()), capture_output=True, text=True)
    
    from src.reporting.analyze_results import deterministic_harvest_compare, deterministic_process_compare
    for sid, fx, tmts in [("25SP", filex25, TREATMENTS_25SP), ("26SP", filex26, list(range(1,13)))]:
        sdir = final_dir / "_seasons" / sid
        sdir.mkdir(parents=True, exist_ok=True)
        batch = sdir / "analysis_batch.v48"
        batch.write_text("\n".join(f"{fx.resolve()} {int(tn)} 1 0 0 0" for tn in tmts) + "\n", encoding="utf-8")
        deterministic_harvest_compare(sid, str(batch), run_dir=str(sdir))
        deterministic_process_compare(sid, str(batch), var_names=["LAID", "LWAD", "SWAD", "CHTD"], run_dir=str(sdir))
        
    h25 = pd.read_csv(final_dir / "_seasons/25SP/25SP_deterministic_harvest_compare.csv")
    p25 = pd.read_csv(final_dir / "_seasons/25SP/25SP_deterministic_process_compare.csv")
    
    m25 = pd.read_csv(PROJECT_ROOT / "configs/runs/e02_mapping_26sp_w2_w1_20260830.csv")
    m25_sub = m25[m25["season_id"] == "25SP"].set_index("treatment")
    inverted_ic_data = parse_original_25sp_ic(filex25)
    
    summary_rows = []
    max25 = h25["HNO"].max()
    t25_map = h25[h25["HNO"] == max25].set_index("TN")
    
    for tn in TREATMENTS_25SP:
        s_val = optimal_scales[tn]
        layers = inverted_ic_data.get(tn, [])
        prev_d = 0.0
        tot_no3_kg = 0.0
        tot_nh4_kg = 0.0
        sno3_strs = []
        snh4_strs = []
        for l in layers:
            thick = l["icbl"] - prev_d
            prev_d = l["icbl"]
            bd = 1.45
            tot_no3_kg += l["sno3"] * bd * thick * 0.1
            tot_nh4_kg += l["snh4"] * bd * thick * 0.1
            sno3_strs.append(f"{l['icbl']:.0f}cm:{l['sno3']:.1f}")
            snh4_strs.append(f"{l['icbl']:.0f}cm:{l['snh4']:.1f}")
            
        w = m25_sub.loc[tn, "water_level"]
        n = m25_sub.loc[tn, "nitrogen_level"]
        n_kg = m25_sub.loc[tn, "nitrogen_kg_ha"]
        role = m25_sub.loc[tn, "objective_role"]
        
        obs_f = float(t25_map.loc[tn, "OBS_FRESH_CUM"])
        sim_f = float(t25_map.loc[tn, "SIM_FRESH_CUM"])
        err_f = sim_f - obs_f
        pbias_f = 100.0 * err_f / obs_f
        
        obs_d = float(t25_map.loc[tn, "OBS_DRY_CUM"])
        sim_d = float(t25_map.loc[tn, "SIM_DRY_CUM"])
        err_d = sim_d - obs_d
        pbias_d = 100.0 * err_d / obs_d
        
        summary_rows.append({
            "TN": tn, "Water": w, "N_Level": n, "Fert_N_kg": n_kg, "Role": role,
            "Matched_Scale_s_k": s_val,
            "Matched_SNO3_kg_ha": round(tot_no3_kg, 1),
            "Matched_SNH4_kg_ha": round(tot_nh4_kg, 1),
            "Total_Matched_MinN_kg_ha": round(tot_no3_kg + tot_nh4_kg, 1),
            "Total_N_Supply_kg_ha": round(tot_no3_kg + tot_nh4_kg + float(n_kg), 1),
            "OBS_Fresh_Yield": obs_f, "SIM_Fresh_Yield": sim_f,
            "Fresh_Error_kg": round(err_f, 1), "Fresh_PBIAS_pct": round(pbias_f, 2),
            "OBS_Dry_Yield": obs_d, "SIM_Dry_Yield": sim_d,
            "Dry_PBIAS_pct": round(pbias_d, 2),
            "SNO3_layers_ppm": " | ".join(sno3_strs),
            "SNH4_layers_ppm": " | ".join(snh4_strs),
        })
        
    sum_df = pd.DataFrame(summary_rows)
    sum_df.to_csv(work_dir / "25SP_yield_matched_initial_nitrogen_summary.csv", index=False)
    
    def _calc_stats(obs, sim):
        ok = np.isfinite(obs) & np.isfinite(sim) & (obs != -99) & (sim != -99)
        o, s = obs[ok], sim[ok]
        sst = np.sum((o - o.mean()) ** 2)
        nse = float(1.0 - np.sum((s - o) ** 2) / sst) if sst > 0 else np.nan
        rrmse = float(100.0 * np.sqrt(np.mean((s - o) ** 2)) / np.mean(np.abs(o))) if len(o) > 0 else np.nan
        r2 = float(np.corrcoef(o, s)[0, 1] ** 2) if len(o) > 1 else np.nan
        d_idx = float(1.0 - np.sum((s - o)**2) / np.sum((np.abs(s - o.mean()) + np.abs(o - o.mean()))**2)) if sst > 0 else np.nan
        return r2, nse, d_idx, rrmse
        
    print("\n========================== 25SP YIELD-MATCHING FINAL SUMMARY ==========================")
    print(sum_df[["TN", "Water", "N_Level", "Fert_N_kg", "Matched_Scale_s_k", "Matched_SNO3_kg_ha", "Total_Matched_MinN_kg_ha", "OBS_Fresh_Yield", "SIM_Fresh_Yield", "Fresh_PBIAS_pct"]].to_string(index=False))
    
    r2_f, nse_f, d_f, rrmse_f = _calc_stats(h25["OBS_FRESH_CUM"].to_numpy(float), h25["SIM_FRESH_CUM"].to_numpy(float))
    r2_d, nse_d, d_d, rrmse_d = _calc_stats(h25["OBS_DRY_CUM"].to_numpy(float), h25["SIM_DRY_CUM"].to_numpy(float))
    r2_l, nse_l, d_l, rrmse_l = _calc_stats(p25["OBS_LAID"].to_numpy(float), p25["SIM_LAID"].to_numpy(float))
    r2_lw, nse_lw, d_lw, rrmse_lw = _calc_stats(p25["OBS_LWAD"].to_numpy(float), p25["SIM_LWAD"].to_numpy(float))
    r2_sw, nse_sw, d_sw, rrmse_sw = _calc_stats(p25["OBS_SWAD"].to_numpy(float), p25["SIM_SWAD"].to_numpy(float))
    
    print("\n========================== 25SP OVERALL FITTING SCORECARD ==========================")
    metrics_table = [
        {"Variable": "Fresh Fruit Yield (FRESH_CUM)", "R2": round(r2_f, 4), "NSE": round(nse_f, 4), "d_index": round(d_f, 4), "RRMSE_%": round(rrmse_f, 2)},
        {"Variable": "Dry Fruit Yield (DRY_CUM)", "R2": round(r2_d, 4), "NSE": round(nse_d, 4), "d_index": round(d_d, 4), "RRMSE_%": round(rrmse_d, 2)},
        {"Variable": "Canopy LAI (LAID)", "R2": round(r2_l, 4), "NSE": round(nse_l, 4), "d_index": round(d_l, 4), "RRMSE_%": round(rrmse_l, 2)},
        {"Variable": "Leaf Dry Mass (LWAD)", "R2": round(r2_lw, 4), "NSE": round(nse_lw, 4), "d_index": round(d_lw, 4), "RRMSE_%": round(rrmse_lw, 2)},
        {"Variable": "Stem Dry Mass (SWAD)", "R2": round(r2_sw, 4), "NSE": round(nse_sw, 4), "d_index": round(d_sw, 4), "RRMSE_%": round(rrmse_sw, 2)},
    ]
    print(pd.DataFrame(metrics_table).to_string(index=False))
    
    w3_diff = sum_df.loc[sum_df["TN"] == 2, "SIM_Fresh_Yield"].values[0] - sum_df.loc[sum_df["TN"] == 5, "SIM_Fresh_Yield"].values[0]
    w1_diff = sum_df.loc[sum_df["TN"] == 10, "SIM_Fresh_Yield"].values[0] - sum_df.loc[sum_df["TN"] == 13, "SIM_Fresh_Yield"].values[0]
    w3_obs = sum_df.loc[sum_df["TN"] == 2, "OBS_Fresh_Yield"].values[0] - sum_df.loc[sum_df["TN"] == 5, "OBS_Fresh_Yield"].values[0]
    w1_obs = sum_df.loc[sum_df["TN"] == 10, "OBS_Fresh_Yield"].values[0] - sum_df.loc[sum_df["TN"] == 13, "OBS_Fresh_Yield"].values[0]
    
    print("\n========================== NITROGEN RESPONSE CONTRASTS (N3 - N0) ==========================")
    print(f"25SP W3 (TN2 - TN5)  -> Matched Sim: {w3_diff:+7.1f} kg/ha | Obs: {w3_obs:+7.1f} kg/ha")
    print(f"25SP W1 (TN10 - TN13) -> Matched Sim: {w1_diff:+7.1f} kg/ha | Obs: {w1_obs:+7.1f} kg/ha")


def main():
    df_sweep = run_candidate_scale_sweep(OUT_DIR)
    best_scales = select_best_yield_matching_scales(df_sweep)
    replay_and_generate_final_report(best_scales, OUT_DIR)


if __name__ == "__main__":
    main()
