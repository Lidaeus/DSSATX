"""Render partial two-season diagnostics for the interrupted 20260814 run."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.calibration import evaluate_fixedsoil_official_best189_20260813 as evaluation

CASE = "e02_v2_fixedsoil_joint_official_25sp26sp_200x5_20260814"
RUN_DIR = ROOT / "workspace" / "runs" / CASE
SOURCE_ITERATION = 1


def _best_member() -> tuple[str, float]:
    phi = pd.read_csv(RUN_DIR / f"{CASE}.phi.actual.csv")
    row = phi.loc[pd.to_numeric(phi["iteration"], errors="coerce") == SOURCE_ITERATION]
    if len(row) != 1:
        raise ValueError(f"expected one Phi row for iteration {SOURCE_ITERATION}")

    par = pd.read_csv(RUN_DIR / f"{CASE}.{SOURCE_ITERATION}.par.csv")
    real_col = next(
        (c for c in par.columns if str(c).lower() in {"real_name", "realization"}),
        None,
    )
    if real_col is None:
        raise ValueError("parameter ensemble has no realization column")
    realizations = par[real_col].astype(str).str.replace(r"\.0$", "", regex=True)
    values = {
        name: float(row.iloc[0][name])
        for name in realizations
        if name in row.columns and pd.notna(row.iloc[0][name])
    }
    if not values:
        raise ValueError("no Phi values match parameter realizations")
    member = min(values, key=values.get)
    return member, values[member]


def main() -> int:
    member, best_phi = _best_member()
    evaluation.CASE = CASE
    evaluation.RUN_DIR = RUN_DIR
    evaluation.BEST_MEMBER = member
    evaluation.SOURCE_ITERATION = SOURCE_ITERATION
    evaluation.BEST_PHI = best_phi
    evaluation.CALIBRATION_STATE = "runtime_failed_after_iteration_1"
    evaluation.ARTIFACT_TYPE = "partial_two_season_diagnostics_fixedsoil_official_20260814"
    evaluation.OBS_REGISTRY = RUN_DIR / f"{CASE}_observation_registry.csv"
    evaluation.OUT_ROOT = ROOT / "figture" / "fixedsoil_official_twoseason_20260814_partial_iter1"
    evaluation.DET_ROOT = RUN_DIR / f"partial_iter1_best_member_{member}_deterministic_20260814"
    evaluation.EXTRA_LIMITATIONS = [
        "Source calibration terminated after iteration 1; these are interim engineering diagnostics, not final calibration evidence.",
        "Best member was selected by minimum actual Phi within the iteration-1 parameter ensemble.",
    ]
    rc = evaluation.main()

    manifest_path = evaluation.OUT_ROOT / "diagnostic_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_run_status"] = str((RUN_DIR / "run_status.json").resolve())
    manifest["selection_rule"] = "minimum_actual_phi_within_iteration_1"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
