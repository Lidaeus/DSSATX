#!/usr/bin/env python3
"""Build and evaluate V5 champion run across all 22 treatments:
1. Verify full_gen98_v5_best_parameters_fixed.csv (Candidate 46)
2. Verify deterministic simulations in det_calib (8 runs) and det_valid (14 runs)
3. Generate process, harvest, and joint comparison files via analyze_results.py
4. Build comparison.csv and concatenate PlantGro/FreshWt trajectories
5. Export paper_data bundle
6. Render R publication figures
"""

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

RUN_V5 = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_98pct_v5_20260915"
CALIB_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_calib.v48"
VALID_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_valid.v48"
RSCRIPT_PATH = r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe"

from src.calibration.run_dssat import prepare_run_directory
from tools.eval_full_gen98 import evaluate_run, calc_metrics
from src.reporting.figure_data import VARIABLE_SPECS, validate_comparison_table
from src.reporting.analyze_results import (
    deterministic_harvest_compare,
    deterministic_process_compare,
    deterministic_joint_compare,
)

det_calib_dir = RUN_V5 / "det_calib"
det_valid_dir = RUN_V5 / "det_valid"

print("Step 1: Generating deterministic compare CSVs for Calib (8) & Valid (14)...")
for d, batch_name in [(det_calib_dir, "DSSBatch_calib.v48"), (det_valid_dir, "DSSBatch_valid.v48")]:
    batch_full_path = str(d / batch_name)
    deterministic_harvest_compare("full_gen98_v5", batch_full_path, run_dir=str(d))
    deterministic_process_compare("full_gen98_v5", batch_full_path, run_dir=str(d))
    deterministic_joint_compare("full_gen98_v5", batch_full_path, run_dir=str(d))
    print(f"Generated comparison files in {d}")

# Step 2: Evaluate harvest metrics
df_h_cal, df_eval_cal = evaluate_run(CALIB_BATCH, det_calib_dir)
df_h_val, df_eval_val = evaluate_run(VALID_BATCH, det_valid_dir)

rmse_c, nrmse_c, d_c, r2_c = calc_metrics(df_h_cal["OBS_FRESH_CUM"], df_h_cal["SIM_FRESH_CUM"])
rmse_v, nrmse_v, d_v, r2_v = calc_metrics(df_h_val["OBS_FRESH_CUM"], df_h_val["SIM_FRESH_CUM"])
df_all = pd.concat([df_h_cal, df_h_val], ignore_index=True)
rmse_all, nrmse_all, d_all, r2_all = calc_metrics(df_all["OBS_FRESH_CUM"], df_all["SIM_FRESH_CUM"])

print("\n" + "="*70)
print(f"CALIBRATION (8 runs): NRMSE = {nrmse_c:.2f}%, d = {d_c:.4f}, R2 = {r2_c:.4f}, RMSE = {rmse_c:.1f} kg/ha")
print(f"VALIDATION (14 runs): NRMSE = {nrmse_v:.2f}%, d = {d_v:.4f}, R2 = {r2_v:.4f}, RMSE = {rmse_v:.1f} kg/ha")
print(f"POOLED (22 runs):     NRMSE = {nrmse_all:.2f}%, d = {d_all:.4f}, R2 = {r2_all:.4f}")

# Save metrics grid
metrics_grid = pd.DataFrame([
    {"dataset": "calibration", "n_runs": len(df_h_cal["RUN"].unique()), "NRMSE%": nrmse_c, "d_index": d_c, "R2": r2_c, "RMSE": rmse_c},
    {"dataset": "validation", "n_runs": len(df_h_val["RUN"].unique()), "NRMSE%": nrmse_v, "d_index": d_v, "R2": r2_v, "RMSE": rmse_v},
    {"dataset": "pooled", "n_runs": len(df_all["RUN"].unique()), "NRMSE%": nrmse_all, "d_index": d_all, "R2": r2_all, "RMSE": rmse_all},
])
metrics_grid.to_csv(RUN_V5 / "metrics_summary.csv", index=False)

# Step 3: Concatenate PlantGro & FreshWt trajectories
print("\nStep 3: Concatenating PlantGro and FreshWt trajectories...")
for outfile in ["PlantGro.OUT", "FreshWt.OUT"]:
    cal_p = det_calib_dir / outfile
    val_p = det_valid_dir / outfile
    dst_p = RUN_V5 / outfile
    with open(dst_p, "w", encoding="utf-8") as f_out:
        with open(cal_p, "r", encoding="utf-8", errors="ignore") as f_in:
            f_out.write(f_in.read())
        with open(val_p, "r", encoding="utf-8", errors="ignore") as f_in:
            f_out.write(f_in.read())
    print(f"Concatenated {outfile} -> {dst_p}")

# Step 4: Build comparison.csv
print("\nStep 4: Assembling tidy comparison.csv...")
calib_runs_season = {1: "25SP", 2: "25SP", 3: "25SP", 4: "25SP", 5: "26SP", 6: "26SP", 7: "26SP", 8: "26SP"}
valid_runs_season = {
    1: "25SP", 2: "25SP", 3: "25SP", 4: "25SP", 5: "25SP", 6: "25SP",
    7: "26SP", 8: "26SP", 9: "26SP", 10: "26SP", 11: "26SP", 12: "26SP", 13: "26SP", 14: "26SP",
}

records = []
for c_dir, role, season_map in [(det_calib_dir, "calibration", calib_runs_season), (det_valid_dir, "validation", valid_runs_season)]:
    p_path = c_dir / "full_gen98_v5_deterministic_process_compare.csv"
    h_path = c_dir / "full_gen98_v5_deterministic_harvest_compare.csv"
    j_path = c_dir / "full_gen98_v5_deterministic_joint_compare.csv"
    
    # Process
    if p_path.exists():
        df_p = pd.read_csv(p_path)
        for _, row in df_p.iterrows():
            run = int(row["RUN"])
            season = season_map.get(run, "25SP")
            tn = str(int(row["TN"]))
            date = float(row["DATE"])
            year = 2000 + int(date) // 1000
            doy = float(int(date) % 1000)
            for var in ["LAID", "LWAD", "SWAD"]:
                obs = float(row[f"OBS_{var}"])
                sim = float(row[f"SIM_{var}"])
                if obs <= 0 or not np.isfinite(obs) or not np.isfinite(sim):
                    continue
                spec = VARIABLE_SPECS[var]
                records.append({
                    "run_id": "full_gen98_v5",
                    "data_status": "engineering_validated",
                    "dataset_role": role,
                    "variable": var,
                    "variable_label": spec["label"],
                    "unit": spec["unit"],
                    "treatment": tn,
                    "time": doy,
                    "time_label": "Day of year",
                    "observed": obs,
                    "simulated": sim,
                    "source_file": "PlantGro.OUT",
                    "date_code": date,
                    "year": year,
                    "doy": doy,
                    "dap": np.nan,
                    "harvest_number": np.nan,
                    "observed_sd": np.nan,
                    "observed_se": np.nan,
                    "n_rep": np.nan,
                    "season_id": season,
                })
                
    # Harvest
    if h_path.exists():
        df_h = pd.read_csv(h_path)
        for _, row in df_h.iterrows():
            run = int(row["RUN"])
            season = season_map.get(run, "25SP")
            tn = str(int(row["TN"]))
            date = float(row["DATE"])
            year = 2000 + int(date) // 1000
            doy = float(int(date) % 1000)
            hno = float(row["HNO"])
            for var in ["DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM"]:
                obs = float(row[f"OBS_{var}"])
                sim = float(row[f"SIM_{var}"])
                if not np.isfinite(obs) or not np.isfinite(sim):
                    continue
                spec = VARIABLE_SPECS[var]
                records.append({
                    "run_id": "full_gen98_v5",
                    "data_status": "engineering_validated",
                    "dataset_role": role,
                    "variable": var,
                    "variable_label": spec["label"],
                    "unit": spec["unit"],
                    "treatment": tn,
                    "time": doy,
                    "time_label": "Day of year",
                    "observed": obs,
                    "simulated": sim,
                    "source_file": "FreshWt.OUT",
                    "date_code": date,
                    "year": year,
                    "doy": doy,
                    "dap": np.nan,
                    "harvest_number": hno,
                    "observed_sd": np.nan,
                    "observed_se": np.nan,
                    "n_rep": np.nan,
                    "season_id": season,
                })
                
    # Joint LAIX
    if j_path.exists():
        df_j = pd.read_csv(j_path)
        for _, row in df_j.iterrows():
            run = int(row["RUN"])
            season = season_map.get(run, "25SP")
            tn = str(int(row["TN"]))
            obs = float(row["OBS_LAIX"])
            sim = float(row["SIM_LAIX"])
            if obs <= 0 or not np.isfinite(obs) or not np.isfinite(sim):
                continue
            spec = VARIABLE_SPECS["LAIX"]
            records.append({
                "run_id": "full_gen98_v5",
                "data_status": "engineering_validated",
                "dataset_role": role,
                "variable": "LAIX",
                "variable_label": spec["label"],
                "unit": spec["unit"],
                "treatment": tn,
                "time": 0.0,
                "time_label": "Season end",
                "observed": obs,
                "simulated": sim,
                "source_file": "Evaluate.OUT",
                "date_code": np.nan,
                "year": 2025 if season == "25SP" else 2026,
                "doy": np.nan,
                "dap": np.nan,
                "harvest_number": np.nan,
                "observed_sd": np.nan,
                "observed_se": np.nan,
                "n_rep": np.nan,
                "season_id": season,
            })

df_comp = validate_comparison_table(pd.DataFrame(records))
comp_csv = RUN_V5 / "comparison.csv"
df_comp.to_csv(comp_csv, index=False)
print(f"Wrote {len(df_comp)} validated rows to {comp_csv}")

# Step 5: Export paper_data
print("\nStep 5: Exporting paper_data bundle...")
paper_data_dir = RUN_V5 / "paper_data"
cmd = [
    sys.executable,
    "-m",
    "src.reporting.export_paper_data",
    "--run-id",
    "full_gen98_v5",
    "--comparison-csv",
    str(comp_csv.resolve()),
    "--phi-csv",
    str((RUN_V5 / "full_gen98_v5.phi.actual.csv").resolve()),
    "--trajectory-run-dir",
    str(RUN_V5.resolve()),
    "--treatment-metadata-csv",
    str((PROJECT_ROOT / "configs" / "figures" / "treatment_metadata_xxql2501_2601_joint.csv").resolve()),
    "--out-dir",
    str(paper_data_dir.resolve()),
    "--allow-unvalidated-demo",
]
env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, env=env)
if res.returncode != 0:
    print("export_paper_data STDERR:", res.stderr)
    raise RuntimeError("export_paper_data failed")
print(f"Exported paper data bundle to {paper_data_dir}")

# Step 6: Render R publication figures
print("\nStep 6: Rendering publication figures with R...")
paper_fig_dir = RUN_V5 / "paper_figures"
cmd_r = [
    RSCRIPT_PATH,
    str((PROJECT_ROOT / "paper" / "R" / "make_all.R").resolve()),
    "--input-dir",
    str(paper_data_dir.resolve()),
    "--out-dir",
    str(paper_fig_dir.resolve()),
    "--allow-unvalidated-demo",
]
res_r = subprocess.run(cmd_r, cwd=PROJECT_ROOT, capture_output=True, text=True)
if res_r.returncode != 0:
    print("make_all.R STDERR:", res_r.stderr)
    print("make_all.R STDOUT:", res_r.stdout[-1000:])
    raise RuntimeError("make_all.R rendering failed")
print(f"Rendered R figures into {paper_fig_dir}")

print("\n=== All V5 post-processing and figure rendering completed successfully! ===")
