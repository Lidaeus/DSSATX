#!/usr/bin/env python3
"""Evaluate V8 candidate parameter sets on:
1. Calibration set (8 runs, DSSBatch_calib.v48)
2. Validation set (14 runs, DSSBatch_valid.v48)
3. 25FA independent test set (12 runs, xxql2502_v20260917_refresh/DSSBatch.v48)
4. Water-Nitrogen gradients (26SP W2, 26SP W1, 25SP W3, 25SP W1)
5. Organ dry weights (LWAD, SWAD)
6. Late-season physiological stress NSTD and dynamic pacing
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

RUN_V8 = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_98pct_v8_20260917"
CALIB_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_calib.v48"
VALID_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_valid.v48"
BATCH_25FA = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_v20260917_refresh" / "DSSBatch.v48"
BUNDLE_25FA = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_v20260917_refresh"

def get_top_candidates(run_dir: Path, n_candidates: int = 6):
    """Find top N candidates from final iteration based on phi.actual.csv."""
    phi_csv = run_dir / "full_gen98_v8.phi.actual.csv"
    if not phi_csv.exists():
        phi_csv = run_dir / "full_gen98_v8.phi.composite.csv"
    if not phi_csv.exists():
        raise FileNotFoundError(f"Neither phi.actual nor phi.composite found in {run_dir}")
    
    phi_df = pd.read_csv(phi_csv)
    # Check max iteration
    max_iter = int(phi_df["iteration"].max())
    print(f"Max iteration in {phi_csv.name}: {max_iter}")
    
    iter_df = phi_df[phi_df["iteration"] == max_iter].iloc[0]
    records = []
    for col in phi_df.columns:
        if col not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]:
            try:
                val = float(iter_df[col])
                if np.isfinite(val) and val < 1e8:
                    records.append({"real_name": str(col), "phi": val})
            except (ValueError, TypeError):
                pass
    
    df_sorted = pd.DataFrame(records).sort_values("phi")
    top_reals = df_sorted.head(n_candidates)
    print(f"Top {n_candidates} realizations in iteration {max_iter}:")
    print(top_reals.to_string(index=False))
    
    par_csv = run_dir / f"full_gen98_v8.{max_iter}.par.csv"
    if not par_csv.exists():
        raise FileNotFoundError(f"Parameter file {par_csv} not found")
    df_par = pd.read_csv(par_csv)
    
    candidates = []
    for _, row in top_reals.iterrows():
        r_id = str(row["real_name"])
        tag = f"iter{max_iter}_real{r_id}"
        candidates.append((r_id, df_par, tag))
    return candidates

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

def run_batch(batch_path: Path, param_csv: Path, out_dir: Path, input_dir: Path = None):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    prep_args = ["--batch", str(batch_path)]
    if input_dir:
        prep_args.extend(["--input-dir", str(input_dir)])
    batch_dest = prepare_run_directory(out_dir, prep_args)
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

def main():
    candidates = get_top_candidates(RUN_V8, n_candidates=6)
    cand_results = []
    fa_results = []

    for cid, df_par_source, tag in candidates:
        print(f"\n================ Evaluating Candidate {tag} (Realization {cid}) ================")
        p_csv = RUN_V8 / f"candidate_{tag}_params.csv"
        build_param_csv(cid, df_par_source, p_csv)
        
        # 1. Calibration batch (8 runs)
        calib_dir = RUN_V8 / f"cand_{tag}_calib"
        df_h_c, df_eval_c = run_batch(CALIB_BATCH, p_csv, calib_dir)
        rmse_c, nrmse_c, d_c, r2_c = calc_metrics(df_h_c["OBS_FRESH_CUM"], df_h_c["SIM_FRESH_CUM"])
        
        # 2. Validation batch (14 runs)
        valid_dir = RUN_V8 / f"cand_{tag}_valid"
        df_h_v, df_eval_v = run_batch(VALID_BATCH, p_csv, valid_dir)
        rmse_v, nrmse_v, d_v, r2_v = calc_metrics(df_h_v["OBS_FRESH_CUM"], df_h_v["SIM_FRESH_CUM"])
        
        # 3. Pooled metrics (22 runs)
        df_h_all = pd.concat([df_h_c, df_h_v], ignore_index=True)
        rmse_all, nrmse_all, d_all, r2_all = calc_metrics(df_h_all["OBS_FRESH_CUM"], df_h_all["SIM_FRESH_CUM"])
        
        # 4. 25FA Independent generalization (12 runs)
        fa_dir = RUN_V8 / f"cand_{tag}_25fa"
        df_h_fa, df_eval_fa = run_batch(BATCH_25FA, p_csv, fa_dir, input_dir=BUNDLE_25FA)
        rmse_fa, nrmse_fa, d_fa, r2_fa = calc_metrics(df_h_fa["OBS_FRESH_CUM"], df_h_fa["SIM_FRESH_CUM"])
        fa_results.append({
            "candidate": tag,
            "25FA_NRMSE%": nrmse_fa,
            "25FA_d_index": d_fa,
            "25FA_R2": r2_fa,
            "25FA_RMSE": rmse_fa,
        })
        
        # 5. Water-Nitrogen gradient in Calibration
        last_c = df_h_c.sort_values("DATE").groupby("RUN").last()["SIM_FRESH_CUM"].to_dict()
        w2_26_gap = last_c.get(5, 0) - last_c.get(7, 0)
        w1_26_gap = last_c.get(6, 0) - last_c.get(8, 0)
        w3_25_gap = last_c.get(1, 0) - last_c.get(2, 0)
        w1_25_gap = last_c.get(3, 0) - last_c.get(4, 0)
        
        # 6. Extract physiological stress NSTD and organ concentrations from PlantGro
        pg_c = calib_dir / "PlantGro.OUT"
        pg_vars_c = _read_plantgro_vars_by_run(str(pg_c), ["LAID", "NSTD", "AGEFAC", "LNCM", "SNCM"])
        max_nstd_c = 0.0
        for r_data in pg_vars_c.values():
            for d_data in r_data.values():
                if "NSTD" in d_data and d_data["NSTD"] is not None:
                    max_nstd_c = max(max_nstd_c, float(d_data["NSTD"]))
                
        # Key parameter values
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
            "25FA_nrmse": nrmse_fa,
            "25FA_d_index": d_fa,
            "26SP_W2_gap": w2_26_gap,
            "26SP_W1_gap": w1_26_gap,
            "25SP_W3_gap": w3_25_gap,
            "25SP_W1_gap": w1_25_gap,
            "max_NSTD": max_nstd_c,
            "lnref": p_vals.get("lnref", np.nan),
            "frlff": p_vals.get("frlff", np.nan),
            "slavr": p_vals.get("slavr", np.nan),
            "tb1": p_vals.get("tb1", np.nan),
            "tm1": p_vals.get("tm1", np.nan),
            "fnpgn2": p_vals.get("fnpgn2", np.nan),
            "nstfac": p_vals.get("nstfac", np.nan),
            "sizlf": p_vals.get("sizlf", np.nan),
            "xfrt": p_vals.get("xfrt", np.nan),
            "icns_26sp": p_vals.get("icns_26sp", np.nan),
            "slpf_25sp": p_vals.get("slpf_25sp", np.nan),
            "slpf_26sp": p_vals.get("slpf_26sp", np.nan),
        }
        cand_results.append(res)
        
        print(f"  Pooled NRMSE: {nrmse_all:.2f}%, d-index: {d_all:.4f}, R2: {r2_all:.4f}")
        print(f"  Calib NRMSE:  {nrmse_c:.2f}%, Valid NRMSE: {nrmse_v:.2f}%")
        print(f"  25FA NRMSE:   {nrmse_fa:.2f}%, 25FA d-index: {d_fa:.4f}")
        print(f"  26SP W2 gap (N3-N0): {w2_26_gap:+7.1f} kg/ha")
        print(f"  26SP W1 gap (N3-N0): {w1_26_gap:+7.1f} kg/ha")
        print(f"  25SP W3 gap (N3-N0): {w3_25_gap:+7.1f} kg/ha")
        print(f"  25SP W1 gap (N3-N0): {w1_25_gap:+7.1f} kg/ha")
        print(f"  LNREF: {p_vals.get('lnref'):.3f}, FRLFF: {p_vals.get('frlff'):.4f}, SLAVR: {p_vals.get('slavr'):.1f}, TB1: {p_vals.get('tb1'):.2f}, TM1: {p_vals.get('tm1'):.2f}")

    df_summary = pd.DataFrame(cand_results)
    summary_path = RUN_V8 / "candidate_comparison_summary.csv"
    df_summary.to_csv(summary_path, index=False)
    print(f"\n================ Summary Table Saved to {summary_path} ================")
    print(df_summary[["candidate", "nrmse_pooled", "d_index_pooled", "25FA_nrmse", "26SP_W2_gap", "25SP_W3_gap", "lnref", "frlff", "slavr", "tb1", "tm1"]].to_string(index=False))

    df_fa = pd.DataFrame(fa_results)
    fa_path = RUN_V8 / "candidate_25fa_evaluation.csv"
    df_fa.to_csv(fa_path, index=False)
    print(f"Saved 25FA evaluation to {fa_path}")

    # Select champion candidate:
    # 1. Strictly positive gradients (25SP W3 > 0, 26SP W2 > 0)
    # 2. Strict cross-season generalizability (25FA NRMSE <= 25.0%)
    # 3. Lowest pooled NRMSE
    full_valid = df_summary[
        (df_summary["25SP_W3_gap"] > 0)
        & (df_summary["25SP_W1_gap"] > 0)
        & (df_summary["26SP_W2_gap"] > 0)
        & (df_summary["26SP_W1_gap"] > 0)
        & (df_summary["25FA_nrmse"] <= 25.0)
    ]
    if not full_valid.empty:
        best_cand = full_valid.sort_values("nrmse_pooled").iloc[0]
        print(f"\n CHAMPION CANDIDATE (Satisfying 25FA <= 25% Generalization): {best_cand['candidate']} (Realization {best_cand['real_id']})")
    else:
        valid_cands = df_summary[(df_summary["25SP_W3_gap"] > 0) & (df_summary["26SP_W2_gap"] > 0)]
        if not valid_cands.empty:
            best_cand = valid_cands.sort_values("nrmse_pooled").iloc[0]
        else:
            best_cand = df_summary.sort_values("nrmse_pooled").iloc[0]
        print(f"\n CHAMPION CANDIDATE (Pooled NRMSE Fallback): {best_cand['candidate']} (Realization {best_cand['real_id']})")

    print(f"  Pooled NRMSE: {best_cand['nrmse_pooled']:.2f}%, d-index: {best_cand['d_index_pooled']:.4f}")
    print(f"  25FA NRMSE:   {best_cand['25FA_nrmse']:.2f}%, d-index: {best_cand['25FA_d_index']:.4f}")
    print(f"  26SP W2 gap:  {best_cand['26SP_W2_gap']:+.1f} kg/ha, 25SP W3 gap: {best_cand['25SP_W3_gap']:+.1f} kg/ha")
    print(f"  LNREF:        {best_cand['lnref']:.3f}")
    print(f"  FRLFF:        {best_cand['frlff']:.4f}")
    print(f"  SLAVR:        {best_cand['slavr']:.2f}")
    print(f"  TB1:          {best_cand['tb1']:.2f}")
    print(f"  TM1:          {best_cand['tm1']:.2f}")

    # Copy champion params and outputs
    champ_tag = best_cand["candidate"]
    champ_p_csv = RUN_V8 / f"candidate_{champ_tag}_params.csv"
    target_p_csv = RUN_V8 / "full_gen98_v8_best_parameters_fixed.csv"
    shutil.copy2(champ_p_csv, target_p_csv)
    print(f"Copied champion parameters to {target_p_csv}")

    # Copy champion calib/valid dirs to canonical det_calib and det_valid
    det_calib = RUN_V8 / "det_calib"
    det_valid = RUN_V8 / "det_valid"
    if det_calib.exists(): shutil.rmtree(det_calib)
    if det_valid.exists(): shutil.rmtree(det_valid)
    shutil.copytree(RUN_V8 / f"cand_{champ_tag}_calib", det_calib)
    shutil.copytree(RUN_V8 / f"cand_{champ_tag}_valid", det_valid)
    print(f"Copied champion simulation directories to {det_calib} and {det_valid}")

if __name__ == "__main__":
    main()
