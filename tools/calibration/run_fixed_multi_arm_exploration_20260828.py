"""Multi-Arm Exploration Launcher & Evaluator with Fixed Parameter Injection Engine and Fused S1-S2 Bounds.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RUN_BASE = ROOT / "workspace/runs"
BOUNDS_FUSED = "eggplant_e02_joint_fused_s1_s2_bounds_20260828"

ARMS = {
    "Arm_B": {
        "run_id": "e02_arm_b_clean_measuredn_fixed_pgeff_20260828",
        "prefix": "e02_arm_b",
        "description": "Arm B: Clean TMT/TMA + Measured Soil Initial N + Fused Bounds",
        "bounds_id": BOUNDS_FUSED,
        "n_reals": 100,
        "noptmax": 5,
        "agents": 6,
        "bundles": {
            "25SP": "data/user/experiments/xxql2501_clean_measuredn_0_4_60cm_20260828",
            "25SP_sha": "c8054ab71316360228308186f97913faf4be030936a74bf64a7fc439d5300c27",
            "26SP": "data/user/experiments/xxql2601_clean_measuredn_0_4_60cm_20260828",
            "26SP_sha": "646dd1a2c0b0624a88ba50824b5d7e4e8f6ea76ea8b1ccf167b9151423f72290",
            "25FA": "data/user/experiments/xxfa_clean_measuredn_0_4_60cm_20260828",
            "25FA_sha": "587dfcc3484454457ae5b0680e9156337823a61f4229c6888a57e805866e069c",
        }
    },
}

def build_and_run_arm(arm_name, cfg):
    print(f"\n=======================================================")
    print(f"Starting {arm_name}: {cfg['description']}")
    print(f"=======================================================")
    
    out_dir = RUN_BASE / cfg["run_id"]
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Create Design JSON by loading baseline template and updating
    tpl_file = ROOT / "configs/runs/e02_from_scratch_arm_a_v15_baseline_20260828.json"
    design_data = json.loads(tpl_file.read_text(encoding="utf-8"))
    
    design_data["design_id"] = cfg["run_id"]
    design_data["stage"] = arm_name
    design_data["purpose"] = cfg["description"]
    design_data["bounds_id"] = cfg["bounds_id"]
    design_data["pest_ies"]["num_reals"] = cfg["n_reals"]
    design_data["pest_ies"]["noptmax"] = cfg["noptmax"]
    design_data["pest_ies"]["agents"] = cfg["agents"]
    
    # Update seasons bundles
    for s in design_data["seasons"]:
        sid = s["season_id"]
        if sid in cfg["bundles"]:
            s["bundle_path"] = cfg["bundles"][sid]
            s["bundle_manifest_sha256"] = cfg["bundles"][f"{sid}_sha"]
            
    design_file = ROOT / "configs/runs" / f"{cfg['run_id']}.json"
    design_file.write_text(json.dumps(design_data, indent=2), encoding="utf-8")
    
    # 2. Build PEST Case
    cmd_build = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(design_file),
        "--bounds-id", cfg["bounds_id"],
        "--bounds-crop", "eggplant",
        "--prefix", cfg["prefix"],
        "--noptmax", str(cfg["noptmax"]),
        "--ies-num-reals", str(cfg["n_reals"]),
        "--random-seed", "42",
        "--param-review-mode", "off",
        "--bounds-review-mode", "off",
        "--out-dir", str(out_dir)
    ]
    print(f"Building PEST case for {arm_name}...")
    res_b = subprocess.run(cmd_build, cwd=ROOT, capture_output=True, text=True)
    if res_b.returncode != 0:
        print(f"Build failed for {arm_name}:", res_b.stderr)
        return False
        
    # 3. Parallel Execution
    cmd_run = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(out_dir),
        "--case", cfg["prefix"],
        "--mode", "ies",
        "--n-agents", str(cfg["agents"]),
        "--wait"
    ]
    print(f"Running parallel IES calibration ({cfg['n_reals']} reals x {cfg['noptmax']} iters x {cfg['agents']} agents)...")
    res_r = subprocess.run(cmd_run, cwd=ROOT, capture_output=True, text=True)
    if res_r.returncode != 0:
        print(f"Execution failed for {arm_name}:", res_r.stderr)
        return False
        
    print(f"{arm_name} completed successfully!")
    return True

if __name__ == "__main__":
    for arm_name, cfg in ARMS.items():
        ok = build_and_run_arm(arm_name, cfg)
        if not ok:
            print(f"Aborting subsequent arms due to failure in {arm_name}")
            break
