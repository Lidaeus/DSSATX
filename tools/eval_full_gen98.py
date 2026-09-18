import os
import sys
import shutil
import numpy as np
import pandas as pd
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.run_dssat import prepare_run_directory
from src.reporting.analyze_results import (
    _parse_batch_entries,
    _read_tmt_harvest_obs,
    _read_freshwt_var_by_run,
    _yyddd_add_days,
    _nearest_on_or_before,
    _infer_excode_from_filex,
    _read_evaluate_out,
)

def run_deterministic(batch_path: Path, param_csv: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_dest = prepare_run_directory(out_dir, ["--batch", str(batch_path)])
    
    # Run DSSAT
    import subprocess
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
    print(f"Running deterministic simulation in {out_dir} with batch {batch_dest.name}...")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    res = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        print("STDOUT:", res.stdout[-1000:] if res.stdout else "")
        print("STDERR:", res.stderr[-1000:] if res.stderr else "")
        raise RuntimeError(f"DSSAT execution failed in {out_dir} with exit code {res.returncode}")
    print("Simulation completed successfully.")

def evaluate_run(batch_path: Path, out_dir: Path):
    entries = _parse_batch_entries(str(batch_path))
    freshwt_path = out_dir / "FreshWt.OUT"
    eval_path = out_dir / "Evaluate.OUT"
    plantgro_path = out_dir / "PlantGro.OUT"
    
    sim_chfpw = _read_freshwt_var_by_run(str(freshwt_path), "CHFPW")
    sim_chpdt = _read_freshwt_var_by_run(str(freshwt_path), "CHPDT")
    
    harvest_rows = []
    
    for e in entries:
        run_no = int(e["run"])
        tn = int(e.get("tn", -99))
        filex = e["filex"]
        filex_name = Path(filex).name
        excode = filex_name.rsplit(".", 1)[0]
        
        # Look for TMT in out_dir or data/raw/experiments
        tmt_cand = out_dir / f"{excode}.TMT"
        if not tmt_cand.exists():
            tmt_cand = PROJECT_ROOT / "data" / "raw" / "experiments" / f"{excode}.TMT"
            
        obs_by_tn = _read_tmt_harvest_obs(str(tmt_cand))
        obs_events = obs_by_tn.get(tn, [])
        
        prev_sim_fresh = None
        for ev in obs_events:
            date = int(ev["DATE"])
            sim_date = _yyddd_add_days(date, 1)
            sim_fresh_cum = _nearest_on_or_before(sim_chfpw.get(run_no, {}), sim_date)
            sim_fresh_cum = float(sim_fresh_cum) if sim_fresh_cum is not None else np.nan
            
            if prev_sim_fresh is None or np.isnan(prev_sim_fresh):
                sim_fresh_inc = sim_fresh_cum
            elif np.isnan(sim_fresh_cum):
                sim_fresh_inc = np.nan
            else:
                sim_fresh_inc = sim_fresh_cum - prev_sim_fresh
                
            prev_sim_fresh = sim_fresh_cum
            
            harvest_rows.append({
                "RUN": run_no,
                "TN": tn,
                "FILEX": filex_name,
                "EXCODE": excode,
                "DATE": date,
                "OBS_FRESH_CUM": ev.get("OBS_FRESH_CUM", np.nan),
                "OBS_FRESH_INC": ev.get("OBS_FRESH_INC", np.nan),
                "SIM_FRESH_CUM": sim_fresh_cum,
                "SIM_FRESH_INC": sim_fresh_inc,
            })
            
    df_h = pd.DataFrame(harvest_rows)
    
    # Also parse Evaluate.OUT for LAIX
    df_eval = pd.DataFrame()
    if eval_path.exists():
        df_eval = _read_evaluate_out(str(eval_path))
        
    return df_h, df_eval

def calc_metrics(obs, sim):
    mask = np.isfinite(obs) & np.isfinite(sim) & (obs > 0)
    o = obs[mask].to_numpy()
    s = sim[mask].to_numpy()
    if len(o) == 0:
        return np.nan, np.nan, np.nan, np.nan
    rmse = np.sqrt(np.mean((s - o)**2))
    nrmse = rmse / np.mean(o) * 100.0
    mae = np.mean(np.abs(s - o))
    
    # d-index (Willmott 1981)
    o_mean = np.mean(o)
    denom = np.sum((np.abs(s - o_mean) + np.abs(o - o_mean))**2)
    if denom > 0:
        d_index = 1.0 - (np.sum((s - o)**2) / denom)
    else:
        d_index = np.nan
        
    # R2
    if len(o) > 1 and np.std(o) > 0 and np.std(s) > 0:
        r = np.corrcoef(o, s)[0, 1]
        r2 = r**2
    else:
        r2 = np.nan
        
    return rmse, nrmse, d_index, r2

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=PROJECT_ROOT / "workspace" / "runs" / "full_genetic_98pct_v2_20260915")
    parser.add_argument("--param-csv", type=Path, default=None)
    args = parser.parse_args()

    run_dir = args.run_dir
    if args.param_csv:
        param_csv = args.param_csv
    else:
        candidates = [
            run_dir / f"{run_dir.name}_best_parameters_fixed.csv",
            run_dir / "full_gen98_v9_best_parameters_fixed.csv",
            run_dir / "full_gen98_v8_best_parameters_fixed.csv",
            run_dir / "full_gen98_v2_best_parameters_fixed.csv",
            run_dir / "full_gen98_best_parameters_fixed.csv",
            PROJECT_ROOT / "workspace" / "runs" / "full_gen98_v2_best_parameters_fixed.csv",
            PROJECT_ROOT / "workspace" / "runs" / "full_gen98_best_parameters_fixed.csv",
        ]
        param_csv = None
        for c in candidates:
            if c.exists():
                param_csv = c
                break
        if not param_csv:
            matches = list(run_dir.glob("*_best_parameters_fixed.csv"))
            if matches:
                param_csv = matches[0]
            else:
                raise FileNotFoundError(f"Could not find best_parameters_fixed.csv in {run_dir}")
        
    calib_batch = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_calib.v48"
    valid_batch = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_valid.v48"
    
    det_calib_dir = run_dir / "det_calib"
    det_valid_dir = run_dir / "det_valid"
    
    # 1. Run calib
    run_deterministic(calib_batch, param_csv, det_calib_dir)
    df_h_cal, df_eval_cal = evaluate_run(calib_batch, det_calib_dir)
    
    # 2. Run valid
    run_deterministic(valid_batch, param_csv, det_valid_dir)
    df_h_val, df_eval_val = evaluate_run(valid_batch, det_valid_dir)
    
    print("\n" + "="*60)
    print("--- CALIBRATION METRICS (Cumulative Fresh Yield CHFPW) ---")
    rmse_c, nrmse_c, d_c, r2_c = calc_metrics(df_h_cal["OBS_FRESH_CUM"], df_h_cal["SIM_FRESH_CUM"])
    print(f"Calibration CHFPW NRMSE: {nrmse_c:.2f}% (Threshold <= 18%)")
    print(f"Calibration CHFPW d-index: {d_c:.4f} (Threshold >= 0.92)")
    print(f"Calibration CHFPW RMSE: {rmse_c:.2f} kg/ha")
    print(f"Calibration CHFPW R2: {r2_c:.4f}")
    
    # Incremental fresh yield R2 (all calibration)
    _, _, _, r2_inc_cal = calc_metrics(df_h_cal["OBS_FRESH_INC"], df_h_cal["SIM_FRESH_INC"])
    print(f"Calibration Incremental Fresh Yield R2: {r2_inc_cal:.4f} (Threshold >= 0.50)")
    
    print("\n" + "="*60)
    print("--- VALIDATION METRICS (Cumulative Fresh Yield CHFPW) ---")
    rmse_v, nrmse_v, d_v, r2_v = calc_metrics(df_h_val["OBS_FRESH_CUM"], df_h_val["SIM_FRESH_CUM"])
    print(f"Validation CHFPW NRMSE: {nrmse_v:.2f}% (Threshold <= 20%)")
    print(f"Validation CHFPW d-index: {d_v:.4f} (Threshold >= 0.92)")
    print(f"Validation CHFPW RMSE: {rmse_v:.2f} kg/ha")
    print(f"Validation CHFPW R2: {r2_v:.4f}")
    
    # Incremental fresh yield R2 (all validation)
    _, _, _, r2_inc_val = calc_metrics(df_h_val["OBS_FRESH_INC"], df_h_val["SIM_FRESH_INC"])
    print(f"Validation Incremental Fresh Yield R2: {r2_inc_val:.4f}")
    
    # Overall pooled metrics
    df_all_h = pd.concat([df_h_cal, df_h_val], ignore_index=True)
    _, nrmse_all, d_all, r2_all = calc_metrics(df_all_h["OBS_FRESH_CUM"], df_all_h["SIM_FRESH_CUM"])
    _, _, _, r2_inc_all = calc_metrics(df_all_h["OBS_FRESH_INC"], df_all_h["SIM_FRESH_INC"])
    print("\n" + "="*60)
    print("--- COMBINED (Calib + Valid) METRICS ---")
    print(f"Combined CHFPW NRMSE: {nrmse_all:.2f}%")
    print(f"Combined CHFPW d-index: {d_all:.4f}")
    print(f"Combined Incremental Fresh Yield R2: {r2_inc_all:.4f}")
    
    # Peak LAIX bias
    print("\n" + "="*60)
    print("--- LAIX PEAK BIAS ---")
    for label, df_ev in [("Calib", df_eval_cal), ("Valid", df_eval_val)]:
        if not df_ev.empty and "LAIXM" in df_ev.columns and "LAIXS" in df_ev.columns:
            m = pd.to_numeric(df_ev["LAIXM"], errors="coerce")
            s = pd.to_numeric(df_ev["LAIXS"], errors="coerce")
            mask = np.isfinite(m) & np.isfinite(s) & (m > 0)
            if mask.any():
                bias = np.mean(s[mask] - m[mask])
                print(f"{label} Peak LAIX Bias: {bias:+.3f} (Threshold |Bias| <= 0.50)")
                
    # W-N Orthogonal Contrasts in Calibration
    print("\n" + "="*60)
    print("--- W-N ORTHOGONAL CONTRASTS & MONOTONIC PENALTIES ---")
    # In calib batch:
    # RUN 1: 25SP TRT 2 (W3 N3)
    # RUN 2: 25SP TRT 5 (W3 N0)
    # RUN 3: 25SP TRT 10 (W1 N3)
    # RUN 4: 25SP TRT 13 (W1 N0)
    # RUN 5: 26SP TRT 2 (W2 N3)
    # RUN 6: 26SP TRT 3 (W1 N3)
    # RUN 7: 26SP TRT 11 (W2 N0)
    # RUN 8: 26SP TRT 12 (W1 N0)
    # Read final cumulative yield from df_h_cal for each run
    final_yields = {}
    for r, grp in df_h_cal.groupby("RUN"):
        final_yields[r] = grp.sort_values("DATE").iloc[-1]["SIM_FRESH_CUM"]
        
    y_25_w3_n3 = final_yields.get(1, np.nan)
    y_25_w3_n0 = final_yields.get(2, np.nan)
    y_25_w1_n3 = final_yields.get(3, np.nan)
    y_25_w1_n0 = final_yields.get(4, np.nan)
    
    y_26_w2_n3 = final_yields.get(5, np.nan)
    y_26_w1_n3 = final_yields.get(6, np.nan)
    y_26_w2_n0 = final_yields.get(7, np.nan)
    y_26_w1_n0 = final_yields.get(8, np.nan)
    
    d_25_w3 = y_25_w3_n3 - y_25_w3_n0
    d_25_w1 = y_25_w1_n3 - y_25_w1_n0
    d_26_w2 = y_26_w2_n3 - y_26_w2_n0
    d_26_w1 = y_26_w1_n3 - y_26_w1_n0
    
    print(f"25SP W3: N0={y_25_w3_n0:.1f}, N3={y_25_w3_n3:.1f}, Delta={d_25_w3:+.1f} kg/ha (Target > 0)")
    print(f"25SP W1: N0={y_25_w1_n0:.1f}, N3={y_25_w1_n3:.1f}, Delta={d_25_w1:+.1f} kg/ha (Target > 0)")
    print(f"26SP W2: N0={y_26_w2_n0:.1f}, N3={y_26_w2_n3:.1f}, Delta={d_26_w2:+.1f} kg/ha (Target >= 8000)")
    print(f"26SP W1: N0={y_26_w1_n0:.1f}, N3={y_26_w1_n3:.1f}, Delta={d_26_w1:+.1f} kg/ha (Target > 0)")
    
    pen_mono_25_w3 = max(0.0, y_25_w3_n0 - y_25_w3_n3)
    pen_mono_25_w1 = max(0.0, y_25_w1_n0 - y_25_w1_n3)
    pen_mono_26_w2 = max(0.0, y_26_w2_n0 - y_26_w2_n3)
    pen_mono_26_w1 = max(0.0, y_26_w1_n0 - y_26_w1_n3)
    total_mono_pen = pen_mono_25_w3 + pen_mono_25_w1 + pen_mono_26_w2 + pen_mono_26_w1
    print(f"Total Monotonic Inversion Penalty: {total_mono_pen:.2f} (Target = 0.0)")
    
    # Save evaluation summary CSVs
    df_h_cal.to_csv(run_dir / "det_calib_harvest_eval.csv", index=False)
    df_h_val.to_csv(run_dir / "det_valid_harvest_eval.csv", index=False)
    print(f"\nSaved evaluation CSVs to {run_dir}")

if __name__ == "__main__":
    main()
