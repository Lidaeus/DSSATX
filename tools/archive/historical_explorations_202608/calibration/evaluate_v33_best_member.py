#!/usr/bin/env python3
"""Run deterministic 22-treatment replay and evaluation for Formal Calibration v33 Best Member #100.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
evaluation = importlib.import_module("tools.calibration.evaluate_fixedsoil_official_best189_20260813")

RUN_ID = "e02_formal_v33_8treat_fresh_200x6_20260829"
CASE_NAME = "e02_formal_v33_fresh_20260829"
RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / RUN_ID

BEST_MEMBER = "100"
BEST_ITER = 5
BEST_PHI = 209.1530

det_root = RUN_DIR / f"best_member_{BEST_MEMBER}_two_season_deterministic_20260829"
out_root = PROJECT_ROOT / "figture" / f"e02_formal_v33_fresh_best{BEST_MEMBER}_20260829"

evaluation.RUN_DIR = RUN_DIR
evaluation.DET_ROOT = det_root
evaluation.OUT_ROOT = out_root
evaluation.FIGURE = PROJECT_ROOT / "figture"
evaluation.CASE = CASE_NAME
evaluation.BEST_MEMBER = BEST_MEMBER
evaluation.SOURCE_ITERATION = BEST_ITER
evaluation.BEST_PHI = BEST_PHI
evaluation.CALIBRATION_STATE = "completed_engineering_validated"
evaluation.ARTIFACT_TYPE = "formal_v33_fresh_deterministic"
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
    "best_member": BEST_MEMBER,
    "best_iteration": BEST_ITER,
    "best_phi": BEST_PHI,
}

for season in ["25SP", "26SP"]:
    met_file = det_root / f"_seasons/{season}/metrics_summary.csv"
    if met_file.exists():
        df_m = pd.read_csv(met_file)
        for var in ["LAID", "CWAD", "SWAD", "LWAD", "FRESH_CUM", "DRY_CUM"]:
            row = df_m[df_m["variable"] == var]
            if not row.empty:
                metrics_summary[f"{season}_{var}_rmse"] = float(row["rmse"].iloc[0])
                metrics_summary[f"{season}_{var}_rrmse_pct"] = float(row["rrmse_pct"].iloc[0])
                metrics_summary[f"{season}_{var}_d"] = float(row["d_index"].iloc[0])
                metrics_summary[f"{season}_{var}_nse"] = float(row["nse"].iloc[0])

print("\n=======================================================")
print("      FORMAL CALIBRATION V33 METRICS SUMMARY           ")
print("=======================================================")
for k, v in metrics_summary.items():
    if isinstance(v, float):
        print(f"{k:35s}: {v:10.4f}")
    else:
        print(f"{k:35s}: {v}")

out_csv = PROJECT_ROOT / "workspace" / "reports" / "e02_formal_v33_scorecard.csv"
out_csv.parent.mkdir(parents=True, exist_ok=True)
pd.DataFrame([metrics_summary]).to_csv(out_csv, index=False)
print(f"\n[REPORT] Scorecard written to {out_csv}")
