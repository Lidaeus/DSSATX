"""Replay the selected-eight-treatment IES best member on all three seasons."""
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

CASE = "e02_selected8_fixedsoil_nse_official_200x6_20260818"
RUN_DIR = ROOT / "workspace/runs" / CASE
BEST_MEMBER = "192"
BEST_PHI = 507.504


def main() -> int:
    evaluation.CASE = CASE
    evaluation.RUN_DIR = RUN_DIR
    evaluation.BEST_MEMBER = BEST_MEMBER
    evaluation.SOURCE_ITERATION = 6
    evaluation.BEST_PHI = BEST_PHI
    evaluation.CALIBRATION_STATE = "engineering_validated"
    evaluation.ARTIFACT_TYPE = "selected8_best192_three_season_full_diagnostics_20260818"
    evaluation.HARVEST_OBJECTIVE = "raw cumulative dry mass; per-season phi = 75*(1-NSE)"
    evaluation.SOIL_INJECTION_DESCRIPTION = "enabled for writing fixed, user-approved soil values; no soil parameter was adjustable"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.OBS_REGISTRY = RUN_DIR / f"{CASE}_observation_registry.csv"
    evaluation.OUT_ROOT = ROOT / "figture/e02_selected8_best192_three_season_full_20260818"
    evaluation.DET_ROOT = RUN_DIR / "deterministic_candidates/best_phi_member192_three_season_20260818"
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
    os.environ["DSSAT_CUSTOM_EXE"] = str(evaluation.EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(evaluation.SPE.resolve())
    evaluation._swap = lambda: []
    evaluation._restore = lambda replacements: None
    evaluation.DET_ROOT.mkdir(parents=True, exist_ok=True)

    mapping_csv = evaluation.DET_ROOT / "three_season_water_n_mapping_from_filex.csv"
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
        "25SP and 26SP calibration used only the four declared N3/N0 factorial-corner treatments; all other plotted treatments are out-of-objective diagnostics.",
        "25FA was not used by the calibration objective and is an external-season validation diagnostic.",
        "Water and nitrogen identities are derived from each current FileX; treatment numbers are not used to infer management levels.",
        "Python run diagnostics only; these files are not publication Fig/FigS artifacts.",
    ]
    rc = int(evaluation.main() or 0)
    if rc:
        return rc
    for name in ("metrics_by_season_variable.csv", "organ_n_compare.csv"):
        source = evaluation.DET_ROOT / name
        if source.is_file():
            shutil.copy2(source, evaluation.OUT_ROOT / name)

    process_path = evaluation.DET_ROOT / "_seasons/25FA/25FA_deterministic_process_compare.csv"
    process = pd.read_csv(process_path)
    audit_columns = [
        name for name in
        ("RUN", "TN", "DATE", "SIM_DATE", "SIM_DATE_GAP_DAYS")
        if name in process.columns
    ]
    alignment_audit = process.loc[:, audit_columns].drop_duplicates().sort_values(["TN", "DATE"])
    audit_path = evaluation.OUT_ROOT / "25FA_cross_year_alignment_audit.csv"
    alignment_audit.to_csv(audit_path, index=False, encoding="utf-8-sig")
    final_rows = alignment_audit.loc[pd.to_numeric(alignment_audit["DATE"]) == 26010]
    if len(alignment_audit) != 36 or len(final_rows) != 12:
        raise RuntimeError(
            "25FA process-alignment audit failed: expected 36 treatment-date rows "
            f"and 12 DATE=26010 rows, got {len(alignment_audit)} and {len(final_rows)}"
        )
    if not (
        (pd.to_numeric(final_rows["SIM_DATE"]) == 26006).all()
        and (pd.to_numeric(final_rows["SIM_DATE_GAP_DAYS"]) == 4).all()
    ):
        raise RuntimeError("25FA DATE=26010 must use the explicit terminal-state fallback DATE=26006 (4 days)")

    manifest_path = evaluation.OUT_ROOT / "diagnostic_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["calibration_treatments"] = {
        "25SP": [2, 5, 10, 13], "26SP": [2, 11, 3, 12], "25FA": []
    }
    manifest["evaluation_treatments"] = {
        season["season_id"]: season["treatments"] for season in evaluation.SEASONS
    }
    manifest["metrics_csv"] = str((evaluation.OUT_ROOT / "metrics_by_season_variable.csv").resolve())
    manifest["organ_n_pairs_csv"] = str((evaluation.OUT_ROOT / "organ_n_compare.csv").resolve())
    manifest["cross_year_alignment"] = {
        "audit_csv": str(audit_path.resolve()),
        "process_observation_rows": int(len(alignment_audit)),
        "terminal_observation_date": 26010,
        "terminal_simulation_date": 26006,
        "terminal_gap_days": 4,
        "plot_rule": "plot the observation at its calendar-correct DAP without extending the simulation curve",
        "metric_rule": "use the nearest previous terminal simulated state and expose the match in SIM_DATE columns",
    }
    manifest["bundle_note"] = "current actual_trial bundles: v8 25SP / v7 25FA / v7 26SP"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
