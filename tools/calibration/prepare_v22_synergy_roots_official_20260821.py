"""Prepare and Launch v22 Formal Calibration (Synergistic Enhanced Roots, Soil Mineralization, Leaf N, & Senescence Protection).

Scale: 200 reals x 6 iterations x 6 agents
Case: e02_v22_synergy_roots_official_200x6_20260821
Bounds ID: eggplant_e02_v22_synergy_roots_20260821
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
from tools.calibration.prepare_v20_senescence_slnf_official_20260820 import apply_phi_budget_weights

CASE_NAME = "e02_v22_synergy_roots_official_200x6_20260821"
BOUNDS_ID = "eggplant_e02_v22_synergy_roots_20260821"
N_REALS = 200
NOPTMAX = 6
SEED = 20260821

RUN_DIR = ROOT / "workspace/runs" / CASE_NAME
BASE_FROZEN = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v21_13layer_synergy_20260820.csv"


def prepare_v22_frozen_bounds() -> tuple[Path, Path]:
    frame = pd.read_csv(BASE_FROZEN, encoding="utf-8-sig")
    existing_names = set(frame["name"].str.lower())
    
    # Synergistic union of Arm A + Arm B + Arm C + Arm D
    adjustments = {
        # Arm A: Measured Leaf Nitrogen & Photosynthetic Capacity
        "lnref": {"init": 4.800, "lower": 4.200, "upper": 5.600, "status": "active"},
        "lfmax": {"init": 1.450, "lower": 1.100, "upper": 1.900, "status": "active"},
        "slavr": {"init": 160.0, "lower": 130.0, "upper": 200.0, "status": "active"},
        
        # Arm B: Greenhouse Soil Mineralization (13-layer profile)
        "soil_slnf": {"init": 2.200, "lower": 1.800, "upper": 2.800, "status": "active"},
        
        # Arm C: Enhanced Early Root Deep Foraging & Nitrogen Capture
        "rtexf": {"init": 0.320, "lower": 0.220, "upper": 0.450, "status": "active"},
        "rwdth": {"init": 0.800, "lower": 0.600, "upper": 1.200, "status": "active"},
        "rtno3": {"init": 0.045, "lower": 0.030, "upper": 0.050, "status": "active"},
        "rtnh4": {"init": 0.045, "lower": 0.030, "upper": 0.050, "status": "active"},
        "nrcvr": {"init": 0.300, "lower": 0.200, "upper": 0.450, "status": "active"},
        
        # Arm D: Smooth Reproductive Partitioning & Physical Senescence Protection
        "xfint": {"init": 0.180, "lower": 0.100, "upper": 0.300, "status": "active"},
        "nmobmx": {"init": 0.140, "lower": 0.080, "upper": 0.200, "status": "active"},
        "senrte": {"init": 0.800, "lower": 0.300, "upper": 2.500, "status": "active"},
        "nvsmob": {"init": 0.220, "lower": 0.200, "upper": 0.250, "status": "active"},
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
            
    proposal_csv = ROOT / "data/parameter_registry/bounds_proposals" / f"{BOUNDS_ID}.csv"
    frozen_csv = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv"
    proposal_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(proposal_csv, index=False, encoding="utf-8-sig")
    
    if frozen_csv.exists():
        os.remove(frozen_csv)
    meta_path = frozen_csv.parent / f"{BOUNDS_ID}.yaml"
    if meta_path.exists():
        os.remove(meta_path)
        
    cmd_freeze = [
        sys.executable, str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(proposal_csv), "--crop", "eggplant",
        "--bounds-id", BOUNDS_ID,
        "--notes", "v22 Formal Calibration: Synergy of Arm A (LNREF 4.2-5.6%, LFMAX 1.1-1.9) + Arm B (SLNF 1.8-2.8) + Arm C (RTEXF 0.22-0.45, RWDTH 0.6-1.2, RTNO3/NH4, NRCVR) + Arm D (XFINT 0.1-0.3, Senescence Protection)"
    ]
    subprocess.run(cmd_freeze, cwd=ROOT, check=True)
    return proposal_csv, frozen_csv


def prepare_v22_task() -> Path:
    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)

    proposal_csv, frozen_csv = prepare_v22_frozen_bounds()

    # Create Design JSON
    design_path = ROOT / "configs/runs" / f"{CASE_NAME}.json"
    design_content = {
        "schema_version": 1,
        "design_id": CASE_NAME,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "Dual-season full-sample joint calibration (13-layer soil + synergy of Arm A/B/C/D)",
        "bounds_id": BOUNDS_ID,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Pure measured FileX IC values with no legacy override",
        "nitrogen_response_objective": {"enabled": False},
        "water_response_objective": {"enabled": False},
        "harvest_dry_objective": {
            "enabled": True, "mode": "increment_plus_terminal", "variable": "CHPDT",
            "process_lambda_per_season": 200.0, "terminal_lambda_per_season": 300.0
        },
        "process_state_objective": {
            "enabled": True, "mode": "signed_difference_plus_terminal", "variables": ["LAID", "LWAD", "SWAD"]
        },
        "seasons": [
            {
                "season_id": "25SP", "experiment_code": "XXQL2501",
                "bundle_path": str(ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v4_13layer_20260820"),
                "role": "calibration", "treatments": [2, 5, 10, 13]
            },
            {
                "season_id": "26SP", "experiment_code": "XXQL2601",
                "bundle_path": str(ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v4_13layer_20260820"),
                "role": "calibration", "treatments": [2, 11, 3, 12]
            }
        ]
    }
    design_path.write_text(json.dumps(design_content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Created design JSON: {design_path}")

    # Build multi-season task using build_fixed_soil_joint_v3
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    cmd_build = [
        sys.executable, str(ROOT / "tools/calibration/build_fixed_soil_joint_v3_20260813.py"),
        "--variant", "official",
        "--case", CASE_NAME,
        "--design", str(design_path),
        "--bounds-id", BOUNDS_ID,
        "--noptmax", str(NOPTMAX),
        "--ies-num-reals", str(N_REALS),
        "--random-seed", str(SEED),
    ]
    print(f"Executing task builder: {' '.join(cmd_build)}")
    subprocess.run(cmd_build, cwd=ROOT, env=env, check=True)

    # Sync PST with frozen bounds
    pst_path = RUN_DIR / f"{CASE_NAME}.pst"
    audit_path = RUN_DIR / f"{CASE_NAME}.weights.audit.csv"
    registry_path = RUN_DIR / f"{CASE_NAME}_observation_registry.csv"

    pst = pyemu.Pst(str(pst_path))
    frozen = pd.read_csv(frozen_csv, encoding="utf-8-sig").set_index("name")

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

    # Apply T10 family-budget weights
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    apply_phi_budget_weights(pst, registry, audit, run_dir=RUN_DIR)

    # Configure PEST++ IES options
    pst.control_data.noptmax = NOPTMAX
    pst.pestpp_options.update({
        "ies_num_reals": N_REALS,
        "rand_seed": SEED,
        "ies_parameter_ensemble": f"{CASE_NAME}.0.par.csv",
        "ies_observation_ensemble": f"{CASE_NAME}.observation_ensemble.csv",
        "ies_include_base": "false",
        "ies_subset_how": "random",
        "ies_accept_phi_fac": 1.05,
    })
    pst.write(str(pst_path))
    print(f"PST successfully synced and written: {pst_path}")

    # Generate Sobol initial parameter ensemble
    par = pst.parameter_data
    ensemble_bounds = pd.DataFrame({
        "name": par.index,
        "init": par.parval1,
        "lower": par.parlbnd,
        "upper": par.parubnd,
        "status": np.where(par.partrans.astype(str).str.lower().eq("fixed"), "fixed", "active"),
    })
    ensemble = generate_lhs_ensemble(N_REALS, ensemble_bounds, SEED, method="sobol")
    write_ensemble_csv(ensemble, RUN_DIR / f"{CASE_NAME}.0.par.csv")
    print(f"Generated Sobol parameter ensemble: {N_REALS} reals x {len(ensemble_bounds)} pars")

    # Generate observation noise ensemble
    _write_observation_noise_ensemble(pst_path, audit_path, RUN_DIR, CASE_NAME, N_REALS, SEED)
    print("Observation noise ensemble generated successfully.")

    return RUN_DIR


def main():
    print("=================================================================")
    print("  Starting v22 Formal Calibration Task Preparation & Launch")
    print("=================================================================")
    run_dir = prepare_v22_task()
    print(f"\nTask prepared successfully at: {run_dir}")
    print("\nLaunching 6-Agent Parallel Calibration...")
    
    cmd_run = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir),
        "--case", CASE_NAME,
        "--mode", "ies",
        "--n-agents", "6",
        "--wait"
    ]
    subprocess.run(cmd_run, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
