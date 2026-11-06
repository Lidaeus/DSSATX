#!/usr/bin/env python3
"""Evaluate V6 candidate parameter sets on:
1. Calibration set (8 runs, DSSBatch_calib.v48)
2. Validation set (14 runs, DSSBatch_valid.v48)
3. Organ N and P concentrations
4. Late-season N0 LAID and peak LAIX
5. Water-nitrogen monotonicity
"""

import os
import sys
import shutil
import subprocess
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.run_dssat import prepare_run_directory
from tools.eval_full_gen98 import evaluate_run, calc_metrics
from src.reporting.analyze_results import _read_plantgro_vars_by_run

RUN_V6 = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_98pct_v6_20260917"
PAR_CSV_5 = RUN_V6 / "full_gen98_v6.5.par.csv"
PAR_CSV_2 = RUN_V6 / "full_gen98_v6.2.par.csv"
CALIB_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_calib.v48"
VALID_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_valid.v48"

df_par_5 = pd.read_csv(PAR_CSV_5)
df_par_2 = pd.read_csv(PAR_CSV_2)

candidates = [
    ("78", df_par_5, "iter5_real78"),
    ("140", df_par_5, "iter5_real140"),
    ("130", df_par_5, "iter5_real130"),
    ("86", df_par_5, "iter5_real86"),
    ("78", df_par_2, "iter2_real78"),
]

def build_param_csv(real_id: str, df_par: pd.DataFrame, out_path: Path):
    sub = df_par[df_par["real_name"].astype(str) == str(real_id)]
    if sub.empty:
        raise ValueError(f"Realization {real_id} not found")
    row = sub.iloc[0]
    items = []
    for col in df_par.columns:
        if col != "real_name":
            items.append({"name": col, "value": row[col]})
    df_out = pd.DataFrame(items)
    df_out.to_csv(out_path, index=False)
    return df_out

def run_batch(batch_path: Path, param_csv: Path, out_dir: Path):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    batch_dest = prepare_run_directory(out_dir, ["--batch", str(batch_path)])
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
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    res = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        print(f"Error running DSSAT in {out_dir}: {res.stderr[-500:]}")
        raise RuntimeError("DSSAT execution failed")
    return evaluate_run(batch_path, out_dir)

cand_results = []

for cid, df_par_source, tag in candidates:
    print(f"\n================ Evaluating Candidate {tag} (Realization {cid}) ================")
    p_csv = RUN_V6 / f"candidate_{tag}_params.csv"
    build_param_csv(cid, df_par_source, p_csv)
    
    # 1. Calibration batch
    calib_dir = RUN_V6 / f"cand_{tag}_calib"
    df_h_c, df_eval_c = run_batch(CALIB_BATCH, p_csv, calib_dir)
    rmse_c, nrmse_c, d_c, r2_c = calc_metrics(df_h_c["OBS_FRESH_CUM"], df_h_c["SIM_FRESH_CUM"])
    
    # Extract LAID and peak LAIX
    laix_25_c = df_eval_c[df_eval_c["EXCODE"].str.contains("2501")]["LAIXS"].astype(float).values
    laix_26_c = df_eval_c[df_eval_c["EXCODE"].str.contains("2601")]["LAIXS"].astype(float).values
    
    pg_c = calib_dir / "PlantGro.OUT"
    pg_vars_c = _read_plantgro_vars_by_run(str(pg_c), ["LAID", "LAPC", "STPC", "FOPC", "LNCM", "SNCM"])
    
    # Calibration N0 runs:
    # 25SP: Run 2 (TN 5, W3N0), Run 4 (TN 13, W1N0) at 25194
    # 26SP: Run 7 (TN 11, W2N0), Run 8 (TN 12, W1N0) at 26198
    laid_25_t5 = pg_vars_c.get(2, {}).get(25194, {}).get("LAID", np.nan)
    laid_25_t13 = pg_vars_c.get(4, {}).get(25194, {}).get("LAID", np.nan)
    laid_26_t11 = pg_vars_c.get(7, {}).get(26198, {}).get("LAID", np.nan)
    laid_26_t12 = pg_vars_c.get(8, {}).get(26198, {}).get("LAID", np.nan)
    
    # Monotonicity in calib
    final_yields_c = {}
    for r, grp in df_h_c.groupby("RUN"):
        final_yields_c[r] = grp.sort_values("DATE").iloc[-1]["SIM_FRESH_CUM"]
    d_25_w3 = final_yields_c.get(1, 0) - final_yields_c.get(2, 0)
    d_26_w2 = final_yields_c.get(5, 0) - final_yields_c.get(7, 0)
    
    # 2. Validation batch
    valid_dir = RUN_V6 / f"cand_{tag}_valid"
    df_h_v, df_eval_v = run_batch(VALID_BATCH, p_csv, valid_dir)
    rmse_v, nrmse_v, d_v, r2_v = calc_metrics(df_h_v["OBS_FRESH_CUM"], df_h_v["SIM_FRESH_CUM"])
    
    # Pooled metrics
    all_obs = pd.concat([df_h_c["OBS_FRESH_CUM"], df_h_v["OBS_FRESH_CUM"]])
    all_sim = pd.concat([df_h_c["SIM_FRESH_CUM"], df_h_v["SIM_FRESH_CUM"]])
    rmse_p, nrmse_p, d_p, r2_p = calc_metrics(all_obs, all_sim)
    
    # Organ N and P at harvest in 25SP high-input (Run 1 / TN 2)
    p_run1_end = pg_vars_c.get(1, {}).get(25192, {})
    leaf_p = p_run1_end.get("LAPC", np.nan)
    stem_p = p_run1_end.get("STPC", np.nan)
    fruit_p = p_run1_end.get("FOPC", np.nan)
    leaf_n = p_run1_end.get("LNCM", np.nan)
    stem_n = p_run1_end.get("SNCM", np.nan)
    
    res = {
        "candidate": tag,
        "calib_NRMSE%": nrmse_c,
        "valid_NRMSE%": nrmse_v,
        "pooled_NRMSE%": nrmse_p,
        "calib_d_index": d_c,
        "valid_d_index": d_v,
        "pooled_d_index": d_p,
        "calib_R2": r2_c,
        "valid_R2": r2_v,
        "pooled_R2": r2_p,
        "26SP_LAIX_max": np.max(laix_26_c) if len(laix_26_c) > 0 else np.nan,
        "25_T5_W3N0_LAI": laid_25_t5,
        "25_T13_W1N0_LAI": laid_25_t13,
        "26_T11_W2N0_LAI": laid_26_t11,
        "26_T12_W1N0_LAI": laid_26_t12,
        "d_25_w3": d_25_w3,
        "d_26_w2": d_26_w2,
        "leaf_P%": leaf_p,
        "stem_P%": stem_p,
        "fruit_P%": fruit_p,
        "leaf_N%": leaf_n,
        "stem_N%": stem_n,
    }
    cand_results.append(res)
    print(f"[{tag}] Calib NRMSE={nrmse_c:.2f}%, Valid NRMSE={nrmse_v:.2f}%, Pooled={nrmse_p:.2f}%")
    print(f"       Calib d={d_c:.4f}, Valid d={d_v:.4f}, Pooled d={d_p:.4f}")
    print(f"       26SP N0 LAID: T11={laid_26_t11:.2f} (obs 2.99), T12={laid_26_t12:.2f} (obs 2.53)")
    print(f"       25SP N0 LAID: T5={laid_25_t5:.2f} (obs 3.35), T13={laid_25_t13:.2f} (obs 3.39)")
    print(f"       Monotonicity (N3-N0): d_25_w3={d_25_w3:+.1f}, d_26_w2={d_26_w2:+.1f}")
    print(f"       Organ N%: leaf={leaf_n:.2f}% (obs 4.55%), stem={stem_n:.2f}% (obs 2.84%)")

df_summary = pd.DataFrame(cand_results)
summary_csv = RUN_V6 / "v6_candidates_comparison_summary.csv"
df_summary.to_csv(summary_csv, index=False)
print("\n" + "="*120)
print(df_summary.to_string())
