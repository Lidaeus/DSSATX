"""Render 3-Season Comprehensive Diagnostic Plot Suite (25SP, 26SP, 25FA - all 34 treatments)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools/analysis") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools/analysis"))

from render_arm_d_best17_diagnostics_20260820 import (
    build_season_harvest_compare,
    build_season_process_compare,
    compute_metrics,
)

CAND_PARAMS = ROOT / "workspace/runs/e02_from_scratch_s3_formal_joint_wide_200reals_20260827/candidates/cand1_lowest_phi_params.csv"
CASE_NAME = "e02_eval_s3_wide_3seasons_all34_20260827"
RUN_DIR = ROOT / "workspace/runs" / CASE_NAME
OUT_FIG_DIR = ROOT / "figture" / "e02_s3_wide_3seasons_diagnostics_20260827"
MAPPING_CSV = ROOT / "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv"
REG_CSV = ROOT / "workspace/runs/e02_from_scratch_s3_formal_joint_wide_200reals_20260827/e02_s3_wide200_observation_registry.csv"

if RUN_DIR.exists():
    shutil.rmtree(RUN_DIR)
RUN_DIR.mkdir(parents=True, exist_ok=True)
OUT_FIG_DIR.mkdir(parents=True, exist_ok=True)

# 3-Season Multi-treatment Design
design_dict = {
    "schema_version": 1,
    "design_id": CASE_NAME,
    "cultivar_identity": "TM0008",
    "shared_parameter_scope": "Full 3-Season Evaluation (25SP, 26SP, 25FA - 34 Treatments)",
    "bounds_id": "eggplant_e02_s3_formal_joint_wide_bounds_20260827",
    "observation_policy": "configs/runs/e02_from_scratch_objective_contract_20260826.csv",
    "group_policy": "configs/runs/e02_from_scratch_group_policy_20260826.csv",
    "harvest_dry_objective": {
        "enabled": True,
        "mode": "increment_plus_terminal",
        "variable": "CHPDT",
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
            "bundle_path": "data/user/experiments/xxql2501_from_scratch_10L_B_20260826",
            "role": "calibration",
            "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]
        },
        {
            "season_id": "26SP",
            "experiment_code": "XXQL2601",
            "bundle_path": "data/user/experiments/xxql2601_from_scratch_10L_B_20260826",
            "role": "calibration",
            "treatments": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
        },
        {
            "season_id": "25FA",
            "experiment_code": "XXQL2502",
            "bundle_path": "data/user/experiments/xxfa_from_scratch_10L_B_20260826",
            "role": "calibration",
            "treatments": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
        }
    ]
}

design_path = RUN_DIR / "joint_design_3seasons.json"
with open(design_path, "w", encoding="utf-8") as f:
    json.dump(design_dict, f, indent=2)

# Forward simulation
env = os.environ.copy()
env["PYTHONPATH"] = str(ROOT)
cmd_run = [
    sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
    "--design", str(design_path),
    "--param-csv", str(CAND_PARAMS),
    "--prefix", "eval_3seasons",
    "--harvest-var", "CHPDT",
    "--keep-nitrogen-outputs",
]
print("Running deterministic forward simulation for all 3 seasons (34 treatments)...")
subprocess.run(cmd_run, cwd=str(RUN_DIR), env=env, check=True)

# Build compare CSVs for all 3 seasons
for s in ["25SP", "26SP", "25FA"]:
    sdir = RUN_DIR / "_seasons" / s
    h_df = build_season_harvest_compare(sdir, s)
    p_df = build_season_process_compare(sdir, s)
    print(f"[{s}] Harvest compare: {len(h_df)} rows | Process compare: {len(p_df)} rows")

# Render diagnostics using existing plot_dynamics.py
cmd_plot = [
    sys.executable, str(ROOT / "tools/calibration/plot_dynamics.py"),
    "--det-root", str(RUN_DIR),
    "--out-root", str(OUT_FIG_DIR),
    "--seasons", "25SP,26SP,25FA",
    "--include-all-treatments",
    "--mapping-csv", str(MAPPING_CSV)
]
if REG_CSV.exists():
    cmd_plot.extend(["--registry-csv", str(REG_CSV)])

print(f"\nRendering 3-season diagnostics via plot_dynamics.py -> {OUT_FIG_DIR}...")
subprocess.run(cmd_plot, cwd=str(ROOT), check=True)
print("All 3 seasons diagnostics successfully created!")
