"""Prepare the formal v47 freer-bound, season-scaled initial-N design."""

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

BASE_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v46_page_penv_n034_formal_20260901.csv"
BASE_DESIGN = ROOT / "configs/runs/e02_formal_v46_page_penv_n034_20260901.json"
BASE_OBS = ROOT / "configs/runs/e02_from_scratch_objective_contract_20260826.csv"
BASE_GROUP = ROOT / "configs/runs/e02_group_policy_v40_formal_fresh_3x_yield.csv"

BOUNDS_ID = "eggplant_e02_v47_free_nscale_formal_20260901"
BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / f"{BOUNDS_ID}.csv"
DESIGN = ROOT / "configs/runs/e02_formal_v47_free_nscale_20260901.json"
OBS = ROOT / "configs/runs/e02_formal_v47_free_nscale_observation_policy_20260901.csv"
GROUP = ROOT / "configs/runs/e02_formal_v47_free_nscale_group_policy_20260901.csv"


def _prepare_bounds() -> pd.DataFrame:
    frame = pd.read_csv(BASE_BOUNDS, encoding="utf-8-sig")
    names = frame["name"].astype(str).str.upper()
    frame.loc[names.eq("SFDUR"), "lower"] = 20.0
    frame.loc[names.eq("SFDUR"), "review_note"] = "v47 user-approved lower relaxation 40 -> 20 d"
    frame.loc[names.eq("VSSINK"), "upper"] = 7.0
    frame.loc[names.eq("VSSINK"), "review_note"] = "v47 modest upper relaxation 5.596237 -> 7.0"
    if int(names.isin(["SFDUR", "VSSINK"]).sum()) != 2:
        raise RuntimeError("SFDUR/VSSINK rows are not unique in base bounds")

    extra = pd.DataFrame(
        [
            {
                "name": "ICNS_25SP", "init": 1.0, "lower": 0.15, "upper": 1.2,
                "status": "active", "pargp": "initial_conditions", "location": "IC",
                "file": "XXQL2501.TMX", "cultivar": "TM0008", "ecotype": "TM0001",
                "mode": "25SP", "review_note": "Season-wide multiplier of bundle SNH4 and SNO3",
                "notes": "Anchor is the v46 25SP double-N FileX bundle; multiplier is not compounded",
            },
            {
                "name": "ICNS_26SP", "init": 1.0, "lower": 0.15, "upper": 1.2,
                "status": "active", "pargp": "initial_conditions", "location": "IC",
                "file": "XXQL2601.TMX", "cultivar": "TM0008", "ecotype": "TM0001",
                "mode": "26SP", "review_note": "Season-wide multiplier of bundle SNH4 and SNO3",
                "notes": "Anchor is the v46 26SP n0.34 FileX bundle; multiplier is not compounded",
            },
        ]
    )
    frame = pd.concat([frame, extra], ignore_index=True)
    BOUNDS.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(BOUNDS, index=False, encoding="utf-8-sig")
    errors = [issue for issue in assert_valid_frozen_bounds(BOUNDS) if issue.severity == "error"]
    if errors:
        raise RuntimeError("new frozen bounds failed validation: " + "; ".join(map(str, errors)))
    return frame


def _prepare_policies() -> None:
    obs = pd.read_csv(BASE_OBS, encoding="utf-8-sig")
    mask = obs["group"].astype(str).str.upper().eq("CHTDM")
    if int(mask.sum()) != 1:
        raise RuntimeError("expected one CHTDM observation-policy row")
    obs.loc[mask, "phi_role"] = "calibration"
    obs.loc[mask, "note"] = "Plant height active in v47; separate Phi family budget is 0.45 per season"
    obs.to_csv(OBS, index=False, encoding="utf-8-sig")

    group = pd.read_csv(BASE_GROUP, encoding="utf-8-sig")
    group = group.loc[~group["group"].astype(str).str.upper().eq("CANOPY_HEIGHT")].copy()
    group = pd.concat(
        [
            group,
            pd.DataFrame([{"group": "CANOPY_HEIGHT", "phi_budget": 0.45, "note": "One tenth of terminal HARVEST_FRESH budget 4.50"}]),
        ],
        ignore_index=True,
    )
    for family in ("N_RESPONSE", "W_RESPONSE"):
        mask = group["group"].astype(str).str.upper().eq(family)
        group.loc[mask, "phi_budget"] = 0.075
        group.loc[mask, "note"] = "v47 response strength tripled; executable NSE lambda is set in design"
    group.to_csv(GROUP, index=False, encoding="utf-8-sig")


def _prepare_design() -> dict[str, object]:
    design = json.loads(BASE_DESIGN.read_text(encoding="utf-8"))
    design.update(
        {
            "design_id": "e02_formal_v47_free_nscale_20260901",
            "status": "approved_for_execution",
            "executable": True,
            "purpose": "Formal freer-condition posterior movement experiment with relaxed SFDUR/VSSINK, active low-budget height, 3x N/W response strength, and independent seasonal initial mineral-N multipliers.",
            "source_design": str(BASE_DESIGN.relative_to(ROOT)).replace("\\", "/"),
            "source_design_id": "e02_formal_v46_page_penv_n034_20260901",
            "bounds_id": BOUNDS_ID,
            "bounds_sha256": hashlib.sha256(BOUNDS.read_bytes()).hexdigest(),
            "observation_policy": str(OBS.relative_to(ROOT)).replace("\\", "/"),
            "group_policy": str(GROUP.relative_to(ROOT)).replace("\\", "/"),
        }
    )
    design["nitrogen_response_objective"]["nse_lambda"] = 3.0
    design["nitrogen_response_objective"]["response_strength_multiplier_vs_v46"] = 3.0
    design["water_response_objective"]["nse_lambda"] = 1.5
    design["water_response_objective"]["response_strength_multiplier_vs_v46"] = 3.0
    design["process_state_objective"]["CHTD"] = "calibration_separate_budget"
    design["initial_nitrogen_scaling"] = {
        "parameterization": "season-wide multiplicative scaling of both SNH4 and SNO3 in FileX *INITIAL CONDITIONS",
        "bounds": [0.15, 1.2],
        "dssat_safe_floors": {"SNH4": 0.1, "SNO3": 0.5},
        "parameters": {"25SP": "ICNS_25SP", "26SP": "ICNS_26SP"},
        "measured_profile_depth_scope_cm": {"25SP": 100, "26SP": 60},
        "anchors": {
            "25SP": "existing xxql2501_scheme4_double_n_20260831 bundle values",
            "26SP": "existing 26SP s0p34 bundle values",
        },
        "no_compounding": True,
    }
    design["objective_interpretation"]["cht_d_weight"] = "CANOPY_HEIGHT budget 0.45 per season"
    design["objective_interpretation"]["response_strength"] = "N_RESPONSE lambda 3.0; W_RESPONSE lambda 1.5"
    design["pest_ies"].update({"num_reals": 200, "noptmax": 6, "agents": 6, "random_seed": 42})
    design["pest_ies"]["executable_command"] = "build_pest.py --mode eggplant_stage2 --noptmax 6 --ies-num-reals 200 --batch DSSBatch.v48 --harvest-var CHFPW --param-review-mode off"
    DESIGN.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return design


def main() -> int:
    bounds = _prepare_bounds()
    _prepare_policies()
    _prepare_design()
    active = bounds["status"].astype(str).str.lower().eq("active")
    print(f"bounds={BOUNDS}")
    print(f"design={DESIGN}")
    print(f"observation_policy={OBS}")
    print(f"group_policy={GROUP}")
    print(f"active_parameters={int(active.sum())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
