#!/usr/bin/env python3
"""Build and export paper data bundle and render publication figures for V3."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.reporting.figure_data import VARIABLE_SPECS, validate_comparison_table

RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_98pct_v3_20260915"
CALIB_DIR = RUN_DIR / "det_calib"
VALID_DIR = RUN_DIR / "det_valid"
PAPER_DATA_DIR = RUN_DIR / "paper_data"
PAPER_FIGURES_DIR = RUN_DIR / "paper_figures"
RSCRIPT_PATH = r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe"

def concatenate_dssat_outputs():
    for outfile in ["PlantGro.OUT", "FreshWt.OUT"]:
        cal_path = CALIB_DIR / outfile
        val_path = VALID_DIR / outfile
        dst_path = RUN_DIR / outfile
        if not cal_path.exists() or not val_path.exists():
            print(f"Warning: {outfile} not found in both calib and valid dirs")
            continue
        with open(dst_path, "w", encoding="utf-8") as f_out:
            with open(cal_path, "r", encoding="utf-8", errors="ignore") as f_in:
                f_out.write(f_in.read())
            with open(val_path, "r", encoding="utf-8", errors="ignore") as f_in:
                f_out.write(f_in.read())
        print(f"Concatenated {outfile} -> {dst_path} ({dst_path.stat().st_size} bytes)")

def build_comparison_table():
    calib_runs_season = {1: "25SP", 2: "25SP", 3: "25SP", 4: "25SP", 5: "26SP", 6: "26SP", 7: "26SP", 8: "26SP"}
    valid_runs_season = {
        1: "25SP", 2: "25SP", 3: "25SP", 4: "25SP", 5: "25SP", 6: "25SP",
        7: "26SP", 8: "26SP", 9: "26SP", 10: "26SP", 11: "26SP", 12: "26SP", 13: "26SP", 14: "26SP",
    }
    
    records = []
    
    for c_dir, role, season_map in [(CALIB_DIR, "calibration", calib_runs_season), (VALID_DIR, "validation", valid_runs_season)]:
        prefix = "full_gen98_v3"
        p_path = c_dir / f"{prefix}_deterministic_process_compare.csv"
        h_path = c_dir / f"{prefix}_deterministic_harvest_compare.csv"
        j_path = c_dir / f"{prefix}_deterministic_joint_compare.csv"
        
        # 1. Process
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
                        "run_id": "full_gen98_v3",
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
                    
        # 2. Harvest
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
                        "run_id": "full_gen98_v3",
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
                    
        # 3. Joint LAIX
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
                    "run_id": "full_gen98_v3",
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
                
    df_out = pd.DataFrame(records)
    df_valid = validate_comparison_table(df_out)
    out_csv = RUN_DIR / "comparison.csv"
    df_valid.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"Wrote comparison table to {out_csv} (rows: {len(df_valid)})")
    return out_csv

def run_export_paper_data(comp_csv: Path):
    cmd = [
        sys.executable,
        "-m",
        "src.reporting.export_paper_data",
        "--run-id",
        "full_gen98_v3",
        "--comparison-csv",
        str(comp_csv.resolve()),
        "--phi-csv",
        str((RUN_DIR / "full_gen98_v3.phi.actual.csv").resolve()),
        "--trajectory-run-dir",
        str(RUN_DIR.resolve()),
        "--treatment-metadata-csv",
        str((PROJECT_ROOT / "configs" / "figures" / "treatment_metadata_xxql2501_2601_joint.csv").resolve()),
        "--out-dir",
        str(PAPER_DATA_DIR.resolve()),
        "--allow-unvalidated-demo",
    ]
    print("Running export_paper_data...")
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
    res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, env=env)
    print("Export stdout:", res.stdout)
    if res.returncode != 0:
        print("Export stderr:", res.stderr)
        raise RuntimeError(f"export_paper_data failed with code {res.returncode}")
    print("Paper data bundle exported successfully.")

def run_r_figures():
    if not Path(RSCRIPT_PATH).exists():
        print(f"Rscript not found at {RSCRIPT_PATH}; skipping R figure rendering")
        return
    cmd = [
        RSCRIPT_PATH,
        str((PROJECT_ROOT / "paper" / "R" / "make_all.R").resolve()),
        "--input-dir",
        str(PAPER_DATA_DIR.resolve()),
        "--out-dir",
        str(PAPER_FIGURES_DIR.resolve()),
        "--allow-unvalidated-demo",
    ]
    print("Running R make_all.R...")
    res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    print("R stdout:", res.stdout[-1500:] if len(res.stdout) > 1500 else res.stdout)
    if res.returncode != 0:
        print("R stderr:", res.stderr[-1500:] if len(res.stderr) > 1500 else res.stderr)
        raise RuntimeError(f"R make_all.R failed with code {res.returncode}")
    print("R figures rendered successfully.")

def main():
    print("Step 1: Concatenating PlantGro.OUT and FreshWt.OUT...")
    concatenate_dssat_outputs()
    
    print("\nStep 2: Building comparison.csv...")
    comp_csv = build_comparison_table()
    
    print("\nStep 3: Exporting paper_data bundle...")
    run_export_paper_data(comp_csv)
    
    print("\nStep 4: Rendering publication figures with R...")
    run_r_figures()
    
    print("\nAll tasks in bundle build finished.")

if __name__ == "__main__":
    main()
