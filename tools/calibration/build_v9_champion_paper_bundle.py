#!/usr/bin/env python3
"""Build and export paper data bundle and render formal publication figures for V9 Champion run.

Champion realization: Realization 125 (full_gen98_v9_best_parameters_fixed.csv)
Run directory: workspace/runs/full_genetic_98pct_v9_20260917/
Includes:
1. Generation of deterministic comparison CSVs for Calibration (8 runs) and Validation (15 runs)
2. Extraction of audited Leaf Nitrogen (LN%D) observations with replicate uncertainty (SD, SE, n_rep)
   from data/user/ref/DSSAT文件/2025春/2025年春季茄子植株样氮磷钾测定.xlsx matched to simulated PlantGro.OUT
3. Concatenation of daily PlantGro.OUT and FreshWt.OUT trajectories
4. Construction and validation of tidy comparison.csv
5. Renderer-neutral data export via src.reporting.export_paper_data
6. Manuscript-ready rendering via Rscript paper/R/make_all.R (including fig_leaf_nitrogen.R)
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

RUN_V9 = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_98pct_v9_20260917"
CALIB_DIR = RUN_V9 / "det_calib"
VALID_DIR = RUN_V9 / "det_valid"
PAPER_DATA_DIR = RUN_V9 / "paper_data"
PAPER_FIGURES_DIR = RUN_V9 / "paper_figures"
RSCRIPT_PATH = r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe"

from src.reporting.figure_data import VARIABLE_SPECS, validate_comparison_table
from src.reporting.analyze_results import (
    _parse_batch_entries,
    deterministic_harvest_compare,
    deterministic_process_compare,
    deterministic_joint_compare,
)


def step1_generate_deterministic_compare_csvs():
    print("=" * 80)
    print("STEP 1: Generating deterministic compare CSVs for Calibration and Validation")
    print("=" * 80)
    prefix = "full_gen98_v9"
    for d, batch_name in [(CALIB_DIR, "DSSBatch_calib.v48"), (VALID_DIR, "DSSBatch_valid.v48")]:
        batch_full_path = str(d / batch_name)
        print(f"Processing {batch_name} in {d}...")
        deterministic_harvest_compare(prefix, batch_full_path, run_dir=str(d))
        deterministic_process_compare(prefix, batch_full_path, run_dir=str(d))
        deterministic_joint_compare(prefix, batch_full_path, run_dir=str(d))
        print(f"  -> Generated {prefix}_deterministic_*.csv in {d}")


def step2_concatenate_trajectories():
    print("\n" + "=" * 80)
    print("STEP 2: Concatenating daily PlantGro.OUT and FreshWt.OUT trajectories")
    print("=" * 80)
    for outfile in ["PlantGro.OUT", "FreshWt.OUT"]:
        cal_path = CALIB_DIR / outfile
        val_path = VALID_DIR / outfile
        dst_path = RUN_V9 / outfile
        with open(dst_path, "w", encoding="utf-8") as f_out:
            with open(cal_path, "r", encoding="utf-8", errors="ignore") as f_in:
                f_out.write(f_in.read())
            with open(val_path, "r", encoding="utf-8", errors="ignore") as f_in:
                f_out.write(f_in.read())
        print(f"  -> Concatenated {outfile} -> {dst_path} ({dst_path.stat().st_size} bytes)")


def step3_extract_leaf_nitrogen_observations():
    print("\n" + "=" * 80)
    print("STEP 3: Tracing & Auditing Leaf Nitrogen (LN%D) in 2025SP & 2025FA")
    print("=" * 80)
    # Ensure 25FA simulation directory is available in RUN_V9
    src_fa = PROJECT_ROOT / "scratch" / "screen_v9" / "cand_iter5_real125_25fa"
    dst_fa1 = RUN_V9 / "cand_iter5_real125_25fa"
    dst_fa2 = RUN_V9 / "det_25fa"
    if src_fa.exists():
        if not dst_fa1.exists():
            shutil.copytree(src_fa, dst_fa1)
        if not dst_fa2.exists():
            shutil.copytree(src_fa, dst_fa2)

    # 1. Trace 2025 Spring Leaf Nitrogen
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

    # Read simulated LN%D on DOY 194 (2025-07-13, DAP 119) from PlantGro.OUT
    sim_by_treatment_sp = {}
    calib_entries = _parse_batch_entries(str(CALIB_DIR / "DSSBatch_calib.v48"))
    valid_entries = _parse_batch_entries(str(VALID_DIR / "DSSBatch_valid.v48"))

    def read_pg_lnd(pg_path, entries):
        run_to_tn_season = {}
        for e in entries:
            filex = e.get("filex", "")
            season = "25SP" if "2501" in filex else ("26SP" if "2601" in filex else "OTHER")
            run_to_tn_season[int(e["run"])] = (str(int(e["tn"])), season)

        out = {}
        with open(pg_path, "r", encoding="utf-8", errors="ignore") as f:
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
                            if run_no in run_to_tn_season:
                                tn, season = run_to_tn_season[run_no]
                                if season == "25SP":
                                    out[tn] = float(parts[header.index("LN%D")])
        return out

    sim_cal = read_pg_lnd(CALIB_DIR / "PlantGro.OUT", calib_entries)
    sim_val = read_pg_lnd(VALID_DIR / "PlantGro.OUT", valid_entries)
    sim_by_treatment_sp.update(sim_cal)
    sim_by_treatment_sp.update(sim_val)

    calib_tmts = {"2", "5", "10", "13"}
    spec = VARIABLE_SPECS["LN%D"]
    sp_records = []
    audit_rows = []

    for _, row in agg_sp.iterrows():
        tn = str(row["treatment"])
        sim_val = sim_by_treatment_sp.get(tn, np.nan)
        role = "calibration" if tn in calib_tmts else "validation"
        if np.isfinite(sim_val):
            sp_records.append({
                "run_id": "full_gen98_v9",
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
        audit_rows.append({
            "season": "2025SP",
            "date": "2025-07-13",
            "doy": 194,
            "dap": 119,
            "plot": int(row["plot"]),
            "treatment": tn,
            "water": row["water"],
            "nitrogen": row["nitrogen"],
            "dataset_role": role,
            "n_rep": int(row["n_rep"]),
            "observed_pct": float(row["observed"]),
            "observed_sd": float(row["observed_sd"]),
            "observed_se": float(row["observed_se"]),
            "simulated_pct": float(sim_val) if np.isfinite(sim_val) else np.nan,
            "error_pct": float(sim_val - row["observed"]) if np.isfinite(sim_val) else np.nan,
        })

    # 2. Trace 2025 Autumn Leaf Nitrogen
    excel_fa = PROJECT_ROOT / "data" / "user" / "ref" / "DSSAT文件" / "2025秋" / "2025年秋季茄子植株样氮磷钾测定.xlsx"
    if excel_fa.exists():
        wb_fa = openpyxl.load_workbook(excel_fa, data_only=True)
        sheet_fa = wb_fa["Sheet1"]
        rows_fa = []
        for r in range(2, sheet_fa.max_row + 1):
            vals = [sheet_fa.cell(r, c).value for c in range(1, 10)]
            if any(vals):
                rows_fa.append(vals)
        df_fa = pd.DataFrame(rows_fa, columns=["date", "organ", "plot", "rep", "n_mg_g", "p_mg_g", "k_mg_g", "water", "nitrogen"])
        leaf_fa = df_fa[df_fa["organ"] == "叶"].copy()
        leaf_fa["n_pct"] = pd.to_numeric(leaf_fa["n_mg_g"], errors="coerce") / 10.0
        leaf_fa["date_str"] = leaf_fa["date"].astype(str).str[:10]

        # Read 25FA simulation from det_25fa / cand_iter5_real125_25fa
        pg_fa = dst_fa2 / "PlantGro.OUT"
        sim_fa_by_run_doy = {}
        if pg_fa.exists():
            with open(pg_fa, "r", encoding="utf-8", errors="ignore") as f:
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
                            sim_fa_by_run_doy[(run_no, year, doy)] = float(parts[header.index("LN%D")])

        agg_fa = leaf_fa.groupby(["date_str", "plot", "water", "nitrogen"])["n_pct"].agg(
            observed="mean", observed_sd="std", n_rep="count"
        ).reset_index()
        agg_fa["observed_se"] = agg_fa["observed_sd"] / np.sqrt(agg_fa["n_rep"])

        for _, row in agg_fa.iterrows():
            d_str = str(row["date_str"])
            plot_no = int(row["plot"])
            doy = 342 if d_str == "2025-12-08" else (9 if d_str == "2026-01-09" else np.nan)
            year = 2025 if d_str == "2025-12-08" else 2026
            sim_val = sim_fa_by_run_doy.get((plot_no, year, doy), np.nan)
            audit_rows.append({
                "season": "2025FA",
                "date": d_str,
                "doy": doy,
                "dap": 106 if doy == 342 else (138 if doy == 9 else np.nan),
                "plot": plot_no,
                "treatment": str(plot_no),
                "water": row["water"],
                "nitrogen": row["nitrogen"],
                "dataset_role": "independent_blind_test",
                "n_rep": int(row["n_rep"]),
                "observed_pct": float(row["observed"]),
                "observed_sd": float(row["observed_sd"]),
                "observed_se": float(row["observed_se"]),
                "simulated_pct": float(sim_val) if np.isfinite(sim_val) else np.nan,
                "error_pct": float(sim_val - row["observed"]) if np.isfinite(sim_val) else np.nan,
            })

    df_audit = pd.DataFrame(audit_rows)
    audit_csv = RUN_V9 / "leaf_nitrogen_audit_25sp_25fa.csv"
    df_audit.to_csv(audit_csv, index=False, encoding="utf-8")
    print(f"  -> Exported comprehensive Leaf N audit table to {audit_csv} ({len(df_audit)} treatment-date conditions across 25SP & 25FA)")
    print(f"  -> Extracted {len(sp_records)} calibrated/validated Leaf Nitrogen pairs for formal paper comparison")
    for r in sp_records:
        print(f"     Tmt {r['treatment']} ({r['dataset_role']}): Obs={r['observed']:.2f}% ± {r['observed_se']:.2f}%, Sim={r['simulated']:.2f}%")
    return sp_records


def step4_build_comparison_table(leaf_n_records):
    print("\n" + "=" * 80)
    print("STEP 4: Assembling tidy comparison.csv with all process, harvest, joint & leaf N pairs")
    print("=" * 80)
    prefix = "full_gen98_v9"

    calib_runs_season = {1: "25SP", 2: "25SP", 3: "25SP", 4: "25SP", 5: "26SP", 6: "26SP", 7: "26SP", 8: "26SP"}
    valid_runs_season = {
        1: "25SP", 2: "25SP", 3: "25SP", 4: "25SP", 5: "25SP", 6: "25SP", 7: "25SP",
        8: "26SP", 9: "26SP", 10: "26SP", 11: "26SP", 12: "26SP", 13: "26SP", 14: "26SP", 15: "26SP",
    }

    records = []

    for c_dir, role, season_map in [(CALIB_DIR, "calibration", calib_runs_season), (VALID_DIR, "validation", valid_runs_season)]:
        p_path = c_dir / f"{prefix}_deterministic_process_compare.csv"
        h_path = c_dir / f"{prefix}_deterministic_harvest_compare.csv"
        j_path = c_dir / f"{prefix}_deterministic_joint_compare.csv"

        # 1. Process variables (LAID, LWAD, SWAD)
        if p_path.exists():
            df_p = pd.read_csv(p_path)
            for _, row in df_p.iterrows():
                run = int(row["RUN"])
                season = season_map.get(run, "25SP")
                tn = str(int(row["TN"]))
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
                        "season_id": season,
                    })

        # 2. Harvest variables (DRY_INC, DRY_CUM, FRESH_INC, FRESH_CUM)
        if h_path.exists():
            df_h = pd.read_csv(h_path)
            for _, row in df_h.iterrows():
                run = int(row["RUN"])
                season = season_map.get(run, "25SP")
                tn = str(int(row["TN"]))
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
                        "season_id": season,
                    })

        # 3. Joint peak variable (LAIX)
        if j_path.exists():
            df_j = pd.read_csv(j_path)
            for _, row in df_j.iterrows():
                run = int(row["RUN"])
                season = season_map.get(run, "25SP")
                tn = str(int(row["TN"]))
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
                    "year": 2025.0 if season == "25SP" else 2026.0,
                    "doy": np.nan,
                    "dap": np.nan,
                    "harvest_number": np.nan,
                    "observed_sd": np.nan,
                    "observed_se": np.nan,
                    "n_rep": np.nan,
                    "season_id": season,
                })

    # Append leaf nitrogen records
    records.extend(leaf_n_records)

    df_out = pd.DataFrame(records)
    df_valid = validate_comparison_table(df_out)
    out_csv = RUN_V9 / "comparison.csv"
    df_valid.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"  -> Wrote validated comparison table to {out_csv} ({len(df_valid)} pairs across {len(df_valid['variable'].unique())} variables: {sorted(df_valid['variable'].unique())})")
    return out_csv


def step5_export_paper_data(comp_csv):
    print("\n" + "=" * 80)
    print("STEP 5: Exporting renderer-neutral paper_data bundle")
    print("=" * 80)
    cmd = [
        sys.executable,
        "-m",
        "src.reporting.export_paper_data",
        "--run-id",
        "full_gen98_v9",
        "--comparison-csv",
        str(comp_csv.resolve()),
        "--phi-csv",
        str((RUN_V9 / "full_gen98_v9.phi.actual.csv").resolve()),
        "--trajectory-run-dir",
        str(RUN_V9.resolve()),
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
    print("  -> paper_data bundle successfully created at:", PAPER_DATA_DIR)


def step6_render_publication_figures():
    print("\n" + "=" * 80)
    print("STEP 6: Rendering publication figures via Rscript make_all.R")
    print("=" * 80)
    if not Path(RSCRIPT_PATH).exists():
        raise FileNotFoundError(f"Rscript not found at {RSCRIPT_PATH}")

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
    print("  -> Complete publication figure suite rendered to:", PAPER_FIGURES_DIR)


def main():
    step1_generate_deterministic_compare_csvs()
    step2_concatenate_trajectories()
    leaf_n_records = step3_extract_leaf_nitrogen_observations()
    comp_csv = step4_build_comparison_table(leaf_n_records)
    step5_export_paper_data(comp_csv)
    step6_render_publication_figures()
    print("\n" + "=" * 80)
    print("ALL TASKS COMPLETED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    main()
