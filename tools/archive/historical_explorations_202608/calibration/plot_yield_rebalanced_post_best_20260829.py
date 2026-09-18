"""Replay and plot the diagnostic best member of the 2026-08-29 formal run.

All 10 treatments from 25SP and all 12 treatments from 26SP are replayed with
official DSSAT.  The figures are deterministic diagnostics and deliberately do
not draw posterior uncertainty intervals.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation


RUN_NAME = "e02_formal_yield_rebalanced_post_official_200x6_20260829"
CASE = "e02_formal_yield_rebalanced_post_200x6_20260829"


def main() -> int:
    run_dir = ROOT / "workspace/runs" / RUN_NAME
    selection = json.loads(
        (run_dir / "candidate_audit_20260829/candidate_selection.json").read_text(encoding="utf-8")
    )
    source_iteration = int(selection["selected_iteration"])
    best_member = str(selection["selected_member"])
    best_phi = float(selection["selected_phi"])
    det_root = run_dir / f"best_member_{best_member}_two_season_deterministic_20260829"
    out_root = ROOT / "figture" / (
        f"e02_formal_yield_rebalanced_post_best{best_member}_two_season_full_20260829"
    )

    evaluation.RUN_DIR = run_dir
    evaluation.DET_ROOT = det_root
    evaluation.OUT_ROOT = out_root
    evaluation.FIGURE = ROOT / "figture"
    evaluation.CASE = CASE
    evaluation.BEST_MEMBER = best_member
    evaluation.SOURCE_ITERATION = source_iteration
    evaluation.BEST_PHI = best_phi
    evaluation.CALIBRATION_STATE = "completed_engineering_validated_science_gate_failed"
    evaluation.ARTIFACT_TYPE = "two_season_deterministic_diagnostics_yield_rebalanced_20260829"
    evaluation.SPE = ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    evaluation.HARVEST_OBJECTIVE = (
        "measured dry increments plus seasonal terminal-yield RRMSE "
        "(lambda=250/season; 25% threshold enforced after calibration)"
    )
    evaluation.SOIL_INJECTION_DESCRIPTION = (
        "enabled: SLPF and audited soil properties allowed only within narrow measured-value bounds"
    )
    evaluation.DSSAT_VERSION_DESCRIPTION = "official DSSAT v4.8 (DSCSM048.EXE)"
    evaluation.SOIL_PARAMETER_STATUS = (
        "calibrated only within narrow measured-value bounds; not globally fixed"
    )
    evaluation.BUNDLE_NOTE = (
        "corrected formal Arm-A/B bundles; 26SP uses measured sequential SH2O and corrected SNH4/SNO3"
    )
    evaluation.OBS_REGISTRY = run_dir / f"{CASE}_observation_registry.csv"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.PLOT_MAPPING_CSV = (
        ROOT / "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv"
    )
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
