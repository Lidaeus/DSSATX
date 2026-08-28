"""Prepare and build the v17 early yield + N remobilization and SLOC recovery calibration run.

Features in v17:
1. Soil Organic Carbon (SLOC):
   - Updated from latest measured SOM (0-20 cm: 1.59% -> 0.922%, 20-40 cm: 1.20% -> 0.696%, 40-60 cm: 0.54% -> 0.313%)
   - Active in calibration with physically consistent bounds
2. Nitrogen Remobilization & Uptake:
   - Active: RTNO3, RTNH4, NMOBMX, NVSMOB, NSTFAC, NRCVR, NREXP, NRMIN, SOIL_SLPF
3. Early Yield & Harvest Trajectory NSE:
   - Split CHPDTS_T (intermediate harvest trajectory, lambda=300.0) and CHPDTS (terminal harvest, lambda=150.0)
   - Pre-fruit timing adjusted: XFINT (0.12-0.35), FL-SD (6.0-16.0), FL-SH (1.0-3.5)
4. Out-of-objective exclusions:
   - CHTD (plant height), W_RESPONSE, N_RESPONSE weights set to 0.0
"""
from __future__ import annotations

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

CASE = "e02_v17_early_yield_n_recovery_official_200x6_20260819"
DESIGN = ROOT / "configs/runs/eggplant_e02_v17_early_yield_n_recovery_20260819.json"
BOUNDS_ID = "eggplant_e02_v17_early_yield_n_recovery_20260819"
PROPOSAL_CSV = ROOT / "data/parameter_registry/bounds_proposals" / f"{BOUNDS_ID}.csv"
BOUNDS = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv"

SOURCE_CASE = "e02_v16_senescence_harvest_fix_official_200x6_20260819"
SOURCE_REALIZATION = "26"
N_REALS = 200
NOPTMAX = 6
SEED = 20260819

PROCESS_HARVEST_LAMBDA = 300.0  # High budget for intermediate harvest trajectory points
TERMINAL_HARVEST_LAMBDA = 150.0  # Budget for terminal harvest point


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_bounds_proposal() -> None:
    """Create updated parameter bounds proposal with SLOC, N remobilization, and early yield timing."""
    base_bounds_path = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v16_senescence_harvest_fix_20260819.csv"
    frame = pd.read_csv(base_bounds_path, encoding="utf-8-sig")

    # Add/Update soil_sloc and nitrogen remobilization parameters
    adjustments = {
        # Soil organic carbon (from measured SOM)
        "soil_sloc_01": {"init": 0.922, "lower": 0.750, "upper": 1.300, "status": "active", "pargp": "SOIL_Chemical", "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Measured SOM 1.59% -> SOC 0.922%"},
        "soil_sloc_02": {"init": 0.696, "lower": 0.500, "upper": 1.000, "status": "active", "pargp": "SOIL_Chemical", "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Measured SOM 1.20% -> SOC 0.696%"},
        "soil_sloc_03": {"init": 0.313, "lower": 0.200, "upper": 0.600, "status": "active", "pargp": "SOIL_Chemical", "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Measured SOM 0.54% -> SOC 0.313%"},
        "soil_slpf": {"init": 0.930, "lower": 0.880, "upper": 1.000, "status": "active", "pargp": "SOIL_Fertility", "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Soil fertility factor active"},
        
        # Root nitrogen uptake
        "rtno3": {"init": 0.045, "lower": 0.010, "upper": 0.050, "status": "active", "pargp": "SPE_RootNitrogen", "location": "SPE", "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Root NO3 uptake active"},
        "rtnh4": {"init": 0.045, "lower": 0.010, "upper": 0.050, "status": "active", "pargp": "SPE_RootNitrogen", "location": "SPE", "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Root NH4 uptake active"},
        
        # Plant nitrogen remobilization & stress
        "nmobmx": {"init": 0.250, "lower": 0.050, "upper": 0.400, "status": "active", "pargp": "SPE_Other", "location": "SPE", "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Max N mob fraction active"},
        "nvsmob": {"init": 0.500, "lower": 0.150, "upper": 0.600, "status": "active", "pargp": "SPE_Other", "location": "SPE", "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Vegetative N mob rate active"},
        "nstfac": {"init": 0.800, "lower": 0.500, "upper": 1.000, "status": "active", "pargp": "SPE_Other", "location": "SPE", "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "N stress factor active"},
        "nrcvr": {"init": 0.250, "lower": 0.050, "upper": 0.350, "status": "active", "pargp": "SPE_Other", "location": "SPE", "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Root N recovery active"},
        
        # Early fruit timing & allocation
        "xfint": {"init": 0.150, "lower": 0.120, "upper": 0.350, "status": "active", "pargp": "ECO_Phenology", "location": "ECO", "file": "TMGRO048.ECO", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Earlier fruit allocation start"},
        "fl-sd": {"init": 10.000, "lower": 6.000, "upper": 16.000, "status": "active", "pargp": "CUL_PhenologyHarvest", "location": "CUL", "file": "TMGRO048.CUL.base", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Flower to first seed duration"},
        "fl-sh": {"init": 1.500, "lower": 1.000, "upper": 3.500, "status": "active", "pargp": "CUL_PhenologyHarvest", "location": "CUL", "file": "TMGRO048.CUL.base", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Flower to first pod duration"},
        "xfrt": {"init": 0.900, "lower": 0.600, "upper": 0.990, "status": "active", "pargp": "CUL_HarvestPartition", "location": "CUL", "file": "TMGRO048.CUL.base", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Max fruit partitioning"},
        "xmage": {"init": 20.000, "lower": 12.000, "upper": 40.000, "status": "active", "pargp": "ECO_Phenology", "location": "ECO", "file": "TMGRO048.ECO", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Multi-harvest fruit age"},
        "sfdur": {"init": 22.000, "lower": 10.000, "upper": 35.000, "status": "active", "pargp": "CUL_PhenologyHarvest", "location": "CUL", "file": "TMGRO048.CUL.base", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Seed fill duration"},
        "podur": {"init": 30.000, "lower": 15.000, "upper": 65.000, "status": "active", "pargp": "CUL_PhenologyHarvest", "location": "CUL", "file": "TMGRO048.CUL.base", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Pod duration"},
        "senrte": {"init": 0.800, "lower": 0.300, "upper": 4.000, "status": "active", "pargp": "SPE_Senescence", "location": "SPE", "file": "TMGRO048.SPE.base", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Senescence rate"},
        "senday": {"init": 0.030, "lower": 0.001, "upper": 0.100, "status": "active", "pargp": "SPE_Senescence", "location": "SPE", "file": "TMGRO048.SPE.base", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Senescence day fraction"},
    }

    # Apply adjustments or insert new rows
    existing_names = set(frame["name"].str.lower())
    for pname, adj in adjustments.items():
        if pname in existing_names:
            idx = frame[frame["name"].str.lower() == pname].index[0]
            for k, v in adj.items():
                if k in frame.columns:
                    frame.at[idx, k] = v
        else:
            new_row = {col: "" for col in frame.columns}
            new_row["name"] = pname
            new_row.update(adj)
            frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    PROPOSAL_CSV.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(PROPOSAL_CSV, index=False, encoding="utf-8-sig")
    print(f"Created bounds proposal: {PROPOSAL_CSV}")

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
        "--notes", "v17 early yield + N remobilization and SLOC recovery bounds"
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)
    print(f"Frozen bounds promoted to: {BOUNDS}")


def create_design_json() -> None:
    """Create design JSON for v17."""
    design_content = {
        "schema_version": 1,
        "design_id": "e02_v17_early_yield_n_recovery_20260819",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "v17 early yield and N remobilization calibration",
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
            "process_lambda_per_season": PROCESS_HARVEST_LAMBDA,
            "terminal_lambda_per_season": TERMINAL_HARVEST_LAMBDA
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
            "process_harvest_lambda": PROCESS_HARVEST_LAMBDA,
            "terminal_harvest_lambda": TERMINAL_HARVEST_LAMBDA
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
        # 1. Process intermediate harvests (CHPDTS_T)
        inter = rows[rows["sim_token"] == "CHPDTS_T"]
        if len(inter) > 0:
            inter_vals = pd.to_numeric(inter["raw_obsval"], errors="raise").to_numpy(float)
            inter_sst = float(np.square(inter_vals - inter_vals.mean()).sum())
            if inter_sst <= 0:
                raise ValueError(f"{season}: intermediate harvest SST must be positive")
            w_inter = float(math.sqrt(PROCESS_HARVEST_LAMBDA / inter_sst))
            sig_inter = float(math.sqrt(inter_sst / len(inter)))
            for name in inter.index:
                val = float(inter.loc[name, "raw_obsval"])
                pst.observation_data.loc[name, ["obsval", "weight", "obgnme"]] = [val, w_inter, "dry_proc_nse"]
                for table in (registry, audit):
                    table.loc[name, ["obsval", "weight", "sigma", "sigma_source", "transform", "obgnme"]] = [
                        val, w_inter, sig_inter, "nse_sst_normalized_raw", "raw", "DRY_PROC_NSE"
                    ]
                    table.loc[name, "group_multiplier"] = w_inter * sig_inter
            dry_summary[f"{season}_process"] = {
                "n": int(len(inter)), "sst": inter_sst, "lambda": PROCESS_HARVEST_LAMBDA, "weight": w_inter,
            }

        # 2. Terminal harvest (CHPDTS)
        term = rows[rows["sim_token"] == "CHPDTS"]
        if len(term) > 0:
            term_vals = pd.to_numeric(term["raw_obsval"], errors="raise").to_numpy(float)
            term_sst = float(np.square(term_vals - term_vals.mean()).sum())
            if term_sst <= 0:
                raise ValueError(f"{season}: terminal harvest SST must be positive")
            w_term = float(math.sqrt(TERMINAL_HARVEST_LAMBDA / term_sst))
            sig_term = float(math.sqrt(term_sst / len(term)))
            for name in term.index:
                val = float(term.loc[name, "raw_obsval"])
                pst.observation_data.loc[name, ["obsval", "weight", "obgnme"]] = [val, w_term, "dry_term_nse"]
                for table in (registry, audit):
                    table.loc[name, ["obsval", "weight", "sigma", "sigma_source", "transform", "obgnme"]] = [
                        val, w_term, sig_term, "nse_sst_normalized_raw", "raw", "DRY_TERM_NSE"
                    ]
                    table.loc[name, "group_multiplier"] = w_term * sig_term
            dry_summary[f"{season}_terminal"] = {
                "n": int(len(term)), "sst": term_sst, "lambda": TERMINAL_HARVEST_LAMBDA, "weight": w_term,
            }

    # Zero out water and nitrogen response observation weights in PST to eliminate penalty interference
    resp_obs = pst.observation_data[
        pst.observation_data["obgnme"].astype(str).str.upper().str.contains("WRESP") |
        pst.observation_data["obgnme"].astype(str).str.upper().str.contains("NRESP")
    ].index
    pst.observation_data.loc[resp_obs, "weight"] = 0.0

    # Zero out CHTD (plant height) observation weights in PST as requested ("株高不应进入参数率定")
    chtd_obs = pst.observation_data[
        pst.observation_data["obgnme"].astype(str).str.upper().str.contains("CHTD")
    ].index
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
                pst.parameter_data.at[name, "partrans"] = "none"
                pst.parameter_data.at[name, "parlbnd"] = lower
                pst.parameter_data.at[name, "parubnd"] = upper
                pst.parameter_data.at[name, "parval1"] = min(max(value, lower), upper)

    print(f"[3/6] Applying split Process vs Terminal Harvest NSE weights & zeroing out CHTD/response penalties...")
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
        "process_harvest_lambda": PROCESS_HARVEST_LAMBDA,
        "terminal_harvest_lambda": TERMINAL_HARVEST_LAMBDA,
        "dry_summary": dry_summary
    }
    (run_dir / "v17_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(contract, ensure_ascii=False, indent=2))
    print(f"\nTask built successfully in: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
