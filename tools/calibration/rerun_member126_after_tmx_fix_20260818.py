"""Replay formal member 126 on the current 25SP/25FA/26SP TMX bundles."""
from __future__ import annotations

import os
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation
from src.calibration.nitrogen_response import derive_filex_water_n_mapping


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
    evaluation.ARTIFACT_TYPE = "member126_three_season_full_diagnostics_20260818"
    evaluation.OBS_REGISTRY = RUN_DIR / f"{CASE}_observation_registry.csv"
    evaluation.OUT_ROOT = ROOT / "figture/member126_two_season_full_20260817"
    evaluation.DET_ROOT = RUN_DIR / "deterministic_candidates/phi_q10_highest_nse_three_season_20260818"
    evaluation.SEASONS = [
        {
            "season_id": "25SP", "excode": "XXQL2501",
            "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
            "bundle": ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
        },
        {
            "season_id": "25FA", "excode": "XXQL2502",
            "treatments": list(range(1, 13)),
            "bundle": ROOT / "data/user/experiments/xxql2502_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        },
        {
            "season_id": "26SP", "excode": "XXQL2601",
            "treatments": list(range(1, 13)),
            "bundle": ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        },
    ]
    evaluation.SEASON_IDS = [item["season_id"] for item in evaluation.SEASONS]
    evaluation.COLORS = {"25SP": "#2878B5", "25FA": "#D95F02", "26SP": "#2A9D55"}
    # The isolated calibration runner accepts an explicit executable.  Avoid
    # swapping shared workspace/template files because calibration jobs may be
    # running concurrently in their own agent sandboxes.
    os.environ["DSSAT_CUSTOM_EXE"] = str(evaluation.EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(evaluation.SPE.resolve())
    evaluation._swap = lambda: []
    evaluation._restore = lambda replacements: None
    evaluation.DET_ROOT.mkdir(parents=True, exist_ok=True)
    mapping_csv = evaluation.DET_ROOT / "three_season_water_n_mapping_from_filex.csv"
    mappings = []
    for season in evaluation.SEASONS:
        mappings.append(derive_filex_water_n_mapping(
            season["bundle"] / f"{season['excode']}.TMX",
            season_id=season["season_id"],
            treatments=season["treatments"],
        ))
    pd.concat(mappings, ignore_index=True).to_csv(mapping_csv, index=False, encoding="utf-8-sig")
    evaluation.PLOT_MAPPING_CSV = mapping_csv
    evaluation.EXTRA_LIMITATIONS = [
        "Deterministic replay uses the 20260818 canonical TMX INITIAL CONDITIONS fixed-width repair (2/6/6/6/6).",
        "The 26SP treatment-12 five-layer SH2O/SNH4/SNO3 profile uses the user-specified 20260818 values.",
        "25FA is an external-season diagnostic because the member-126 calibration objective used 25SP and 26SP only.",
        "Water and nitrogen treatment identities are derived from each current FileX rather than inferred from treatment numbers.",
    ]
    rc = int(evaluation.main() or 0)
    if rc:
        return rc
    # Keep the user-facing diagnostics directory self-contained.  The shared
    # evaluator writes metric tables beside deterministic outputs, while this
    # directory may still contain two-season tables from an earlier render.
    for name in ("metrics_by_season_variable.csv", "organ_n_compare.csv"):
        shutil.copy2(evaluation.DET_ROOT / name, evaluation.OUT_ROOT / name)
    manifest_path = evaluation.OUT_ROOT / "diagnostic_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["metrics_csv"] = str((evaluation.OUT_ROOT / "metrics_by_season_variable.csv").resolve())
    manifest["organ_n_pairs_csv"] = str((evaluation.OUT_ROOT / "organ_n_compare.csv").resolve())
    manifest["bundle_note"] = "current actual_trial bundles: v8 25SP / v7 25FA / v7 26SP"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
