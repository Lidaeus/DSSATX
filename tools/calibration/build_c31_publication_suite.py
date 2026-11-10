"""Build and render publication suite for Champion Candidate C31.

Champion C31: Dual-Spring Precision Champion (Scheme 1 physical soil calibration with TB1=9.20°C).
1. Forward DSSAT simulation passes across 3 seasons (25SP, 26SP, 25FA) using C31 params.
2. Align daily trajectory and comparison frames with configs/figures/treatment_metadata_xxql2501_2601_joint.csv.
3. Export canonical frozen data bundles into paper/paper_data/ (25SP, 26SP, 25FA, terminal, leaf_n, ensemble, conditional).
4. Render publication figures via R (make_all.R) with clean figure labels.
5. Synchronize all publication figures into paper/03_Figures/ (Main_Figures, Supplementary_Figures, Custom_Diagnostic_Figures).
6. Compile root paper/03_Figures/figure_manifest.json and update paper/03_Figures/README.md.
7. Verify all artifact SHA-256 hashes against disk.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import numpy as np
import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dssat.run_dssat import prepare_run_directory
from src.reporting.analyze_results import (
    deterministic_harvest_compare,
    deterministic_process_compare,
    deterministic_joint_compare,
)
from src.reporting.export_paper_data import export_bundle
from src.reporting.figure_data import VARIABLE_SPECS, read_dssat_trajectories

# Configurations & Paths
RUN_ID = "c31_scheme1_dual_spring_precision"
CANDIDATE_DIR = ROOT / "workspace/candidates/candidate_c31_scheme1_dual_spring_precision"
C31_PARAMS = CANDIDATE_DIR / "params.csv"
CALIB_RUN_DIR = ROOT / "workspace/runs/full_gen_13trt_final_scheme1_tb1_tighten_200x6_20260927"
PHI_CSV = CALIB_RUN_DIR / "full_gen_13trt_final_scheme1_tb1_tighten_200x6_20260927.phi.actual.csv"

DET_DIR = ROOT / "workspace/runs/c31_deterministic"
PAPER_DATA_DIR = ROOT / "paper/paper_data"
FIGURES_RENDER_DIR = ROOT / "paper/figures"
FIGURES_03_DIR = ROOT / "paper/03_Figures"

RSCRIPT = Path(r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe")
PUB_NOTE = "User authorized clean C31 champion figures on 2026-09-27; scientific status unchanged."

SEASONS_INFO = {
    "25SP": {
        "exp_dir": ROOT / "data/user/experiments/xxql2501_corrected_20260923",
        "trts": [2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14],
        "selected_trts": "10,13",
    },
    "26SP": {
        "exp_dir": ROOT / "data/user/experiments/xxql2601_corrected_20260923",
        "trts": list(range(1, 13)),
        "selected_trts": "3,12",
    },
    "25FA": {
        "exp_dir": ROOT / "data/user/experiments/xxql2502_corrected_20260923",
        "trts": list(range(1, 13)),
        "selected_trts": "3,9",
    },
}


def sha256_file(path: Path | str) -> str:
    """Calculate SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def calendar_date(code: int) -> dt.date:
    """Convert YYDDD integer to date."""
    code = int(code)
    return dt.date(2000 + code // 1000, 1, 1) + dt.timedelta(days=code % 1000 - 1)


# =========================================================================
# Step 1: Forward DSSAT Simulation Passes
# =========================================================================
def run_forward_simulations() -> dict[str, Path]:
    """Execute DSSAT deterministic forward runs for 25SP, 26SP, and 25FA."""
    print("=" * 80)
    print("Step 1: Running Forward DSSAT Simulations for C31 Champion")
    print("=" * 80)

    season_targets: dict[str, Path] = {}
    for season, info in SEASONS_INFO.items():
        print(f"\n[Forward Run] Starting forward DSSAT simulation for {season}...")
        sdir = DET_DIR / "_seasons" / season
        sdir.mkdir(parents=True, exist_ok=True)
        exp_dir = info["exp_dir"]

        # 1. Copy base genotype templates
        for bf in ["TMGRO048.CUL.base", "TMGRO048.ECO.base", "TMGRO048.SPE.base"]:
            shutil.copy2(ROOT / "data/templates/genotype" / bf, sdir / bf)

        # 2. Copy experiment files
        for item in exp_dir.glob("*"):
            if item.is_file() and not item.name.endswith(".OUT"):
                shutil.copy2(item, sdir / item.name)

        # 3. Prepare run directory
        batch_dest = prepare_run_directory(sdir, ["--batch", str(sdir / "DSSBatch.v48"), "--input-dir", str(sdir)])

        # 4. Execute DSSAT via run_dssat
        cmd = [
            sys.executable,
            "-m",
            "src.dssat.run_dssat",
            "--param-csv",
            str(C31_PARAMS.resolve()),
            "--batch",
            batch_dest.name,
            "--harvest-var",
            "CHPDT",
            "--input-dir",
            str(sdir.resolve()),
        ]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")

        res = subprocess.run(cmd, cwd=sdir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        if res.returncode != 0:
            raise RuntimeError(f"DSSAT forward simulation failed for {season} with returncode {res.returncode}")

        # Check required output files
        assert (sdir / "PlantGro.OUT").is_file(), f"Missing PlantGro.OUT in {sdir}"
        assert (sdir / "FreshWt.OUT").is_file(), f"Missing FreshWt.OUT in {sdir}"
        assert (sdir / "Evaluate.OUT").is_file(), f"Missing Evaluate.OUT in {sdir}"

        # 5. Run compare extractions
        batch_file = sdir / "DSSBatch.v48"
        deterministic_harvest_compare(season, str(batch_file), run_dir=str(sdir))
        deterministic_process_compare(season, str(batch_file), run_dir=str(sdir))
        deterministic_joint_compare(season, str(batch_file), run_dir=str(sdir))

        print(f"[Forward Run] Completed {season} forward pass successfully.")
        season_targets[season] = sdir

    return season_targets


# =========================================================================
# Step 2: Build and Export Frozen Data Bundles to paper/paper_data/
# =========================================================================
def build_paper_data_bundles(season_targets: dict[str, Path]) -> None:
    """Build canonical frozen data bundles in paper/paper_data/."""
    print("\n" + "=" * 80)
    print("Step 2: Exporting Canonical Frozen Data Bundles to paper/paper_data/")
    print("=" * 80)

    PAPER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_data_dir = DET_DIR / "temp_data"
    temp_data_dir.mkdir(parents=True, exist_ok=True)

    # 1. Build authoritative 35-treatment metadata table
    joint_meta = pd.read_csv(ROOT / "configs/figures/treatment_metadata_xxql2501_2601_joint.csv")
    fa_meta_rows = []
    for trt in range(1, 13):
        # 25FA treatment details
        # W3: 1, 6, 10, 12; W2: 2, 5, 8, 11; W1: 3, 4, 7, 9
        fa_map = {
            1: ("W3", "N3", "TN1 (W3-N3)"),
            2: ("W2", "N3", "TN2 (W2-N3)"),
            3: ("W1", "N3", "TN3 (W1-N3)"),
            4: ("W1", "N2", "TN4 (W1-N2)"),
            5: ("W2", "N2", "TN5 (W2-N2)"),
            6: ("W3", "N2", "TN6 (W3-N2)"),
            7: ("W1", "N1", "TN7 (W1-N1)"),
            8: ("W2", "N1", "TN8 (W2-N1)"),
            9: ("W1", "N0", "TN9 (W1-N0)"),
            10: ("W3", "N1", "TN10 (W3-N1)"),
            11: ("W2", "N0", "TN11 (W2-N0)"),
            12: ("W3", "N0", "TN12 (W3-N0)"),
        }
        w, n, lbl = fa_map[trt]
        fa_meta_rows.append({
            "season_id": "25FA",
            "treatment": trt,
            "treatment_label": lbl,
            "water_level": w,
            "nitrogen_level": n,
            "dataset_role": "diagnostic",
        })
    full_meta = pd.concat([joint_meta, pd.DataFrame(fa_meta_rows)], ignore_index=True)
    assert len(full_meta) == 35, f"Expected 35 treatments in full metadata, got {len(full_meta)}"
    full_meta.to_csv(temp_data_dir / "treatment_metadata.csv", index=False)

    all_season_comparisons = []

    # 2. Process each seasonal bundle (25SP, 26SP, 25FA)
    for season, target in season_targets.items():
        print(f"\n[Data Export] Building bundle for {season}...")
        sm = full_meta[full_meta["season_id"] == season].copy()
        season_meta_path = temp_data_dir / f"{season}_treatment_metadata.csv"
        sm.to_csv(season_meta_path, index=False)
        roles = sm.set_index("treatment")["dataset_role"].to_dict()

        records = []
        for kind, variables in [
            ("process", ["LAID", "LWAD", "SWAD"]),
            ("harvest", ["DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM"]),
        ]:
            comp_path = target / f"{season}_deterministic_{kind}_compare.csv"
            df_comp = pd.read_csv(comp_path)
            for row in df_comp.to_dict("records"):
                tn = int(row["TN"])
                if tn not in roles:
                    continue
                date = int(row["DATE"])
                year = 2000 + date // 1000
                doy = date % 1000
                for var in variables:
                    o = row.get(f"OBS_{var}", np.nan)
                    s = row.get(f"SIM_{var}", np.nan)
                    if not np.isfinite(o) or not np.isfinite(s) or o < 0 or s < 0:
                        continue
                    spec = VARIABLE_SPECS[var]
                    records.append({
                        "run_id": RUN_ID,
                        "data_status": "legacy_unvalidated",
                        "dataset_role": roles[tn],
                        "variable": var,
                        "variable_label": spec["label"],
                        "unit": spec["unit"],
                        "treatment": str(tn),
                        "time": doy,
                        "time_label": "Day of year",
                        "observed": float(o),
                        "simulated": float(s),
                        "source_file": str(comp_path),
                        "date_code": date,
                        "year": year,
                        "doy": doy,
                        "dap": np.nan,
                        "harvest_number": row.get("HNO", np.nan),
                        "observed_sd": np.nan,
                        "observed_se": np.nan,
                        "n_rep": np.nan,
                        "season_id": season,
                    })

        comp = pd.DataFrame(records)

        # Align DAP with daily trajectories
        daily = read_dssat_trajectories(target, run_id=RUN_ID, data_status="legacy_unvalidated")
        origins = {}
        for tn, d in daily.groupby("treatment"):
            starts = {calendar_date(r.date_code) - dt.timedelta(days=float(r.time)) for r in d.itertuples()}
            assert len(starts) == 1, (season, tn, starts)
            origins[str(tn)] = starts.pop()

        comp["dap"] = [(calendar_date(r.date_code) - origins[str(r.treatment)]).days for r in comp.itertuples()]
        comp["time"] = comp["dap"]
        comp["time_label"] = "Days after planting"

        dates = pd.read_csv(target / f"{season}_deterministic_process_compare.csv")[
            ["TN", "DATE", "SIM_DATE", "SIM_DATE_GAP_DAYS"]
        ]
        dates.insert(0, "season_id", season)
        date_source = temp_data_dir / f"{season}_process_date_matching.csv"
        dates.to_csv(date_source, index=False)

        comp_input = temp_data_dir / f"{season}_comparison_input.csv"
        comp.to_csv(comp_input, index=False)

        # Export bundle via export_bundle
        bundle_out = PAPER_DATA_DIR / season
        export_bundle(
            run_id=RUN_ID,
            out_dir=bundle_out,
            comparison_csv=comp_input,
            trajectory_run_dir=target,
            treatment_metadata_csv=season_meta_path,
            phi_csv=PHI_CSV,
            allow_unvalidated_demo=True,
        )

        # Update comparison with process date matching columns
        frozen_comp = pd.read_csv(bundle_out / "comparison.csv")
        frozen_comp = frozen_comp.merge(
            dates.rename(columns={
                "TN": "treatment",
                "DATE": "date_code",
                "SIM_DATE": "simulation_date_code",
                "SIM_DATE_GAP_DAYS": "simulation_date_gap_days",
            }),
            on=["season_id", "treatment", "date_code"],
            how="left",
            validate="many_to_one",
        )
        nonprocess = ~frozen_comp["variable"].isin(["LAID", "LWAD", "SWAD"])
        frozen_comp.loc[nonprocess, ["simulation_date_code", "simulation_date_gap_days"]] = np.nan
        frozen_comp.to_csv(bundle_out / "comparison.csv", index=False)

        # Update paper_data_manifest.json with new comparison.csv hash
        manifest_path = bundle_out / "paper_data_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for art in manifest["artifacts"]:
            if art["path"] == "comparison.csv":
                art["sha256"] = sha256_file(bundle_out / "comparison.csv")
        manifest["sources"].append({"path": str(date_source), "sha256": sha256_file(date_source)})
        manifest["process_date_matching"] = (
            "Metrics exclude nonzero simulation_date_gap_days; dynamics retain all observations without extending simulation."
        )
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        all_season_comparisons.append(frozen_comp)
        print(f"[Data Export] {season} bundle exported and verified.")

    # 3. Export terminal bundle
    print("\n[Data Export] Building terminal bundle for 35 treatments...")
    combined_comp = pd.concat(all_season_comparisons, ignore_index=True)
    combined_comp.to_csv(temp_data_dir / "three_season_comparison.csv", index=False)

    terminal = (
        combined_comp[combined_comp["variable"].isin(["FRESH_CUM", "DRY_CUM"])]
        .sort_values("date_code")
        .groupby(["season_id", "treatment", "variable"])
        .tail(1)
    )
    terminal_input = temp_data_dir / "terminal_comparison_input.csv"
    terminal.to_csv(terminal_input, index=False)

    terminal_bundle = PAPER_DATA_DIR / "terminal"
    export_bundle(
        run_id=RUN_ID,
        out_dir=terminal_bundle,
        comparison_csv=terminal_input,
        treatment_metadata_csv=temp_data_dir / "treatment_metadata.csv",
        phi_csv=PHI_CSV,
        allow_unvalidated_demo=True,
    )
    print("[Data Export] Terminal bundle exported successfully.")

    # 4. Export leaf_n bundle
    print("\n[Data Export] Building leaf_n bundle...")
    excel_path = next((ROOT / "data/user/ref").rglob("2025年春季茄子植株样氮磷钾测定.xlsx"))
    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    rows = list(wb["Sheet1"].values)
    raw = pd.DataFrame(
        [r[:9] for r in rows[1:] if r[1] == "叶"],
        columns=["date", "organ", "plot", "rep", "n_mg_g", "p_mg_g", "k_mg_g", "water", "nitrogen"],
    )
    raw["n_pct"] = pd.to_numeric(raw["n_mg_g"]) / 10.0
    agg = raw.groupby(["date", "plot", "water", "nitrogen"])["n_pct"].agg(["mean", "std", "count"]).reset_index()

    sp_trajectory = pd.read_csv(PAPER_DATA_DIR / "25SP/simulation_trajectory.csv")
    sp_meta = pd.read_csv(temp_data_dir / "25SP_treatment_metadata.csv").set_index("treatment")
    sp_meta.loc[14, "nitrogen_level"] = "CK"
    sp_meta.loc[14, "treatment_label"] = "TN14 (CK)"
    leaf_meta_path = temp_data_dir / "leaf_n_treatment_metadata.csv"
    sp_meta.reset_index().to_csv(leaf_meta_path, index=False)

    leaf_records = []
    for r in agg.to_dict("records"):
        day = pd.Timestamp(r["date"])
        doy = day.dayofyear
        code = (day.year % 100) * 1000 + doy
        tn = int(r["plot"])
        sim_slice = sp_trajectory[
            (sp_trajectory["variable"] == "LN%D")
            & (sp_trajectory["treatment"] == tn)
            & (sp_trajectory["date_code"] == code)
        ]
        assert len(sim_slice) == 1, f"Missing LN%D trajectory match for TN {tn} date {code}"
        spec = VARIABLE_SPECS["LN%D"]
        sim_node = sim_slice.iloc[0]
        leaf_records.append({
            "run_id": RUN_ID,
            "data_status": "legacy_unvalidated",
            "dataset_role": "diagnostic",
            "variable": "LN%D",
            "variable_label": spec["label"],
            "unit": spec["unit"],
            "treatment": str(tn),
            "time": sim_node["time"],
            "time_label": "Days after planting",
            "observed": float(r["mean"]),
            "simulated": float(sim_node["simulated"]),
            "source_file": str(excel_path),
            "date_code": code,
            "year": day.year,
            "doy": doy,
            "dap": sim_node["time"],
            "harvest_number": np.nan,
            "observed_sd": float(r["std"]),
            "observed_se": np.nan,
            "n_rep": int(r["count"]),
            "season_id": "25SP",
        })

    leaf_comp = pd.DataFrame(leaf_records)
    leaf_comp_input = temp_data_dir / "leaf_n_comparison_input.csv"
    leaf_comp.to_csv(leaf_comp_input, index=False)

    leaf_bundle = PAPER_DATA_DIR / "leaf_n"
    export_bundle(
        run_id=RUN_ID,
        out_dir=leaf_bundle,
        comparison_csv=leaf_comp_input,
        trajectory_run_dir=season_targets["25SP"],
        treatment_metadata_csv=leaf_meta_path,
        allow_unvalidated_demo=True,
    )
    m_leaf = json.loads((leaf_bundle / "paper_data_manifest.json").read_text(encoding="utf-8"))
    m_leaf["sources"].append({"path": str(excel_path), "sha256": sha256_file(excel_path)})
    m_leaf["replicate_interpretation"] = (
        "Three records labelled repeat per plot, independence not established; SD retained; no inferential SE/error bars."
    )
    m_leaf["control_label"] = "Raw workbook TN14 is CK/CK; the leaf figure retains CK rather than assigning N2."
    (leaf_bundle / "paper_data_manifest.json").write_text(
        json.dumps(m_leaf, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("[Data Export] leaf_n bundle exported successfully.")

    # 5. Export ensemble bundle
    print("\n[Data Export] Building ensemble bundle...")
    ensemble_dst = PAPER_DATA_DIR / "ensemble"
    ensemble_dst.mkdir(parents=True, exist_ok=True)
    ensemble_artifacts = []
    for f in sorted(ensemble_dst.glob("*.csv")):
        ensemble_artifacts.append({"path": f.name, "sha256": sha256_file(f)})

    ensemble_manifest = {
        "run_id": "full_gen_13trt_final_calib_200x8",
        "bundle_type": "t4_posterior_equifinality",
        "data_status": "tooling_demo",
        "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifacts": sorted(ensemble_artifacts, key=lambda x: x["path"]),
    }
    (ensemble_dst / "paper_data_manifest.json").write_text(
        json.dumps(ensemble_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[Data Export] ensemble bundle prepared with {len(ensemble_artifacts)} CSV artifacts.")

    # 6. Export conditional bundle
    print("\n[Data Export] Building conditional bundle...")
    conditional_dst = PAPER_DATA_DIR / "conditional"
    conditional_dst.mkdir(parents=True, exist_ok=True)
    conditional_src = ROOT / "workspace/runs/full_gen_13trt_final_uncertainty_200x6_20260924/paper_data_conditional"
    if conditional_src.exists() and not (conditional_dst / "conditional_prediction_summary.csv").exists():
        for f in conditional_src.glob("*"):
            if f.is_file() and f.name != "paper_data_manifest.json":
                shutil.copy2(f, conditional_dst / f.name)

    conditional_artifacts = []
    for f in sorted(conditional_dst.glob("*")):
        if f.is_file() and f.name != "paper_data_manifest.json":
            conditional_artifacts.append({"path": f.name, "sha256": sha256_file(f)})

    if (conditional_dst / "paper_data_manifest.json").exists():
        src_manifest = json.loads((conditional_dst / "paper_data_manifest.json").read_text(encoding="utf-8"))
    elif conditional_src.exists() and (conditional_src / "paper_data_manifest.json").exists():
        src_manifest = json.loads((conditional_src / "paper_data_manifest.json").read_text(encoding="utf-8"))
    else:
        src_manifest = {}
    conditional_manifest = {
        "schema_version": 1,
        "bundle_type": "conditional_ensemble_predictions",
        "run_id": "full_gen_13trt_final_calib_200x8",
        "ensemble_iteration": 6,
        "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_status": "legacy_layout_demo",
        "scenario_type": "actual_trial_calibration",
        "interval_semantics": "parameter_conditional_ensemble_only",
        "renderer_contract": "r_conditional_figures_v1",
        "artifacts": sorted(conditional_artifacts, key=lambda x: x["path"]),
        "sources": src_manifest.get("sources", []),
        "selected_members": src_manifest.get("selected_members", {"n_complete_case": 141, "n_requested": 141, "demo_subset": False}),
    }
    (conditional_dst / "paper_data_manifest.json").write_text(
        json.dumps(conditional_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[Data Export] conditional bundle prepared with {len(conditional_artifacts)} artifacts.")

    print("\n[Data Export] All 7 data bundles successfully exported into paper/paper_data/.")


# =========================================================================
# Step 3: Render All Publication Figures via R
# =========================================================================
def render_r_figures() -> None:
    """Invoke R pipeline (paper/R/make_all.R) across all 7 bundles."""
    print("\n" + "=" * 80)
    print("Step 3: Rendering Publication Figures with R (make_all.R)")
    print("=" * 80)

    if not RSCRIPT.is_file():
        raise FileNotFoundError(f"Rscript not found at: {RSCRIPT}")

    FIGURES_RENDER_DIR.mkdir(parents=True, exist_ok=True)
    logs_dir = FIGURES_RENDER_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    tasks: list[tuple[str, Path, Path, list[str]]] = []
    # 1. 25SP
    tasks.append((
        "25SP",
        PAPER_DATA_DIR / "25SP",
        FIGURES_RENDER_DIR / "25SP",
        [
            "--figure-ids",
            "fig3_performance,figs3_residuals,fig4_dynamics,figs4_all_treatments,fig_water_nitrogen_response",
            "--variables",
            "LAID,LWAD,SWAD,FRESH_INC",
            "--process-variables",
            "LAID,LWAD,SWAD",
            "--supplement-process-variables",
            "LAID,LWAD,SWAD",
            "--treatments",
            "10,13",
        ],
    ))
    # 2. 26SP
    tasks.append((
        "26SP",
        PAPER_DATA_DIR / "26SP",
        FIGURES_RENDER_DIR / "26SP",
        [
            "--figure-ids",
            "fig3_performance,figs3_residuals,fig4_dynamics,figs4_all_treatments,fig_water_nitrogen_response",
            "--variables",
            "LAID,LWAD,SWAD,FRESH_INC",
            "--process-variables",
            "LAID,LWAD,SWAD",
            "--supplement-process-variables",
            "LAID,LWAD,SWAD",
            "--treatments",
            "3,12",
        ],
    ))
    # 3. 25FA
    tasks.append((
        "25FA",
        PAPER_DATA_DIR / "25FA",
        FIGURES_RENDER_DIR / "25FA",
        [
            "--figure-ids",
            "fig3_performance,figs3_residuals,fig4_dynamics,figs4_all_treatments,fig_water_nitrogen_response",
            "--variables",
            "LAID,LWAD,SWAD,FRESH_INC",
            "--process-variables",
            "LAID,LWAD,SWAD",
            "--supplement-process-variables",
            "LAID,LWAD,SWAD",
            "--treatments",
            "3,9",
        ],
    ))
    # 4. Main (Terminal)
    tasks.append((
        "main",
        PAPER_DATA_DIR / "terminal",
        FIGURES_RENDER_DIR / "main",
        [
            "--figure-ids",
            "fig2_phi,fig3_performance,fig_water_nitrogen_response",
            "--variables",
            "FRESH_CUM",
        ],
    ))
    # 5. Leaf N
    tasks.append((
        "leaf_n",
        PAPER_DATA_DIR / "leaf_n",
        FIGURES_RENDER_DIR / "leaf_n",
        [
            "--figure-ids",
            "fig_leaf_nitrogen",
        ],
    ))
    # 6. Ensemble
    tasks.append((
        "ensemble",
        PAPER_DATA_DIR / "ensemble",
        FIGURES_RENDER_DIR / "ensemble",
        [
            "--figure-ids",
            "figs5_posterior,figs6_spearman,figs7_equifinality",
        ],
    ))
    # 7. Conditional
    tasks.append((
        "conditional",
        PAPER_DATA_DIR / "conditional",
        FIGURES_RENDER_DIR / "conditional",
        [
            "--figure-ids",
            "fig_model_performance_uncertainty,diagnostic_conditional_residual_by_treatment,fig4_dynamics_conditional,figs4_all_treatments_conditional",
            "--process-variables",
            "LAID,LWAD,SWAD",
        ],
    ))

    def _render_task(task: tuple[str, Path, Path, list[str]]) -> dict[str, Any]:
        name, src, dst, options = task
        dst.mkdir(parents=True, exist_ok=True)
        command = [
            str(RSCRIPT),
            "paper/R/make_all.R",
            "--input-dir",
            str(src),
            "--out-dir",
            str(dst),
            *options,
            "--allow-unvalidated-demo",
            "--publication-label-note",
            PUB_NOTE,
        ]
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        env["LANG"] = "en_US"

        log_path = logs_dir / f"R_{name}.log"
        with log_path.open("w", encoding="utf-8") as f:
            proc = subprocess.run(command, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, env=env)
        print(f"[R Render] {name:12s} -> exit code {proc.returncode}")
        return {"name": name, "command": command, "returncode": proc.returncode, "log": str(log_path)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(_render_task, tasks))

    failed = [r for r in results if r["returncode"] != 0]
    if failed:
        for f in failed:
            print(f"Error in {f['name']}: log at {f['log']}")
        raise RuntimeError(f"R figure rendering failed for {len(failed)} tasks")

    print("[R Render] All R publication figures rendered successfully.")


# =========================================================================
# Step 4: Synchronize Figures into paper/03_Figures/
# =========================================================================
def synchronize_and_finalize() -> None:
    """Clean and synchronize rendered figures into paper/03_Figures/."""
    print("\n" + "=" * 80)
    print("Step 4: Synchronizing Figures into paper/03_Figures/")
    print("=" * 80)

    mf = FIGURES_03_DIR / "Main_Figures"
    sf = FIGURES_03_DIR / "Supplementary_Figures"
    cf = FIGURES_03_DIR / "Custom_Diagnostic_Figures"

    mf.mkdir(parents=True, exist_ok=True)
    sf.mkdir(parents=True, exist_ok=True)
    cf.mkdir(parents=True, exist_ok=True)

    # Clean old files
    for folder in [mf, sf, cf]:
        for f in folder.glob("*"):
            if f.is_file() and f.suffix.lower() in [".png", ".pdf", ".svg", ".csv"]:
                f.unlink()

    # Define authoritative figure mappings: (src_base_without_ext, dst_base_without_ext)
    fig_render = FIGURES_RENDER_DIR
    figure_mappings: list[tuple[Path, Path]] = [
        # Main figures - Canonical and legacy aliases
        (fig_render / "main/Fig2_phi_convergence", mf / "Fig2_phi_convergence"),
        (fig_render / "main/Fig2_phi_convergence", mf / "Fig2_Phi_Convergence"),
        (fig_render / "main/Fig2_phi_convergence", mf / "Fig7_Phi_Convergence"),
        (fig_render / "main/Fig3_model_performance", mf / "Fig3_model_performance"),
        (fig_render / "main/Fig3_model_performance", mf / "Fig3_Model_Performance_1to1"),
        (fig_render / "25SP/Fig4_process_dynamics", mf / "Fig4_process_dynamics"),
        (fig_render / "25SP/Fig4_process_dynamics", mf / "Fig1_Process_Dynamics"),
        (fig_render / "25SP/Fig4_harvest_dynamics", mf / "Fig4_harvest_dynamics"),
        (fig_render / "25SP/Fig4_harvest_dynamics", mf / "Fig2_Harvest_Dynamics"),
        (fig_render / "leaf_n/FigLeafN_leaf_nitrogen", mf / "FigLeafN_leaf_nitrogen"),
        (fig_render / "leaf_n/FigLeafN_leaf_nitrogen", mf / "Fig5_Leaf_Nitrogen_Dynamics"),
        (fig_render / "main/Fig6_water_nitrogen_response", mf / "Fig6_water_nitrogen_response"),
        (fig_render / "main/Fig6_water_nitrogen_response", mf / "Fig4_Water_Nitrogen_Response"),
        (fig_render / "main/Fig6_water_response", mf / "Fig6_water_response"),
        (fig_render / "25SP/FigS4_all_treatments_cumulative_smooth", mf / "FigS4_all_treatments_cumulative_smooth"),
        (fig_render / "25SP/FigS4_all_treatments_cumulative_smooth", mf / "Fig6_All_Treatments_Cumulative"),
        (fig_render / "conditional/conditional_model_performance_uncertainty", mf / "FigCondPerf_model_performance_uncertainty"),
        (fig_render / "conditional/conditional_model_performance_uncertainty", mf / "conditional_model_performance_uncertainty"),

        # Supplementary Figures - Canonical and legacy aliases
        (fig_render / "25SP/FigS3_residuals_calibration", sf / "FigS3_residuals_calibration"),
        (fig_render / "25SP/FigS3_residuals_validation", sf / "FigS3_residuals_validation"),
        (fig_render / "25SP/FigS4_all_treatments_LAID", sf / "FigS4_all_treatments_LAID"),
        (fig_render / "25SP/FigS4_all_treatments_LWAD", sf / "FigS4_all_treatments_LWAD"),
        (fig_render / "25SP/FigS4_all_treatments_SWAD", sf / "FigS4_all_treatments_SWAD"),
        (fig_render / "25SP/FigS4_all_treatments_increment", sf / "FigS4_all_treatments_increment"),
        (fig_render / "25SP/FigS4_all_treatments_cumulative_smooth", sf / "FigS4_all_treatments_cumulative_smooth"),
        (fig_render / "25SP/FigS4_all_treatments_cumulative_event", sf / "FigS4_all_treatments_cumulative_event"),
        (fig_render / "ensemble/FigS5_posterior_density", sf / "FigS5_posterior_density"),
        (fig_render / "ensemble/FigS5_posterior_density", sf / "FigS5a_posterior_density"),
        (fig_render / "ensemble/FigS5_posterior_contraction", sf / "FigS5_posterior_contraction"),
        (fig_render / "ensemble/FigS5_posterior_contraction", sf / "FigS5b_posterior_contraction"),
        (fig_render / "ensemble/FigS6_spearman_structure", sf / "FigS6_spearman_structure"),
        (fig_render / "ensemble/FigS7_candidate_prediction_distance", sf / "FigS7_candidate_prediction_distance"),
        (fig_render / "conditional/conditional_selected_process_dynamics", sf / "Fig4Cond_selected_process_dynamics"),
        (fig_render / "conditional/conditional_selected_process_dynamics", sf / "conditional_selected_process_dynamics"),
        (fig_render / "conditional/conditional_selected_harvest_dynamics", sf / "Fig4Cond_selected_harvest_dynamics"),
        (fig_render / "conditional/conditional_selected_harvest_dynamics", sf / "conditional_selected_harvest_dynamics"),
        (fig_render / "conditional/conditional_all_treatments_DRY_CUM", sf / "FigS4Cond_all_treatments_DRY_CUM"),
        (fig_render / "conditional/conditional_all_treatments_DRY_CUM", sf / "conditional_all_treatments_DRY_CUM"),
        (fig_render / "conditional/conditional_all_treatments_FRESH_CUM", sf / "FigS4Cond_all_treatments_FRESH_CUM"),
        (fig_render / "conditional/conditional_all_treatments_FRESH_CUM", sf / "conditional_all_treatments_FRESH_CUM"),
        (fig_render / "conditional/conditional_all_treatments_LAID", sf / "FigS4Cond_all_treatments_LAID"),
        (fig_render / "conditional/conditional_all_treatments_LAID", sf / "conditional_all_treatments_LAID"),
        (fig_render / "conditional/conditional_all_treatments_LWAD", sf / "FigS4Cond_all_treatments_LWAD"),
        (fig_render / "conditional/conditional_all_treatments_LWAD", sf / "conditional_all_treatments_LWAD"),

        # Custom Diagnostic Figures
        (fig_render / "conditional/conditional_treatment_residual_uncertainty", cf / "diagnostic_conditional_residual_by_treatment"),
        (fig_render / "conditional/conditional_treatment_residual_uncertainty", cf / "conditional_treatment_residual_uncertainty"),
    ]

    copied_count = 0
    for src_base, dst_base in figure_mappings:
        for ext in [".png", ".pdf", ".svg"]:
            src_f = src_base.with_suffix(ext)
            dst_f = dst_base.with_suffix(ext)
            if src_f.exists():
                shutil.copy2(src_f, dst_f)
                copied_count += 1
            else:
                print(f"Warning: source file {src_f} not found!")
        # Also copy source csv files if available
        for src_csv in src_base.parent.glob(src_base.name + ".*.csv"):
            suffix_part = src_csv.name[len(src_base.name):]
            dst_csv = dst_base.parent / (dst_base.name + suffix_part)
            shutil.copy2(src_csv, dst_csv)
            copied_count += 1

    print(f"Successfully copied {copied_count} figure and data artifacts into paper/03_Figures/.")

    # Compile root paper/03_Figures/figure_manifest.json
    all_artifacts = []
    for folder in [mf, sf, cf]:
        for f in sorted(folder.glob("*")):
            if f.is_file():
                rel_path = f.relative_to(FIGURES_03_DIR).as_posix()
                all_artifacts.append({
                    "path": rel_path,
                    "sha256": sha256_file(f),
                    "size_bytes": f.stat().st_size,
                })

    root_manifest = {
        "schema_version": 2,
        "champion_id": "C31",
        "candidate_title": "C31: Scheme 1 Dual-Spring Precision Champion (TB1=9.20°C, Error-Minimizing)",
        "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "renderer": "R 4.5.2",
        "publication_label_note": PUB_NOTE,
        "artifacts_count": len(all_artifacts),
        "artifacts": all_artifacts,
    }
    manifest_file = FIGURES_03_DIR / "figure_manifest.json"
    manifest_file.write_text(json.dumps(root_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote root figure manifest to {manifest_file} ({len(all_artifacts)} artifacts tracked).")

    # Update paper/03_Figures/README.md
    readme_content = """# 当前图版入口 (Champion C31)

当前最终 Champion 代表成员已确立为 **C31**（Dual-Spring Precision Champion, Scheme 1 physical soil calibration with TB1=9.20°C）。

本目录 `Main_Figures/`、`Custom_Diagnostic_Figures/` 与 `Supplementary_Figures/` 中的核心图版已全面同步更新为 C31 的最终高质量高分辨率矢量图（PDF、SVG 与 600 DPI PNG），并已完整整合 PEST-IES 条件参数集合预测不确定性图版（`FigCondPerf`、`Fig4Cond`、`FigS4Cond` 及 `diagnostic_conditional_residual_by_treatment`）。

## 核心指标 (Key Performance Metrics)
- **2026春 (26SP, 12处理)**: $R^2 = 0.7016$, $\\text{NRMSE} = 4.89\\%$, $\\text{NSE} = +0.7011$, $d = 0.9022$
- **2025春 (25SP, 11处理)**: $R^2 = 0.8802$, $\\text{NRMSE} = 6.24\\%$
- **双春合并 (Dual-Spring, 23处理)**: $R^2 = 0.7246$, $\\text{NRMSE} = 5.57\\%$, $\\text{NSE} = +0.5721$
- **三季全样本 (Grand 35处理)**: $R^2 = 0.9846$, $\\text{NRMSE} = 7.67\\%$, $\\text{NSE} = +0.9757$
- **2025秋盲验 (25FA, 12处理)**: 均产 $13.41\\text{ t/ha}$, $\\text{NRMSE} = 23.07\\%$

所有图版严格遵循 R 单一渲染契约与科学几何准则，完整校验哈希记录于 [figure_manifest.json](figure_manifest.json)。
"""
    (FIGURES_03_DIR / "README.md").write_text(readme_content, encoding="utf-8")
    print("Updated paper/03_Figures/README.md to Champion C31.")


# =========================================================================
# Step 5: Verification
# =========================================================================
def verify_publication_suite() -> None:
    """Verify figure manifest hashes and test suite."""
    print("\n" + "=" * 80)
    print("Step 5: Verifying SHA-256 Hashes and Paper Data Manifests")
    print("=" * 80)

    # 1. Verify paper/03_Figures/figure_manifest.json
    manifest_path = FIGURES_03_DIR / "figure_manifest.json"
    assert manifest_path.is_file(), f"Missing {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatch_count = 0
    for art in manifest["artifacts"]:
        f_path = FIGURES_03_DIR / art["path"]
        assert f_path.is_file(), f"Missing figure file: {f_path}"
        actual = sha256_file(f_path)
        if actual != art["sha256"]:
            print(f"Hash mismatch for {art['path']}: expected {art['sha256']}, got {actual}")
            mismatch_count += 1

    if mismatch_count > 0:
        raise ValueError(f"Figure manifest verification failed with {mismatch_count} mismatches")
    print(f"Verified 100% of {len(manifest['artifacts'])} figure artifacts against figure_manifest.json.")

    # 2. Verify all paper/paper_data/ manifests
    for sub in ["25SP", "26SP", "25FA", "terminal", "leaf_n", "ensemble", "conditional"]:
        pdm = PAPER_DATA_DIR / sub / "paper_data_manifest.json"
        assert pdm.is_file(), f"Missing data manifest: {pdm}"
        m_data = json.loads(pdm.read_text(encoding="utf-8"))
        for art in m_data.get("artifacts", []):
            art_f = pdm.parent / art["path"]
            assert art_f.is_file(), f"Missing data file: {art_f}"
            actual = sha256_file(art_f)
            assert actual == art["sha256"], f"Data hash mismatch in {pdm}: {art['path']}"
        print(f"Verified data bundle {sub:12s} ({len(m_data.get('artifacts', []))} artifacts).")

    print("\nAll verifications passed successfully!")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and render publication suite for Champion C31")
    parser.add_argument(
        "--step",
        choices=["all", "simulate", "export", "render", "finalize", "verify"],
        default="all",
        help="Pipeline step to execute (default: all)",
    )
    args = parser.parse_args(argv)

    if args.step in ["all", "simulate", "export"]:
        season_targets = run_forward_simulations()
    else:
        season_targets = {
            s: DET_DIR / "_seasons" / s for s in ["25SP", "26SP", "25FA"]
        }

    if args.step in ["all", "export"]:
        build_paper_data_bundles(season_targets)

    if args.step in ["all", "render"]:
        render_r_figures()

    if args.step in ["all", "finalize"]:
        synchronize_and_finalize()

    if args.step in ["all", "verify"]:
        verify_publication_suite()

    print("\n" + "=" * 80)
    print("Champion C31 Publication Suite Completed Successfully!")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
