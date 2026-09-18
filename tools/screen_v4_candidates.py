#!/usr/bin/env python3
"""Screen top V4 candidates across all 22 treatments (Calib + Valid)"""

import os
import sys
import shutil
import subprocess
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.run_dssat import prepare_run_directory
from tools.eval_full_gen98 import evaluate_run, calc_metrics

RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_98pct_v4_20260915"
CALIB_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_calib.v48"
VALID_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_valid.v48"
FROZEN_BOUNDS = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_full_genetic_98pct_v4_20260915.csv"

WORK_DIR = PROJECT_ROOT / "scratch" / "screen_v4_candidates"
if WORK_DIR.exists():
    shutil.rmtree(WORK_DIR)
WORK_DIR.mkdir(parents=True)

# Read iter 5 par file
par5_df = pd.read_csv(RUN_DIR / "full_gen98_v4.5.par.csv", index_col=0)
bounds_df = pd.read_csv(FROZEN_BOUNDS)
fixed_params = dict(zip(bounds_df[bounds_df["status"] == "fixed"]["name"], bounds_df[bounds_df["status"] == "fixed"]["init"]))

# Read phi history to find top members
phi_df = pd.read_csv(RUN_DIR / "full_gen98_v4.phi.actual.csv")
phi_cols = [c for c in phi_df.columns if c not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]]
last_phis = phi_df[phi_df["iteration"] == 5][phi_cols].iloc[0].to_dict()
valid_phis = {k: v for k, v in last_phis.items() if np.isfinite(v)}
sorted_candidates = [k for k, v in sorted(valid_phis.items(), key=lambda x: x[1])[:8]]

print(f"Screening top {len(sorted_candidates)} candidates: {sorted_candidates}")

results = []

for real_id in sorted_candidates:
    real_str = str(real_id)
    cand_dir = WORK_DIR / f"real_{real_str}"
    cand_dir.mkdir(parents=True)
    
    # Extract parameter vector
    if real_str in par5_df.index:
        active_p = par5_df.loc[real_str].to_dict()
    elif real_str == "base" and "base" in par5_df.index:
        active_p = par5_df.loc["base"].to_dict()
    else:
        try:
            active_p = par5_df.iloc[int(real_str)].to_dict()
        except:
            print(f"Could not find parameter vector for {real_str}")
            continue
            
    # Combine active + fixed
    full_p = {**fixed_params, **active_p}
    param_rows = [{"name": k, "value": v} for k, v in full_p.items()]
    df_param = pd.DataFrame(param_rows)
    p_csv = cand_dir / "params.csv"
    df_param.to_csv(p_csv, index=False)
    
    # Run calibration
    cal_dir = cand_dir / "calib"
    cal_dir.mkdir()
    shutil.copy(p_csv, cal_dir / "params.csv")
    b_cal = prepare_run_directory(cal_dir, ["--batch", str(CALIB_BATCH)])
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    r_cal = subprocess.run([sys.executable, "-m", "src.dssat.run_dssat", "--param-csv", str((cal_dir/"params.csv").resolve()), "--batch", b_cal.name, "--harvest-var", "CHPDT"], cwd=cal_dir, capture_output=True, env=env)
    if r_cal.returncode != 0:
        print(f"[Real {real_str}] Calib run failed")
        continue
        
    df_h_cal, df_eval_cal = evaluate_run(CALIB_BATCH, cal_dir)
    rmse_c, nrmse_c, d_c, r2_c = calc_metrics(df_h_cal["OBS_FRESH_CUM"], df_h_cal["SIM_FRESH_CUM"])
    
    # Run validation
    val_dir = cand_dir / "valid"
    val_dir.mkdir()
    shutil.copy(p_csv, val_dir / "params.csv")
    b_val = prepare_run_directory(val_dir, ["--batch", str(VALID_BATCH)])
    r_val = subprocess.run([sys.executable, "-m", "src.dssat.run_dssat", "--param-csv", str((val_dir/"params.csv").resolve()), "--batch", b_val.name, "--harvest-var", "CHPDT"], cwd=val_dir, capture_output=True, env=env)
    if r_val.returncode != 0:
        print(f"[Real {real_str}] Valid run failed")
        continue
        
    df_h_val, df_eval_val = evaluate_run(VALID_BATCH, val_dir)
    rmse_v, nrmse_v, d_v, r2_v = calc_metrics(df_h_val["OBS_FRESH_CUM"], df_h_val["SIM_FRESH_CUM"])
    
    # Overall pooled metrics
    df_all = pd.concat([df_h_cal, df_h_val], ignore_index=True)
    _, nrmse_all, d_all, r2_all = calc_metrics(df_all["OBS_FRESH_CUM"], df_all["SIM_FRESH_CUM"])
    
    # Contrasts
    final_yields = {r: grp.sort_values("DATE").iloc[-1]["SIM_FRESH_CUM"] for r, grp in df_h_cal.groupby("RUN")}
    d_25_w3 = final_yields.get(1, 0) - final_yields.get(2, 0)
    d_25_w1 = final_yields.get(3, 0) - final_yields.get(4, 0)
    d_26_w2 = final_yields.get(5, 0) - final_yields.get(7, 0)
    d_26_w1 = final_yields.get(6, 0) - final_yields.get(8, 0)
    
    mono_penalty = max(0.0, -d_25_w3) + max(0.0, -d_25_w1) + max(0.0, -d_26_w2) + max(0.0, -d_26_w1)
    
    # LAIX
    eval_all = pd.concat([df_eval_cal, df_eval_val], ignore_index=True)
    sub26 = eval_all[eval_all["EXCODE"].str.contains("2601")]
    laix26_sim = pd.to_numeric(sub26["LAIXS"], errors="coerce")
    laix26_obs = pd.to_numeric(sub26["LAIXM"], errors="coerce")
    mask26 = np.isfinite(laix26_sim) & np.isfinite(laix26_obs) & (laix26_obs > 0)
    laix26_bias = (laix26_sim[mask26] - laix26_obs[mask26]).mean() if mask26.any() else np.nan
    
    results.append({
        "realization": real_str,
        "phi": valid_phis.get(real_id, np.nan),
        "calib_NRMSE%": nrmse_c,
        "valid_NRMSE%": nrmse_v,
        "pooled_NRMSE%": nrmse_all,
        "calib_d": d_c,
        "valid_d": d_v,
        "d_25_w3": d_25_w3,
        "d_26_w2": d_26_w2,
        "mono_penalty": mono_penalty,
        "laix26_bias": laix26_bias,
        "laix26_max": laix26_sim.max() if not laix26_sim.empty else np.nan,
    })
    print(f"[{real_str}] Phi={valid_phis.get(real_id, np.nan):.1f} | Cal={nrmse_c:.2f}% | Val={nrmse_v:.2f}% | 26_w2={d_26_w2:+.0f} | 26_bias={laix26_bias:+.2f}")

res_df = pd.DataFrame(results)
print("\n" + "="*85)
print(res_df.to_string())
res_df.to_csv(WORK_DIR / "candidate_screening_summary.csv", index=False)
