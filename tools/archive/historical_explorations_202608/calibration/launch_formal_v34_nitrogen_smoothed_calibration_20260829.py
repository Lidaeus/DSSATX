#!/usr/bin/env python3
"""Master execution script for Formal Calibration v34 with Smoothed Nitrogen Stress.

Features:
1. 8 Calibration Treatments (4 in 25SP: TN2, TN5, TN10, TN13; 4 in 26SP: TN1, TN3, TN9, TN12).
   14 Independent Validation Treatments (6 in 25SP: TN3, TN4, TN9, TN11, TN12, TN14; 8 in 26SP: TN2, TN4, TN5, TN6, TN7, TN8, TN10, TN11).
2. Broadened Organ Protein Bounds (PROLFF/PROSTF/PRORTF, PROLFG/PROSTG/PRORTG, PROLFI/PROSTI/PRORTI).
3. Enhanced N Mobilization Buffer (NMOBMX, NVSMOB, NRCVR).
4. Smoothed Leaf N - Photosynthesis Curve & Relaxed Expansion Sensitivity (FNPGN1, FNPGN2, LNREF, NSLOPE, NSTFAC).
5. Root N Uptake & Translocation (RTNO3, RTNH4, RTEXF, NREXP, NRMIN).
6. Photosynthesis Efficiency & Physiological Pool (PGEFF, FINREF, LNGSH, SIZLF, CMOBMX, SFDUR, WTFSD, PORPT, LFMAX, PHTMAX).
7. Harvest Objective: Fresh Weight (CHFPW / HFPOW).
8. 200 Realizations x 6 Iterations executed with 6 sandboxed parallel agents on port 4080.
9. Post-calibration deterministic evaluation across all 22 field treatments with pure deterministic plotting (zero uncertainty ribbons).
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYTHON_EXE = sys.executable

sys.path.insert(0, str(PROJECT_ROOT))
evaluation = importlib.import_module("tools.calibration.evaluate_fixedsoil_official_best189_20260813")

DESIGN_JSON = PROJECT_ROOT / "configs" / "runs" / "e02_formal_v34_nitrogen_smoothed_200x6_20260829.json"
RUN_ID = "e02_formal_v34_nitrogen_smoothed_200x6_20260829"
CASE_NAME = "e02_formal_v34_n_smooth_20260829"
BOUNDS_ID = "eggplant_e02_v34_formal_nitrogen_smoothed_bounds"
RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / RUN_ID
PORT = 4080
N_AGENTS = 6


def run_cmd(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(str(x) for x in cmd))
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    res = subprocess.run(cmd, cwd=cwd or PROJECT_ROOT, env=env, check=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {res.returncode}")


def build_formal_run() -> None:
    print(f"\n[BUILD] Building PEST setup for Formal Calibration v34 (Smoothed Nitrogen Response)...")
    if RUN_DIR.exists():
        print(f"Cleaning existing run dir: {RUN_DIR}")
        shutil.rmtree(RUN_DIR, ignore_errors=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        PYTHON_EXE,
        str(PROJECT_ROOT / "src" / "calibration" / "build_pest.py"),
        "--mode", "eggplant_stage2",
        "--prefix", CASE_NAME,
        "--bounds-id", BOUNDS_ID,
        "--bounds-crop", "eggplant",
        "--multiseason-design", str(DESIGN_JSON),
        "--noptmax", "6",
        "--ies-num-reals", "200",
        "--batch", "DSSBatch.v48",
        "--harvest-var", "CHFPW",
        "--param-review-mode", "off",
        "--out-dir", str(RUN_DIR),
    ]
    run_cmd(cmd)
    print(f"[BUILD] Built successfully at {RUN_ID}")


def execute_parallel_calibration() -> None:
    print(f"\n[RUN] Launching PEST++ IES on port {PORT} with {N_AGENTS} agents...")
    cmd = [
        PYTHON_EXE,
        str(PROJECT_ROOT / "tools" / "parallel" / "run_parallel.py"),
        "--run-dir", str(RUN_DIR),
        "--case", CASE_NAME,
        "--mode", "ies",
        "--n-agents", str(N_AGENTS),
        "--port", str(PORT),
        "--wait",
    ]
    run_cmd(cmd)
    print(f"[RUN] Calibration finished successfully!")


def evaluate_formal_run() -> dict[str, Any]:
    print(f"\n[EVALUATE] Running 22-treatment deterministic replay for Formal Calibration v34...")
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
    out_root = PROJECT_ROOT / "figture" / f"e02_formal_v34_fresh_best{best_member}_20260829"

    evaluation.RUN_DIR = RUN_DIR
    evaluation.DET_ROOT = det_root
    evaluation.OUT_ROOT = out_root
    evaluation.FIGURE = PROJECT_ROOT / "figture"
    evaluation.CASE = CASE_NAME
    evaluation.BEST_MEMBER = best_member
    evaluation.SOURCE_ITERATION = best_iter
    evaluation.BEST_PHI = best_phi
    evaluation.CALIBRATION_STATE = "completed_engineering_validated"
    evaluation.ARTIFACT_TYPE = "formal_v34_fresh_deterministic"
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

    metrics_csv = det_root / "metrics_by_season_variable.csv"
    if metrics_csv.exists():
        df_m = pd.read_csv(metrics_csv)
        for _, r in df_m.iterrows():
            s = r["season"]
            v = r["variable"]
            metrics_summary[f"{s}_{v}_r2"] = float(r.get("r2", 0))
            metrics_summary[f"{s}_{v}_d"] = float(r.get("d_index", 0))
            metrics_summary[f"{s}_{v}_nse"] = float(r.get("nse", 0))
            metrics_summary[f"{s}_{v}_rrmse_pct"] = float(r.get("rrmse_pct", 0))

    print("\n=======================================================")
    print("      FORMAL CALIBRATION V34 METRICS SUMMARY           ")
    print("=======================================================")
    for k, v in metrics_summary.items():
        if isinstance(v, float):
            print(f"{k:35s}: {v:10.4f}")
        else:
            print(f"{k:35s}: {v}")

    out_csv = PROJECT_ROOT / "workspace" / "reports" / "e02_formal_v34_scorecard.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([metrics_summary]).to_csv(out_csv, index=False)
    print(f"\n[REPORT] Scorecard written to {out_csv}")
    return metrics_summary


def main() -> None:
    build_formal_run()
    execute_parallel_calibration()
    evaluate_formal_run()


if __name__ == "__main__":
    main()
