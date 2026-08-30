"""Build formal calibration task for v19:
Incorporates exploratory findings:
1. Active greenhouse soil nitrogen mineralization factor SOIL_SLNF (1.10 - 1.60, init 1.30).
2. Mild crop N mobilization & stress tolerance bounds (NMOBMX: 0.08-0.25, NSTFAC: 0.30-0.65, LNREF: 3.0-4.2%).
3. Enhanced low-concentration root N uptake (RTNO3/RTNH4: 0.010-0.050).
4. Explicit Phi Budgeting: Harvest Dry 50% (Process 200 + Terminal 300) : Process States 45% (LAID 150 + LWAD 150 + SWAD 150) : Soil Water 5% (50).
5. 10-layer refined soil profile with active SRGF (layers 04..09), 5cm topdressing depth, SLPF capped at 0.955, SLAVR in [160, 260].
6. Scale: 200 realizations x 6 iterations, 6 parallel agents.
"""
from __future__ import annotations

import json
import math
import os
import shutil
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

CASE = "e02_v19_nitrogen_solution_official_200x6_20260820"
BOUNDS_ID = "eggplant_e02_v19_nitrogen_solution_20260820"
NOPTMAX = 6
N_REALS = 200
SEED = 20260820

SOURCE_CASE = "e02_arm_b_soil_n_supply_50x3_20260820"
SOURCE_REALIZATION = "31"

BASE_FROZEN_PATH = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v18_srgf_phi_budget_20260820.csv"


def _source_anchor() -> dict[str, float]:
    source = ROOT / "workspace/runs" / SOURCE_CASE / f"{SOURCE_CASE}.3.par.csv"
    if not source.exists():
        return {}
    frame = pd.read_csv(source)
    real_col = frame.columns[0]
    row = frame.loc[
        frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(SOURCE_REALIZATION)
    ]
    if len(row) != 1:
        return {}
    return {
        str(key).lower(): float(value)
        for key, value in row.iloc[0].items()
        if key != real_col and pd.notna(value)
    }


def prepare_bounds_and_design(run_dir: Path) -> tuple[Path, Path]:
    proposal_csv = ROOT / "data/parameter_registry/bounds_proposals" / f"{BOUNDS_ID}.csv"
    frozen_csv = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv"
    design_path = ROOT / "configs/runs" / f"{CASE}.json"

    frame = pd.read_csv(BASE_FROZEN_PATH, encoding="utf-8-sig")
    existing_names = set(frame["name"].str.lower())

    adjustments = {
        # Soil nitrogen mineralization in greenhouse microenvironment
        "soil_slnf": {
            "init": 1.300, "lower": 1.100, "upper": 1.600, "status": "active",
            "pargp": "SOIL_Chemical", "location": "SOIL", "file": "SOIL.SOL",
            "cultivar": "TM0008", "ecotype": "TM0001", "mode": "both"
        },
        # Root uptake in low N concentrations
        "rtno3": {"init": 0.045, "lower": 0.010, "upper": 0.050, "status": "active"},
        "rtnh4": {"init": 0.045, "lower": 0.010, "upper": 0.050, "status": "active"},
        # Crop N mobilization & senescence tolerance
        "nmobmx": {"init": 0.150, "lower": 0.080, "upper": 0.250, "status": "active"},
        "nvsmob": {"init": 0.350, "lower": 0.200, "upper": 0.450, "status": "active"},
        "nstfac": {"init": 0.450, "lower": 0.300, "upper": 0.650, "status": "active"},
        "lnref": {"init": 3.600, "lower": 3.000, "upper": 4.200, "status": "active"},
        "nslope": {"init": 0.180, "lower": 0.100, "upper": 0.250, "status": "active"},
        # Soil SLPF strict cap at 0.955
        "soil_slpf": {"init": 0.930, "lower": 0.880, "upper": 0.955, "status": "active"},
        # Specific leaf area for accurate LAI
        "slavr": {"init": 210.000, "lower": 160.000, "upper": 260.000, "status": "active"},
        "slaref": {"init": 230.000, "lower": 180.000, "upper": 280.000, "status": "active"},
        # Fruit allocation parameter
        "xfrt": {"init": 0.900, "lower": 0.650, "upper": 0.990, "status": "active"},
    }

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

    proposal_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(proposal_csv, index=False, encoding="utf-8-sig")

    if frozen_csv.exists():
        os.remove(frozen_csv)
    meta_path = frozen_csv.parent / f"{BOUNDS_ID}.yaml"
    if meta_path.exists():
        os.remove(meta_path)

    cmd = [
        sys.executable, str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(proposal_csv), "--crop", "eggplant",
        "--bounds-id", BOUNDS_ID,
        "--notes", "v19 formal: Active greenhouse SOIL_SLNF + mild crop N bounds + Phi budget (200 proc + 300 term)"
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)

    design_content = {
        "schema_version": 1,
        "design_id": CASE,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "v19 formal nitrogen solution + 10-layer soil + Phi budget (200 proc + 300 term)",
        "bounds_id": BOUNDS_ID,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Fixed corrected FileX with 5cm topdressing depth and 10-layer soil inputs",
        "nitrogen_response_objective": {"enabled": False},
        "water_response_objective": {"enabled": False},
        "harvest_dry_objective": {
            "enabled": True, "mode": "increment_plus_terminal",
            "variable": "CHPDT", "process_lambda_per_season": 200.0, "terminal_lambda_per_season": 300.0
        },
        "process_state_objective": {
            "enabled": True, "mode": "signed_difference_plus_terminal", "variables": ["LAID", "LWAD", "SWAD"]
        },
        "seasonal_parameterization": None,
        "seasons": [
            {
                "season_id": "25SP", "experiment_code": "XXQL2501",
                "bundle_path": str(ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v3_measuredn_20260820"),
                "role": "calibration", "treatments": [2, 5, 10, 13]
            },
            {
                "season_id": "26SP", "experiment_code": "XXQL2601",
                "bundle_path": str(ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v3_measuredn_20260820"),
                "role": "calibration", "treatments": [2, 11, 3, 12]
            }
        ],
        "formal_contract": {
            "phi_budget": {
                "dry_proc": 200.0, "dry_term": 300.0, "laid": 150.0, "lwad": 150.0, "swad": 150.0, "soil_water": 50.0
            },
            "n_reals": N_REALS, "noptmax": NOPTMAX
        }
    }
    design_path.parent.mkdir(parents=True, exist_ok=True)
    design_path.write_text(json.dumps(design_content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return frozen_csv, design_path


def apply_phi_budget_weights(pst: pyemu.Pst, registry: pd.DataFrame, audit: pd.DataFrame, run_dir: Path) -> dict:
    """Applies exact Phi budget weights with User-Specified Budget:
    - DRY_PROCESS: 200 per season
    - DRY_TERMINAL: 300 per season
    - LAID: 150 per season
    - LWAD: 150 per season
    - SWAD: 150 per season
    """
    registry.index = registry["obsnme"].astype(str).str.lower()
    audit.index = audit["obsnme"].astype(str).str.lower()

    budget_summary = {}

    # 1. Harvest Dry (CHPDTS_T: 200, CHPDTS: 300)
    dry = registry[registry["sim_token"].astype(str).isin(["CHPDTS_T", "CHPDTS"])].copy()
    for season, rows in dry.groupby("season_id", sort=True):
        # Process (CHPDTS_T) -> Budget = 200.0
        sub_proc = rows[rows["sim_token"] == "CHPDTS_T"]
        if len(sub_proc) > 0:
            vals = pd.to_numeric(sub_proc["raw_obsval"], errors="raise").to_numpy(float)
            sst = float(np.square(vals - vals.mean()).sum())
            bgt = 200.0
            w = float(math.sqrt(bgt / sst))
            sig = float(math.sqrt(sst / len(sub_proc)))
            for n in sub_proc.index:
                v = float(sub_proc.loc[n, "raw_obsval"])
                pst.observation_data.loc[n, ["obsval", "weight", "obgnme"]] = [v, w, "dry_proc_nse"]
                for t in (registry, audit):
                    t.loc[n, ["obsval", "weight", "sigma", "sigma_source", "transform", "obgnme"]] = [v, w, sig, "phi_budget", "raw", "DRY_PROC_NSE"]
                    t.loc[n, "group_multiplier"] = w * sig
            budget_summary[f"{season}_dry_proc"] = {"n": len(sub_proc), "sst": sst, "budget": bgt, "weight": w}

        # Terminal (CHPDTS) -> Budget = 300.0
        sub_term = rows[rows["sim_token"] == "CHPDTS"]
        if len(sub_term) > 0:
            vals = pd.to_numeric(sub_term["raw_obsval"], errors="raise").to_numpy(float)
            sst = float(np.square(vals - vals.mean()).sum())
            bgt = 300.0
            w = float(math.sqrt(bgt / sst))
            sig = float(math.sqrt(sst / len(sub_term)))
            for n in sub_term.index:
                v = float(sub_term.loc[n, "raw_obsval"])
                pst.observation_data.loc[n, ["obsval", "weight", "obgnme"]] = [v, w, "dry_term_nse"]
                for t in (registry, audit):
                    t.loc[n, ["obsval", "weight", "sigma", "sigma_source", "transform", "obgnme"]] = [v, w, sig, "phi_budget", "raw", "DRY_TERM_NSE"]
                    t.loc[n, "group_multiplier"] = w * sig
            budget_summary[f"{season}_dry_term"] = {"n": len(sub_term), "sst": sst, "budget": bgt, "weight": w}

    # 2. Process State Variables (LAID: 150, LWAD: 150, SWAD: 150)
    for var, budget, toks in [
        ("LAID", 150.0, ["LAIDS_T", "LAIDS", "LAIDM_T", "LAIDM"]),
        ("LWAD", 150.0, ["LWADS_T", "LWADS", "LWADM_T", "LWADM"]),
        ("SWAD", 150.0, ["SWADS_T", "SWADS", "SWADM_T", "SWADM"]),
    ]:
        v_rows = registry[registry["sim_token"].astype(str).isin(toks)].copy()
        for season, rows in v_rows.groupby("season_id", sort=True):
            vals = pd.to_numeric(rows["raw_obsval"], errors="raise").to_numpy(float)
            sst = float(np.square(vals - vals.mean()).sum())
            if sst > 0:
                w = float(math.sqrt(budget / sst))
                sig = float(math.sqrt(sst / len(rows)))
                for n in rows.index:
                    v = float(rows.loc[n, "raw_obsval"])
                    pst.observation_data.loc[n, ["obsval", "weight", "obgnme"]] = [v, w, f"proc_{var.lower()}"]
                    for t in (registry, audit):
                        t.loc[n, ["obsval", "weight", "sigma", "sigma_source", "transform", "obgnme"]] = [v, w, sig, "phi_budget", "raw", f"PROC_{var}"]
                        t.loc[n, "group_multiplier"] = w * sig
                budget_summary[f"{season}_{var.lower()}"] = {"n": len(rows), "sst": sst, "budget": budget, "weight": w}

    # 3. Explicitly zero out CHTD, WRESP, NRESP
    zero_obs = pst.observation_data[
        pst.observation_data["obgnme"].astype(str).str.upper().str.contains("CHTD") |
        pst.observation_data["obgnme"].astype(str).str.upper().str.contains("WRESP") |
        pst.observation_data["obgnme"].astype(str).str.upper().str.contains("NRESP")
    ].index
    pst.observation_data.loc[zero_obs, "weight"] = 0.0

    return budget_summary


def main() -> int:
    run_dir = ROOT / "workspace/runs" / CASE
    if run_dir.exists():
        shutil.rmtree(run_dir)

    frozen_csv, design_path = prepare_bounds_and_design(run_dir)

    print(f"[1/6] Running base PST build...")
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    subprocess.run(
        [
            sys.executable, str(ROOT / "tools/calibration/build_fixed_soil_joint_v3_20260813.py"),
            "--variant", "official", "--case", CASE, "--design", str(design_path),
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
    frozen = pd.read_csv(frozen_csv, encoding="utf-8-sig")
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
    budget_summary = apply_phi_budget_weights(pst, registry, audit, run_dir=run_dir)
    
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
    params["value"] = params.apply(lambda r: lookup.get(str(r["name"]).lower(), r["value"]), axis=1)
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
    _write_observation_noise_ensemble(pst_path, audit_path, run_dir, CASE, N_REALS, SEED)

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
        "n_adjustable": int((pst.parameter_data["partrans"] != "fixed").sum()),
        "budget_summary": budget_summary,
    }
    (run_dir / "formal_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(contract, ensure_ascii=False, indent=2))
    print(f"\nTask built successfully in: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
