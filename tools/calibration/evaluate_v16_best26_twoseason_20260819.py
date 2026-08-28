"""Evaluate deterministic performance of Best Member 26 for v16 run."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_v16_senescence_harvest_fix_official_200x6_20260819"
RUN = ROOT / "workspace/runs" / CASE
BEST_MEMBER = "26"
DET_DIR = RUN / f"deterministic_candidates/best_phi_member{BEST_MEMBER}_two_season_20260819"
OUT_FIG_DIR = ROOT / f"figture/e02_v16_senescence_harvest_fix_best{BEST_MEMBER}_two_season_full_20260819"


def main() -> int:
    par_file = RUN / f"{CASE}.6.par.csv"
    if not par_file.exists():
        raise FileNotFoundError(f"Parameter file {par_file} not found")

    par_df = pd.read_csv(par_file)
    real_col = par_df.columns[0]
    row = par_df.loc[par_df[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(BEST_MEMBER)]
    if len(row) != 1:
        raise ValueError(f"Could not find realization {BEST_MEMBER} in {par_file}")

    DET_DIR.mkdir(parents=True, exist_ok=True)
    params = []
    for col in row.columns[1:]:
        params.append({"name": str(col).lower(), "value": float(row[col].iloc[0])})
    param_csv = DET_DIR / f"best_member_{BEST_MEMBER}_params.csv"
    pd.DataFrame(params).to_csv(param_csv, index=False)

    # Run deterministic simulation using run_multiseason
    design_path = RUN / "joint_design.json"
    cmd = [
        sys.executable,
        str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_path),
        "--param-csv", str(param_csv),
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
        "--prefix", f"{CASE}_best{BEST_MEMBER}",
    ]
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    print(f"Running deterministic simulation for Best Member {BEST_MEMBER}...")
    subprocess.run(cmd, cwd=DET_DIR, env=env, check=True)

    print("Deterministic simulation completed successfully!")

    # Calculate metrics for 25SP and 26SP
    selected_trts = {"25SP": [2, 5, 10, 13], "26SP": [2, 11, 3, 12]}
    summary_metrics = []

    for season, trts in selected_trts.items():
        harvest_file = DET_DIR / "_seasons" / season / f"{season}_deterministic_harvest_compare.csv"
        process_file = DET_DIR / "_seasons" / season / f"{season}_deterministic_process_compare.csv"

        if harvest_file.exists():
            h_df = pd.read_csv(harvest_file)
            h_sub = h_df.loc[h_df["TN"].astype(int).isin(trts)].copy()
            obs_dry = h_sub["OBS_DRY_CUM"].to_numpy(float)
            sim_dry = h_sub["SIM_DRY_CUM"].to_numpy(float)
            err = sim_dry - obs_dry
            sst = float(np.square(obs_dry - obs_dry.mean()).sum())
            nse = float(1 - np.square(err).sum() / sst) if sst else np.nan
            rmse = float(np.sqrt(np.square(err).mean()))
            rrmse = float(100 * rmse / np.abs(obs_dry).mean())
            bias = float(err.mean())
            summary_metrics.append({
                "season": season, "variable": "DRY_CUM", "scope": "calibration_trts",
                "nse": nse, "rmse": rmse, "rrmse_pct": rrmse, "bias": bias, "n": len(obs_dry)
            })

        if process_file.exists():
            p_df = pd.read_csv(process_file)
            p_sub = p_df.loc[p_df["TN"].astype(int).isin(trts)].copy()
            for var in ["LAID", "LWAD", "SWAD", "CHTD"]:
                obs = pd.to_numeric(p_sub[f"OBS_{var}"], errors="coerce").to_numpy(float)
                sim = pd.to_numeric(p_sub[f"SIM_{var}"], errors="coerce").to_numpy(float)
                valid = ~np.isnan(obs) & ~np.isnan(sim) & (obs != -99) & (sim != -99)
                if valid.sum() > 0:
                    o = obs[valid]
                    s = sim[valid]
                    e = s - o
                    sst = float(np.square(o - o.mean()).sum())
                    nse = float(1 - np.square(e).sum() / sst) if sst > 0 else np.nan
                    rmse = float(np.sqrt(np.square(e).mean()))
                    rrmse = float(100 * rmse / np.abs(o).mean()) if np.abs(o).mean() > 0 else np.nan
                    bias = float(e.mean())
                    summary_metrics.append({
                        "season": season, "variable": var, "scope": "calibration_trts",
                        "nse": nse, "rmse": rmse, "rrmse_pct": rrmse, "bias": bias, "n": int(valid.sum())
                    })

    metrics_df = pd.DataFrame(summary_metrics)
    print("\n=== Deterministic Metrics Summary ===")
    print(metrics_df.to_string(index=False))

    # Print 26SP Harvest Sequence & End-of-season LAI
    print("\n=== 26SP End of Season LAI Check ===")
    p26_file = DET_DIR / "_seasons/26SP/26SP_deterministic_process_compare.csv"
    if p26_file.exists():
        p26 = pd.read_csv(p26_file)
        end_p26 = p26[p26["DAP"] > 100]
        print(end_p26[["TN", "DAP", "OBS_LAID", "SIM_LAID"]].groupby("TN").last())

    print("\n=== 26SP Harvest Sequence Compare ===")
    h26_file = DET_DIR / "_seasons/26SP/26SP_deterministic_harvest_compare.csv"
    if h26_file.exists():
        h26 = pd.read_csv(h26_file)
        h26_sub = h26.loc[h26["TN"].isin([2, 11, 3, 12])]
        print(h26_sub[["TN", "HNO", "DATE", "OBS_DRY_CUM", "SIM_DRY_CUM", "OBS_DRY_INC", "SIM_DRY_INC"]])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
