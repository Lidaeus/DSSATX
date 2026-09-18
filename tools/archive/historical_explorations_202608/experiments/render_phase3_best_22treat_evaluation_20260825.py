"""Evaluate Phase 3 Best Posterior Parameters across all 22 treatments (Two Seasons: 25SP 10 treatments + 26SP 12 treatments).

Outputs:
- Replay outputs in workspace/runs/eval_22treat_phase3_best_20260825
- Metrics by season & variable
- Full 22-treatment diagnostic plots in figture/eval_22treat_phase3_best_20260825/
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PHASE3_BEST_PARAMS = ROOT / "workspace/runs/calib_25sp_nresp_phase3_20260825/deterministic_best_base/best_params.csv"
CASE_NAME = "eval_22treat_phase3_best_20260825"
RUN_DIR = ROOT / "workspace/runs" / CASE_NAME
OUT_FIG_DIR = ROOT / "figture" / CASE_NAME

BUNDLE_25SP = ROOT / "data/user/experiments/xxql2501_best_env_10layer_20260825"
BUNDLE_26SP = ROOT / "data/user/experiments/xxql2601_best_env_10layer_20260825"
MAPPING_SRC = ROOT / "workspace/runs/e02_arm_d_full_synergy_50x3_20260820/deterministic_best_17/two_season_water_n_mapping_from_filex.csv"
OFFICIAL_SPE = Path(r"C:\DSSAT48\Genotype\TMGRO048.SPE")

# Import compare builders
sys.path.insert(0, str(ROOT / "tools/analysis"))
from render_arm_d_best17_diagnostics_20260820 import (
    build_season_harvest_compare,
    build_season_process_compare,
    compute_metrics,
)


def run_evaluation():
    print(f"\n====================================================================")
    print(f"   Replaying and Plotting Full 22 Treatments Evaluation")
    print(f"   Parameters: Phase 3 Best Posterior Parameters")
    print(f"   25SP: 10 treatments (TRNO 2, 3, 4, 5, 9, 10, 11, 12, 13, 14)")
    print(f"   26SP: 12 treatments (TRNO 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)")
    print(f"   Total: 22 Treatments")
    print(f"====================================================================\n")

    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Create multi-season design JSON for all 22 treatments
    design_path = RUN_DIR / "joint_design.json"
    design_dict = {
        "schema_version": 1,
        "design_id": CASE_NAME,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "Full 22 Treatments Evaluation with Phase 3 Best Parameters",
        "bounds_id": "eggplant_calib_25sp_nresp_phase3_20260825",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "diagnostic_single_season": False,
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
                "bundle_path": str(BUNDLE_25SP),
                "role": "calibration",
                "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]
            },
            {
                "season_id": "26SP",
                "experiment_code": "XXQL2601",
                "bundle_path": str(BUNDLE_26SP),
                "role": "calibration",
                "treatments": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
            }
        ]
    }
    with open(design_path, "w", encoding="utf-8") as f:
        json.dump(design_dict, f, indent=2)

    # 2. Copy best parameters
    param_csv = RUN_DIR / "best_params.csv"
    shutil.copy2(PHASE3_BEST_PARAMS, param_csv)

    # 3. Run multi-season simulation
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = str(OFFICIAL_SPE.resolve())
    cmd_run = [
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_path),
        "--param-csv", str(param_csv),
        "--prefix", "eval_det",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    print("Running deterministic simulation across 22 treatments...")
    subprocess.run(cmd_run, cwd=str(RUN_DIR), env=env, check=True)
    print("Multi-season simulation completed successfully!")

    # 4. Build compare files and compute metrics
    metrics_rows = []
    for season in ["25SP", "26SP"]:
        sdir = RUN_DIR / "_seasons" / season
        h_compare = build_season_harvest_compare(sdir, season)
        h_compare.to_csv(sdir / "compare_harvest.csv", index=False)
        for vcol in ["DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM"]:
            obs_c = f"OBS_{vcol}"
            sim_c = f"SIM_{vcol}"
            if obs_c in h_compare.columns and sim_c in h_compare.columns:
                m = compute_metrics(h_compare[obs_c].to_numpy(float), h_compare[sim_c].to_numpy(float))
                m.update({"season": season, "kind": "harvest", "variable": vcol, "n": len(h_compare)})
                metrics_rows.append(m)

        p_compare = build_season_process_compare(sdir, season)
        p_compare.to_csv(sdir / "compare_process.csv", index=False)
        for var in ["LAID", "LWAD", "SWAD", "CHTD"]:
            obs_c = f"OBS_{var}"
            sim_c = f"SIM_{var}"
            if obs_c in p_compare.columns and sim_c in p_compare.columns:
                m = compute_metrics(p_compare[obs_c].to_numpy(float), p_compare[sim_c].to_numpy(float))
                m.update({"season": season, "kind": "process", "variable": var, "n": len(p_compare)})
                metrics_rows.append(m)

    metrics_df = pd.DataFrame(metrics_rows)
    metrics_path = RUN_DIR / "metrics_by_season_variable.csv"
    metrics_df.to_csv(metrics_path, index=False)
    print("\n=== Comprehensive Metrics for 22 Treatments ===")
    print(metrics_df[["season", "kind", "variable", "n", "rmse", "rrmse_pct", "nse", "d_index", "r2"]].to_string(index=False))

    # 5. Render Diagnostic plots for all 22 treatments
    if MAPPING_SRC.exists():
        shutil.copy2(MAPPING_SRC, RUN_DIR / "two_season_water_n_mapping_from_filex.csv")

    OUT_FIG_DIR.mkdir(parents=True, exist_ok=True)
    reg_csv = ROOT / "workspace/runs/calib_25sp_nresp_phase3_20260825/calib_25sp_nresp_phase3_20260825_observation_registry.csv"
    
    cmd_plot = [
        sys.executable, str(ROOT / "tools/calibration/plot_dynamics.py"),
        "--det-root", str(RUN_DIR),
        "--out-root", str(OUT_FIG_DIR),
        "--seasons", "25SP,26SP",
        "--include-all-treatments",
        "--mapping-csv", str(RUN_DIR / "two_season_water_n_mapping_from_filex.csv")
    ]
    if reg_csv.exists():
        cmd_plot.extend(["--registry-csv", str(reg_csv)])

    print(f"\nRendering full 22-treatment diagnostic figures to: {OUT_FIG_DIR}...")
    subprocess.run(cmd_plot, cwd=str(ROOT), check=True)
    print(f"\nAll 22 treatments diagnostic plots successfully generated in: {OUT_FIG_DIR}!")


if __name__ == "__main__":
    run_evaluation()
