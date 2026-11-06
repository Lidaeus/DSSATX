"""Full-Scale Calibration Launcher (v25) Incorporating:
1. 9-Layer 0-30cm Plow Layer Soil Structure (SLB = 30, 40, 50, 60, 80, 100, 120, 140, 180 cm).
2. Dynamic Calibratable Initial Root Depth (RTDEPI [8.0, 20.0] cm).
3. Dynamic Calibratable Transplant Seedling Plug Biomass (PLWT [4.0, 9.5] g/plant).
4. Active Nitrogen & Water Root Foraging (RTNO3, RTNH4, RWUMX, PORMIN, RTEXF).
5. Leaf Nitrogen Ceiling & Senescence Protection (LNREF, NRCVR, SENRTE).
6. Greenhouse Steady-State Mineralization (SOIL_SLNF [2.8, 3.6]).
7. Full Cultivar & Ecotype Genetic Parameters.

Scale: 80 Realizations x 5 Iterations x 6 Parallel Workers.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CASE_NAME = "e02_v25_full_root_state_9layer_80x5_20260822"
RUN_DIR = ROOT / "workspace/runs" / CASE_NAME
BOUNDS_ID = "eggplant_e02_v25_full_root_state_9layer_20260822"

N_REALS = 80
NOPTMAX = 5
N_AGENTS = 6
SEED = 20260822

EXP_25_BASE = ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v4_13layer_20260820"
EXP_26_BASE = ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v4_13layer_20260820"

EXP_25_9L = ROOT / "data/user/experiments/xxql2501_rootzone_9layer_30cm_20260822"
EXP_26_9L = ROOT / "data/user/experiments/xxql2601_rootzone_9layer_30cm_20260822"

BOUNDS_SRC = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v23_formal_full_synergy_20260821.csv"


def build_9layer_bundles():
    sys.path.insert(0, str(ROOT / "tools/experiments"))
    import clean_build_9layer_bundles_20260822
    clean_build_9layer_bundles_20260822.main()


def prepare_bounds_with_root_state():
    frame = pd.read_csv(BOUNDS_SRC, encoding="utf-8-sig")
    
    # Check if RTDEPI is present; if not or fixed, make it active
    # In SPE: RTDEPI
    idx_rtdepi = frame.index[frame["name"].str.upper() == "RTDEPI"].tolist()
    if idx_rtdepi:
        frame.loc[idx_rtdepi[0], ["init", "lower", "upper", "status"]] = [12.0, 8.0, 20.0, "active"]
    else:
        new_row = {
            "name": "RTDEPI", "init": 12.0, "lower": 8.0, "upper": 20.0,
            "status": "active", "pargp": "species", "location": "SPE",
            "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
        }
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)
        
    # Check if PLWT is present
    idx_plwt = frame.index[frame["name"].str.upper() == "PLWT"].tolist()
    if idx_plwt:
        frame.loc[idx_plwt[0], ["init", "lower", "upper", "status", "location"]] = [7.0, 4.0, 9.5, "active", "IC"]
    else:
        new_row = {
            "name": "PLWT", "init": 7.0, "lower": 4.0, "upper": 9.5,
            "status": "active", "pargp": "ic", "location": "IC",
            "file": "XXQL2501.TMX", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
        }
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)
        
    # Active root foraging params in SPE
    for pname, init_v, low_v, up_v in [
        ("RTNO3", 0.006, 0.003, 0.015),
        ("RTNH4", 0.006, 0.003, 0.015),
        ("RWUMX", 0.040, 0.020, 0.080),
        ("PORMIN", 0.025, 0.010, 0.050),
        ("RTEXF", 0.500, 0.300, 0.800),
    ]:
        idx_p = frame.index[frame["name"].str.upper() == pname].tolist()
        if idx_p:
            frame.loc[idx_p[0], ["init", "lower", "upper", "status"]] = [init_v, low_v, up_v, "active"]
        else:
            new_row = {
                "name": pname, "init": init_v, "lower": low_v, "upper": up_v,
                "status": "active", "pargp": "species", "location": "SPE",
                "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
            }
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
        
    subprocess.run([
        sys.executable, str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(proposal_csv), "--crop", "eggplant",
        "--bounds-id", BOUNDS_ID, "--notes", "v25 Calibration with RTDEPI, PLWT, 9-layer 0-30cm Plow Soil"
    ], cwd=ROOT, check=True)
    print(f"Frozen bounds prepared & registered: {BOUNDS_ID}")


def build_and_launch():
    build_9layer_bundles()
    prepare_bounds_with_root_state()
    
    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)
        
    design_path = ROOT / "configs/runs" / f"{CASE_NAME}.json"
    design_content = {
        "schema_version": 1,
        "design_id": CASE_NAME,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "v25 Full Root State Calibration with RTDEPI, PLWT, and 9-Layer Soil",
        "bounds_id": BOUNDS_ID,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Pure measured FileX IC values with 9-layer 0-30cm plow soil",
        "nitrogen_response_objective": {"enabled": False},
        "water_response_objective": {"enabled": False},
        "harvest_dry_objective": {
            "enabled": True,
            "mode": "increment_plus_terminal",
            "variable": "CHPDT",
            "process_lambda_per_season": 200.0,
            "terminal_lambda_per_season": 300.0
        },
        "process_state_objective": {
            "enabled": True,
            "mode": "signed_difference_plus_terminal",
            "variables": ["LAID", "LWAD", "SWAD"]
        },
        "seasons": [
            {
                "season_id": "25SP",
                "experiment_code": "XXQL2501",
                "bundle_path": str(EXP_25_9L),
                "role": "calibration",
                "treatments": [2, 5, 10, 13]
            },
            {
                "season_id": "26SP",
                "experiment_code": "XXQL2601",
                "bundle_path": str(EXP_26_9L),
                "role": "calibration",
                "treatments": [2, 11, 3, 12]
            }
        ],
        "pest_ies": {
            "num_reals": N_REALS,
            "noptmax": NOPTMAX,
            "par_sigma_range": 4.0,
            "lambda_mults": [0.1, 1.0, 10.0],
            "subreg": True,
            "subreg_how": "par_sigma_range"
        }
    }
    
    with open(design_path, "w", encoding="utf-8") as f:
        json.dump(design_content, f, indent=2)
        
    print(f"\n=======================================================")
    print(f"   Building v25 Calibration with RTDEPI, PLWT & 9-Layer Soil: {CASE_NAME}")
    print(f"   Config: {N_REALS} reals x {NOPTMAX} iters x {N_AGENTS} agents")
    print(f"=======================================================")
    
    builder_cmd = [
        sys.executable, str(ROOT / "tools/calibration/build_fixed_soil_joint_v3_20260813.py"),
        "--variant", "official",
        "--case", CASE_NAME,
        "--design", str(design_path),
        "--bounds-id", BOUNDS_ID,
        "--noptmax", str(NOPTMAX),
        "--ies-num-reals", str(N_REALS),
        "--random-seed", str(SEED)
    ]
    subprocess.run(builder_cmd, cwd=ROOT, check=True)
    
    cmd_parallel = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(RUN_DIR),
        "--case", CASE_NAME,
        "--mode", "ies",
        "--n-agents", str(N_AGENTS),
        "--wait"
    ]
    print(f"Launching {N_AGENTS}-Agent Parallel IES for {CASE_NAME}...")
    subprocess.run(cmd_parallel, cwd=ROOT, check=True)
    print(f"\nv25 Full Root State Calibration completed successfully!")


if __name__ == "__main__":
    build_and_launch()
