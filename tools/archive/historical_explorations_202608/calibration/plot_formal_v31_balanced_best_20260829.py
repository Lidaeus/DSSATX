"""Replay the lowest-Phi member of the v31 balanced formal run on all 22 treatments."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation
from src.calibration.nitrogen_response import derive_filex_water_n_mapping


RUN_NAME = "e02_formal_v31_balanced_official_200x6_20260829"
CASE = "e02_formal_v31_balanced_200x6_20260829"


def lowest_phi_member(run_dir: Path) -> tuple[int, str, float]:
    phi = pd.read_csv(run_dir / f"{CASE}.phi.actual.csv", index_col=0)
    member_columns = [column for column in phi.columns if str(column).isdigit()]
    candidates: list[tuple[float, int, str]] = []
    for iteration in phi.index:
        values = pd.to_numeric(phi.loc[iteration, member_columns], errors="coerce")
        for member, value in values.items():
            if pd.notna(value):
                candidates.append((float(value), int(iteration), str(member)))
    if not candidates:
        raise ValueError("No finite realization-level actual Phi values found")
    value, iteration, member = min(candidates)
    if not (run_dir / f"{CASE}.{iteration}.par.csv").is_file():
        raise FileNotFoundError(run_dir / f"{CASE}.{iteration}.par.csv")
    return iteration, member, value


def main() -> int:
    run_dir = ROOT / "workspace/runs" / RUN_NAME
    source_iteration, best_member, best_phi = lowest_phi_member(run_dir)
    det_root = run_dir / f"best_member_{best_member}_two_season_deterministic_20260829"
    out_root = ROOT / "figture" / f"e02_formal_v31_balanced_best{best_member}_two_season_full_20260829"

    evaluation.RUN_DIR = run_dir
    evaluation.DET_ROOT = det_root
    evaluation.OUT_ROOT = out_root
    evaluation.FIGURE = ROOT / "figture"
    evaluation.CASE = CASE
    evaluation.BEST_MEMBER = best_member
    evaluation.SOURCE_ITERATION = source_iteration
    evaluation.BEST_PHI = best_phi
    evaluation.CALIBRATION_STATE = "completed_engineering_validated"
    evaluation.ARTIFACT_TYPE = "two_season_diagnostics_formal_v31_balanced_20260829"
    evaluation.SPE = ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    evaluation.HARVEST_OBJECTIVE = (
        "measured dry increments plus seasonal terminal-yield RRMSE (lambda=35/season, budget boosted to 4.0)"
    )
    evaluation.SOIL_INJECTION_DESCRIPTION = (
        "enabled: SLPF (0.88-0.96) plus SBDM/SLLL/SDUL/SSAT in layers 1-6 calibrated within narrow audited bounds"
    )
    evaluation.OBS_REGISTRY = run_dir / f"{CASE}_observation_registry.csv"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.SEASONS = [
        {
            "season_id": "25SP",
            "excode": "XXQL2501",
            "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
            "bundle": ROOT / "data/user/experiments/xxql2501_formal_armab_rrmse_20260828",
        },
        {
            "season_id": "26SP",
            "excode": "XXQL2601",
            "treatments": list(range(1, 13)),
            "bundle": ROOT / "data/user/experiments/xxql2601_formal_armab_rrmse_26spncal_20260828",
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
    return evaluation.main()


if __name__ == "__main__":
    raise SystemExit(main())
