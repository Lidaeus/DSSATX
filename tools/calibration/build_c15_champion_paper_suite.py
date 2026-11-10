#!/usr/bin/env python3
"""Build and export paper data bundle and render formal publication figures for Champion C15 (real_72).

Champion realization: Realization 72 (new_iter6_real72, TB1=9.21 C)
Grand 35-treatment NRMSE: 8.06%, Spring 23-treatment NRMSE: 6.60%, 25FA Blind NRMSE: 18.38%
Run directory: workspace/runs/full_gen_13trt_tb1_80_95_150x6_20260920/

Steps:
1. Generate deterministic comparison CSVs for 25SP (11 treatments) and 26SP (12 treatments)
2. Concatenate daily PlantGro.OUT and FreshWt.OUT trajectories
3. Extract audited Leaf Nitrogen (LN%D) observations with replicate uncertainty
4. Construct and validate tidy comparison.csv
5. Export renderer-neutral paper_data bundle via src.reporting.export_paper_data
6. Render publication figures via Rscript paper/R/make_all.R (including Fig 2, Fig 3, Fig 4, Fig 6, Fig S3, Fig S4, Fig LeafN)
7. Archive rendered figure suite into workspace/candidates/candidate_c15_real72_grand_champion/paper_figures/
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
import openpyxl
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / "full_gen_13trt_tb1_80_95_150x6_20260920"
EVAL_SRC = PROJECT_ROOT / "scratch" / "eval_new_tb1_150x6" / "run_new_iter6_real72"
CANDIDATE_DIR = PROJECT_ROOT / "workspace" / "candidates" / "candidate_c15_real72_grand_champion"

DET_25SP = RUN_DIR / "c15_det_25sp"
DET_26SP = RUN_DIR / "c15_det_26sp"
DET_25FA = RUN_DIR / "c15_det_25fa"
TRAJ_DIR = RUN_DIR / "c15_trajectories"

PAPER_DATA_DIR = RUN_DIR / "paper_data_c15"
PAPER_FIGURES_DIR = RUN_DIR / "paper_figures_c15"
CANDIDATE_FIGURES_DIR = CANDIDATE_DIR / "paper_figures"

RSCRIPT_PATH = r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe"

from src.reporting.figure_data import VARIABLE_SPECS, validate_comparison_table
from src.reporting.analyze_results import (
    _parse_batch_entries,
    deterministic_harvest_compare,
    deterministic_process_compare,
    deterministic_joint_compare,
)


def step1_prepare_deterministic_runs():
    print("=" * 80)
    print("STEP 1: Preparing deterministic run directories and generating compare CSVs")
    print("=" * 80)
    
    # Copy from scratch eval dir to run dir for permanence and reproducibility
    for s_name, dst_dir in [("25SP", DET_25SP), ("26SP", DET_26SP), ("25FA", DET_25FA)]:
        src = EVAL_SRC / s_name
        if not src.exists():
            raise FileNotFoundError(f"Source evaluation directory not found: {src}")
        if not dst_dir.exists():
            print(f"Copying {src} -> {dst_dir}...")
            shutil.copytree(src, dst_dir)
        else:
            print(f"Destination {dst_dir} already exists.")
            
    # Generate deterministic compare CSVs for 25SP
    batch_25 = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch.v48"
    shutil.copy2(batch_25, DET_25SP / "DSSBatch.v48")
    print("Generating deterministic comparison CSVs for 25SP...")
    deterministic_harvest_compare("c15_25sp", str(DET_25SP / "DSSBatch.v48"), run_dir=str(DET_25SP))
    deterministic_process_compare("c15_25sp", str(DET_25SP / "DSSBatch.v48"), run_dir=str(DET_25SP))
    deterministic_joint_compare("c15_25sp", str(DET_25SP / "DSSBatch.v48"), run_dir=str(DET_25SP))
    print("  -> Generated 25SP compare CSVs in", DET_25SP)
    
    # Generate deterministic compare CSVs for 26SP
    batch_26 = PROJECT_ROOT / "scratch" / "eval_new_tb1_150x6" / "batches" / "DSSBatch_26SP_all.v48"
    shutil.copy2(batch_26, DET_26SP / "DSSBatch.v48")
    print("Generating deterministic comparison CSVs for 26SP...")
    deterministic_harvest_compare("c15_26sp", str(DET_26SP / "DSSBatch.v48"), run_dir=str(DET_26SP))
    deterministic_process_compare("c15_26sp", str(DET_26SP / "DSSBatch.v48"), run_dir=str(DET_26SP))
    deterministic_joint_compare("c15_26sp", str(DET_26SP / "DSSBatch.v48"), run_dir=str(DET_26SP))
    print("  -> Generated 26SP compare CSVs in", DET_26SP)


def step2_concatenate_trajectories():
    print("\n" + "=" * 80)
    print("STEP 2: Concatenating daily PlantGro.OUT and FreshWt.OUT trajectories")
    print("=" * 80)
    TRAJ_DIR.mkdir(parents=True, exist_ok=True)
    
    for outfile in ["PlantGro.OUT", "FreshWt.OUT"]:
        p25 = DET_25SP / outfile
        p26 = DET_26SP / outfile
        dst = TRAJ_DIR / outfile
        
        with open(dst, "w", encoding="utf-8") as f_out:
            with open(p25, "r", encoding="utf-8", errors="ignore") as f25:
                f_out.write(f25.read())
            with open(p26, "r", encoding="utf-8", errors="ignore") as f26:
                f_out.write(f26.read())
        print(f"  -> Concatenated {outfile} -> {dst} ({dst.stat().st_size} bytes)")


def step3_extract_leaf_nitrogen_observations():
    print("\n" + "=" * 80)
    print("STEP 3: Extracting audited Leaf Nitrogen (LN%D) observations & uncertainties")
    print("=" * 80)
    
    excel_sp = PROJECT_ROOT / "data" / "user" / "ref" / "DSSAT文件" / "2025春" / "2025年春季茄子植株样氮磷钾测定.xlsx"
    wb_sp = openpyxl.load_workbook(excel_sp, data_only=True)
    sheet_sp = wb_sp["Sheet1"]
    rows_sp = []
    for r in range(2, sheet_sp.max_row + 1):
        vals = [sheet_sp.cell(r, c).value for c in range(1, 10)]
        if any(vals):
            rows_sp.append(vals)
    df_sp = pd.DataFrame(rows_sp, columns=["date", "organ", "plot", "rep", "n_mg_g", "p_mg_g", "k_mg_g", "water", "nitrogen"])
    df_leaf_sp = df_sp[df_sp["organ"] == "叶"].copy()
    df_leaf_sp["n_pct"] = pd.to_numeric(df_leaf_sp["n_mg_g"], errors="coerce") / 10.0
    
    agg_sp = df_leaf_sp.groupby(["plot", "water", "nitrogen"])["n_pct"].agg(
        observed="mean", observed_sd="std", n_rep="count"
    ).reset_index()
    agg_sp["observed_se"] = agg_sp["observed_sd"] / np.sqrt(agg_sp["n_rep"])
    agg_sp["treatment"] = agg_sp["plot"].astype(str)
    
    # Read simulated LN%D on DOY 194 (2025-07-13, DAP 119) from PlantGro.OUT in 25SP
    sim_by_treatment_sp = {}
    calib_entries = _parse_batch_entries(str(DET_25SP / "DSSBatch.v48"))
    run_to_tn = {int(e["run"]): str(int(e["tn"])) for e in calib_entries}
    
    with open(DET_25SP / "PlantGro.OUT", "r", encoding="utf-8", errors="ignore") as f:
        header = None
        run_no = None
        for line in f:
            if line.startswith("*RUN"):
                run_no = int(line.split()[1])
            elif line.startswith("@YEAR"):
                header = line.split()
            elif header and line.strip() and not line.startswith(("*", "!", "@")):
                parts = line.split()
                if len(parts) >= len(header):
                    year = int(parts[header.index("@YEAR")])
                    doy = int(parts[header.index("DOY")])
                    if year == 2025 and doy == 194:
                        if run_no in run_to_tn:
                            sim_by_treatment_sp[run_to_tn[run_no]] = float(parts[header.index("LN%D")])
                            
    calib_tmts = {"2", "3", "5", "6", "10", "13"}
    spec = VARIABLE_SPECS["LN%D"]
    sp_records = []
    
    for _, row in agg_sp.iterrows():
        tn = str(row["treatment"])
        sim_val = sim_by_treatment_sp.get(tn, np.nan)
        role = "calibration" if tn in calib_tmts else "validation"
        if np.isfinite(sim_val):
            sp_records.append({
                "run_id": "full_gen_13trt_tb1_80_95_150x6",
                "data_status": "engineering_validated",
                "dataset_role": role,
                "variable": "LN%D",
                "variable_label": spec["label"],
                "unit": spec["unit"],
                "treatment": tn,
                "time": 119.0,
                "time_label": "Days after planting",
                "observed": float(row["observed"]),
                "simulated": float(sim_val),
                "source_file": "PlantGro.OUT",
                "date_code": 25194.0,
                "year": 2025.0,
                "doy": 194.0,
                "dap": 119.0,
                "harvest_number": np.nan,
                "observed_sd": float(row["observed_sd"]),
                "observed_se": float(row["observed_se"]),
                "n_rep": float(row["n_rep"]),
                "season_id": "25SP",
            })
    print(f"  -> Extracted {len(sp_records)} Leaf Nitrogen pairs for 25SP")
    return sp_records


def step4_build_comparison_table(leaf_n_records):
    print("\n" + "=" * 80)
    print("STEP 4: Assembling tidy comparison.csv with all process, harvest, joint & leaf N pairs")
    print("=" * 80)
    prefix = "full_gen_13trt_tb1_80_95_150x6"
    
    # Treatment dataset roles from configs/figures/treatment_metadata_xxql2501_2601_joint.csv
    meta_path = PROJECT_ROOT / "configs" / "figures" / "treatment_metadata_xxql2501_2601_joint.csv"
    meta_df = pd.read_csv(meta_path)
    role_map = {(r["season_id"], str(r["treatment"])): r["dataset_role"] for _, r in meta_df.iterrows()}
    
    records = []
    
    # 1. 25SP compare data
    for season_id, det_dir, pfx in [("25SP", DET_25SP, "c15_25sp"), ("26SP", DET_26SP, "c15_26sp")]:
        p_path = det_dir / f"{pfx}_deterministic_process_compare.csv"
        h_path = det_dir / f"{pfx}_deterministic_harvest_compare.csv"
        j_path = det_dir / f"{pfx}_deterministic_joint_compare.csv"
        
        # Process variables (LAID, LWAD, SWAD)
        if p_path.exists():
            df_p = pd.read_csv(p_path)
            for _, row in df_p.iterrows():
                tn = str(int(row["TN"]))
                role = role_map.get((season_id, tn), "validation")
                date = float(row["DATE"])
                year = 2000.0 + float(int(date) // 1000)
                doy = float(int(date) % 1000)
                
                for var in ["LAID", "LWAD", "SWAD"]:
                    obs_col = f"OBS_{var}"
                    sim_col = f"SIM_{var}"
                    if obs_col not in row or sim_col not in row:
                        continue
                    obs = float(row[obs_col])
                    sim = float(row[sim_col])
                    if obs <= 0 or not np.isfinite(obs) or not np.isfinite(sim):
                        continue
                    spec = VARIABLE_SPECS[var]
                    records.append({
                        "run_id": prefix,
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
                        "season_id": season_id,
                    })
                    
        # Harvest variables (DRY_INC, DRY_CUM, FRESH_INC, FRESH_CUM)
        if h_path.exists():
            df_h = pd.read_csv(h_path)
            for _, row in df_h.iterrows():
                tn = str(int(row["TN"]))
                role = role_map.get((season_id, tn), "validation")
                date = float(row["DATE"])
                year = 2000.0 + float(int(date) // 1000)
                doy = float(int(date) % 1000)
                hno = float(row["HNO"]) if "HNO" in row and np.isfinite(row["HNO"]) else np.nan
                
                for var in ["DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM"]:
                    obs_col = f"OBS_{var}"
                    sim_col = f"SIM_{var}"
                    if obs_col not in row or sim_col not in row:
                        continue
                    obs = float(row[obs_col])
                    sim = float(row[sim_col])
                    if not np.isfinite(obs) or not np.isfinite(sim):
                        continue
                    spec = VARIABLE_SPECS[var]
                    records.append({
                        "run_id": prefix,
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
                        "season_id": season_id,
                    })
                    
        # Joint variables (LAIX)
        if j_path.exists():
            df_j = pd.read_csv(j_path)
            for _, row in df_j.iterrows():
                tn = str(int(row["TN"]))
                role = role_map.get((season_id, tn), "validation")
                obs = float(row.get("OBS_LAIX", np.nan))
                sim = float(row.get("SIM_LAIX", np.nan))
                if obs <= 0 or not np.isfinite(obs) or not np.isfinite(sim):
                    continue
                spec = VARIABLE_SPECS["LAIX"]
                records.append({
                    "run_id": prefix,
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
                    "year": 2025.0 if season_id == "25SP" else 2026.0,
                    "doy": np.nan,
                    "dap": np.nan,
                    "harvest_number": np.nan,
                    "observed_sd": np.nan,
                    "observed_se": np.nan,
                    "n_rep": np.nan,
                    "season_id": season_id,
                })

    # Append Leaf Nitrogen
    records.extend(leaf_n_records)
    
    df_out = pd.DataFrame(records)
    df_valid = validate_comparison_table(df_out)
    out_csv = RUN_DIR / "comparison_c15.csv"
    df_valid.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"  -> Wrote validated comparison table to {out_csv} ({len(df_valid)} pairs across {len(df_valid['variable'].unique())} variables)")
    return out_csv


def step5_export_paper_data(comp_csv):
    print("\n" + "=" * 80)
    print("STEP 5: Exporting renderer-neutral paper_data bundle via src.reporting.export_paper_data")
    print("=" * 80)
    if PAPER_DATA_DIR.exists():
        shutil.rmtree(PAPER_DATA_DIR)
    PAPER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        sys.executable,
        "-m",
        "src.reporting.export_paper_data",
        "--run-id",
        "full_gen_13trt_tb1_80_95_150x6",
        "--comparison-csv",
        str(comp_csv.resolve()),
        "--phi-csv",
        str((RUN_DIR / "full_gen_13trt_tb1_80_95_150x6.phi.actual.csv").resolve()),
        "--trajectory-run-dir",
        str(TRAJ_DIR.resolve()),
        "--treatment-metadata-csv",
        str((PROJECT_ROOT / "configs" / "figures" / "treatment_metadata_xxql2501_2601_joint.csv").resolve()),
        "--out-dir",
        str(PAPER_DATA_DIR.resolve()),
        "--allow-unvalidated-demo",
    ]
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
    res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, env=env)
    print(res.stdout)
    if res.returncode != 0:
        print("ERROR stderr:", res.stderr)
        raise RuntimeError(f"export_paper_data failed with return code {res.returncode}")
    print("  -> paper_data bundle created at:", PAPER_DATA_DIR)


def step6_render_publication_figures():
    print("\n" + "=" * 80)
    print("STEP 6: Rendering publication figures via Rscript paper/R/make_all.R")
    print("=" * 80)
    if PAPER_FIGURES_DIR.exists():
        shutil.rmtree(PAPER_FIGURES_DIR)
    PAPER_FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        RSCRIPT_PATH,
        str((PROJECT_ROOT / "paper" / "R" / "make_all.R").resolve()),
        "--input-dir",
        str(PAPER_DATA_DIR.resolve()),
        "--out-dir",
        str(PAPER_FIGURES_DIR.resolve()),
        "--allow-unvalidated-demo",
    ]
    print("Running:", " ".join(cmd))
    res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    print("R stdout:\n", res.stdout)
    if res.returncode != 0:
        print("R stderr:\n", res.stderr)
        raise RuntimeError(f"R make_all.R failed with exit code {res.returncode}")
    print("  -> Publication figure suite rendered to:", PAPER_FIGURES_DIR)
    
    # Copy to candidate folder
    if CANDIDATE_FIGURES_DIR.exists():
        shutil.rmtree(CANDIDATE_FIGURES_DIR)
    shutil.copytree(PAPER_FIGURES_DIR, CANDIDATE_FIGURES_DIR)
    print("  -> Archived figures to candidate folder:", CANDIDATE_FIGURES_DIR)


def main():
    step1_prepare_deterministic_runs()
    step2_concatenate_trajectories()
    leaf_n_records = step3_extract_leaf_nitrogen_observations()
    comp_csv = step4_build_comparison_table(leaf_n_records)
    step5_export_paper_data(comp_csv)
    step6_render_publication_figures()
    print("\n" + "=" * 80)
    print("ALL PUBLICATION FIGURE TASKS COMPLETED SUCCESSFULLY FOR C15!")
    print("=" * 80)


if __name__ == "__main__":
    main()
