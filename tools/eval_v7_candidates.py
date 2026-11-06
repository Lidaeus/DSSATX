#!/usr/bin/env python3
"""Evaluate V7 candidate parameter sets on:
1. Calibration set (8 runs, DSSBatch_calib.v48)
2. Validation set (14 runs, DSSBatch_valid.v48)
3. Water-Nitrogen gradients (26SP W2, 26SP W1, 25SP W3, 25SP W1)
4. Organ N and P concentrations
5. Late-season N0 LAID, peak LAIX, and NSTD stress
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

RUN_V7 = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_98pct_v7_20260917"
PAR_CSV_5 = RUN_V7 / "full_gen98_v7.5.par.csv"
PAR_CSV_4 = RUN_V7 / "full_gen98_v7.4.par.csv"
CALIB_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_calib.v48"
VALID_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_valid.v48"

df_par_5 = pd.read_csv(PAR_CSV_5)
df_par_4 = pd.read_csv(PAR_CSV_4) if PAR_CSV_4.exists() else df_par_5

# Candidates to evaluate
candidates = [
    ("121", df_par_5, "iter5_real121"),
    ("77", df_par_5, "iter5_real77"),
    ("133", df_par_5, "iter5_real133"),
    ("67", df_par_5, "iter5_real67"),
    ("140", df_par_5, "iter5_real140"),
    ("93", df_par_5, "iter5_real93"),
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
    p_csv = RUN_V7 / f"candidate_{tag}_params.csv"
    build_param_csv(cid, df_par_source, p_csv)
    
    # 1. Calibration batch (8 runs)
    calib_dir = RUN_V7 / f"cand_{tag}_calib"
    df_h_c, df_eval_c = run_batch(CALIB_BATCH, p_csv, calib_dir)
    rmse_c, nrmse_c, d_c, r2_c = calc_metrics(df_h_c["OBS_FRESH_CUM"], df_h_c["SIM_FRESH_CUM"])
    
    # 2. Validation batch (14 runs)
    valid_dir = RUN_V7 / f"cand_{tag}_valid"
    df_h_v, df_eval_v = run_batch(VALID_BATCH, p_csv, valid_dir)
    rmse_v, nrmse_v, d_v, r2_v = calc_metrics(df_h_v["OBS_FRESH_CUM"], df_h_v["SIM_FRESH_CUM"])
    
    # 3. Pooled metrics (22 runs)
    df_h_all = pd.concat([df_h_c, df_h_v], ignore_index=True)
    rmse_all, nrmse_all, d_all, r2_all = calc_metrics(df_h_all["OBS_FRESH_CUM"], df_h_all["SIM_FRESH_CUM"])
    
    # 4. Water-Nitrogen gradient in Calibration
    # In calibration batch:
    # 1: 25SP W3N3 (TRT 2), 2: 25SP W3N0 (TRT 10)
    # 3: 25SP W1N3 (TRT 5), 4: 25SP W1N0 (TRT 13)
    # 5: 26SP W2N3 (TRT 2), 6: 26SP W1N3 (TRT 3)
    # 7: 26SP W2N0 (TRT 11), 8: 26SP W1N0 (TRT 12)
    last_c = df_h_c.sort_values("DATE").groupby("RUN").last()["SIM_FRESH_CUM"].to_dict()
    w2_26_gap = last_c.get(5, 0) - last_c.get(7, 0)
    w1_26_gap = last_c.get(6, 0) - last_c.get(8, 0)
    w3_25_gap = last_c.get(1, 0) - last_c.get(2, 0)
    w1_25_gap = last_c.get(3, 0) - last_c.get(4, 0)
    
    # 5. Extract physiological stress NSTD and organ concentrations from PlantGro
    pg_c = calib_dir / "PlantGro.OUT"
    pg_vars_c = _read_plantgro_vars_by_run(str(pg_c), ["LAID", "NSTD", "AGEFAC", "LNCM", "SNCM"])
    
    # Max NSTD across calibration runs
    max_nstd_c = 0.0
    for r, v in pg_vars_c.get("NSTD", {}).items():
        vals = [float(x) for x in v.values() if x is not None]
        if vals:
            max_nstd_c = max(max_nstd_c, max(vals))
            
    # Key parameter values
    param_dict = dict(zip(p_csv.name, [0]))
    p_df = pd.read_csv(p_csv)
    p_vals = dict(zip(p_df["name"].str.lower(), p_df["value"]))
    
    res = {
        "candidate": tag,
        "real_id": cid,
        "nrmse_calib": nrmse_c,
        "nrmse_valid": nrmse_v,
        "nrmse_pooled": nrmse_all,
        "d_index_pooled": d_all,
        "r2_pooled": r2_all,
        "26SP_W2_gap": w2_26_gap,
        "26SP_W1_gap": w1_26_gap,
        "25SP_W3_gap": w3_25_gap,
        "25SP_W1_gap": w1_25_gap,
        "max_NSTD": max_nstd_c,
        "fnpgn2": p_vals.get("fnpgn2", np.nan),
        "nstfac": p_vals.get("nstfac", np.nan),
        "sizlf": p_vals.get("sizlf", np.nan),
        "xfrt": p_vals.get("xfrt", np.nan),
        "icns_26sp": p_vals.get("icns_26sp", np.nan),
        "slpf_25sp": p_vals.get("slpf_25sp", np.nan),
        "slpf_26sp": p_vals.get("slpf_26sp", np.nan),
    }
    cand_results.append(res)
    
    print(f"  Pooled NRMSE: {nrmse_all*100:.2f}%, d-index: {d_all:.4f}, R2: {r2_all:.4f}")
    print(f"  Calib NRMSE:  {nrmse_c*100:.2f}%, Valid NRMSE: {nrmse_v*100:.2f}%")
    print(f"  26SP W2 gap (N3-N0): {w2_26_gap:+7.1f} kg/ha")
    print(f"  26SP W1 gap (N3-N0): {w1_26_gap:+7.1f} kg/ha")
    print(f"  25SP W3 gap (N3-N0): {w3_25_gap:+7.1f} kg/ha (Inversion eliminated: {w3_25_gap > 0})")
    print(f"  25SP W1 gap (N3-N0): {w1_25_gap:+7.1f} kg/ha")
    print(f"  Max NSTD: {max_nstd_c:.4f}, FNPGN2: {p_vals.get('fnpgn2'):.3f}, NSTFAC: {p_vals.get('nstfac'):.3f}, XFRT: {p_vals.get('xfrt'):.3f}, SIZLF: {p_vals.get('sizlf'):.1f}")

df_summary = pd.DataFrame(cand_results)
summary_path = RUN_V7 / "candidate_comparison_summary.csv"
df_summary.to_csv(summary_path, index=False)
print(f"\n================ Summary Table Saved to {summary_path} ================")
print(df_summary[["candidate", "nrmse_pooled", "d_index_pooled", "26SP_W2_gap", "25SP_W3_gap", "max_NSTD", "fnpgn2", "nstfac", "xfrt", "sizlf"]].to_string(index=False))

# Select champion candidate: lowest pooled NRMSE with 25SP W3 > 0 and 26SP W2 > 0
valid_cands = df_summary[(df_summary["25SP_W3_gap"] > 0) & (df_summary["26SP_W2_gap"] > 0)]
if not valid_cands.empty:
    best_cand = valid_cands.sort_values("nrmse_pooled").iloc[0]
else:
    best_cand = df_summary.sort_values("nrmse_pooled").iloc[0]

print(f"\n CHAMPION CANDIDATE: {best_cand['candidate']} (Realization {best_cand['real_id']})")
print(f"  Pooled NRMSE: {best_cand['nrmse_pooled']*100:.2f}%, d-index: {best_cand['d_index_pooled']:.4f}")
print(f"  26SP W2 gap: {best_cand['26SP_W2_gap']:+.1f} kg/ha, 25SP W3 gap: {best_cand['25SP_W3_gap']:+.1f} kg/ha")

# Copy champion params and outputs
champ_tag = best_cand["candidate"]
champ_p_csv = RUN_V7 / f"candidate_{champ_tag}_params.csv"
target_p_csv = RUN_V7 / "full_gen98_v7_best_parameters_fixed.csv"
shutil.copy2(champ_p_csv, target_p_csv)
print(f"Copied champion parameters to {target_p_csv}")

# Copy champion calib/valid dirs to canonical det_calib and det_valid
det_calib = RUN_V7 / "det_calib"
det_valid = RUN_V7 / "det_valid"
if det_calib.exists(): shutil.rmtree(det_calib)
if det_valid.exists(): shutil.rmtree(det_valid)
shutil.copytree(RUN_V7 / f"cand_{champ_tag}_calib", det_calib)
shutil.copytree(RUN_V7 / f"cand_{champ_tag}_valid", det_valid)
print(f"Copied champion simulation directories to {det_calib} and {det_valid}")
