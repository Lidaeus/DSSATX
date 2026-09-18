"""Prepare v48: 26SP non-N0 N-gradient objective and doubled W response."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.param_registry import assert_valid_frozen_bounds

BASE_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v47_free_nscale_formal_20260901.csv"
BASE_DESIGN = ROOT / "configs/runs/e02_formal_v47_free_nscale_20260901.json"
BASE_GROUP = ROOT / "configs/runs/e02_formal_v47_free_nscale_group_policy_20260901.csv"
ANCHOR = ROOT / "workspace/reports/e02_formal_v47_free_nscale_20260902_candidates/lowest_phi_params.csv"

BOUNDS_ID = "eggplant_e02_v48_n_gradient_water2x_formal_20260902"
BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / f"{BOUNDS_ID}.csv"
DESIGN = ROOT / "configs/runs/e02_formal_v48_n_gradient_water2x_20260902.json"
GROUP = ROOT / "configs/runs/e02_formal_v48_n_gradient_water2x_group_policy_20260902.csv"


def prepare_bounds() -> pd.DataFrame:
    frame = pd.read_csv(BASE_BOUNDS, encoding="utf-8-sig")
    anchor = pd.read_csv(ANCHOR, encoding="utf-8-sig")
    anchor_values = dict(zip(anchor["name"].astype(str).str.lower(), pd.to_numeric(anchor["value"], errors="raise")))
    names = frame["name"].astype(str).str.lower()
    for idx, row in frame.iterrows():
        name = str(row["name"]).lower()
        if name in anchor_values and str(row["status"]).lower() != "disabled":
            frame.at[idx, "init"] = min(max(float(anchor_values[name]), float(row["lower"])), float(row["upper"]))
    changes = {
        "xfpht": ("lower", 35.0, "v48 lower relaxation after 95% posterior lower-bound pressure"),
        "xfrt": ("upper", 1.0, "v48 upper relaxation after 92% posterior upper-bound pressure"),
        "frlff": ("lower", 0.15, "v48 lower relaxation after 78.5% posterior lower-bound pressure"),
        "finref": ("lower", 100.0, "v48 lower relaxation after 74% posterior lower-bound pressure"),
    }
    for name, (field, value, note) in changes.items():
        mask = names.eq(name)
        if int(mask.sum()) != 1:
            raise RuntimeError(f"expected one frozen-bounds row for {name}")
        frame.loc[mask, field] = value
        frame.loc[mask, "review_note"] = note
    BOUNDS.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(BOUNDS, index=False, encoding="utf-8-sig")
    errors = [issue for issue in assert_valid_frozen_bounds(BOUNDS) if issue.severity == "error"]
    if errors:
        raise RuntimeError("v48 frozen bounds failed validation: " + "; ".join(map(str, errors)))
    return frame


def prepare_group_policy() -> None:
    group = pd.read_csv(BASE_GROUP, encoding="utf-8-sig")
    wmask = group["group"].astype(str).str.upper().eq("W_RESPONSE")
    group.loc[wmask, "phi_budget"] = 0.15
    group.loc[wmask, "note"] = "v48 doubled W-response strength; executable season/stratum NSE lambda=3.0"
    group = group.loc[~group["group"].astype(str).str.upper().eq("N_DOSE_GRADIENT")].copy()
    group = pd.concat([group, pd.DataFrame([{
        "group": "N_DOSE_GRADIENT",
        "phi_budget": 1.5,
        "note": "26SP non-N0 log(N2/N1), log(N3/N2), and N1:N3 CV objective",
    }])], ignore_index=True)
    group.to_csv(GROUP, index=False, encoding="utf-8-sig")


def prepare_design() -> dict[str, object]:
    design = json.loads(BASE_DESIGN.read_text(encoding="utf-8"))
    design.update({
        "design_id": "e02_formal_v48_n_gradient_water2x_20260902",
        "status": "approved_for_execution",
        "purpose": "v47 follow-up adding a directional 26SP non-N0 N-dose/CV family, doubled W response, and targeted boundary relaxations.",
        "source_design": str(BASE_DESIGN.relative_to(ROOT)).replace("\\", "/"),
        "source_run": "workspace/runs/e02_formal_v47_free_nscale_200x6_20260901_r2",
        "parameter_anchor": {
            "member": 23,
            "selection": "v47 final-iteration lowest Phi",
            "parameter_csv": str(ANCHOR.relative_to(ROOT)).replace("\\", "/"),
        },
        "bounds_id": BOUNDS_ID,
        "bounds_sha256": hashlib.sha256(BOUNDS.read_bytes()).hexdigest(),
        "group_policy": str(GROUP.relative_to(ROOT)).replace("\\", "/"),
    })
    # Correct the v47 metadata typo.  The v47 PST already used 34 d correctly.
    for term in design.get("seedling_parameterization", {}).get("terms", []):
        if str(term.get("name", "")).upper() == "PAGE_26SP":
            term["init"] = 34.0
    design["nitrogen_dose_gradient_objective"] = {
        "enabled": True,
        "mapping_csv": "configs/runs/e02_mapping_26sp_w2_w1_20260830.csv",
        "seasons": ["26SP"],
        "source_variable": "CHFPW",
        "levels": ["N1", "N2", "N3"],
        "metrics": ["log_N2_minus_N1", "log_N3_minus_N2", "cv_N1_N2_N3"],
        "response_target": "monotone_plateau",
        "harvest_scope": "all",
        "weighting": "static",
        "sigma_floor": 0.05,
        "phi_budget": 1.5,
        "direction_contract": "observed target is non-decreasing; simulated adjacent gradients are not clamped",
    }
    design["water_response_objective"]["nse_lambda"] = 3.0
    design["water_response_objective"]["response_strength_multiplier_vs_v47"] = 2.0
    design["objective_interpretation"]["response_strength"] = (
        "N_RESPONSE lambda 3.0; W_RESPONSE lambda 3.0; 26SP N_DOSE_GRADIENT static budget 1.5"
    )
    design["pest_ies"].update({"num_reals": 200, "noptmax": 4, "agents": 6, "random_seed": 43})
    design["pest_ies"]["executable_command"] = (
        "build_pest.py --mode eggplant_stage2 --noptmax 4 --ies-num-reals 200 "
        "--batch DSSBatch.v48 --harvest-var CHFPW --param-review-mode off"
    )
    DESIGN.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return design


def main() -> int:
    bounds = prepare_bounds()
    prepare_group_policy()
    prepare_design()
    print(f"bounds={BOUNDS}")
    print(f"design={DESIGN}")
    print(f"group_policy={GROUP}")
    print(f"active_parameters={int(bounds['status'].astype(str).str.lower().eq('active').sum())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
