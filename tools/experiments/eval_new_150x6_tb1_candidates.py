#!/usr/bin/env python3
"""Evaluate new 150x6 TB1 in [8.0, 9.5] calibration candidates across all 35 treatments:
1. 25SP: 11 treatments (DSSBatch.v48)
2. 26SP: 12 treatments (DSSBatch_26SP_all.v48)
3. 25FA: 12 treatments (DSSBatch_25FA_all.v48) - Blind Out-of-sample Test

Compares new candidates against C14 (real_90) and C13 (real_159).
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

RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / "full_gen_13trt_tb1_80_95_150x6_20260920"
FROZEN_BOUNDS = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_full_gen_tb1_80_95_13trt_20260920.csv"

SCRATCH_DIR = PROJECT_ROOT / "scratch" / "eval_new_tb1_150x6"
if SCRATCH_DIR.exists():
    shutil.rmtree(SCRATCH_DIR)
SCRATCH_DIR.mkdir(parents=True)

BATCH_DIR = SCRATCH_DIR / "batches"
BATCH_DIR.mkdir()

# 25SP
b25 = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch.v48"

# 26SP
b26_lines = ["$BATCH(SEASON)", "! 2026 Spring all 12 treatments"]
for tn in range(1, 13):
    b26_lines.append(f"XXQL2601.TMX                                                                                    {tn:2d}      1      0      0      0")
b26 = BATCH_DIR / "DSSBatch_26SP_all.v48"
b26.write_text("\n".join(b26_lines) + "\n", encoding="utf-8")

# 25FA
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

def prepare_candidates():
    cands = {}
    
    # 1. Benchmarks: C14 and C13
    cands["Benchmark_C14_real90"] = (PROJECT_ROOT / "workspace/candidates/candidate_c14_real90_three_season_champion/params.csv", 921.13)
    cands["Benchmark_C13_real159"] = (PROJECT_ROOT / "workspace/candidates/candidate_c13_real159_best_balanced/params.csv", 924.24)
    
    # 2. Iteration 6 realizations
    p6_file = RUN_DIR / "full_gen_13trt_tb1_80_95_150x6.6.par.csv"
    fb_df = pd.read_csv(FROZEN_BOUNDS)
    
    phi_df = pd.read_csv(RUN_DIR / "full_gen_13trt_tb1_80_95_150x6.phi.actual.csv")
    row6 = phi_df[phi_df["iteration"] == 6].iloc[0]
    phi_map6 = {str(k): float(v) for k, v in row6.items() if str(k) not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"] and pd.notna(v)}
    
    df_p6 = pd.read_csv(p6_file)
    df_p6["real_name"] = df_p6["real_name"].astype(str)
    
    target_reals_6 = ["39", "72", "135", "62", "81", "97", "52", "107", "82", "90", "148", "96", "121", "45", "37"]
    for r_id in target_reals_6:
        sub = df_p6[df_p6["real_name"] == r_id]
        if sub.empty: continue
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
        p_out = SCRATCH_DIR / f"new_iter6_real{r_id}_params.csv"
        pd.DataFrame(items).to_csv(p_out, index=False)
        cands[f"new_iter6_real{r_id}"] = (p_out, phi_map6.get(r_id, np.nan))
        
    # 3. Iteration 4 real 39 (lowest Phi across all iterations: 931.38)
    p4_file = RUN_DIR / "full_gen_13trt_tb1_80_95_150x6.4.par.csv"
    if p4_file.is_file():
        df_p4 = pd.read_csv(p4_file)
        df_p4["real_name"] = df_p4["real_name"].astype(str)
        sub4 = df_p4[df_p4["real_name"] == "39"]
        if not sub4.empty:
            row_dict = {col.lower(): sub4.iloc[0][col] for col in df_p4.columns if col != "real_name"}
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
            p_out4 = SCRATCH_DIR / "new_iter4_real39_params.csv"
            pd.DataFrame(items).to_csv(p_out4, index=False)
            cands["new_iter4_real39"] = (p_out4, 931.38)
            
    return cands

def main():
    candidates = prepare_candidates()
    print(f"Total candidates to evaluate: {len(candidates)}")
    for k, (p, phi_val) in candidates.items():
        print(f"  {k}: Phi={phi_val:.1f} -> {p.name}")
        
    records = []
    
    for tag, (param_csv, phi_val) in candidates.items():
        print(f"\n=======================================================")
        print(f"Evaluating {tag} (Phi={phi_val:.1f}) across 3 seasons (35 treatments)...")
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
            
            last_rows = df_h.sort_values("DATE").groupby(["EXCODE", "TN"]).last().reset_index()
            season_terms[season] = last_rows
            
            rmse_s, nrmse_s, d_s, r2_s = calc_metrics(last_rows["OBS_FRESH_CUM"], last_rows["SIM_FRESH_CUM"])
            nse_s = calc_nse(df_h["OBS_FRESH_CUM"], df_h["SIM_FRESH_CUM"])
            dyn_nses[season] = (rmse_s, nrmse_s, d_s, r2_s, nse_s)
            print(f"  [{season}]: NRMSE={nrmse_s:.2f}%, d={d_s:.4f}, R2={r2_s:.4f}, Dyn NSE={nse_s:.4f}")
            
        if len(season_terms) < 3:
            print(f"Skipping {tag} due to incomplete seasons")
            continue
            
        # Combine Spring (23 runs)
        spring_last = pd.concat([season_terms["25SP"], season_terms["26SP"]], ignore_index=True)
        rmse_sp, nrmse_sp, d_sp, r2_sp = calc_metrics(spring_last["OBS_FRESH_CUM"], spring_last["SIM_FRESH_CUM"])
        spring_dyn = pd.concat([all_season_h[0], all_season_h[1]], ignore_index=True)
        nse_sp = calc_nse(spring_dyn["OBS_FRESH_CUM"], spring_dyn["SIM_FRESH_CUM"])
        
        # Combine Grand (35 runs)
        grand_last = pd.concat([spring_last, season_terms["25FA"]], ignore_index=True)
        rmse_grand, nrmse_grand, d_grand, r2_grand = calc_metrics(grand_last["OBS_FRESH_CUM"], grand_last["SIM_FRESH_CUM"])
        grand_dyn = pd.concat(all_season_h, ignore_index=True)
        nse_grand = calc_nse(grand_dyn["OBS_FRESH_CUM"], grand_dyn["SIM_FRESH_CUM"])
        
        # Treatment checks
        t26 = season_terms["26SP"].set_index("TN")["SIM_FRESH_CUM"]
        y_26_w3n3 = t26.get(1, np.nan)
        y_26_w2n3 = t26.get(2, np.nan)
        y_26_w1n3 = t26.get(3, np.nan)
        y_26_w2n0 = t26.get(11, np.nan)
        y_26_w1n0 = t26.get(12, np.nan)
        
        delta_y_26_w2 = y_26_w2n3 - y_26_w2n0
        delta_y_26_w1 = y_26_w1n3 - y_26_w1n0
        
        t25 = season_terms["25SP"].set_index("TN")["SIM_FRESH_CUM"]
        y_25_w1n3 = t25.get(10, np.nan)
        y_25_w1n0 = t25.get(13, np.nan)
        delta_y_25_w1 = y_25_w1n3 - y_25_w1n0
        
        rmse_fa, nrmse_fa, d_fa, r2_fa, nse_fa = dyn_nses["25FA"]
        rmse_25sp, nrmse_25sp, d_25sp, r2_25sp, nse_25sp = dyn_nses["25SP"]
        rmse_26sp, nrmse_26sp, d_26sp, r2_26sp, nse_26sp = dyn_nses["26SP"]
        
        max_26sp_yield = max(y_26_w3n3, y_26_w2n3, y_26_w1n3)
        ceiling_passed = (max_26sp_yield <= 75000.0)
        
        # Read TB1 value
        p_df = pd.read_csv(param_csv)
        tb1_val = p_df[p_df['name'].str.lower() == 'tb1']['value'].iloc[0]
        
        records.append({
            "candidate": tag,
            "Phi": phi_val,
            "TB1": tb1_val,
            "Spring_NRMSE_pct": nrmse_sp,
            "Spring_d": d_sp,
            "Spring_R2": r2_sp,
            "Spring_NSE": nse_sp,
            "25SP_NRMSE_pct": nrmse_25sp,
            "25SP_d": d_25sp,
            "25SP_NSE": nse_25sp,
            "26SP_NRMSE_pct": nrmse_26sp,
            "26SP_d": d_26sp,
            "26SP_NSE": nse_26sp,
            "25FA_NRMSE_pct": nrmse_fa,
            "25FA_d": d_fa,
            "25FA_NSE": nse_fa,
            "Grand_NRMSE_pct": nrmse_grand,
            "Grand_d": d_grand,
            "Grand_NSE": nse_grand,
            "Max_26SP_Y_t_ha": max_26sp_yield / 1000.0,
            "Ceiling_Passed": ceiling_passed,
            "Delta_Y_26W2_kg": delta_y_26_w2,
            "Delta_Y_25W1_kg": delta_y_25_w1,
        })
        
    df_res = pd.DataFrame(records)
    out_csv = PROJECT_ROOT / "workspace" / "runs" / "full_gen_13trt_tb1_80_95_150x6_20260920" / "all_candidates_3season_benchmark.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\n=========================================================================================")
    print(f"Saved benchmark matrix to {out_csv}")
    print(f"=========================================================================================\n")
    
    df_sorted = df_res.sort_values("Grand_NRMSE_pct")
    cols_display = [
        "candidate", "Phi", "TB1", "Grand_NRMSE_pct", "Spring_NRMSE_pct", "25SP_NRMSE_pct", "26SP_NRMSE_pct", "25FA_NRMSE_pct",
        "Max_26SP_Y_t_ha", "Ceiling_Passed", "Delta_Y_26W2_kg", "Delta_Y_25W1_kg"
    ]
    print(df_sorted[cols_display].to_string(index=False))

if __name__ == "__main__":
    main()
