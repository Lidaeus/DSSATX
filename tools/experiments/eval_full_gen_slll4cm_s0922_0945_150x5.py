#!/usr/bin/env python3
"""Comprehensive evaluation and screening script for full_gen_slll4cm_s0922_0945_150x5.

Screening rules (Gate 4 cancelled per user request):
- Gate 1: 25SP W1 N response >= 20% (Delta Y_W1 >= 2,046 kg/ha, obs=11,590 kg/ha)
- Gate 2: 25SP W3N0 end LAI >= 1.20
- Gate 3: 26SP high-N ceiling suppressed (Y_26SP_W2N3 <= 75,000 and Y_26SP_W1N3 <= 75,000 kg/ha)
- Multi-season evaluation: 25SP (11 trt), 26SP (12 trt), 25FA (12 trt) = 35 treatments total.
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

RUN_DIR = PROJECT_ROOT / "workspace/runs/full_gen_slll4cm_s0922_0945_150x5_20260919"
CASE = "full_gen_slll4cm_s0922_0945_150x5"

from src.calibration.run_dssat import prepare_run_directory
from tools.eval_full_gen98 import evaluate_run, calc_metrics

def analyze_phi(run_dir: Path, case: str):
    phi_actual = run_dir / f"{case}.phi.actual.csv"
    phi_meas = run_dir / f"{case}.phi.meas.csv"
    target = phi_actual if phi_actual.exists() else phi_meas
    if not target.exists():
        print("Phi file not found.")
        return None
    df_phi = pd.read_csv(target)
    print(f"\n=== Phi Progression ({target.name}) ===")
    std_col = "standard_deviation" if "standard_deviation" in df_phi.columns else "std"
    print(df_phi[["iteration", "mean", "min", "max", std_col]].to_string(index=False))
    return df_phi

def extract_realizations_by_phi(run_dir: Path, case: str, iter_no: int = 5):
    par_file = run_dir / f"{case}.{iter_no}.par.csv"
    df_par = pd.read_csv(par_file)
    df_par["real_name"] = df_par["real_name"].astype(str)
    
    # Check phi group for ranking
    phi_grp = pd.read_csv(run_dir / f"{case}.phi.group.csv")
    sub = phi_grp[phi_grp["iteration"] == iter_no].copy()
    grp_cols = [c for c in sub.columns if c not in ["iteration", "total_runs", "obs_realization", "par_realization"]]
    sub["total_phi"] = sub[grp_cols].sum(axis=1)
    sub["par_realization"] = sub["par_realization"].astype(str)
    
    merged = df_par.merge(sub[["par_realization", "total_phi"]], left_on="real_name", right_on="par_realization", how="left")
    merged = merged.sort_values("total_phi")
    print(f"Loaded and ranked {len(merged)} realizations from iter {iter_no}. Min Phi: {merged['total_phi'].min():.2f}")
    return merged, iter_no

def run_single_eval(param_series: pd.Series, out_dir: Path, batch_template: Path):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    
    # Save params to CSV
    param_df = pd.DataFrame({"name": param_series.index, "value": param_series.values})
    param_csv = out_dir / "params.csv"
    param_df.to_csv(param_csv, index=False)
    
    batch_dest = prepare_run_directory(out_dir, ["--batch", str(batch_template)])
    
    # Run DSSAT
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
        return None
        
    df_h, df_eval = evaluate_run(batch_dest, out_dir)
    return df_h, df_eval

def screen_candidates(df_par: pd.DataFrame, iter_no: int, max_reals: int = 50):
    screen_dir = RUN_DIR / "screening"
    screen_dir.mkdir(exist_ok=True)
    
    calib_batch = PROJECT_ROOT / "data/templates/batch/DSSBatch_calib.v48"
    
    records = []
    print(f"\nStarting screening across top {min(len(df_par), max_reals)} realizations from iter {iter_no}...")
    
    for idx, row in df_par.head(max_reals).reset_index().iterrows():
        real_name = str(row["real_name"])
        cur_phi = row["total_phi"] if "total_phi" in row else np.nan
        
        real_dir = screen_dir / f"cand_{real_name}"
        drop_cols = ["real_name", "par_realization", "total_phi", "index"]
        p_row = row.drop(drop_cols, errors="ignore")
        
        res = run_single_eval(p_row, real_dir, calib_batch)
        if res is None:
            continue
        df_h, _ = res
        
        # 25SP: XXQL2501
        df_25 = df_h[df_h["EXCODE"] == "XXQL2501"]
        last_25 = df_25.sort_values("DATE").groupby("TN").last().reset_index()
        y25_dict = dict(zip(last_25["TN"].astype(int), last_25["SIM_FRESH_CUM"]))
        y_25_w1n3 = y25_dict.get(10, np.nan)
        y_25_w1n0 = y25_dict.get(13, np.nan)
        delta_25_w1 = y_25_w1n3 - y_25_w1n0
        w1_ratio = (delta_25_w1 / 11590.0) * 100.0
        
        # 26SP: XXQL2601
        df_26 = df_h[df_h["EXCODE"] == "XXQL2601"]
        last_26 = df_26.sort_values("DATE").groupby("TN").last().reset_index()
        y26_dict = dict(zip(last_26["TN"].astype(int), last_26["SIM_FRESH_CUM"]))
        y_26_w2n3 = y26_dict.get(2, np.nan)
        y_26_w1n3 = y26_dict.get(3, np.nan)
        
        # Calib 8-treatment metrics
        last_all = df_h.sort_values("DATE").groupby(["EXCODE", "TN"]).last().reset_index()
        rmse_c, nrmse_c, d_c, r2_c = calc_metrics(last_all["OBS_FRESH_CUM"], last_all["SIM_FRESH_CUM"])
        
        # LAI of 25SP W3N0 from PlantGro.OUT (RUN 2)
        pg_file = real_dir / "PlantGro.OUT"
        lai_w3n0 = np.nan
        if pg_file.exists():
            with open(pg_file, encoding="latin1") as f:
                cur_run = None
                last_l = None
                for line in f:
                    if line.startswith("*RUN"):
                        if cur_run == 2 and last_l:
                            lai_w3n0 = float(last_l.split()[6])
                        cur_run = int(line.split()[1])
                        last_l = None
                    elif cur_run == 2 and len(line.split()) > 20 and line.strip()[0].isdigit():
                        last_l = line
                if cur_run == 2 and last_l:
                    lai_w3n0 = float(last_l.split()[6])
                    
        # Check Gates
        gate1_pass = (w1_ratio >= 20.0)
        gate2_pass = (lai_w3n0 >= 1.20)
        gate3_pass = (y_26_w2n3 <= 75000.0 and y_26_w1n3 <= 75000.0)
        all_pass = gate1_pass and gate2_pass and gate3_pass
        
        rec = {
            "real_name": real_name,
            "phi": cur_phi,
            "Calib_NRMSE_pct": round(nrmse_c, 2),
            "Calib_d": round(d_c, 4),
            "Delta_Y_W1_25SP": round(delta_25_w1, 1),
            "W1_N_ratio_pct": round(w1_ratio, 2),
            "LAI_W3N0_end": round(lai_w3n0, 2),
            "Y_26SP_W2N3": round(y_26_w2n3, 1),
            "Y_26SP_W1N3": round(y_26_w1n3, 1),
            "gate1_w1_20pct": gate1_pass,
            "gate2_lai_1p2": gate2_pass,
            "gate3_high_n_75t": gate3_pass,
            "all_gates_pass": all_pass,
        }
        records.append(rec)
        print(f"[{idx+1:02d}] {real_name}: Phi={cur_phi:.1f}, Calib NRMSE={nrmse_c:.2f}%, W1_ratio={w1_ratio:.1f}%, LAI_N0={lai_w3n0:.2f}, 26_W2N3={y_26_w2n3/1000:.1f}t | Pass={all_pass}")
        
    df_res = pd.DataFrame(records)
    df_res.to_csv(RUN_DIR / "screening_results.csv", index=False)
    print(f"\nScreening complete! Saved to {RUN_DIR / 'screening_results.csv'}")
    return df_res

def main():
    print(f"Evaluating run: {RUN_DIR}")
    df_phi = analyze_phi(RUN_DIR, CASE)
    if df_phi is None:
        return
    df_par, best_iter = extract_realizations_by_phi(RUN_DIR, CASE)
    df_screen = screen_candidates(df_par, best_iter, max_reals=50)

if __name__ == "__main__":
    main()
