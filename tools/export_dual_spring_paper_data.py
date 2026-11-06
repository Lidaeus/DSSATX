"""Export frozen Dual-Spring paper data bundle for R publication figure pipeline.

Combines:
- 2026 Spring (26SP / XXQL2601, 12 treatments, Calibration Set)
- 2025 Spring (25SP / XXQL2501, 8 treatments, Validation Set)

Under DSSAT v7a critical nitrogen & organ buffer model.
Excludes 2025 Autumn (25FA) per scientific boundary decision.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

from src.reporting.figure_data import (
    COMPARISON_COLUMNS,
    TRAJECTORY_COLUMNS,
    TREATMENT_METADATA_COLUMNS,
    VARIABLE_SPECS,
    read_dssat_trajectories,
    read_phi_ensemble,
    validate_comparison_table,
    validate_treatment_metadata,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, str]:
    return {"path": path.name, "sha256": _sha256(path)}


def _parse_evaluate_file(eval_path: Path) -> dict[str, dict[str, float]]:
    """Parse Evaluate.OUT for ADAP and LAIX by treatment."""
    records: dict[str, dict[str, float]] = {}
    if not eval_path.is_file():
        return records
    with eval_path.open("r", encoding="utf-8", errors="ignore") as f:
        header = None
        for line in f:
            line_str = line.strip()
            if line_str.startswith("@RUN"):
                header = line_str.split()
                continue
            if not header or not line_str or line_str.startswith(("*", "!", "@")):
                continue
            parts = line_str.split()
            if len(parts) < len(header):
                continue
            try:
                tn_idx = header.index("TN")
                treatment = str(int(float(parts[tn_idx])))
                data: dict[str, float] = {}
                for col in ["ADAPS", "ADAPM", "LAIXS", "LAIXM"]:
                    if col in header:
                        val = float(parts[header.index(col)])
                        if val > -90.0:
                            data[col] = val
                records[treatment] = data
            except (ValueError, IndexError):
                continue
    return records


def extract_season_comparison(
    *,
    season_id: str,
    dataset_role: str,
    run_id: str,
    data_status: str,
    run_dir: Path,
    staged_dir: Path,
    treatment_map: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    # 1. Load observation files
    file_t = pd.read_csv(staged_dir / "FileT_values.csv")
    file_a = pd.read_csv(staged_dir / "FileA_values.csv")
    unc_path = staged_dir / "observation_uncertainty.csv"
    unc_df = pd.read_csv(unc_path) if unc_path.is_file() else pd.DataFrame()

    # Pre-index uncertainty: (trno, date_str, variable) -> (raw_sd, n_rep, observed_se)
    unc_lookup: dict[tuple[str, str, str], tuple[float, float, float]] = {}
    if not unc_df.empty:
        for row in unc_df.itertuples(index=False):
            trno_str = str(int(float(row.trno)))
            date_str = str(row.date).strip()
            var_name = str(row.variable).strip().upper()
            sd_val = float(row.raw_sd) if np.isfinite(row.raw_sd) else np.nan
            n_rep_val = float(row.n_rep) if np.isfinite(row.n_rep) and row.n_rep > 0 else np.nan
            se_val = (sd_val / np.sqrt(n_rep_val)) if np.isfinite(sd_val) and np.isfinite(n_rep_val) else np.nan
            unc_lookup[(trno_str, date_str, var_name)] = (sd_val, n_rep_val, se_val)

    # 2. Load simulation trajectories for lookup
    trajectories = read_dssat_trajectories(
        run_dir, run_id=run_id, data_status=data_status
    )

    # Group trajectories by (variable, treatment, date_code) -> simulated value, dap
    sim_lookup: dict[tuple[str, str, int], tuple[float, float]] = {}
    for r in trajectories.itertuples(index=False):
        var = str(r.variable)
        trt = str(r.treatment)
        dcode = int(r.date_code)
        sim_lookup[(var, trt, dcode)] = (float(r.simulated), float(r.time))

    # Also build cumulative harvest event lookup for incremental difference
    # For FreshWt harvest events in simulation
    fresh_traj = trajectories[trajectories["variable"] == "FRESH_CUM"].sort_values(["treatment", "time"])
    dry_traj = trajectories[trajectories["variable"] == "DRY_CUM"].sort_values(["treatment", "time"])

    # 3. Extract Harvest Observations from FileT
    # Harvest dates have HFPOW / CHFPW / HPODW / CHPDT > 0
    t_treatments = sorted(file_t["TRNO"].unique())
    for trno_val in t_treatments:
        trt_str = str(int(float(trno_val)))
        t_sub = file_t[file_t["TRNO"] == trno_val].sort_values("DATE")

        # Harvest rows
        h_rows = t_sub[t_sub["CHFPW"] > 0].copy()
        h_num = 1
        prev_sim_fresh = 0.0
        prev_sim_dry = 0.0

        for h_row in h_rows.itertuples(index=False):
            date_code = int(h_row.DATE)
            year = 2000 + date_code // 1000
            doy = date_code % 1000

            # Find matching simulated fresh and dry cum at date_code
            sim_fresh_pair = sim_lookup.get(("FRESH_CUM", trt_str, date_code))
            sim_dry_pair = sim_lookup.get(("DRY_CUM", trt_str, date_code))

            if sim_fresh_pair is None or sim_dry_pair is None:
                # Try finding closest on or before date_code
                sub_f = fresh_traj[(fresh_traj["treatment"] == trt_str) & (fresh_traj["date_code"] <= date_code)]
                sub_d = dry_traj[(dry_traj["treatment"] == trt_str) & (dry_traj["date_code"] <= date_code)]
                if not sub_f.empty and not sub_d.empty:
                    sim_fresh_pair = (float(sub_f.iloc[-1]["simulated"]), float(sub_f.iloc[-1]["time"]))
                    sim_dry_pair = (float(sub_d.iloc[-1]["simulated"]), float(sub_d.iloc[-1]["time"]))

            if sim_fresh_pair is None or sim_dry_pair is None:
                continue

            sim_fresh_cum, dap = sim_fresh_pair
            sim_dry_cum, _ = sim_dry_pair
            sim_fresh_inc = max(0.0, sim_fresh_cum - prev_sim_fresh)
            sim_dry_inc = max(0.0, sim_dry_cum - prev_sim_dry)

            obs_fresh_cum = float(h_row.CHFPW)
            obs_fresh_inc = float(h_row.HFPOW) if hasattr(h_row, "HFPOW") and h_row.HFPOW > 0 else (obs_fresh_cum - prev_sim_fresh)
            obs_dry_cum = float(h_row.CHPDT)
            obs_dry_inc = float(h_row.HPODW) if hasattr(h_row, "HPODW") and h_row.HPODW > 0 else (obs_dry_cum - prev_sim_dry)

            # Get uncertainties
            sd_fc, n_fc, se_fc = unc_lookup.get((trt_str, f"{year:04d}-{doy:03d}", "CHFPW"), (np.nan, np.nan, np.nan))
            sd_fi, n_fi, se_fi = unc_lookup.get((trt_str, f"{year:04d}-{doy:03d}", "HFPOW"), (np.nan, np.nan, np.nan))
            sd_dc, n_dc, se_dc = unc_lookup.get((trt_str, f"{year:04d}-{doy:03d}", "CHPDT"), (np.nan, np.nan, np.nan))
            sd_di, n_di, se_di = unc_lookup.get((trt_str, f"{year:04d}-{doy:03d}", "HPODW"), (np.nan, np.nan, np.nan))

            base_record = {
                "run_id": run_id,
                "data_status": data_status,
                "dataset_role": dataset_role,
                "treatment": trt_str,
                "time": dap,
                "time_label": "Days after planting",
                "source_file": "FreshWt.OUT",
                "date_code": float(date_code),
                "year": float(year),
                "doy": float(doy),
                "dap": float(dap),
                "harvest_number": float(h_num),
                "season_id": season_id,
            }

            # 1. FRESH_CUM
            spec = VARIABLE_SPECS["FRESH_CUM"]
            records.append({
                **base_record,
                "variable": "FRESH_CUM",
                "variable_label": spec["label"],
                "unit": spec["unit"],
                "observed": obs_fresh_cum,
                "simulated": sim_fresh_cum,
                "observed_sd": sd_fc,
                "observed_se": se_fc,
                "n_rep": n_fc,
            })

            # 2. FRESH_INC
            spec = VARIABLE_SPECS["FRESH_INC"]
            records.append({
                **base_record,
                "variable": "FRESH_INC",
                "variable_label": spec["label"],
                "unit": spec["unit"],
                "observed": obs_fresh_inc,
                "simulated": sim_fresh_inc,
                "observed_sd": sd_fi,
                "observed_se": se_fi,
                "n_rep": n_fi,
            })

            # 3. DRY_CUM
            spec = VARIABLE_SPECS["DRY_CUM"]
            records.append({
                **base_record,
                "variable": "DRY_CUM",
                "variable_label": spec["label"],
                "unit": spec["unit"],
                "observed": obs_dry_cum,
                "simulated": sim_dry_cum,
                "observed_sd": sd_dc,
                "observed_se": se_dc,
                "n_rep": n_dc,
            })

            # 4. DRY_INC
            spec = VARIABLE_SPECS["DRY_INC"]
            records.append({
                **base_record,
                "variable": "DRY_INC",
                "variable_label": spec["label"],
                "unit": spec["unit"],
                "observed": obs_dry_inc,
                "simulated": sim_dry_inc,
                "observed_sd": sd_di,
                "observed_se": se_di,
                "n_rep": n_di,
            })

            prev_sim_fresh = sim_fresh_cum
            prev_sim_dry = sim_dry_cum
            h_num += 1

        # Growth rows (LAID, LWAD, SWAD, CWAD, LN%D)
        g_rows = t_sub[t_sub["LAID"] > 0].copy()
        for g_row in g_rows.itertuples(index=False):
            date_code = int(g_row.DATE)
            year = 2000 + date_code // 1000
            doy = date_code % 1000

            for v in ["LAID", "LWAD", "SWAD", "CWAD", "LN%D"]:
                sim_pair = sim_lookup.get((v, trt_str, date_code))
                if sim_pair is None:
                    continue
                sim_val, dap = sim_pair

                obs_val = np.nan
                if v == "LAID":
                    obs_val = float(g_row.LAID)
                elif v == "LWAD":
                    obs_val = float(g_row.LWAD)
                elif v == "SWAD":
                    obs_val = float(g_row.SWAD)
                elif v == "CWAD":
                    if float(g_row.LWAD) > 0 and float(g_row.SWAD) > 0:
                        obs_val = float(g_row.LWAD) + float(g_row.SWAD)
                elif v == "LN%D":
                    if hasattr(g_row, "LNAM") and float(g_row.LNAM) > 0 and float(g_row.LWAD) > 0:
                        obs_val = (float(g_row.LNAM) / float(g_row.LWAD)) * 100.0

                if not np.isfinite(obs_val) or obs_val <= 0:
                    continue

                spec = VARIABLE_SPECS[v]
                sd_v, n_v, se_v = unc_lookup.get((trt_str, f"{year:04d}-{doy:03d}", v), (np.nan, np.nan, np.nan))

                records.append({
                    "run_id": run_id,
                    "data_status": data_status,
                    "dataset_role": dataset_role,
                    "variable": v,
                    "variable_label": spec["label"],
                    "unit": spec["unit"],
                    "treatment": trt_str,
                    "time": dap,
                    "time_label": "Days after planting",
                    "observed": obs_val,
                    "simulated": sim_val,
                    "source_file": "PlantGro.OUT",
                    "date_code": float(date_code),
                    "year": float(year),
                    "doy": float(doy),
                    "dap": float(dap),
                    "harvest_number": np.nan,
                    "observed_sd": sd_v,
                    "observed_se": se_v,
                    "n_rep": n_v,
                    "season_id": season_id,
                })

    # 4. Extract Season-End Observations from Evaluate.OUT / FileA
    eval_dict = _parse_evaluate_file(run_dir / "Evaluate.OUT")
    for trno_val in sorted(file_a["TRNO"].unique()):
        trt_str = str(int(float(trno_val)))
        a_row = file_a[file_a["TRNO"] == trno_val].iloc[0]
        eval_trt = eval_dict.get(trt_str, {})

        # LAIX
        obs_laix = float(a_row.LAIX) if "LAIX" in a_row and a_row.LAIX > 0 else np.nan
        sim_laix = eval_trt.get("LAIXS")
        if sim_laix is None:
            # Fall back to max LAID in trajectory
            sub_laid = trajectories[(trajectories["treatment"] == trt_str) & (trajectories["variable"] == "LAID")]
            if not sub_laid.empty:
                sim_laix = float(sub_laid["simulated"].max())

        if np.isfinite(obs_laix) and sim_laix is not None and np.isfinite(sim_laix):
            spec = VARIABLE_SPECS["LAIX"]
            records.append({
                "run_id": run_id,
                "data_status": data_status,
                "dataset_role": dataset_role,
                "variable": "LAIX",
                "variable_label": spec["label"],
                "unit": spec["unit"],
                "treatment": trt_str,
                "time": 0.0,
                "time_label": "Season end",
                "observed": obs_laix,
                "simulated": float(sim_laix),
                "source_file": "Evaluate.OUT",
                "date_code": np.nan,
                "year": float(2000 + int(a_row.PDAT) // 1000) if "PDAT" in a_row and a_row.PDAT > 0 else np.nan,
                "doy": np.nan,
                "dap": np.nan,
                "harvest_number": np.nan,
                "observed_sd": np.nan,
                "observed_se": np.nan,
                "n_rep": np.nan,
                "season_id": season_id,
            })

        # ADAP
        obs_adap = eval_trt.get("ADAPM")
        sim_adap = eval_trt.get("ADAPS")
        if obs_adap is None and "ADAT" in a_row and "PDAT" in a_row:
            if a_row.ADAT > 0 and a_row.PDAT > 0:
                obs_adap = float(a_row.ADAT - a_row.PDAT)

        if obs_adap is not None and sim_adap is not None and np.isfinite(obs_adap) and np.isfinite(sim_adap):
            spec = VARIABLE_SPECS["ADAP"]
            records.append({
                "run_id": run_id,
                "data_status": data_status,
                "dataset_role": dataset_role,
                "variable": "ADAP",
                "variable_label": spec["label"],
                "unit": spec["unit"],
                "treatment": trt_str,
                "time": float(obs_adap),
                "time_label": "Days after planting",
                "observed": float(obs_adap),
                "simulated": float(sim_adap),
                "source_file": "Evaluate.OUT",
                "date_code": np.nan,
                "year": float(2000 + int(a_row.PDAT) // 1000) if "PDAT" in a_row and a_row.PDAT > 0 else np.nan,
                "doy": np.nan,
                "dap": float(obs_adap),
                "harvest_number": np.nan,
                "observed_sd": np.nan,
                "observed_se": np.nan,
                "n_rep": np.nan,
                "season_id": season_id,
            })

    return records


def export_dual_spring_bundle(
    *,
    run_id: str = "eggplant_150x5_v7a_joint",
    out_dir: Path,
    dir_26sp_sim: Path,
    dir_26sp_staged: Path,
    dir_25sp_sim: Path,
    dir_25sp_staged: Path,
    phi_csv: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    data_status = "legacy_unvalidated"

    print("Extracting 2026 Spring comparison pairs (Calibration)...")
    records_26 = extract_season_comparison(
        season_id="26SP",
        dataset_role="calibration",
        run_id=run_id,
        data_status=data_status,
        run_dir=dir_26sp_sim,
        staged_dir=dir_26sp_staged,
    )
    print(f"  Extracted {len(records_26)} records from 26SP.")

    print("Extracting 2025 Spring comparison pairs (Validation)...")
    records_25 = extract_season_comparison(
        season_id="25SP",
        dataset_role="validation",
        run_id=run_id,
        data_status=data_status,
        run_dir=dir_25sp_sim,
        staged_dir=dir_25sp_staged,
    )
    print(f"  Extracted {len(records_25)} records from 25SP.")

    # 1. Comparison table
    all_comparison = pd.DataFrame(records_26 + records_25)
    valid_comparison = validate_comparison_table(all_comparison)
    comp_file = out_dir / "comparison.csv"
    valid_comparison.to_csv(comp_file, index=False, encoding="utf-8")
    print(f"Saved {comp_file} ({len(valid_comparison)} total pairs).")

    # 2. Simulation Trajectory table
    print("Reading daily DSSAT trajectories...")
    traj_26 = read_dssat_trajectories(dir_26sp_sim, run_id=run_id, data_status=data_status)
    traj_26["season_id"] = "26SP"
    traj_26["dataset_role"] = "calibration"

    traj_25 = read_dssat_trajectories(dir_25sp_sim, run_id=run_id, data_status=data_status)
    traj_25["season_id"] = "25SP"
    traj_25["dataset_role"] = "validation"

    traj_cols = list(TRAJECTORY_COLUMNS) + ["season_id"]
    all_traj = pd.concat([traj_26, traj_25], ignore_index=True)[traj_cols]
    traj_file = out_dir / "simulation_trajectory.csv"
    all_traj.to_csv(traj_file, index=False, encoding="utf-8")
    print(f"Saved {traj_file} ({len(all_traj)} daily simulation records).")

    # 3. Treatment Metadata
    meta_26 = pd.read_csv(dir_26sp_staged / "treatment_metadata.csv")
    meta_26["season_id"] = "26SP"
    meta_26["dataset_role"] = "calibration"
    meta_26["treatment_label"] = "TN" + meta_26["treatment"].astype(str) + " (" + meta_26["water_level"] + "-" + meta_26["nitrogen_level"] + ")"

    meta_25 = pd.read_csv(dir_25sp_staged / "treatment_metadata.csv")
    meta_25["season_id"] = "25SP"
    meta_25["dataset_role"] = "validation"
    meta_25["treatment_label"] = "TN" + meta_25["treatment"].astype(str) + " (" + meta_25["water_level"] + "-" + meta_25["nitrogen_level"] + ")"

    meta_cols = ["season_id", "treatment", "treatment_label", "water_level", "nitrogen_level", "dataset_role"]
    all_meta = pd.concat([meta_25, meta_26], ignore_index=True)[meta_cols]
    valid_meta = validate_treatment_metadata(all_meta)
    meta_file = out_dir / "treatment_metadata.csv"
    valid_meta.to_csv(meta_file, index=False, encoding="utf-8")
    print(f"Saved {meta_file} ({len(valid_meta)} treatments).")

    # 4. Phi history
    phi = read_phi_ensemble(phi_csv)
    phi.insert(0, "data_status", data_status)
    phi.insert(0, "run_id", run_id)
    phi_file = out_dir / "phi_ensemble.csv"
    phi.to_csv(phi_file, index=False, encoding="utf-8")
    print(f"Saved {phi_file} ({len(phi)} ensemble realization records).")

    # 5. Manifest
    artifacts = [comp_file, traj_file, meta_file, phi_file]
    manifest_data = {
        "schema_version": 2,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_status": "legacy_layout_demo",
        "scenario_type": "actual_trial_calibration",
        "renderer_contract": "r_paper_figures_v2",
        "artifacts": [_artifact(p) for p in artifacts],
        "sources": [
            {"path": str(p), "sha256": _sha256(p)}
            for p in [comp_file, traj_file, meta_file, phi_file, phi_csv]
            if p.is_file()
        ],
        "notes": "Dual-Spring (26SP Calibration + 25SP Validation) evaluation bundle under DSSAT v7a critical N & organ buffer model."
    }
    manifest_file = out_dir / "paper_data_manifest.json"
    manifest_file.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved manifest: {manifest_file}")
    return manifest_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export dual-spring paper data bundle")
    parser.add_argument("--out-dir", default=r"D:\Tomato_Cal\workspace\paper_data_dual_spring")
    args = parser.parse_args()

    dir_26_sim = Path(r"D:\Tomato_Cal\subprojects\critical_n\n_buffer_v7\runs\eggplant_150x5_v7a_joint\champion_eval\native_trials\a8edaa17efc74cdf997b82eea84b4cd9")
    dir_26_stg = Path(r"D:\Tomato_Cal\workspace\staging\input_refresh_20261010\xxql2601_refreshed_20261010")
    dir_25_sim = Path(r"D:\Tomato_Cal\subprojects\critical_n\n_buffer_v7\experiments\eval_25sp_slpf_0.960")
    dir_25_stg = Path(r"D:\Tomato_Cal\workspace\staging\input_refresh_20261010\xxql2501_refreshed_20261010")
    phi_path = Path(r"D:\Tomato_Cal\subprojects\critical_n\n_buffer_v7\runs\eggplant_150x5_v7a_joint\master\case.phi.actual.csv")

    export_dual_spring_bundle(
        out_dir=Path(args.out_dir),
        dir_26sp_sim=dir_26_sim,
        dir_26sp_staged=dir_26_stg,
        dir_25sp_sim=dir_25_sim,
        dir_25sp_staged=dir_25_stg,
        phi_csv=phi_path,
    )
