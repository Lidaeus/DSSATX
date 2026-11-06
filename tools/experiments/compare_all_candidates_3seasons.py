#!/usr/bin/env python3
"""Run full 3-season deterministic evaluation across all 35 treatments:
1. 2025 Spring (25SP, 11 treatments)
2. 2026 Spring (26SP, 12 treatments)
3. 2025 Autumn (25FA, 12 treatments) - Pure Blind Out-of-sample Validation

Evaluates all key candidate parameter sets:
- C13: real_159 (13-treatment objective-tuned best balanced champion)
- C12: real_152 (13-treatment objective-tuned minimum Phi)
- C10: real_125 (previous 200x6 minimum Phi)
- C09: real_164 (previous 200x6 best balanced)
- C05: real_26 (historical benchmark)
- C11: real_140
- Other top candidates from 13trt 200x6 iteration 6: real_135, real_35, real_149, real_8, real_189, real_151, real_62, real_168, real_158, real_90, real_92
- Historical real38 (from full_gen_century_sasc094_formal)

Computes comprehensive metrics and outputs ranked comparison tables.
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dssat.run_dssat import prepare_run_directory
from tools.eval_full_gen98 import evaluate_run, calc_metrics

SCRATCH_DIR = PROJECT_ROOT / "scratch" / "cand_3season_compare"
if SCRATCH_DIR.exists():
    shutil.rmtree(SCRATCH_DIR)
SCRATCH_DIR.mkdir(parents=True)

# Prepare batch files
BATCH_DIR = SCRATCH_DIR / "batches"
BATCH_DIR.mkdir()

# 25SP: 11 treatments
b25 = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch.v48"

# 26SP: 12 treatments
b26_lines = ["$BATCH(SEASON)", "! 2026 Spring all 12 treatments"]
for tn in range(1, 13):
    b26_lines.append(f"XXQL2601.TMX                                                                                    {tn:2d}      1      0      0      0")
b26 = BATCH_DIR / "DSSBatch_26SP_all.v48"
b26.write_text("\n".join(b26_lines) + "\n", encoding="utf-8")

# 25FA: 12 treatments
bfa_lines = ["$BATCH(SEASON)", "! 2025 Autumn all 12 treatments"]
for tn in range(1, 13):
    bfa_lines.append(f"XXQL2502.TMX                                                                                    {tn:2d}      1      0      0      0")
bfa = BATCH_DIR / "DSSBatch_25FA_all.v48"
bfa.write_text("\n".join(bfa_lines) + "\n", encoding="utf-8")

SEASONS = {
    "25SP": (b25, PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2501_v20260917_refresh"),
    "26SP": (b26, PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2601_v20260917_refresh"),
    "25FA": (bfa, PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_v20260917_refresh"),
}

TMT_META = {
    # 25SP
    ("XXQL2501", 2): {"season": "25SP", "water": "W3", "nitro": "N3"},
    ("XXQL2501", 3): {"season": "25SP", "water": "W3", "nitro": "N2"},
    ("XXQL2501", 4): {"season": "25SP", "water": "W3", "nitro": "N1"},
    ("XXQL2501", 5): {"season": "25SP", "water": "W3", "nitro": "N0"},
    ("XXQL2501", 6): {"season": "25SP", "water": "W2", "nitro": "N3"},
    ("XXQL2501", 9): {"season": "25SP", "water": "W2", "nitro": "N0"},
    ("XXQL2501", 10): {"season": "25SP", "water": "W1", "nitro": "N3"},
    ("XXQL2501", 11): {"season": "25SP", "water": "W1", "nitro": "N2"},
    ("XXQL2501", 12): {"season": "25SP", "water": "W1", "nitro": "N1"},
    ("XXQL2501", 13): {"season": "25SP", "water": "W1", "nitro": "N0"},
    ("XXQL2501", 14): {"season": "25SP", "water": "CK", "nitro": "N2"},
    # 26SP
    ("XXQL2601", 1): {"season": "26SP", "water": "W3", "nitro": "N3"},
    ("XXQL2601", 2): {"season": "26SP", "water": "W2", "nitro": "N3"},
    ("XXQL2601", 3): {"season": "26SP", "water": "W1", "nitro": "N3"},
    ("XXQL2601", 4): {"season": "26SP", "water": "W3", "nitro": "N2"},
    ("XXQL2601", 5): {"season": "26SP", "water": "W2", "nitro": "N2"},
    ("XXQL2601", 6): {"season": "26SP", "water": "W1", "nitro": "N2"},
    ("XXQL2601", 7): {"season": "26SP", "water": "W3", "nitro": "N1"},
    ("XXQL2601", 8): {"season": "26SP", "water": "W2", "nitro": "N1"},
    ("XXQL2601", 9): {"season": "26SP", "water": "W3", "nitro": "N0"},
    ("XXQL2601", 10): {"season": "26SP", "water": "W1", "nitro": "N1"},
    ("XXQL2601", 11): {"season": "26SP", "water": "W2", "nitro": "N0"},
    ("XXQL2601", 12): {"season": "26SP", "water": "W1", "nitro": "N0"},
    # 25FA
    ("XXQL2502", 1): {"season": "25FA", "water": "W3", "nitro": "N3"},
    ("XXQL2502", 2): {"season": "25FA", "water": "W2", "nitro": "N3"},
    ("XXQL2502", 3): {"season": "25FA", "water": "W1", "nitro": "N3"},
    ("XXQL2502", 4): {"season": "25FA", "water": "W3", "nitro": "N2"},
    ("XXQL2502", 5): {"season": "25FA", "water": "W2", "nitro": "N2"},
    ("XXQL2502", 6): {"season": "25FA", "water": "W1", "nitro": "N2"},
    ("XXQL2502", 7): {"season": "25FA", "water": "W3", "nitro": "N1"},
    ("XXQL2502", 8): {"season": "25FA", "water": "W2", "nitro": "N1"},
    ("XXQL2502", 9): {"season": "25FA", "water": "W3", "nitro": "N0"},
    ("XXQL2502", 10): {"season": "25FA", "water": "W1", "nitro": "N1"},
    ("XXQL2502", 11): {"season": "25FA", "water": "W2", "nitro": "N0"},
    ("XXQL2502", 12): {"season": "25FA", "water": "W1", "nitro": "N0"},
}

def calc_nse(obs, sim):
    mask = np.isfinite(obs) & np.isfinite(sim)
    o = obs[mask].to_numpy()
    s = sim[mask].to_numpy()
    if len(o) < 2: return np.nan
    denom = np.sum((o - np.mean(o))**2)
    if denom == 0: return np.nan
    return 1.0 - (np.sum((o - s)**2) / denom)

def run_season(param_csv: Path, batch_path: Path, input_dir: Path, out_dir: Path):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    
    batch_dest = prepare_run_directory(out_dir, ["--batch", str(batch_path), "--input-dir", str(input_dir)])
    cmd = [
        sys.executable,
        "-m",
        "src.dssat.run_dssat",
        "--param-csv",
        str(param_csv.resolve()),
        "--batch",
        batch_dest.name,
        "--harvest-var",
        "CHPDT",
        "--input-dir",
        str(input_dir.resolve()),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    res = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        print(f"Error in {out_dir}: {res.stderr[-300:]}")
        return None
    return evaluate_run(batch_dest, out_dir)

def collect_candidate_params():
    candidates = {}
    
    # 1. Existing archived candidates
    cand_dir = PROJECT_ROOT / "workspace" / "candidates"
    named_map = {
        "C13_real159": cand_dir / "candidate_c13_real159_best_balanced" / "params.csv",
        "C12_real152": cand_dir / "candidate_c12_real152_minphi" / "params.csv",
        "C10_real125": cand_dir / "candidate_c10_real125" / "params.csv",
        "C09_real164": cand_dir / "candidate_c09_real164" / "params.csv",
        "C05_real26": cand_dir / "candidate_c05_real26" / "params.csv",
        "C11_real140": cand_dir / "candidate_c11_real140" / "params.csv",
    }
    for tag, p in named_map.items():
        if p.is_file():
            candidates[tag] = p
            
    # 2. Historical real38
    p_r38 = PROJECT_ROOT / "workspace" / "runs" / "full_gen_century_sasc094_formal_20260918" / "candidate_iter5_real38_params.csv"
    if p_r38.is_file():
        candidates["real38_century"] = p_r38
        
    # 3. Top realizations from full_gen_13trt_obj_tune_200x6
    run_13trt = PROJECT_ROOT / "workspace" / "runs" / "full_gen_13trt_obj_tune_200x6_20260919"
    par_6 = run_13trt / "full_gen_13trt_obj_tune_200x6.6.par.csv"
    fb_csv = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_full_gen_sasc094_sldr024_slll018_020_20260919.csv"
    
    if par_6.is_file() and fb_csv.is_file():
        df_p6 = pd.read_csv(par_6)
        df_p6["real_name"] = df_p6["real_name"].astype(str)
        fb_df = pd.read_csv(fb_csv)
        
        extra_reals = ["135", "35", "149", "8", "189", "151", "62", "168", "158", "90", "92"]
        for r_id in extra_reals:
            tag = f"13trt_real{r_id}"
            sub = df_p6[df_p6["real_name"] == r_id]
            if sub.empty:
                continue
            row_dict = {col.lower(): sub.iloc[0][col] for col in df_p6.columns if col != "real_name"}
            items = []
            seen = set()
            for _, r in fb_df.iterrows():
                pname = str(r["name"]).strip()
                pname_lower = pname.lower()
                val = row_dict.get(pname_lower, float(r["init"]))
                items.append({"name": pname, "value": val})
                seen.add(pname_lower)
            for k, v in row_dict.items():
                if k not in seen:
                    items.append({"name": k.upper(), "value": v})
            p_out = SCRATCH_DIR / f"{tag}_params.csv"
            pd.DataFrame(items).to_csv(p_out, index=False)
            candidates[tag] = p_out
            
    return candidates

def evaluate_all():
    candidates = collect_candidate_params()
    print(f"Total candidates to evaluate: {len(candidates)}")
    for k, v in candidates.items():
        print(f"  {k} -> {v.name}")
        
    records = []
    
    for tag, param_csv in candidates.items():
        print(f"\n=======================================================")
        print(f"Evaluating {tag} across 3 seasons (35 treatments)...")
        print(f"=======================================================")
        
        cand_dir = SCRATCH_DIR / f"run_{tag}"
        cand_dir.mkdir(exist_ok=True)
        
        all_season_h = []
        season_terms = {}
        dyn_nses = {}
        
        for season, (bpath, idir) in SEASONS.items():
            s_out = cand_dir / season
            res = run_season(param_csv, bpath, idir, s_out)
            if res is None:
                print(f"Failed to run {season} for {tag}")
                continue
            df_h, _ = res
            df_h["SEASON"] = season
            all_season_h.append(df_h)
            
            # Terminal yield
            last_rows = df_h.sort_values("DATE").groupby(["EXCODE", "TN"]).last().reset_index()
            season_terms[season] = last_rows
            
            rmse_s, nrmse_s, d_s, r2_s = calc_metrics(last_rows["OBS_FRESH_CUM"], last_rows["SIM_FRESH_CUM"])
            nse_s = calc_nse(df_h["OBS_FRESH_CUM"], df_h["SIM_FRESH_CUM"])
            dyn_nses[season] = (rmse_s, nrmse_s, d_s, r2_s, nse_s)
            print(f"  [{season}]: NRMSE={nrmse_s:.2f}%, d={d_s:.4f}, R2={r2_s:.4f}, Dyn NSE={nse_s:.4f}")
            
        if len(season_terms) < 3:
            print(f"Skipping {tag} due to incomplete seasons")
            continue
            
        # Combine Spring (25SP 11 + 26SP 12 = 23 treatments)
        spring_last = pd.concat([season_terms["25SP"], season_terms["26SP"]], ignore_index=True)
        rmse_sp, nrmse_sp, d_sp, r2_sp = calc_metrics(spring_last["OBS_FRESH_CUM"], spring_last["SIM_FRESH_CUM"])
        
        spring_dyn = pd.concat([all_season_h[0], all_season_h[1]], ignore_index=True)
        nse_sp = calc_nse(spring_dyn["OBS_FRESH_CUM"], spring_dyn["SIM_FRESH_CUM"])
        
        # Combine Grand (All 35 treatments)
        grand_last = pd.concat([spring_last, season_terms["25FA"]], ignore_index=True)
        rmse_grand, nrmse_grand, d_grand, r2_grand = calc_metrics(grand_last["OBS_FRESH_CUM"], grand_last["SIM_FRESH_CUM"])
        
        grand_dyn = pd.concat(all_season_h, ignore_index=True)
        nse_grand = calc_nse(grand_dyn["OBS_FRESH_CUM"], grand_dyn["SIM_FRESH_CUM"])
        
        # Treatment specific checks:
        # 26SP yield ceilings
        t26 = season_terms["26SP"].set_index("TN")["SIM_FRESH_CUM"]
        y_26_w3n3 = t26.get(1, np.nan)
        y_26_w2n3 = t26.get(2, np.nan)
        y_26_w1n3 = t26.get(3, np.nan)
        y_26_w2n0 = t26.get(11, np.nan)
        y_26_w1n0 = t26.get(12, np.nan)
        
        delta_y_26_w2 = y_26_w2n3 - y_26_w2n0  # Obs = 9,523 kg/ha
        delta_y_26_w1 = y_26_w1n3 - y_26_w1n0  # Obs = 16,497 kg/ha
        
        # 25SP W1 drought nitrogen response
        t25 = season_terms["25SP"].set_index("TN")["SIM_FRESH_CUM"]
        y_25_w1n3 = t25.get(10, np.nan)
        y_25_w1n0 = t25.get(13, np.nan)
        delta_y_25_w1 = y_25_w1n3 - y_25_w1n0  # Obs = 11,590 kg/ha
        
        # 25FA metrics
        rmse_fa, nrmse_fa, d_fa, r2_fa, nse_fa = dyn_nses["25FA"]
        rmse_25sp, nrmse_25sp, d_25sp, r2_25sp, nse_25sp = dyn_nses["25SP"]
        rmse_26sp, nrmse_26sp, d_26sp, r2_26sp, nse_26sp = dyn_nses["26SP"]
        
        # Max yield across 26SP N3
        max_26sp_yield = max(y_26_w3n3, y_26_w2n3, y_26_w1n3)
        ceiling_passed = (max_26sp_yield <= 75000.0)
        
        records.append({
            "candidate": tag,
            # Spring Pooled 23 trt
            "Spring_NRMSE_pct": nrmse_sp,
            "Spring_d": d_sp,
            "Spring_R2": r2_sp,
            "Spring_NSE": nse_sp,
            # Individual seasons
            "25SP_NRMSE_pct": nrmse_25sp,
            "25SP_d": d_25sp,
            "25SP_NSE": nse_25sp,
            "26SP_NRMSE_pct": nrmse_26sp,
            "26SP_d": d_26sp,
            "26SP_NSE": nse_26sp,
            "25FA_NRMSE_pct": nrmse_fa,
            "25FA_d": d_fa,
            "25FA_NSE": nse_fa,
            # Grand pooled 35 trt
            "Grand_NRMSE_pct": nrmse_grand,
            "Grand_d": d_grand,
            "Grand_NSE": nse_grand,
            # Key physiological checks
            "Max_26SP_Y_t_ha": max_26sp_yield / 1000.0,
            "Ceiling_Passed": ceiling_passed,
            "Delta_Y_26W2_kg": delta_y_26_w2,
            "Delta_Y_26W1_kg": delta_y_26_w1,
            "Delta_Y_25W1_kg": delta_y_25_w1,
            "W1_N_ratio_pct": (delta_y_25_w1 / 11590.0 * 100.0) if pd.notna(delta_y_25_w1) else np.nan,
        })
        
    df_res = pd.DataFrame(records)
    out_csv = PROJECT_ROOT / "workspace" / "candidates" / "all_candidates_3season_benchmark_matrix.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\n=========================================================================================")
    print(f"Saved benchmark matrix to {out_csv}")
    print(f"=========================================================================================\n")
    
    # Sort and print table
    df_sorted = df_res.sort_values("Spring_NRMSE_pct")
    cols_display = [
        "candidate", "Spring_NRMSE_pct", "25SP_NRMSE_pct", "26SP_NRMSE_pct", "25FA_NRMSE_pct",
        "Grand_NRMSE_pct", "Max_26SP_Y_t_ha", "Ceiling_Passed", "Delta_Y_26W2_kg", "Delta_Y_25W1_kg", "Spring_NSE"
    ]
    print(df_sorted[cols_display].to_string(index=False))

if __name__ == "__main__":
    evaluate_all()
