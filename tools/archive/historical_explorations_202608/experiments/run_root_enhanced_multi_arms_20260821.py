"""Run 4-Arm Small-Scale Exploratory Trials on Root Enhancement and Greenhouse Mineralization.

Arms:
- Arm 1: High Specific Root Length & Active Uptake (RWDTH 0.9-1.5, RTNO3 0.04-0.05, RTEXF 0.30-0.45)
- Arm 2: High Greenhouse Soil Mineralization (SOIL_SLNF 2.5-3.2, RWDTH 0.8-1.2, RTNO3 0.04-0.05)
- Arm 3: High Root Nitrogen Recovery & Longevity (NRCVR 0.35-0.55, RTSEN 0.005-0.012, SOIL_SLNF 2.2-2.8)
- Arm 4: Full High-Efficiency Root-N Synergy (RWDTH 1.0-1.5, SOIL_SLNF 2.4-3.0, RTNO3 0.045-0.050, NRCVR 0.35-0.50, LNREF 4.5-5.6)
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

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.build_pest import _write_observation_noise_ensemble
from src.calibration.initial_ensemble import generate_lhs_ensemble, write_ensemble_csv
from tools.calibration.prepare_v20_senescence_slnf_official_20260820 import apply_phi_budget_weights

N_REALS = 40
NOPTMAX = 3
SEED = 20260821
BASE_FROZEN = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v22_synergy_roots_20260821.csv"


def build_and_run_arm(arm_id: str, arm_name: str, bound_mods: dict[str, dict[str, float | str]]) -> dict:
    case_name = f"e02_root_arm_{arm_id.lower()}_{arm_name}_40x3_20260821"
    run_dir = ROOT / "workspace/runs" / case_name
    bounds_id = f"eggplant_e02_root_arm_{arm_id.lower()}_20260821"
    
    if run_dir.exists():
        shutil.rmtree(run_dir)
        
    print(f"\n=======================================================")
    print(f"   Building Root Exploration {arm_id}: {arm_name}")
    print(f"   Run Dir: {run_dir}")
    print(f"=======================================================")
    
    # 1. Prepare bounds proposal
    frame = pd.read_csv(BASE_FROZEN, encoding="utf-8-sig")
    existing = set(frame["name"].str.lower())
    for pname, adj in bound_mods.items():
        if pname in existing:
            idx = frame[frame["name"].str.lower() == pname].index[0]
            for k, v in adj.items():
                if k in frame.columns:
                    frame.at[idx, k] = v
        else:
            new_row = {c: "" for c in frame.columns}
            new_row["name"] = pname
            new_row.update(adj)
            frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)
            
    proposal_csv = ROOT / "data/parameter_registry/bounds_proposals" / f"{bounds_id}.csv"
    frozen_csv = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{bounds_id}.csv"
    proposal_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(proposal_csv, index=False, encoding="utf-8-sig")
    
    if frozen_csv.exists():
        os.remove(frozen_csv)
    meta_path = frozen_csv.parent / f"{bounds_id}.yaml"
    if meta_path.exists():
        os.remove(meta_path)
        
    subprocess.run([
        sys.executable, str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(proposal_csv), "--crop", "eggplant",
        "--bounds-id", bounds_id, "--notes", f"Root Exploration {arm_id} ({arm_name})"
    ], cwd=ROOT, check=True)
    
    # 2. Design JSON
    design_path = ROOT / "configs/runs" / f"{case_name}.json"
    design_content = {
        "schema_version": 1,
        "design_id": case_name,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": f"Root Exploration {arm_id} ({arm_name})",
        "bounds_id": bounds_id,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Pure measured FileX IC values with 13-layer soil",
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
                "season_id": "25SP",
                "experiment_code": "XXQL2501",
                "bundle_path": str(ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v4_13layer_20260820"),
                "role": "calibration",
                "treatments": [2, 5, 10, 13]
            },
            {
                "season_id": "26SP",
                "experiment_code": "XXQL2601",
                "bundle_path": str(ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v4_13layer_20260820"),
                "role": "calibration",
                "treatments": [2, 11, 3, 12]
            }
        ],
        "pest_ies": {
            "num_reals": N_REALS, "noptmax": NOPTMAX, "par_sigma_range": 4.0,
            "lambda_mults": [0.1, 1.0, 10.0], "subreg": True, "subreg_how": "par_sigma_range"
        }
    }
    with open(design_path, "w", encoding="utf-8") as f:
        json.dump(design_content, f, indent=2)
        
    # 3. Build task PST
    builder_cmd = [
        sys.executable, str(ROOT / "tools/calibration/build_fixed_soil_joint_v3_20260813.py"),
        "--variant", "official",
        "--case", case_name,
        "--design", str(design_path),
        "--bounds-id", bounds_id,
        "--noptmax", str(NOPTMAX),
        "--ies-num-reals", str(N_REALS),
        "--random-seed", str(SEED)
    ]
    subprocess.run(builder_cmd, cwd=ROOT, check=True)
    
    # 4. Run Parallel IES (4 agents)
    cmd_parallel = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir),
        "--case", case_name,
        "--mode", "ies",
        "--n-agents", "4",
        "--wait"
    ]
    print(f"Launching 4-Agent Parallel IES for {arm_id}...")
    subprocess.run(cmd_parallel, cwd=ROOT, check=True)
    
    # Read phi progression
    phi_csv = run_dir / f"{case_name}.phi.actual.csv"
    phi_df = pd.read_csv(phi_csv) if phi_csv.exists() else pd.DataFrame()
    last_min = phi_df.iloc[-1]["min"] if not phi_df.empty else float("nan")
    last_mean = phi_df.iloc[-1]["mean"] if not phi_df.empty else float("nan")
    
    return {
        "arm_id": arm_id, "arm_name": arm_name, "run_dir": str(run_dir),
        "case_name": case_name, "last_min_phi": last_min, "last_mean_phi": last_mean
    }


def main():
    trials = [
        ("Arm1", "high_rwdth_uptake", {
            "rwdth": {"lower": 0.90, "upper": 1.50, "init": 1.15, "status": "active"},
            "rtno3": {"lower": 0.040, "upper": 0.050, "init": 0.048, "status": "active"},
            "rtnh4": {"lower": 0.040, "upper": 0.050, "init": 0.048, "status": "active"},
            "rtexf": {"lower": 0.30, "upper": 0.45, "init": 0.36, "status": "active"},
            "soil_slnf": {"lower": 1.90, "upper": 2.40, "init": 2.10, "status": "active"},
        }),
        ("Arm2", "high_soil_mineralization", {
            "soil_slnf": {"lower": 2.50, "upper": 3.20, "init": 2.80, "status": "active"},
            "rwdth": {"lower": 0.80, "upper": 1.20, "init": 1.00, "status": "active"},
            "rtno3": {"lower": 0.040, "upper": 0.050, "init": 0.048, "status": "active"},
            "rtnh4": {"lower": 0.040, "upper": 0.050, "init": 0.048, "status": "active"},
            "rtexf": {"lower": 0.25, "upper": 0.40, "init": 0.32, "status": "active"},
        }),
        ("Arm3", "high_nrcvr_root_longevity", {
            "nrcvr": {"lower": 0.35, "upper": 0.55, "init": 0.45, "status": "active"},
            "soil_slnf": {"lower": 2.20, "upper": 2.80, "init": 2.50, "status": "active"},
            "rwdth": {"lower": 0.80, "upper": 1.30, "init": 1.05, "status": "active"},
            "rtexf": {"lower": 0.28, "upper": 0.42, "init": 0.35, "status": "active"},
            "rtno3": {"lower": 0.040, "upper": 0.050, "init": 0.048, "status": "active"},
        }),
        ("Arm4", "full_root_n_synergy", {
            "rwdth": {"lower": 1.00, "upper": 1.50, "init": 1.25, "status": "active"},
            "soil_slnf": {"lower": 2.40, "upper": 3.00, "init": 2.70, "status": "active"},
            "rtno3": {"lower": 0.045, "upper": 0.050, "init": 0.048, "status": "active"},
            "rtnh4": {"lower": 0.045, "upper": 0.050, "init": 0.048, "status": "active"},
            "rtexf": {"lower": 0.32, "upper": 0.45, "init": 0.38, "status": "active"},
            "nrcvr": {"lower": 0.35, "upper": 0.50, "init": 0.42, "status": "active"},
            "lnref": {"lower": 4.50, "upper": 5.60, "init": 5.00, "status": "active"},
            "xfint": {"lower": 0.10, "upper": 0.25, "init": 0.18, "status": "active"},
            "nmobmx": {"lower": 0.08, "upper": 0.18, "init": 0.12, "status": "active"},
            "senrte": {"lower": 0.30, "upper": 2.00, "init": 0.80, "status": "active"},
        }),
    ]
    
    results = []
    for aid, aname, bmods in trials:
        res = build_and_run_arm(aid, aname, bmods)
        results.append(res)
        
    print("\n=======================================================")
    print("        4-Arm Root Exploration Summary Results")
    print("=======================================================")
    res_df = pd.DataFrame(results)
    print(res_df[["arm_id", "arm_name", "last_min_phi", "last_mean_phi"]].to_string(index=False))


if __name__ == "__main__":
    main()
