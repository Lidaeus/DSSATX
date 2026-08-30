"""Automated post-processing, metrics computation, and diagnostic plotting for v25 Full Root State Calibration."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_v25_full_root_state_9layer_80x5_20260822"
RUN_DIR = ROOT / "workspace/runs" / CASE
PHI_FILE = RUN_DIR / f"{CASE}.phi.actual.csv"
PAR_FILE = RUN_DIR / f"{CASE}.5.par.csv"
MAPPING_SRC = ROOT / "workspace/runs/e02_arm_d_full_synergy_50x3_20260820/deterministic_best_17/two_season_water_n_mapping_from_filex.csv"
REGISTRY_CSV = RUN_DIR / f"{CASE}_observation_registry.csv"

# Import robust compare builders
sys.path.insert(0, str(ROOT / "tools/analysis"))
from render_arm_d_best17_diagnostics_20260820 import (
    build_season_harvest_compare,
    build_season_process_compare,
    compute_metrics,
)


def main() -> int:
    if not PHI_FILE.exists():
        print(f"Phi file not found: {PHI_FILE}")
        return 1

    df_phi = pd.read_csv(PHI_FILE)
    print("=== v25 Full Root State PHI PROGRESSION ===")
    print(df_phi[["iteration", "total_runs", "mean", "min", "max"]])

    last_row = df_phi.iloc[-1]
    members = [c for c in df_phi.columns if c not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]]
    best_mem = None
    min_phi = float("inf")
    for m in members:
        val = float(last_row[m])
        if val < min_phi:
            min_phi = val
            best_mem = m

    print(f"\nLowest Phi Best Member: #{best_mem} with Phi = {min_phi:.2f}")

    det_dir = RUN_DIR / f"deterministic_candidates/best_phi_member{best_mem}_two_season_20260822"
    det_dir.mkdir(parents=True, exist_ok=True)
    out_fig_dir = ROOT / f"figture/e02_v25_full_root_state_9layer_best{best_mem}_two_season_full_20260822"

    # Extract best member params
    df_par = pd.read_csv(PAR_FILE)
    real_col = df_par.columns[0]
    row_p = df_par.loc[df_par[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(str(best_mem))]

    params = []
    for col in df_par.columns[1:]:
        params.append({"name": str(col).lower(), "value": float(row_p.iloc[0][col])})
    param_csv = det_dir / f"best_member_{best_mem}_params.csv"
    pd.DataFrame(params).to_csv(param_csv, index=False)

    # Replay simulation
    design_path = RUN_DIR / "joint_design.json"
    cmd_run = [
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_path),
        "--param-csv", str(param_csv),
        "--prefix", f"best{best_mem}_det_official",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    print(f"Running deterministic replay for Best Member #{best_mem} in {det_dir}...")
    subprocess.run(cmd_run, cwd=det_dir, env=env, check=True)

    # Build comparison files & metrics
    metrics_rows = []
    for season in ["25SP", "26SP"]:
        sdir = det_dir / "_seasons" / season
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
    metrics_path = det_dir / "metrics_by_season_variable.csv"
    metrics_df.to_csv(metrics_path, index=False)
    print(f"\n=== v25 Best Member #{best_mem} Metrics Summary ===")
    print(metrics_df[["season", "kind", "variable", "n", "rmse", "mae", "nse", "d_index", "r2"]].to_string(index=False))

    # Render Diagnostic plots
    if MAPPING_SRC.exists():
        shutil.copy2(MAPPING_SRC, det_dir / "two_season_water_n_mapping_from_filex.csv")
    out_fig_dir.mkdir(parents=True, exist_ok=True)
    cmd_plot = [
        sys.executable, str(ROOT / "tools/calibration/plot_dynamics.py"),
        "--det-root", str(det_dir),
        "--out-root", str(out_fig_dir),
        "--seasons", "25SP,26SP",
        "--registry-csv", str(REGISTRY_CSV),
        "--include-all-treatments",
        "--mapping-csv", str(det_dir / "two_season_water_n_mapping_from_filex.csv")
    ]
    print(f"\nRendering diagnostic plots to: {out_fig_dir}...")
    subprocess.run(cmd_plot, cwd=ROOT, check=True)
    print(f"v25 Diagnostic plotting completed successfully to {out_fig_dir}!")
    return 0


if __name__ == "__main__":
    main()
