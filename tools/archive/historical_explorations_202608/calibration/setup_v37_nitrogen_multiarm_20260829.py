"""Create audited local nitrogen arms A-E anchored to v37 iteration-3 member 137."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.param_registry import assert_valid_frozen_bounds


BASE_RUN = ROOT / "workspace/runs/e02_formal_v37_fresh_yield_source_sink_200x4_20260829"
ANCHOR_PARAMS = BASE_RUN / "best_member_137_two_season_deterministic_20260829/best_member_137_params.csv"
BASE_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v37_formal_source_sink_balanced_bounds.csv"
BASE_DESIGN = ROOT / "configs/runs/e02_formal_v37_fresh_yield_source_sink_200x4_20260829.json"
BOUNDS_DIR = BASE_BOUNDS.parent
CONFIG_DIR = BASE_DESIGN.parent
REPORT_DIR = ROOT / "workspace/reports/e02_v37_n_response_multiarm_execution_20260829"

COMMON = {
    "nstfac": (0.30, 0.70),
    "rtno3": (0.025, 0.050),
    "rtnh4": (0.018, 0.042),
    "rtexf": (0.12, 0.24),
    "prolfi": (0.21, 0.27),
    "prosti": (0.24, 0.30),
    "prolff": (0.090, 0.115),
    "prostf": (0.028, 0.045),
    "nmobmx": (0.35, 0.60),
    "nvsmob": (0.60, 0.80),
    "nrcvr": (0.13, 0.23),
    "senrte": (2.10, 3.00),
    "fnpgn1": (0.42, 0.58),
    "fnpgn2": (3.25, 3.85),
    "lnref": (2.90, 3.65),
    "nslope": (0.070, 0.140),
}

ARM_SPECS = {
    "a": {"label": "local_nitrogen_baseline", "lambda": 1.0, "active": COMMON},
    "b": {"label": "nresponse_weight_only", "lambda": 2.0, "active": COMMON},
    # C/D/E are parameter-family contrasts against A.  Their response weight
    # must remain at the A baseline; otherwise parameter and weight effects are
    # confounded.  The completed 2026-08-29 historical runs used 2.0 and are
    # intentionally not rewritten—future setup runs use the corrected design.
    "c": {
        "label": "uptake_supply_trigger",
        "lambda": 1.0,
        "active": {
            "rtno3": (0.035, 0.050), "rtnh4": (0.018, 0.042), "rtexf": (0.12, 0.24),
            "nstfac": (0.50, 0.75), "prolfi": (0.23, 0.27), "prosti": (0.24, 0.30),
        },
    },
    "d": {
        "label": "protein_demand_mobilization",
        "lambda": 1.0,
        "active": {
            "prolfi": (0.23, 0.27), "prosti": (0.24, 0.30),
            "prolff": (0.090, 0.115), "prostf": (0.028, 0.045),
            "nmobmx": (0.35, 0.60), "nvsmob": (0.60, 0.80),
            "nrcvr": (0.13, 0.23), "senrte": (2.10, 3.00),
        },
    },
    "e": {
        "label": "leaf_n_photosynthesis_curve",
        "lambda": 1.0,
        "active": {
            "fnpgn1": (0.42, 0.58), "fnpgn2": (3.25, 3.85),
            "lnref": (2.90, 3.65), "nslope": (0.070, 0.140),
        },
    },
}


def _anchor() -> dict[str, float]:
    frame = pd.read_csv(ANCHOR_PARAMS)
    return dict(zip(frame["name"].astype(str).str.lower(), pd.to_numeric(frame["value"])))


def _bounds_for_arm(arm: str, anchor: dict[str, float]) -> tuple[str, Path]:
    spec = ARM_SPECS[arm]
    bounds_id = f"eggplant_e02_v37_nmulti_arm_{arm}_{spec['label']}_bounds"
    output = BOUNDS_DIR / f"{bounds_id}.csv"
    frame = pd.read_csv(BASE_BOUNDS)
    frame["name"] = frame["name"].astype(str)
    names = frame["name"].str.lower()
    missing_anchor = sorted(set(names) - set(anchor))
    if missing_anchor:
        raise RuntimeError(f"anchor is missing bounds parameters: {missing_anchor}")
    frame["init"] = names.map(anchor)
    frame["lower"] = frame["init"]
    frame["upper"] = frame["init"]
    frame["status"] = "fixed"
    frame["review_note"] = "fixed to v37 iteration-3 member 137 for nitrogen mechanism attribution"

    for name, (lower, upper) in spec["active"].items():
        selected = names.eq(name)
        if selected.sum() != 1:
            raise RuntimeError(f"{arm}: parameter {name!r} occurs {selected.sum()} times")
        init = float(anchor[name])
        if init < lower or init > upper:
            init = min(max(init, lower), upper)
        frame.loc[selected, ["init", "lower", "upper", "status"]] = [init, lower, upper, "active"]
        frame.loc[selected, "review_note"] = (
            f"v37 nitrogen P0 local arm {arm}; explicit member137 anchor; range {lower}-{upper}"
        )
    frame.to_csv(output, index=False)
    assert_valid_frozen_bounds(str(output))
    return bounds_id, output


def _design_for_arm(arm: str, bounds_id: str) -> Path:
    spec = ARM_SPECS[arm]
    design = json.loads(BASE_DESIGN.read_text(encoding="utf-8"))
    run_id = f"e02_v37_nmulti_arm_{arm}_60x3_20260829"
    design.update(
        {
            "status": "exploratory_local_nitrogen_arm",
            "design_id": run_id,
            "run_id": run_id,
            "case": f"e02_v37_nmulti_arm_{arm}_20260829",
            "purpose": (
                f"v37 member137 iteration3 local nitrogen arm {arm}: {spec['label']}; "
                "all non-arm parameters fixed"
            ),
            "shared_parameter_scope": f"{len(spec['active'])} active nitrogen parameters only",
            "bounds_id": bounds_id,
        }
    )
    design["nitrogen_response_objective"]["nse_lambda"] = spec["lambda"]
    design["pest_ies"] = {"num_reals": 60, "noptmax": 3, "agents": 6, "random_seed": 42}
    path = CONFIG_DIR / f"{run_id}.json"
    path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    anchor = _anchor()
    manifest = []
    for arm in ARM_SPECS:
        bounds_id, bounds_path = _bounds_for_arm(arm, anchor)
        design_path = _design_for_arm(arm, bounds_id)
        manifest.append(
            {
                "arm": arm,
                "label": ARM_SPECS[arm]["label"],
                "bounds_id": bounds_id,
                "bounds_path": str(bounds_path),
                "design_path": str(design_path),
                "nresponse_lambda": ARM_SPECS[arm]["lambda"],
                "active_count": len(ARM_SPECS[arm]["active"]),
                "active_parameters": ";".join(ARM_SPECS[arm]["active"]),
                "anchor_iteration": 3,
                "anchor_member": 137,
            }
        )
    pd.DataFrame(manifest).to_csv(REPORT_DIR / "arm_configuration_manifest.csv", index=False)
    print(pd.DataFrame(manifest).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
