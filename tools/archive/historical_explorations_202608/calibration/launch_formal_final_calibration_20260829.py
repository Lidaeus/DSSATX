#!/usr/bin/env python3
"""Master execution script for Final Formal Calibration (200 realizations x 6 iterations).

Champion architecture synthesized from Multi-Arm Exploration (Sink Duration & Remobilization + Nitrogen Resilience).
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYTHON_EXE = sys.executable

# Load evaluation module dynamically
sys.path.insert(0, str(PROJECT_ROOT))
evaluation = importlib.import_module("tools.calibration.evaluate_fixedsoil_official_best189_20260813")

DESIGN_JSON = PROJECT_ROOT / "configs" / "runs" / "e02_formal_final_champion_200x6_20260829.json"
RUN_ID = "e02_formal_final_champion_200x6_20260829"
CASE_NAME = "e02_formal_final_champion_20260829"
RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / RUN_ID
PORT = 4060
N_AGENTS = 6


def run_cmd(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(str(x) for x in cmd))
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    res = subprocess.run(cmd, cwd=cwd or PROJECT_ROOT, env=env, check=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {res.returncode}")


def evaluate_formal_run() -> dict[str, Any]:
    print(f"\n[EVALUATE] Running 22-treatment deterministic replay for Final Formal Calibration...")
    phi_csv = RUN_DIR / f"{CASE_NAME}.phi.actual.csv"
    if not phi_csv.is_file():
        raise FileNotFoundError(f"Phi file not found: {phi_csv}")

    phi_df = pd.read_csv(phi_csv, index_col=0)
    member_cols = [c for c in phi_df.columns if str(c).isdigit()]
    candidates = []
    for iteration in phi_df.index:
        values = pd.to_numeric(phi_df.loc[iteration, member_cols], errors="coerce")
        for member, val in values.items():
            if pd.notna(val):
                candidates.append((float(val), int(iteration), str(member)))
    if not candidates:
        raise RuntimeError("No valid candidate realization found in phi.actual.csv")

    best_phi, best_iter, best_member = min(candidates)
    print(f"[EVALUATE] Found global best member: #{best_member} (iteration={best_iter}, phi={best_phi:.4f})")

    det_root = RUN_DIR / f"best_member_{best_member}_two_season_deterministic_20260829"
    out_root = PROJECT_ROOT / "figture" / f"e02_formal_final_champion_best{best_member}_20260829"

    evaluation.RUN_DIR = RUN_DIR
    evaluation.DET_ROOT = det_root
    evaluation.OUT_ROOT = out_root
    evaluation.FIGURE = PROJECT_ROOT / "figture"
    evaluation.CASE = CASE_NAME
    evaluation.BEST_MEMBER = best_member
    evaluation.SOURCE_ITERATION = best_iter
    evaluation.BEST_PHI = best_phi
    evaluation.CALIBRATION_STATE = "completed_engineering_validated"
    evaluation.ARTIFACT_TYPE = "formal_final_champion_deterministic"
    evaluation.SPE = PROJECT_ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    evaluation.OBS_REGISTRY = RUN_DIR / f"{CASE_NAME}_observation_registry.csv"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.SEASONS = [
        {
            "season_id": "25SP",
            "excode": "XXQL2501",
            "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
            "bundle": PROJECT_ROOT / "data/user/experiments/xxql2501_formal_armab_rrmse_20260828",
        },
        {
            "season_id": "26SP",
            "excode": "XXQL2601",
            "treatments": list(range(1, 13)),
            "bundle": PROJECT_ROOT / "data/user/experiments/xxql2601_formal_armab_rrmse_26spncal_20260828",
        },
    ]
    evaluation.CALIBRATION_TREATMENTS = {
        "25SP": [2, 5, 10, 13],
        "26SP": [1, 3, 9, 12],
    }
    evaluation.DIAGNOSTIC_TREATMENTS = {
        "25SP": [3, 4, 9, 11, 12, 14],
        "26SP": [2, 4, 5, 6, 7, 8, 10, 11],
    }

    evaluation.main()

    # Extract score metrics
    metrics_summary: dict[str, Any] = {
        "run_id": RUN_ID,
        "best_member": best_member,
        "best_iteration": best_iter,
        "best_phi": best_phi,
    }

    # Harvest metrics
    h26_file = det_root / "_seasons/26SP/26SP_deterministic_harvest_compare.csv"
    if h26_file.exists():
        df_h26 = pd.read_csv(h26_file)
        h3_sub = df_h26[df_h26["HNO"] == 3]
        if not h3_sub.empty:
            metrics_summary["26SP_H3_sim_inc"] = float(h3_sub["SIM_DRY_INC"].mean())
            metrics_summary["26SP_H3_gap"] = float((h3_sub["SIM_DRY_INC"] - h3_sub["OBS_DRY_INC"]).mean())

        h5_sub = df_h26.sort_values(by=["TN", "HNO"]).groupby("TN").last().reset_index()
        y = h5_sub["OBS_DRY_CUM"].to_numpy(float)
        p = h5_sub["SIM_DRY_CUM"].to_numpy(float)
        err = p - y
        rmse = float(np.sqrt(np.mean(err**2)))
        rrmse = float(100 * rmse / np.mean(y)) if np.mean(y) > 0 else np.nan
        metrics_summary["26SP_term_dry_rrmse_pct"] = rrmse
        metrics_summary["26SP_term_dry_bias"] = float(np.mean(err))

        n0_sub = h5_sub[h5_sub["TN"].isin([9, 11, 12])]
        n1_sub = h5_sub[h5_sub["TN"].isin([7, 8, 10])]
        n3_sub = h5_sub[h5_sub["TN"].isin([1, 2, 3])]
        if not n0_sub.empty:
            metrics_summary["26SP_N0_sim_mean"] = float(n0_sub["SIM_DRY_CUM"].mean())
            metrics_summary["26SP_N0_bias_pct"] = float(((n0_sub["SIM_DRY_CUM"] - n0_sub["OBS_DRY_CUM"]) / n0_sub["OBS_DRY_CUM"] * 100).mean())
        if not n1_sub.empty:
            metrics_summary["26SP_N1_sim_mean"] = float(n1_sub["SIM_DRY_CUM"].mean())
        if not n3_sub.empty:
            metrics_summary["26SP_N3_sim_mean"] = float(n3_sub["SIM_DRY_CUM"].mean())

    h25_file = det_root / "_seasons/25SP/25SP_deterministic_harvest_compare.csv"
    if h25_file.exists():
        df_h25 = pd.read_csv(h25_file)
        h_end25 = df_h25.sort_values(by=["TN", "HNO"]).groupby("TN").last().reset_index()
        y25 = h_end25["OBS_DRY_CUM"].to_numpy(float)
        p25 = h_end25["SIM_DRY_CUM"].to_numpy(float)
        err25 = p25 - y25
        rmse25 = float(np.sqrt(np.mean(err25**2)))
        rrmse25 = float(100 * rmse25 / np.mean(y25)) if np.mean(y25) > 0 else np.nan
        metrics_summary["25SP_term_dry_rrmse_pct"] = rrmse25
        metrics_summary["25SP_term_dry_bias"] = float(np.mean(err25))

    # Time series metrics
    for season in ["25SP", "26SP"]:
        met_file = det_root / f"_seasons/{season}/metrics_summary.csv"
        if met_file.exists():
            df_m = pd.read_csv(met_file)
            for var in ["LAID", "CWAD", "SWAD", "LWAD"]:
                row = df_m[df_m["variable"] == var]
                if not row.empty:
                    metrics_summary[f"{season}_{var}_rmse"] = float(row["rmse"].iloc[0])
                    metrics_summary[f"{season}_{var}_rrmse_pct"] = float(row["rrmse_pct"].iloc[0])
                    metrics_summary[f"{season}_{var}_d"] = float(row["d_index"].iloc[0])
                    metrics_summary[f"{season}_{var}_nse"] = float(row["nse"].iloc[0])

    print("\n=======================================================")
    print("      FINAL FORMAL CALIBRATION METRICS SUMMARY         ")
    print("=======================================================")
    for k, v in metrics_summary.items():
        if isinstance(v, float):
            print(f"{k:35s}: {v:10.4f}")
        else:
            print(f"{k:35s}: {v}")

    # Save summary
    out_csv = PROJECT_ROOT / "workspace" / "reports" / "e02_formal_final_champion_scorecard.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([metrics_summary]).to_csv(out_csv, index=False)
    print(f"\n[REPORT] Scorecard written to {out_csv}")
    return metrics_summary


def main() -> None:
    evaluate_formal_run()


if __name__ == "__main__":
    main()
