"""Replay formal member 126 with the repaired source TMX bundles."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation


CASE = "e02_fixedsoil_nse_official_25sp26sp_200x6_20260817"
RUN_DIR = ROOT / "workspace/runs" / CASE


def main() -> int:
    evaluation.CASE = CASE
    evaluation.RUN_DIR = RUN_DIR
    evaluation.BEST_MEMBER = "126"
    evaluation.SOURCE_ITERATION = 6
    evaluation.BEST_PHI = 557.466
    evaluation.CALIBRATION_STATE = "engineering_validated"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.PLOT_MAPPING_CSV = ROOT / "configs/runs/e02_v2_25sp26sp_water_n_mapping_20260808.csv"
    evaluation.ARTIFACT_TYPE = "member126_two_season_full_diagnostics_26sp_t12_ic_20260818"
    evaluation.OBS_REGISTRY = RUN_DIR / f"{CASE}_observation_registry.csv"
    evaluation.OUT_ROOT = ROOT / "figture/member126_two_season_full_20260817"
    evaluation.DET_ROOT = RUN_DIR / "deterministic_candidates/phi_q10_highest_nse_26sp_t12_ic_20260818"
    evaluation.SEASONS = [
        {
            "season_id": "25SP", "excode": "XXQL2501",
            "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
            "bundle": ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
        },
        {
            "season_id": "26SP", "excode": "XXQL2601",
            "treatments": list(range(1, 13)),
            "bundle": ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        },
    ]
    evaluation.SEASON_IDS = [item["season_id"] for item in evaluation.SEASONS]
    evaluation.EXTRA_LIMITATIONS = [
        "Deterministic replay uses the 20260818 canonical TMX INITIAL CONDITIONS fixed-width repair (2/6/6/6/6).",
        "The 26SP treatment-12 five-layer SH2O/SNH4/SNO3 profile uses the user-specified 20260818 values.",
    ]
    return int(evaluation.main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
