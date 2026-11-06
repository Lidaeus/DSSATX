"""Prepare and build the v16 senescence + harvest sequence rebalance calibration run.

This run addresses:
1. Senescence & Fruit Fill (SFDUR, PODUR, SENRTE, SENDAY, XFRT) to promote late 26SP canopy senescence (target LAI ~2.5-3.0)
   and release maintenance respiration assimilates for fruit harvest sink.
2. Harvest sequence rebalancing: disable artificial water/nitrogen response objective weights,
   increase harvest sequence / cumulative dry weight lambda to match process states.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.build_pest import _write_observation_noise_ensemble
from src.calibration.initial_ensemble import generate_lhs_ensemble, write_ensemble_csv

CASE = "e02_v16_senescence_harvest_fix_official_200x6_20260819"
DESIGN = ROOT / "configs/runs/eggplant_e02_v16_senescence_harvest_fix_20260819.json"
BOUNDS_ID = "eggplant_e02_v16_senescence_harvest_fix_20260819"
PROPOSAL_CSV = ROOT / "data/parameter_registry/bounds_proposals" / f"{BOUNDS_ID}.csv"
BOUNDS = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv"

SOURCE_CASE = "e02_selected8_water_formal_measuredmoisture_official_200x6_20260819"
SOURCE_REALIZATION = "42"
N_REALS = 200
NOPTMAX = 6
SEED = 20260819

DRY_LAMBDA = 150.0  # Doubled dry harvest sequence weight lambda
WATER_LAMBDA_PER_SEASON = 0.0  # Disabled water response weight penalty in PST


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_bounds_proposal() -> None:
    """Create updated parameter bounds proposal promoting senescence and fruit filling."""
    base_bounds_path = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_selected8_water_formal_measuredmoisture_20260819.csv"
    frame = pd.read_csv(base_bounds_path, encoding="utf-8-sig")

    # Parameter adjustments for senescence and harvest fruit sink expansion
    adjustments = {
        "sfdur": {"init": 22.0, "lower": 10.0, "upper": 35.0, "notes": "Relaxed upper to 35 for fruit filling duration"},
        "podur": {"init": 30.0, "lower": 15.0, "upper": 65.0, "notes": "Relaxed upper to 65 for pod duration"},
        "senrte": {"init": 0.8, "lower": 0.3, "upper": 4.0, "notes": "Relaxed upper to 4.0 to promote late LAI senescence"},
        "senday": {"init": 0.03, "lower": 0.001, "upper": 0.10, "notes": "Relaxed upper to 0.10 for canopy age senescence"},
        "xfrt": {"init": 0.90, "lower": 0.60, "upper": 0.99, "notes": "Adjusted lower to 0.60 for fruit partitioning"},
        "xmage": {"init": 20.0, "lower": 12.0, "upper": 40.0, "notes": "Relaxed upper to 40 for multi-harvest fruit age"},
    }

    for idx, row in frame.iterrows():
        pname = str(row["name"]).lower()
        if pname in adjustments:
            adj = adjustments[pname]
            frame.at[idx, "init"] = adj["init"]
            frame.at[idx, "lower"] = adj["lower"]
            frame.at[idx, "upper"] = adj["upper"]
            frame.at[idx, "notes"] = adj["notes"]

    PROPOSAL_CSV.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(PROPOSAL_CSV, index=False, encoding="utf-8-sig")
    print(f"Created bounds proposal: {PROPOSAL_CSV}")

    # Freeze bounds using freeze_bounds script logic
    if BOUNDS.exists():
        os.remove(BOUNDS)
    meta_path = BOUNDS.parent / f"{BOUNDS_ID}.yaml"
    if meta_path.exists():
        os.remove(meta_path)

    cmd = [
        sys.executable,
        str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(PROPOSAL_CSV),
        "--crop", "eggplant",
        "--bounds-id", BOUNDS_ID,
        "--notes", "v16 senescence + harvest sequence rebalance bounds"
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)
    print(f"Frozen bounds promoted to: {BOUNDS}")


def create_design_json() -> None:
    """Create design JSON with rebalanced objective weights."""
    design_content = {
        "schema_version": 1,
        "design_id": "e02_v16_senescence_harvest_fix_20260819",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "v16 senescence and harvest sequence rebalance calibration",
        "bounds_id": BOUNDS_ID,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Fixed corrected FileX and soil inputs; not inverted",
        "nitrogen_response_objective": {
            "enabled": False,
            "mapping_csv": "configs/runs/e02_selected8_water_n_mapping_20260818.csv",
            "source_variable": "CHPDT",
            "contrast": "N3_minus_N0_within_same_water",
            "contrast_scale": "raw_difference",
            "response_target": "observed_shape",
            "levels": ["N3"],
            "harvest_scope": "all",
            "sigma_floor": 50.0,
            "weighting": "static"
        },
        "water_response_objective": {
            "enabled": False,
            "mapping_csv": "configs/runs/e02_selected8_water_n_mapping_20260818.csv",
            "source_variable": "CHPDT",
            "contrast": "season_specific_high_minus_W1_within_same_nitrogen",
            "contrast_scale": "raw_difference",
            "response_target": "observed_shape",
            "levels": ["N3"],
            "nitrogen_levels": ["N0", "N3"],
            "season_contrasts": {
                "25SP": {"high_water": "W3", "low_water": "W1"},
                "26SP": {"high_water": "W2", "low_water": "W1"}
            },
            "harvest_scope": "all",
            "sigma_floor": 50.0,
            "weighting": "nse",
            "nse_lambda": 0.0,
            "nse_lambda_allocation": "equal_split_N0_N3_separate_SST"
        },
        "harvest_dry_objective": {
            "enabled": True,
            "mode": "increment_plus_terminal",
            "variable": "CHPDT",
            "lambda_per_season": DRY_LAMBDA
        },
        "process_state_objective": {
            "enabled": True,
            "mode": "signed_difference_plus_terminal",
            "variables": ["LAID", "LWAD", "SWAD"]
        },
        "seasonal_parameterization": None,
        "seasons": [
            {
                "season_id": "25SP",
                "experiment_code": "XXQL2501",
                "bundle_path": str(ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v2_20260819"),
                "role": "calibration",
                "treatments": [2, 5, 10, 13]
            },
            {
                "season_id": "26SP",
                "experiment_code": "XXQL2601",
                "bundle_path": str(ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v2_20260819"),
                "role": "calibration",
                "treatments": [2, 11, 3, 12]
            }
        ],
        "formal_contract": {
            "source_case": SOURCE_CASE,
            "source_realization": SOURCE_REALIZATION,
            "n_reals": N_REALS,
            "noptmax": NOPTMAX,
            "agents": 6,
            "dry_nse_lambda_per_season": DRY_LAMBDA,
            "water_nse_lambda_per_season": WATER_LAMBDA_PER_SEASON
        }
    }
    DESIGN.parent.mkdir(parents=True, exist_ok=True)
    DESIGN.write_text(json.dumps(design_content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Created design JSON: {DESIGN}")


def _source_anchor() -> dict[str, float]:
    source = ROOT / "workspace/runs" / SOURCE_CASE / f"{SOURCE_CASE}.6.par.csv"
    frame = pd.read_csv(source)
    real_col = frame.columns[0]
    row = frame.loc[
        frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(SOURCE_REALIZATION)
    ]
    if len(row) != 1:
        raise ValueError(f"expected source realization {SOURCE_REALIZATION} exactly once in {source}")
    return {
        str(key).lower(): float(value)
        for key, value in row.iloc[0].items()
        if key != real_col and pd.notna(value)
    }


def _nse_weights(
    pst: pyemu.Pst,
    registry: pd.DataFrame,
    audit: pd.DataFrame,
    *,
    run_dir: Path,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    registry.index = registry["obsnme"].astype(str).str.lower()
    audit.index = audit["obsnme"].astype(str).str.lower()

    dry_summary: dict[str, dict[str, float]] = {}
    dry = registry[registry["sim_token"].astype(str).isin(["CHPDTS_T", "CHPDTS"])].copy()
    for season, rows in dry.groupby("season_id", sort=True):
        values = pd.to_numeric(rows["raw_obsval"], errors="raise").to_numpy(float)
        sst = float(np.square(values - values.mean()).sum())
        if sst <= 0:
            raise ValueError(f"{season}: dry cumulative SST must be positive")
        weight = float(math.sqrt(DRY_LAMBDA / sst))
        sigma = float(math.sqrt(sst / len(rows)))
        for name, row in rows.iterrows():
            value = float(row["raw_obsval"])
            pst.observation_data.loc[name, ["obsval", "weight", "obgnme"]] = [value, weight, "drynse"]
            for table in (registry, audit):
                table.loc[name, ["obsval", "weight", "sigma", "sigma_source", "transform", "obgnme"]] = [
                    value, weight, sigma, "nse_sst_normalized_raw", "raw", "DRYNSE"
                ]
                table.loc[name, "group_multiplier"] = weight * sigma
        dry_summary[str(season)] = {
            "n": int(len(rows)), "sst": sst, "lambda": DRY_LAMBDA, "weight": weight,
        }

    # Zero out water response observation weights in PST to eliminate penalty interference
    water_obs = pst.observation_data[pst.observation_data["obgnme"].astype(str).str.upper().str.contains("WRESP")].index
    pst.observation_data.loc[water_obs, "weight"] = 0.0

    # Zero out CHTD (plant height) observation weights in PST as requested ("株高不应进入参数率定")
    chtd_obs = pst.observation_data[pst.observation_data["obgnme"].astype(str).str.upper().str.contains("CHTD")].index
    pst.observation_data.loc[chtd_obs, "weight"] = 0.0

    return dry_summary, {}


def main() -> int:
    create_bounds_proposal()
    create_design_json()

    run_dir = ROOT / "workspace/runs" / CASE
    if run_dir.exists():
        import shutil
        shutil.rmtree(run_dir)

    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    print(f"[1/6] Running base PST build...")
    subprocess.run(
        [
            sys.executable, str(ROOT / "tools/calibration/build_fixed_soil_joint_v3_20260813.py"),
            "--variant", "official", "--case", CASE, "--design", str(DESIGN),
            "--bounds-id", BOUNDS_ID, "--noptmax", str(NOPTMAX),
            "--ies-num-reals", str(N_REALS), "--random-seed", str(SEED),
        ],
        cwd=ROOT, env=env, check=True,
    )

    print(f"[2/6] Updating parameter initial values and bounds from frozen bounds...")
    pst_path = run_dir / f"{CASE}.pst"
    audit_path = run_dir / f"{CASE}.weights.audit.csv"
    registry_path = run_dir / f"{CASE}_observation_registry.csv"
    pst = pyemu.Pst(str(pst_path))
    frozen = pd.read_csv(BOUNDS, encoding="utf-8-sig")
    frozen["name"] = frozen["name"].astype(str).str.lower()
    frozen = frozen.set_index("name")
    for name in pst.parameter_data.index:
        if name in frozen.index:
            status = str(frozen.at[name, "status"]).lower()
            if status == "fixed":
                pst.parameter_data.at[name, "partrans"] = "fixed"
                pst.parameter_data.at[name, "parval1"] = float(frozen.at[name, "init"])
                pst.parameter_data.at[name, "parlbnd"] = float(frozen.at[name, "lower"])
                pst.parameter_data.at[name, "parubnd"] = float(frozen.at[name, "upper"])
            else:
                value = float(frozen.at[name, "init"])
                lower = float(frozen.at[name, "lower"])
                upper = float(frozen.at[name, "upper"])
                pst.parameter_data.at[name, "parlbnd"] = lower
                pst.parameter_data.at[name, "parubnd"] = upper
                pst.parameter_data.at[name, "parval1"] = min(max(value, lower), upper)

    print(f"[3/6] Applying NSE weights and zeroing out water response penalty...")
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    dry_summary, _ = _nse_weights(pst, registry, audit, run_dir=run_dir)
    pst.control_data.noptmax = NOPTMAX
    pst.pestpp_options.update({
        "ies_num_reals": N_REALS,
        "rand_seed": SEED,
        "ies_parameter_ensemble": f"{CASE}.0.par.csv",
        "ies_observation_ensemble": f"{CASE}.observation_ensemble.csv",
        "ies_include_base": "false",
    })
    pst.write(str(pst_path))
    registry.reset_index(drop=True).to_csv(registry_path, index=False, encoding="utf-8-sig")
    audit.reset_index(drop=True).to_csv(audit_path, index=False, encoding="utf-8-sig")

    params_path = run_dir / f"{CASE}_params.csv"
    params = pd.read_csv(params_path)
    lookup = pst.parameter_data["parval1"].to_dict()
    params["value"] = params.apply(
        lambda row: lookup.get(str(row["name"]).lower(), row["value"]), axis=1
    )
    params.to_csv(params_path, index=False)

    print(f"[4/6] Generating initial parameter ensemble with Sobol sampling + anchor member...")
    par = pst.parameter_data
    ensemble_bounds = pd.DataFrame({
        "name": par.index,
        "init": par.parval1,
        "lower": par.parlbnd,
        "upper": par.parubnd,
        "status": np.where(par.partrans.astype(str).str.lower().eq("fixed"), "fixed", "active"),
    })
    ensemble = generate_lhs_ensemble(N_REALS, ensemble_bounds, SEED, method="sobol")
    anchor = _source_anchor()
    real_col = ensemble.columns[0]
    first = ensemble.index[0]
    for name in ensemble.columns[1:]:
        key = str(name).lower()
        if key in anchor:
            lower = float(par.at[key, "parlbnd"])
            upper = float(par.at[key, "parubnd"])
            ensemble.at[first, name] = min(max(anchor[key], lower), upper)
    ensemble.at[first, real_col] = f"anchor_member{SOURCE_REALIZATION}"
    ensemble_path = run_dir / f"{CASE}.0.par.csv"
    write_ensemble_csv(ensemble, ensemble_path)

    print(f"[5/6] Generating observation noise ensemble...")
    observation_path, _, _ = _write_observation_noise_ensemble(
        pst_path, audit_path, run_dir, CASE, N_REALS, SEED
    )

    print(f"[6/6] Finalizing run manifest and contract...")
    contract = {
        "schema_version": 1,
        "case": CASE,
        "source_case": SOURCE_CASE,
        "source_realization": SOURCE_REALIZATION,
        "official_dssat_required": True,
        "n_reals": N_REALS,
        "noptmax": NOPTMAX,
        "agents": 6,
        "n_adjustable": int(pst.npar_adj),
        "dry_lambda": DRY_LAMBDA,
        "water_lambda": WATER_LAMBDA_PER_SEASON,
    }
    (run_dir / "v16_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(contract, ensure_ascii=False, indent=2))
    print(f"\nTask built successfully in: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
