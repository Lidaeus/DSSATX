"""Render final two-season diagnostics for the completed 20260814 calibration."""

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
SOURCE_ITERATION = 5


def _validated_status() -> dict:
    status = json.loads((RUN_DIR / "run_status.json").read_text(encoding="utf-8"))
    if not (
        status.get("status") == "completed"
        and status.get("manager_exit_code") == 0
        and status.get("engineering_status") == "engineering_validated"
    ):
        raise RuntimeError(f"calibration is not engineering-validated: {status}")
    return status


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
    names = par[real_col].astype(str).str.replace(r"\.0$", "", regex=True)
    values = {
        name: float(row.iloc[0][name])
        for name in names
        if name in row.columns and pd.notna(row.iloc[0][name])
    }
    if len(values) != len(par):
        raise ValueError("final Phi and parameter ensemble realizations are not aligned")
    member = min(values, key=values.get)
    return member, values[member]


def main() -> int:
    status = _validated_status()
    member, best_phi = _best_member()
    evaluation.CASE = CASE
    evaluation.RUN_DIR = RUN_DIR
    evaluation.BEST_MEMBER = member
    evaluation.SOURCE_ITERATION = SOURCE_ITERATION
    evaluation.BEST_PHI = best_phi
    evaluation.CALIBRATION_STATE = "completed_engineering_validated"
    evaluation.ARTIFACT_TYPE = "two_season_diagnostics_fixedsoil_official_20260814"
    evaluation.OBS_REGISTRY = RUN_DIR / f"{CASE}_observation_registry.csv"
    evaluation.OUT_ROOT = ROOT / "figture" / "fixedsoil_official_twoseason_20260814"
    evaluation.DET_ROOT = RUN_DIR / f"final_iter5_best_member_{member}_deterministic_20260814"
    evaluation.EXTRA_LIMITATIONS = [
        "Engineering-validated run diagnostics; formal science promotion remains a separate evidence gate.",
    ]
    rc = evaluation.main()

    manifest_path = evaluation.OUT_ROOT / "diagnostic_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "source_run_status": str((RUN_DIR / "run_status.json").resolve()),
        "selection_rule": "minimum_actual_phi_within_final_iteration_5",
        "manager_exit_code": status["manager_exit_code"],
        "engineering_status": status["engineering_status"],
        "science_status": status.get("science_status", "science_pending"),
        "objective_contract": {
            "CANOPY_LAIX": "diagnostic_only_zero_weight",
            "CANOPY_TERMINAL": "last_observed_LAI_paired_to_same_date_simulation",
            "W_RESPONSE": "W2_minus_W1",
            "W_RESPONSE_phi_budget_per_season": 0.025,
        },
    })
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
