"""Replay Arm D Best Member #17 with True Measured Initial Nitrogen Gradient (no legacy IC overwrite)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ARM_D_DIR = ROOT / "workspace/runs/e02_arm_d_full_synergy_50x3_20260820"
DET_DIR = ROOT / "workspace/runs/e02_arm_d_best17_measured_ic_20260820"
OUT_FIG_DIR = ROOT / "figture/e02_arm_d_best17_measured_ic_two_season_20260820"
REGISTRY_CSV = ARM_D_DIR / "e02_arm_d_full_synergy_50x3_20260820_observation_registry.csv"
MAPPING_CSV = ARM_D_DIR / "deterministic_best_17/two_season_water_n_mapping_from_filex.csv"

sys.path.insert(0, str(ROOT / "tools/analysis"))
from render_arm_d_best17_diagnostics_20260820 import (
    build_season_harvest_compare,
    build_season_process_compare,
    compute_metrics,
)


def replay_and_plot():
    DET_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FIG_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Load Arm D Member 17 genetic and soil parameters (FILTER OUT IC_ parameters so DSSAT uses pure FileX measured values!)
    raw_params = pd.read_csv(ARM_D_DIR / "deterministic_best_17/best_params.csv")
    pure_params = raw_params[~raw_params["name"].str.upper().str.startswith("IC_")].copy()
    param_csv = DET_DIR / "pure_measured_ic_best_params.csv"
    pure_params.to_csv(param_csv, index=False)
    print(f"Prepared {len(pure_params)} parameters (filtered out {len(raw_params) - len(pure_params)} legacy IC overrides)")

    # 2. Run DSSAT multiseason simulation
    design_path = ARM_D_DIR / "joint_design.json"
    cmd_run = [
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_path),
        "--param-csv", str(param_csv),
        "--prefix", "arm_d_best17_measured_ic",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    print(f"Running deterministic simulation for Arm D #17 with pure measured IC in {DET_DIR}...")
    subprocess.run(cmd_run, cwd=DET_DIR, env=env, check=True)

    # 3. Build comparison CSVs and calculate metrics
    metrics_rows = []
    for season in ["25SP", "26SP"]:
        sdir = DET_DIR / "_seasons" / season
        h_compare = build_season_harvest_compare(sdir, season)
        for vcol in ["DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM"]:
            obs_c = f"OBS_{vcol}"
            sim_c = f"SIM_{vcol}"
            if obs_c in h_compare.columns and sim_c in h_compare.columns:
                m = compute_metrics(h_compare[obs_c].to_numpy(float), h_compare[sim_c].to_numpy(float))
                m.update({"season": season, "kind": "harvest", "variable": vcol, "n": len(h_compare)})
                metrics_rows.append(m)

        p_compare = build_season_process_compare(sdir, season)
        for var in ["LAID", "LWAD", "SWAD", "CHTD"]:
            obs_c = f"OBS_{var}"
            sim_c = f"SIM_{var}"
            if obs_c in p_compare.columns and sim_c in p_compare.columns:
                m = compute_metrics(p_compare[obs_c].to_numpy(float), p_compare[sim_c].to_numpy(float))
                m.update({"season": season, "kind": "process", "variable": var, "n": len(p_compare)})
                metrics_rows.append(m)

    metrics_df = pd.DataFrame(metrics_rows)
    metrics_path = DET_DIR / "metrics_by_season_variable.csv"
    metrics_df.to_csv(metrics_path, index=False)
    print(f"\n=== Arm D Best #17 (Measured IC) Metrics Summary ===")
    print(metrics_df[["season", "kind", "variable", "n", "rmse", "mae", "nse", "d_index", "r2"]].to_string(index=False))

    # 4. Check N3 vs N0 simulated harvest yields
    print("\n=== 25SP Harvest Comparison (Pure Measured IC) ===")
    h25 = pd.read_csv(DET_DIR / "_seasons/25SP/25SP_deterministic_harvest_compare.csv")
    print(h25.groupby("TN")[["OBS_DRY_CUM", "SIM_DRY_CUM", "OBS_FRESH_CUM", "SIM_FRESH_CUM"]].last())

    print("\n=== 26SP Harvest Comparison (Pure Measured IC) ===")
    h26 = pd.read_csv(DET_DIR / "_seasons/26SP/26SP_deterministic_harvest_compare.csv")
    print(h26.groupby("TN")[["OBS_DRY_CUM", "SIM_DRY_CUM", "OBS_FRESH_CUM", "SIM_FRESH_CUM"]].last())

    # 5. Render Diagnostic plots
    if MAPPING_CSV.exists():
        shutil.copy2(MAPPING_CSV, DET_DIR / "two_season_water_n_mapping_from_filex.csv")
    cmd_plot = [
        sys.executable, str(ROOT / "tools/calibration/plot_dynamics.py"),
        "--det-root", str(DET_DIR),
        "--out-root", str(OUT_FIG_DIR),
        "--seasons", "25SP,26SP",
        "--registry-csv", str(REGISTRY_CSV),
        "--include-all-treatments",
        "--mapping-csv", str(DET_DIR / "two_season_water_n_mapping_from_filex.csv")
    ]
    print(f"\nRendering diagnostic plots to: {OUT_FIG_DIR}...")
    subprocess.run(cmd_plot, cwd=ROOT, check=True)
    print(f"Diagnostic plots rendered successfully to: {OUT_FIG_DIR}")


if __name__ == "__main__":
    replay_and_plot()
