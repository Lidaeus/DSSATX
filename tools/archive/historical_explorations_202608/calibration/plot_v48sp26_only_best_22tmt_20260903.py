"""Replay the 26SP-only best member on all 22 treatments and render the full
deterministic fit-capability suite (no posterior/ensemble figures).

Best member = minimum realization-level actual Phi across iterations of the
26SP-only run ``e02_formal_v48_26sp_only_200x4_20260903_r1``.  The 25SP season
is replayed as a cross-season check; its three season-scoped parameters
(PAGE_25SP/PENV_25SP/ICNS_25SP) were not calibrated in the 26SP-only run and
are supplemented at their v48 frozen prior init values.
"""
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

RUN_NAME = "e02_formal_v48_26sp_only_200x4_20260903_r1"
CASE = "e02_formal_v48_26sp_only_200x4_20260903"
BASE_BOUNDS_V48 = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v48_n_gradient_water2x_formal_20260902.csv"
SUPPLEMENT_25SP = {"PAGE_25SP", "PENV_25SP", "ICNS_25SP"}


def lowest_phi_member(run_dir: Path) -> tuple[int, str, float]:
    phi = pd.read_csv(run_dir / f"{CASE}.phi.actual.csv", index_col=0)
    member_columns = [c for c in phi.columns if str(c).isdigit()]
    candidates: list[tuple[float, int, str]] = []
    for iteration in phi.index:
        values = pd.to_numeric(phi.loc[iteration, member_columns], errors="coerce")
        for member, value in values.items():
            if pd.notna(value):
                candidates.append((float(value), int(iteration), str(member)))
    if not candidates:
        raise ValueError("No finite realization-level actual Phi values found")
    value, iteration, member = min(candidates)
    return iteration, member, value


def main() -> int:
    run_dir = ROOT / "workspace/runs" / RUN_NAME
    source_iteration, best_member, best_phi = lowest_phi_member(run_dir)
    det_root = run_dir / f"best_member_{best_member}_two_season_deterministic_20260903"
    out_root = ROOT / "figture" / f"e02_v48sp26_only_best{best_member}_22tmt_full_suite_20260903"

    evaluation.RUN_DIR = run_dir
    evaluation.DET_ROOT = det_root
    evaluation.OUT_ROOT = out_root
    evaluation.FIGURE = ROOT / "figture"
    evaluation.CASE = CASE
    evaluation.BEST_MEMBER = best_member
    evaluation.SOURCE_ITERATION = source_iteration
    evaluation.BEST_PHI = best_phi
    evaluation.CALIBRATION_STATE = "completed_engineering_validated"
    evaluation.ARTIFACT_TYPE = "two_season_diagnostics_v48sp26_only_best_20260903"
    evaluation.SPE = ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    evaluation.HARVEST_OBJECTIVE = (
        "v48 fresh increments + terminal season-RRMSE gate (lambda=750, threshold 25%); "
        "26SP-only calibration (25SP replayed as cross-season check)"
    )
    evaluation.SOIL_INJECTION_DESCRIPTION = "per v48 frozen bounds (Scheme 4 soil layering where active)"
    evaluation.OBS_REGISTRY = run_dir / f"{CASE}_observation_registry.csv"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.SEASONS = [
        {
            "season_id": "25SP",
            "excode": "XXQL2501",
            "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
            "bundle": ROOT / "data/user/experiments/xxql2501_scheme4_double_n_20260831",
        },
        {
            "season_id": "26SP",
            "excode": "XXQL2601",
            "treatments": list(range(1, 13)),
            "bundle": ROOT / "workspace/reports/e02_v46_26sp_soil_n_scale_sweep_20260901/bundles_v2/s0p34",
        },
    ]
    evaluation.SEASON_IDS = [s["season_id"] for s in evaluation.SEASONS]
    evaluation.COLORS = {"25SP": "#2878B5", "26SP": "#2A9D55"}

    os.environ["DSSAT_CUSTOM_EXE"] = str(evaluation.EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(evaluation.SPE.resolve())
    existing_pp = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = str(ROOT) + (os.pathsep + existing_pp if existing_pp else "")
    evaluation._swap = lambda: []
    evaluation._restore = lambda replacements: None

    det_done = (det_root / "multiseason_run_status.json").is_file()
    if det_done:
        print("deterministic replay already present; rendering only")
    else:
        if det_root.exists():
            shutil.rmtree(det_root)
        det_root.mkdir(parents=True)
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    mappings = [
        derive_filex_water_n_mapping(
            season["bundle"] / f"{season['excode']}.TMX",
            season_id=season["season_id"],
            treatments=season["treatments"],
        )
        for season in evaluation.SEASONS
    ]
    mapping_csv = det_root / "two_season_water_n_mapping_from_filex.csv"
    pd.concat(mappings, ignore_index=True).to_csv(mapping_csv, index=False, encoding="utf-8-sig")
    evaluation.PLOT_MAPPING_CSV = mapping_csv
    evaluation.EXTRA_LIMITATIONS = [
        "Best member calibrated on 26SP data ONLY (117 active parameters); "
        "25SP replay is a cross-season check.",
        "25SP season-scoped parameters (PAGE_25SP/PENV_25SP/ICNS_25SP) were not "
        "calibrated in the 26SP-only run and sit at their v48 frozen prior init values.",
        "No posterior/ensemble figures: deterministic best-member suite only.",
    ]

    _original_export = evaluation._export_member

    def _export_with_25sp_prior(out_csv: Path) -> int:
        n = _original_export(out_csv)
        frame = pd.read_csv(out_csv)
        v48 = pd.read_csv(BASE_BOUNDS_V48, encoding="utf-8-sig")
        add = v48[v48["name"].astype(str).str.upper().isin(SUPPLEMENT_25SP)][["name", "init"]]
        existing = set(frame["name"].astype(str).str.lower())
        added = 0
        for _, r in add.iterrows():
            name = str(r["name"]).lower()
            if name in existing:
                continue
            frame = pd.concat([frame, pd.DataFrame({"name": [name], "value": [float(r["init"])]})],
                              ignore_index=True)
            added += 1
        frame.to_csv(out_csv, index=False)
        return n + added

    evaluation._export_member = _export_with_25sp_prior

    result = int(evaluation.main() or 0)
    manifest_path = out_root / "diagnostic_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        dssat_version="official DSSAT v4.8",
        member_selection_rule="minimum realization-level actual Phi across all persisted iterations",
        custom_genetic_params=(
            f"member #{best_member} from iteration {source_iteration} of the 26SP-only run"
        ),
        bundle_note=(
            "v48 25SP scheme4_double_n bundle plus v48 26SP s0p34 sweep bundle; "
            "all 10 25SP and all 12 26SP treatments replayed"
        ),
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
