#!/usr/bin/env python3
"""Detailed comparative analysis of Objective Function composition across the last 3 calibrations:
- v33: e02_formal_v33_8treat_fresh_200x6_20260829
- v34: e02_formal_v34_nitrogen_smoothed_200x6_20260829
- v35: e02_formal_v35_boundary_relaxed_200x6_20260829
"""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]

V_CONFIGS = [
    ("Formal v33 (8-Treat Fresh)", "configs/runs/e02_formal_v33_8treat_fresh_200x6_20260829.json", "workspace/runs/e02_formal_v33_8treat_fresh_200x6_20260829"),
    ("Formal v34 (N-Smoothed)", "configs/runs/e02_formal_v34_nitrogen_smoothed_200x6_20260829.json", "workspace/runs/e02_formal_v34_nitrogen_smoothed_200x6_20260829"),
    ("Formal v35 (Boundary-Relaxed)", "configs/runs/e02_formal_v35_boundary_relaxed_200x6_20260829.json", "workspace/runs/e02_formal_v35_boundary_relaxed_200x6_20260829"),
]

for label, cfg_path, run_dir in V_CONFIGS:
    print("=" * 80)
    print(f" {label.upper()} ")
    print("=" * 80)
    
    cp = PROJECT_ROOT / cfg_path
    if cp.exists():
        cfg = json.loads(cp.read_text(encoding="utf-8"))
        print(f"Design ID       : {cfg.get('design_id')}")
        print(f"Bounds ID       : {cfg.get('bounds_id')}")
        print(f"Harvest Obj     : {json.dumps(cfg.get('harvest_fresh_objective'), indent=2)}")
        print(f"Process Obj     : {json.dumps(cfg.get('process_state_objective'), indent=2)}")
        print(f"N Response Obj  : {json.dumps(cfg.get('nitrogen_response_objective'), indent=2)}")
        print(f"W Response Obj  : {json.dumps(cfg.get('water_response_objective'), indent=2)}")
        print(f"Calib Seasons/Trt:")
        for s in cfg.get("seasons", []):
            print(f"  - {s.get('season_id')}: {s.get('treatments')}")
        print(f"Diagnostic Trt  : {cfg.get('diagnostic_only')}")

    # Inspect observation registry & group audit
    rd = PROJECT_ROOT / run_dir
    audit_files = list(rd.glob("*group_weight_audit.csv"))
    if audit_files:
        adf = pd.read_csv(audit_files[0])
        print("\n--- Observation Group Weight & Budget Audit ---")
        active_groups = adf[adf["n_obs"] > 0]
        print(active_groups[["group", "season_id", "variable_family", "phi_budget", "n_obs", "mean_weight", "weight_mode"]].to_string(index=False))

    reg_files = list(rd.glob("*observation_registry.csv"))
    if reg_files:
        rdf = pd.read_csv(reg_files[0])
        pos_obs = rdf[rdf["weight"] > 0]
        print(f"\nTotal Registered Observations: {len(rdf)}")
        print(f"Active (Non-Zero Weight) Observations: {len(pos_obs)}")
        print("\nActive Observations breakdown by obgnme / group:")
        grp_summary = pos_obs.groupby(["season_id", "obgnme", "sim_token"]).agg(
            n_obs=("obsval", "count"),
            mean_weight=("weight", "mean"),
            min_weight=("weight", "min"),
            max_weight=("weight", "max")
        ).reset_index()
        print(grp_summary.to_string(index=False))
        
    print("\n")
