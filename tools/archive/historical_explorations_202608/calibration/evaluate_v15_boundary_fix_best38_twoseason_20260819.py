"""Replay v15 boundary-fix member 38 and render two-season diagnostics."""
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

CASE = "e02_v15_boundary_fix_official_200x6_20260819"
RUN_DIR = ROOT / "workspace/runs" / CASE
BEST_MEMBER = "38"
BEST_PHI = 643.149


def main() -> int:
    evaluation.CASE = CASE
    evaluation.RUN_DIR = RUN_DIR
    evaluation.BEST_MEMBER = BEST_MEMBER
    evaluation.SOURCE_ITERATION = 6
    evaluation.BEST_PHI = BEST_PHI
    evaluation.CALIBRATION_STATE = "engineering_validated"
    evaluation.ARTIFACT_TYPE = "v15_boundary_fix_best38_two_season_diagnostics_20260819"
    evaluation.HARVEST_OBJECTIVE = "raw cumulative dry mass; per-season phi = 75*(1-NSE); W_RESPONSE NSE lambda=1/season"
    evaluation.SOIL_INJECTION_DESCRIPTION = "fixed corrected soil and initial conditions; no soil/IC parameter adjustable"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.OBS_REGISTRY = RUN_DIR / f"{CASE}_observation_registry.csv"
    evaluation.OUT_ROOT = ROOT / "figture/e02_v15_boundary_fix_best38_two_season_full_20260819"
    evaluation.DET_ROOT = RUN_DIR / "deterministic_candidates/best_phi_member38_two_season_20260819"
    evaluation.SEASONS = [
        {
            "season_id": "25SP", "excode": "XXQL2501",
            "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
            "bundle": ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v2_20260819",
        },
        {
            "season_id": "26SP", "excode": "XXQL2601",
            "treatments": list(range(1, 13)),
            "bundle": ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v2_20260819",
        },
    ]
    evaluation.SEASON_IDS = [item["season_id"] for item in evaluation.SEASONS]
    evaluation.COLORS = {"25SP": "#2878B5", "26SP": "#2A9D55"}
    os.environ["DSSAT_CUSTOM_EXE"] = str(evaluation.EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(evaluation.SPE.resolve())
    evaluation._swap = lambda: []
    evaluation._restore = lambda replacements: None
    evaluation.DET_ROOT.mkdir(parents=True, exist_ok=True)

    mapping_csv = evaluation.DET_ROOT / "two_season_water_n_mapping_from_filex.csv"
    mappings = [
        derive_filex_water_n_mapping(
            season["bundle"] / f"{season['excode']}.TMX",
            season_id=season["season_id"], treatments=season["treatments"],
        )
        for season in evaluation.SEASONS
    ]
    pd.concat(mappings, ignore_index=True).to_csv(mapping_csv, index=False, encoding="utf-8-sig")
    evaluation.PLOT_MAPPING_CSV = mapping_csv
    evaluation.EXTRA_LIMITATIONS = [
        "Calibration used 25SP TN 2/5/10/13 and 26SP TN 2/11/3/12 only; other treatments are out-of-objective diagnostics.",
        "Both spring seasons use harvest-date matched measured fruit dry-matter fractions from corrected bundles.",
        "Water and nitrogen identities are read from current FileX management data, not inferred from treatment numbers.",
        "Python run diagnostics only; these files are not publication Fig/FigS artifacts.",
    ]
    rc = int(evaluation.main() or 0)
    if rc:
        return rc
    for name in ("metrics_by_season_variable.csv", "organ_n_compare.csv"):
        source = evaluation.DET_ROOT / name
        if source.is_file():
            shutil.copy2(source, evaluation.OUT_ROOT / name)
    manifest_path = evaluation.OUT_ROOT / "diagnostic_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["calibration_treatments"] = {
        "25SP": [2, 5, 10, 13], "26SP": [2, 11, 3, 12]
    }
    manifest["evaluation_treatments"] = {
        season["season_id"]: season["treatments"] for season in evaluation.SEASONS
    }
    manifest["bundle_note"] = "corrected repfilter_measuredmoisture_v2 bundles for 25SP and 26SP"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
