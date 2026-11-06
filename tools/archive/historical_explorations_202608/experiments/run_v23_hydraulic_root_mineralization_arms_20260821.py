"""Run 4-Arm Small-Scale Exploratory Trials on Soil Solute Transport, Root Interception, and Mineralization Compensation (v23).

Arms:
- Arm A: Hydraulic Retention & Leaching Retardation (PORMIN 0.002-0.008, SOIL_SLNF 2.4-3.0, RWDTH 1.0-1.4, RTNO3 0.045-0.050)
- Arm B: Deep Root Interception & High-Density Active Foraging (RWDTH 1.3-1.8, RTEXF 0.35-0.45, RTNO3 0.048-0.050, SOIL_SLNF 2.4-3.0)
- Arm C: Steady-State Greenhouse Mineralization Compensation (SOIL_SLNF 2.8-3.6, NRCVR 0.35-0.55, RWDTH 1.0-1.4, RTNO3 0.045-0.050)
- Arm D: Full Eco-Hydraulic & Metabolic Synergy (RWDTH 1.2-1.6, RTEXF 0.32-0.45, SOIL_SLNF 2.6-3.2, NRCVR 0.35-0.50, LNREF 4.5-5.6, XFINT 0.10-0.25, NMOBMX 0.08-0.18, SENRTE 0.30-2.00)
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

N_REALS = 40
NOPTMAX = 3
SEED = 20260821
BASE_FROZEN = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v22_synergy_roots_20260821.csv"


def build_and_run_arm(arm_id: str, arm_name: str, bound_mods: dict[str, dict[str, float | str]]) -> dict:
    case_name = f"e02_v23_arm_{arm_id.lower()}_{arm_name}_40x3_20260821"
    run_dir = ROOT / "workspace/runs" / case_name
    bounds_id = f"eggplant_e02_v23_arm_{arm_id.lower()}_20260821"
    
    if run_dir.exists():
        shutil.rmtree(run_dir)
        
    print(f"\n=======================================================")
    print(f"   Building v23 Exploratory {arm_id}: {arm_name}")
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
        "--bounds-id", bounds_id, "--notes", f"v23 Exploratory {arm_id} ({arm_name})"
    ], cwd=ROOT, check=True)
    
    # 2. Design JSON
    design_path = ROOT / "configs/runs" / f"{case_name}.json"
    design_content = {
        "schema_version": 1,
        "design_id": case_name,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": f"v23 Exploratory {arm_id} ({arm_name})",
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
        ("ArmA", "hydraulic_retention", {
            "pormin": {"lower": 0.002, "upper": 0.008, "init": 0.005, "status": "active"},
            "soil_slnf": {"lower": 2.40, "upper": 3.00, "init": 2.70, "status": "active"},
            "rwdth": {"lower": 1.00, "upper": 1.40, "init": 1.20, "status": "active"},
            "rtno3": {"lower": 0.045, "upper": 0.050, "init": 0.048, "status": "active"},
            "rtnh4": {"lower": 0.045, "upper": 0.050, "init": 0.048, "status": "active"},
            "rtexf": {"lower": 0.30, "upper": 0.42, "init": 0.36, "status": "active"},
        }),
        ("ArmB", "deep_interception_foraging", {
            "rwdth": {"lower": 1.30, "upper": 1.80, "init": 1.50, "status": "active"},
            "rtexf": {"lower": 0.35, "upper": 0.45, "init": 0.40, "status": "active"},
            "rtno3": {"lower": 0.048, "upper": 0.050, "init": 0.050, "status": "active"},
            "rtnh4": {"lower": 0.048, "upper": 0.050, "init": 0.050, "status": "active"},
            "soil_slnf": {"lower": 2.40, "upper": 3.00, "init": 2.70, "status": "active"},
        }),
        ("ArmC", "greenhouse_mineralization_boost", {
            "soil_slnf": {"lower": 2.80, "upper": 3.60, "init": 3.20, "status": "active"},
            "nrcvr": {"lower": 0.35, "upper": 0.55, "init": 0.45, "status": "active"},
            "rwdth": {"lower": 1.00, "upper": 1.40, "init": 1.20, "status": "active"},
            "rtexf": {"lower": 0.30, "upper": 0.42, "init": 0.36, "status": "active"},
            "rtno3": {"lower": 0.045, "upper": 0.050, "init": 0.048, "status": "active"},
        }),
        ("ArmD", "full_eco_hydraulic_synergy", {
            "rwdth": {"lower": 1.20, "upper": 1.60, "init": 1.40, "status": "active"},
            "rtexf": {"lower": 0.32, "upper": 0.45, "init": 0.38, "status": "active"},
            "soil_slnf": {"lower": 2.60, "upper": 3.20, "init": 2.90, "status": "active"},
            "nrcvr": {"lower": 0.35, "upper": 0.50, "init": 0.42, "status": "active"},
            "rtno3": {"lower": 0.045, "upper": 0.050, "init": 0.048, "status": "active"},
            "rtnh4": {"lower": 0.045, "upper": 0.050, "init": 0.048, "status": "active"},
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
    print("        v23 4-Arm Exploration Summary Results")
    print("=======================================================")
    res_df = pd.DataFrame(results)
    print(res_df[["arm_id", "arm_name", "last_min_phi", "last_mean_phi"]].to_string(index=False))


if __name__ == "__main__":
    main()
