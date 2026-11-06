#!/usr/bin/env python3
"""Build and evaluate V4 champion run across all 22 treatments:
1. Save full_gen98_v4_best_parameters_fixed.csv
2. Execute det_calib (8 runs) and det_valid (14 runs)
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

RUN_V3 = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_98pct_v3_20260915"
RUN_V4 = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_98pct_v4_20260915"
CALIB_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_calib.v48"
VALID_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_valid.v48"
RSCRIPT_PATH = r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe"

from src.calibration.run_dssat import prepare_run_directory
from tools.eval_full_gen98 import evaluate_run, calc_metrics
from src.reporting.figure_data import VARIABLE_SPECS, validate_comparison_table

print("Step 1: Constructing V4 champion parameter set...")
df_v3 = pd.read_csv(RUN_V3 / "full_gen98_v3_best_parameters_fixed.csv")
df_v4 = df_v3.copy()

# Apply targeted senescence tuning & organ P refinement
df_v4.loc[df_v4["name"] == "senrte", "value"] = 6.50
df_v4.loc[df_v4["name"] == "optlfp_fs", "value"] = 0.00340
df_v4.loc[df_v4["name"] == "optstp_fs", "value"] = 0.00285
df_v4.loc[df_v4["name"] == "optsdp_fs", "value"] = 0.00475

if "SENPOR_LATE" not in df_v4["name"].values and "senpor_late" not in df_v4["name"].values:
    df_v4 = pd.concat([df_v4, pd.DataFrame([{"name": "SENPOR_LATE", "value": 0.19}])], ignore_index=True)
else:
    df_v4.loc[df_v4["name"].str.lower() == "senpor_late", "value"] = 0.19

best_param_csv = RUN_V4 / "full_gen98_v4_best_parameters_fixed.csv"
df_v4.to_csv(best_param_csv, index=False)
print(f"Saved V4 champion parameters to {best_param_csv}")

# Step 2: Deterministic simulation for Calib (8) and Valid (14)
det_calib_dir = RUN_V4 / "det_calib"
det_valid_dir = RUN_V4 / "det_valid"

def run_dssat_suite(batch_file: Path, out_dir: Path):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    batch_dest = prepare_run_directory(out_dir, ["--batch", str(batch_file)])
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [
        sys.executable,
        "-m",
        "src.dssat.run_dssat",
        "--param-csv",
        str(best_param_csv.resolve()),
        "--batch",
        batch_dest.name,
        "--harvest-var",
        "CHPDT",
    ]
    res = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        print("DSSAT STDERR:", res.stderr[-500:])
        raise RuntimeError(f"DSSAT run failed in {out_dir}")
    print(f"DSSAT completed successfully in {out_dir}")

print("\nStep 2A: Running calibration batch (8 runs)...")
run_dssat_suite(CALIB_BATCH, det_calib_dir)

print("\nStep 2B: Running validation batch (14 runs)...")
run_dssat_suite(VALID_BATCH, det_valid_dir)

# Step 3: Run post-processing analyze_results.py to generate compare tables
from src.reporting.analyze_results import (
    deterministic_harvest_compare,
    deterministic_process_compare,
    deterministic_joint_compare,
)

print("\nStep 3: Generating deterministic compare CSVs for Calib & Valid...")
for d, batch_name in [(det_calib_dir, "DSSBatch_calib.v48"), (det_valid_dir, "DSSBatch_valid.v48")]:
    batch_full_path = str(d / batch_name)
    deterministic_harvest_compare("full_gen98_v4", batch_full_path, run_dir=str(d))
    deterministic_process_compare("full_gen98_v4", batch_full_path, run_dir=str(d))
    deterministic_joint_compare("full_gen98_v4", batch_full_path, run_dir=str(d))
    print(f"Generated comparison files in {d}")

# Step 4: Evaluate harvest metrics
df_h_cal, df_eval_cal = evaluate_run(CALIB_BATCH, det_calib_dir)
df_h_val, df_eval_val = evaluate_run(VALID_BATCH, det_valid_dir)

rmse_c, nrmse_c, d_c, r2_c = calc_metrics(df_h_cal["OBS_FRESH_CUM"], df_h_cal["SIM_FRESH_CUM"])
rmse_v, nrmse_v, d_v, r2_v = calc_metrics(df_h_val["OBS_FRESH_CUM"], df_h_val["SIM_FRESH_CUM"])
df_all = pd.concat([df_h_cal, df_h_val], ignore_index=True)
rmse_all, nrmse_all, d_all, r2_all = calc_metrics(df_all["OBS_FRESH_CUM"], df_all["SIM_FRESH_CUM"])

print("\n" + "="*70)
print(f"CALIBRATION: NRMSE = {nrmse_c:.2f}%, d = {d_c:.4f}, R2 = {r2_c:.4f}, RMSE = {rmse_c:.1f} kg/ha")
print(f"VALIDATION:  NRMSE = {nrmse_v:.2f}%, d = {d_v:.4f}, R2 = {r2_v:.4f}, RMSE = {rmse_v:.1f} kg/ha")
print(f"POOLED 22:   NRMSE = {nrmse_all:.2f}%, d = {d_all:.4f}, R2 = {r2_all:.4f}")

# Contrasts
final_yields = {r: grp.sort_values("DATE").iloc[-1]["SIM_FRESH_CUM"] for r, grp in df_h_cal.groupby("RUN")}
d_25_w3 = final_yields.get(1, 0) - final_yields.get(2, 0)
d_25_w1 = final_yields.get(3, 0) - final_yields.get(4, 0)
d_26_w2 = final_yields.get(5, 0) - final_yields.get(7, 0)
d_26_w1 = final_yields.get(6, 0) - final_yields.get(8, 0)
print(f"25SP W3 Delta = {d_25_w3:+.1f} kg/ha")
print(f"25SP W1 Delta = {d_25_w1:+.1f} kg/ha")
print(f"26SP W2 Delta = {d_26_w2:+.1f} kg/ha")
print(f"26SP W1 Delta = {d_26_w1:+.1f} kg/ha")

# Step 5: Concatenate PlantGro & FreshWt trajectories
print("\nStep 5: Concatenating PlantGro and FreshWt trajectories...")
for outfile in ["PlantGro.OUT", "FreshWt.OUT"]:
    cal_p = det_calib_dir / outfile
    val_p = det_valid_dir / outfile
    dst_p = RUN_V4 / outfile
    with open(dst_p, "w", encoding="utf-8") as f_out:
        with open(cal_p, "r", encoding="utf-8", errors="ignore") as f_in:
            f_out.write(f_in.read())
        with open(val_p, "r", encoding="utf-8", errors="ignore") as f_in:
            f_out.write(f_in.read())
    print(f"Concatenated {outfile} -> {dst_p}")

# Step 6: Build comparison.csv
print("\nStep 6: Assembling tidy comparison.csv...")
calib_runs_season = {1: "25SP", 2: "25SP", 3: "25SP", 4: "25SP", 5: "26SP", 6: "26SP", 7: "26SP", 8: "26SP"}
valid_runs_season = {
    1: "25SP", 2: "25SP", 3: "25SP", 4: "25SP", 5: "25SP", 6: "25SP",
    7: "26SP", 8: "26SP", 9: "26SP", 10: "26SP", 11: "26SP", 12: "26SP", 13: "26SP", 14: "26SP",
}

records = []
for c_dir, role, season_map in [(det_calib_dir, "calibration", calib_runs_season), (det_valid_dir, "validation", valid_runs_season)]:
    p_path = c_dir / "full_gen98_v4_deterministic_process_compare.csv"
    h_path = c_dir / "full_gen98_v4_deterministic_harvest_compare.csv"
    j_path = c_dir / "full_gen98_v4_deterministic_joint_compare.csv"
    
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
                    "run_id": "full_gen98_v4",
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
                    "run_id": "full_gen98_v4",
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
                "run_id": "full_gen98_v4",
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
comp_csv = RUN_V4 / "comparison.csv"
df_comp.to_csv(comp_csv, index=False)
print(f"Wrote {len(df_comp)} validated rows to {comp_csv}")

# Step 7: Export paper_data
print("\nStep 7: Exporting paper_data bundle...")
paper_data_dir = RUN_V4 / "paper_data"
cmd = [
    sys.executable,
    "-m",
    "src.reporting.export_paper_data",
    "--run-id",
    "full_gen98_v4",
    "--comparison-csv",
    str(comp_csv.resolve()),
    "--phi-csv",
    str((RUN_V4 / "full_gen98_v4.phi.actual.csv").resolve()),
    "--trajectory-run-dir",
    str(RUN_V4.resolve()),
    "--treatment-metadata-csv",
    str((PROJECT_ROOT / "configs" / "figures" / "treatment_metadata_xxql2501_2601_joint.csv").resolve()),
    "--out-dir",
    str(paper_data_dir.resolve()),
    "--allow-unvalidated-demo",
]
env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, env=env)
print(f"Exported paper data bundle to {paper_data_dir}")

# Step 8: Render R publication figures
print("\nStep 8: Rendering publication figures with R...")
paper_fig_dir = RUN_V4 / "paper_figures"
cmd_r = [
    RSCRIPT_PATH,
    str((PROJECT_ROOT / "paper" / "R" / "make_all.R").resolve()),
    "--input-dir",
    str(paper_data_dir.resolve()),
    "--out-dir",
    str(paper_fig_dir.resolve()),
    "--allow-unvalidated-demo",
]
subprocess.run(cmd_r, cwd=PROJECT_ROOT, capture_output=True, text=True)
print(f"Rendered R figures into {paper_fig_dir}")

print("\n=== All V4 tasks completed successfully! ===")
