"""Replay the lowest-Phi member of the corrected-26SP-N formal run on all 22 treatments."""

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


RUN_NAME = "e02_formal_armab_rrmse_26spncal_official_200x6_20260828"
CASE = "e02_formal_armab_rrmse_26spncal_200x6_20260828"


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
    det_root = run_dir / f"best_member_{best_member}_two_season_deterministic_20260828"
    out_root = ROOT / "figture" / f"e02_formal_armab_rrmse_26spncal_best{best_member}_two_season_full_20260828"

    evaluation.RUN_DIR = run_dir
    evaluation.DET_ROOT = det_root
    evaluation.OUT_ROOT = out_root
    evaluation.FIGURE = ROOT / "figture"
    evaluation.CASE = CASE
    evaluation.BEST_MEMBER = best_member
    evaluation.SOURCE_ITERATION = source_iteration
    evaluation.BEST_PHI = best_phi
    evaluation.CALIBRATION_STATE = "completed_engineering_validated"
    evaluation.ARTIFACT_TYPE = "two_season_diagnostics_formal_armab_rrmse_26spncal_20260828"
    evaluation.SPE = ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    evaluation.HARVEST_OBJECTIVE = (
        "measured dry increments plus seasonal terminal-yield RRMSE (lambda=25/season)"
    )
    evaluation.SOIL_INJECTION_DESCRIPTION = (
        "enabled: SLPF plus SBDM/SLLL/SDUL/SSAT in layers 1-6 calibrated within narrow audited bounds"
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
    evaluation.SEASON_IDS = [season["season_id"] for season in evaluation.SEASONS]
    evaluation.COLORS = {"25SP": "#2878B5", "26SP": "#2A9D55"}

    # The forward model honors these environment variables, so no global file
    # replacement is needed for this deterministic replay.
    os.environ["DSSAT_CUSTOM_EXE"] = str(evaluation.EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(evaluation.SPE.resolve())
    evaluation._swap = lambda: []
    evaluation._restore = lambda replacements: None

    if det_root.exists():
        shutil.rmtree(det_root)
    if out_root.exists():
        shutil.rmtree(out_root)
    det_root.mkdir(parents=True)
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
        "All 22 spring treatments are plotted; only TN 2/5/10/13 in 25SP and TN 1/3/9/12 in 26SP entered calibration.",
        "The selected member is the minimum actual-Phi realization across iterations; it occurs at iteration 5 rather than the final iteration 6.",
        "25FA is excluded from this user-requested two-season figure suite.",
    ]

    result = int(evaluation.main() or 0)
    manifest_path = out_root / "diagnostic_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        dssat_version="official DSSAT v4.8",
        member_selection_rule="minimum realization-level actual Phi across all persisted iterations",
        custom_genetic_params=(
            f"formal member #{best_member} from iteration {source_iteration}: calibrated crop parameters "
            "injected into repaired project SPE/CUL/ECO templates"
        ),
        soil_params=(
            "SLPF and SBDM/SLLL/SDUL/SSAT layers 1-6 active within narrow bounds; "
            "treatment initial conditions fixed"
        ),
        bundle_note=(
            "25SP formal Arm-A/B bundle plus corrected-26SP-N formal bundle; "
            "all 10 25SP and all 12 26SP treatments replayed"
        ),
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
