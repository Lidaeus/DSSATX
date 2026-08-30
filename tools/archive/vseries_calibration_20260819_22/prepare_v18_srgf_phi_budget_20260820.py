"""Prepare and build the v18 calibration run with:
1. Explicit Phi-budget driven objective function weighting (50% Harvest yield : 45% Process states : 5% Soil water).
2. 10-layer refined soil profile with SRGF (Root Growth Factor) active calibration.
3. Specific Leaf Area (SLAVR/SLAREF) calibrated to realistic physiological range (160-260 cm2/g).
4. SOIL_SLPF hard-capped at 0.955.
5. XFRT active up to 0.99 with balanced terminal yield Phi budget.
6. Topdressing fertilizer depth set to 5 cm.
7. CHTD (plant height), W_RESPONSE, and N_RESPONSE zero-weighted.
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

CASE = "e02_v18_srgf_phi_budget_official_200x6_20260820"
DESIGN = ROOT / "configs/runs/eggplant_e02_v18_srgf_phi_budget_20260820.json"
BOUNDS_ID = "eggplant_e02_v18_srgf_phi_budget_20260820"
PROPOSAL_CSV = ROOT / "data/parameter_registry/bounds_proposals" / f"{BOUNDS_ID}.csv"
BOUNDS = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv"

SOURCE_CASE = "e02_v17_early_yield_n_recovery_official_200x6_20260819"
SOURCE_REALIZATION = "76"
N_REALS = 200
NOPTMAX = 6
SEED = 20260820

# Explicit Phi Budget Allocation (Per Season)
BUDGET_DRY_PROCESS = 300.0   # 30% of total Phi budget for intermediate harvest curve
BUDGET_DRY_TERMINAL = 200.0  # 20% of total Phi budget for terminal harvest point
BUDGET_LAID = 150.0          # 15% of total Phi budget for LAI
BUDGET_LWAD = 150.0          # 15% of total Phi budget for Leaf Dry Weight
BUDGET_SWAD = 150.0          # 15% of total Phi budget for Stem Dry Weight
BUDGET_SOIL_WATER = 50.0     # 5% of total Phi budget for Soil Water


def create_bounds_proposal() -> None:
    """Create updated parameter bounds proposal for v18."""
    base_bounds_path = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v17_early_yield_n_recovery_20260819.csv"
    frame = pd.read_csv(base_bounds_path, encoding="utf-8-sig")

    adjustments = {
        # Specific Leaf Area (calibrated to realistic physiological range)
        "slavr": {"init": 210.0, "lower": 160.0, "upper": 260.0, "status": "active", "pargp": "CUL_Morphology", "location": "CUL", "file": "TMGRO048.CUL.base", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Realistic specific leaf area"},
        "slaref": {"init": 230.0, "lower": 180.0, "upper": 280.0, "status": "active", "pargp": "SPE_Morphology", "location": "SPE", "file": "TMGRO048.SPE.base", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Reference specific leaf area"},
        "sizlf": {"init": 270.0, "lower": 220.0, "upper": 320.0, "status": "active", "pargp": "CUL_Morphology", "location": "CUL", "file": "TMGRO048.CUL.base", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Max single leaf size"},
        
        # Soil fertility factor hard-capped at 0.955
        "soil_slpf": {"init": 0.930, "lower": 0.880, "upper": 0.955, "status": "active", "pargp": "SOIL_Fertility", "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Soil fertility capped at 0.955"},
        
        # Assimilate fruit partitioning upper bound at 0.99
        "xfrt": {"init": 0.900, "lower": 0.650, "upper": 0.990, "status": "active", "pargp": "CUL_HarvestPartition", "location": "CUL", "file": "TMGRO048.CUL.base", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Max fruit partitioning"},
        
        # Soil Root Growth Factor (SRGF) for 10-layer profile
        "soil_srgf_04": {"init": 0.850, "lower": 0.500, "upper": 1.000, "status": "active", "pargp": "SOIL_Root", "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Root growth factor 20-30 cm"},
        "soil_srgf_05": {"init": 0.650, "lower": 0.350, "upper": 0.900, "status": "active", "pargp": "SOIL_Root", "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Root growth factor 30-40 cm"},
        "soil_srgf_06": {"init": 0.450, "lower": 0.200, "upper": 0.750, "status": "active", "pargp": "SOIL_Root", "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Root growth factor 40-50 cm"},
        "soil_srgf_07": {"init": 0.300, "lower": 0.100, "upper": 0.600, "status": "active", "pargp": "SOIL_Root", "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Root growth factor 50-60 cm"},
        "soil_srgf_08": {"init": 0.180, "lower": 0.050, "upper": 0.400, "status": "active", "pargp": "SOIL_Root", "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Root growth factor 60-80 cm"},
        "soil_srgf_09": {"init": 0.080, "lower": 0.010, "upper": 0.250, "status": "active", "pargp": "SOIL_Root", "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both", "notes": "Root growth factor 80-100 cm"},
    }

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
        "--notes", "v18 SRGF active + SLA realistic range + Phi budget balanced weights"
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)
    print(f"Frozen bounds promoted to: {BOUNDS}")


def create_design_json() -> None:
    """Create design JSON for v18."""
    design_content = {
        "schema_version": 1,
        "design_id": "e02_v18_srgf_phi_budget_20260820",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "v18 SRGF active, SLA realistic range, explicit Phi budget",
        "bounds_id": BOUNDS_ID,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Fixed corrected FileX with 5cm topdressing depth and 10-layer soil inputs",
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
            "process_lambda_per_season": BUDGET_DRY_PROCESS,
            "terminal_lambda_per_season": BUDGET_DRY_TERMINAL
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
            "phi_budget": {
                "dry_process": BUDGET_DRY_PROCESS,
                "dry_terminal": BUDGET_DRY_TERMINAL,
                "laid": BUDGET_LAID,
                "lwad": BUDGET_LWAD,
                "swad": BUDGET_SWAD,
                "soil_water": BUDGET_SOIL_WATER
            }
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


def _phi_budget_weights(
    pst: pyemu.Pst,
    registry: pd.DataFrame,
    audit: pd.DataFrame,
    *,
    run_dir: Path,
) -> dict[str, dict[str, float]]:
    """Compute exact observation weights directly from explicit target Phi budgets."""
    registry.index = registry["obsnme"].astype(str).str.lower()
    audit.index = audit["obsnme"].astype(str).str.lower()

    budget_summary: dict[str, dict[str, float]] = {}

    # 1. Harvest Dry Cumulative Process & Terminal
    dry = registry[registry["sim_token"].astype(str).isin(["CHPDTS_T", "CHPDTS"])].copy()
    for season, rows in dry.groupby("season_id", sort=True):
        # A. Process Harvest Trajectory (CHPDTS_T)
        inter = rows[rows["sim_token"] == "CHPDTS_T"]
        if len(inter) > 0:
            inter_vals = pd.to_numeric(inter["raw_obsval"], errors="raise").to_numpy(float)
            inter_sst = float(np.square(inter_vals - inter_vals.mean()).sum())
            w_inter = float(math.sqrt(BUDGET_DRY_PROCESS / inter_sst))
            sig_inter = float(math.sqrt(inter_sst / len(inter)))
            for name in inter.index:
                val = float(inter.loc[name, "raw_obsval"])
                pst.observation_data.loc[name, ["obsval", "weight", "obgnme"]] = [val, w_inter, "dry_proc_nse"]
                for table in (registry, audit):
                    table.loc[name, ["obsval", "weight", "sigma", "sigma_source", "transform", "obgnme"]] = [
                        val, w_inter, sig_inter, "phi_budget_sst", "raw", "DRY_PROC_NSE"
                    ]
                    table.loc[name, "group_multiplier"] = w_inter * sig_inter
            budget_summary[f"{season}_dry_proc"] = {"n": len(inter), "sst": inter_sst, "budget": BUDGET_DRY_PROCESS, "weight": w_inter}

        # B. Terminal Harvest Point (CHPDTS)
        term = rows[rows["sim_token"] == "CHPDTS"]
        if len(term) > 0:
            term_vals = pd.to_numeric(term["raw_obsval"], errors="raise").to_numpy(float)
            term_sst = float(np.square(term_vals - term_vals.mean()).sum())
            w_term = float(math.sqrt(BUDGET_DRY_TERMINAL / term_sst))
            sig_term = float(math.sqrt(term_sst / len(term)))
            for name in term.index:
                val = float(term.loc[name, "raw_obsval"])
                pst.observation_data.loc[name, ["obsval", "weight", "obgnme"]] = [val, w_term, "dry_term_nse"]
                for table in (registry, audit):
                    table.loc[name, ["obsval", "weight", "sigma", "sigma_source", "transform", "obgnme"]] = [
                        val, w_term, sig_term, "phi_budget_sst", "raw", "DRY_TERM_NSE"
                    ]
                    table.loc[name, "group_multiplier"] = w_term * sig_term
            budget_summary[f"{season}_dry_term"] = {"n": len(term), "sst": term_sst, "budget": BUDGET_DRY_TERMINAL, "weight": w_term}

    # 2. Process State Variables (LAID, LWAD, SWAD)
    process_specs = [
        ("LAID", BUDGET_LAID, ["LAIDS_T", "LAIDS", "LAIDM_T", "LAIDM"]),
        ("LWAD", BUDGET_LWAD, ["LWADS_T", "LWADS", "LWADM_T", "LWADM"]),
        ("SWAD", BUDGET_SWAD, ["SWADS_T", "SWADS", "SWADM_T", "SWADM"]),
    ]
    for var, budget, tokens in process_specs:
        var_rows = registry[registry["sim_token"].astype(str).isin(tokens)].copy()
        for season, rows in var_rows.groupby("season_id", sort=True):
            vals = pd.to_numeric(rows["raw_obsval"], errors="raise").to_numpy(float)
            sst = float(np.square(vals - vals.mean()).sum())
            if sst > 0:
                weight = float(math.sqrt(budget / sst))
                sigma = float(math.sqrt(sst / len(rows)))
                for name in rows.index:
                    val = float(rows.loc[name, "raw_obsval"])
                    pst.observation_data.loc[name, ["obsval", "weight", "obgnme"]] = [val, weight, f"proc_{var.lower()}"]
                    for table in (registry, audit):
                        table.loc[name, ["obsval", "weight", "sigma", "sigma_source", "transform", "obgnme"]] = [
                            val, weight, sigma, "phi_budget_sst", "raw", f"PROC_{var}"
                        ]
                        table.loc[name, "group_multiplier"] = weight * sigma
                budget_summary[f"{season}_{var.lower()}"] = {"n": len(rows), "sst": sst, "budget": budget, "weight": weight}

    # 3. Zero out CHTD, WRESP, and NRESP observation weights
    zero_obs = pst.observation_data[
        pst.observation_data["obgnme"].astype(str).str.upper().str.contains("CHTD") |
        pst.observation_data["obgnme"].astype(str).str.upper().str.contains("WRESP") |
        pst.observation_data["obgnme"].astype(str).str.upper().str.contains("NRESP")
    ].index
    pst.observation_data.loc[zero_obs, "weight"] = 0.0

    return budget_summary


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

    print(f"[3/6] Applying explicit Phi Budget weights & zeroing out exclusions...")
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    budget_summary = _phi_budget_weights(pst, registry, audit, run_dir=run_dir)
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
        "budget_summary": budget_summary
    }
    (run_dir / "v18_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(contract, ensure_ascii=False, indent=2))
    print(f"\nTask built successfully in: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
