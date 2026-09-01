"""Create corrected 25SP/26SP local yield arms A-E from v45 member 44."""

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
from src.common.experiment_inputs import filex_harvest_dates, filex_observed_harvest_dates


BASE_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v45_nitrogen_synergy_bounds.csv"
BASE_DESIGN = ROOT / "configs/runs/e02_formal_v45_nitrogen_synergy_two_seasons_20260830.json"
ANCHOR = ROOT / "workspace/runs/e02_formal_v45_nitrogen_synergy_two_seasons_20260830/best_member_44_two_season_deterministic_20260830/best_member_44_params.csv"
BOUNDS_DIR = BASE_BOUNDS.parent
CONFIG_DIR = BASE_DESIGN.parent
REPORT_DIR = ROOT / "workspace/reports/e02_v46_corrected_yield_multiarm_20260830"

SCALE = {
    "phtmax": (58.0, 80.0),
    "parmax": (38.0, 55.0),
    "wtfsd": (0.30, 0.58),
    "lfmax": (1.85, 2.12),
}
ARMS = {
    "a": {"label": "corrected_v45_scale_baseline", "policy": "e02_group_policy_v41_nresp_10x_yield_3x.csv", "active": SCALE},
    "b": {"label": "fresh_yield_6x_only", "policy": "e02_group_policy_v46_fresh_yield_6x.csv", "active": SCALE},
    "c": {
        "label": "fresh6x_n_trigger",
        "policy": "e02_group_policy_v46_fresh_yield_6x.csv",
        "active": {**SCALE, "nstfac": (0.55, 0.85), "rtno3": (0.025, 0.035)},
    },
    "d": {
        "label": "fresh6x_source_sink",
        "policy": "e02_group_policy_v46_fresh_yield_6x.csv",
        "active": {
            **SCALE, "xfrt": (0.88, 0.98), "sfdur": (26.0, 40.0),
            "podur": (18.0, 35.0), "xfint": (0.35, 0.50), "xfrmax": (0.25, 0.50),
        },
    },
    "e": {
        "label": "fresh6x_n_supply_mobilization",
        "policy": "e02_group_policy_v46_fresh_yield_6x.csv",
        "active": {
            **SCALE, "nmobmx": (0.15, 0.30), "nvsmob": (0.40, 0.65),
            "rtexf": (0.12, 0.30),
        },
    },
}

SOIL_CANONICAL = {
    "soil_slpf": 0.92,
    **{f"soil_slll_{i:02d}": v for i, v in enumerate([.125, .121, .138, .158, .173, .179, .161], 1)},
    **{f"soil_sdul_{i:02d}": v for i, v in enumerate([.198, .214, .250, .271, .285, .288, .270], 1)},
    **{f"soil_ssat_{i:02d}": v for i, v in enumerate([.294, .310, .332, .331, .332, .332, .320], 1)},
    **{f"soil_sbdm_{i:02d}": v for i, v in enumerate([1.49, 1.45, 1.44, 1.53, 1.58, 1.59, 1.60], 1)},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    base = pd.read_csv(BASE_BOUNDS)
    base["key"] = base["name"].astype(str).str.lower()
    anchor_frame = pd.read_csv(ANCHOR)
    anchor = dict(zip(anchor_frame["name"].astype(str).str.lower(), pd.to_numeric(anchor_frame["value"])))
    source_design = json.loads(BASE_DESIGN.read_text(encoding="utf-8"))
    bundles = {
        "25SP": ROOT / "data/user/experiments/xxql2501_user_ic_scheme4_20260830",
        "26SP": ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830",
    }
    soil_hashes = {sid: sha256(path / "SOIL.SOL") for sid, path in bundles.items()}
    if len(set(soil_hashes.values())) != 1:
        raise RuntimeError(f"bundle SOIL.SOL files are not unified: {soil_hashes}")
    if filex_harvest_dates(bundles["25SP"] / "XXQL2501.TMX")[-1] != 25194:
        raise RuntimeError("25SP simulation does not extend through virtual harvest 25194")
    if filex_observed_harvest_dates(bundles["25SP"] / "XXQL2501.TMX")[-1] != 25192:
        raise RuntimeError("25SP observed-yield cutoff is not 25192")

    manifest = []
    for arm, spec in ARMS.items():
        frame = base.drop(columns=["key"]).copy()
        keys = frame["name"].astype(str).str.lower()
        for idx, key in keys.items():
            value = float(anchor.get(key, frame.at[idx, "init"]))
            if key in SOIL_CANONICAL:
                value = SOIL_CANONICAL[key]
            # Layer 08 belongs to the superseded profile and is deliberately
            # fixed; the 180-cm seven-layer bundle has no eighth row to inject.
            frame.at[idx, "init"] = value
            frame.at[idx, "lower"] = value
            frame.at[idx, "upper"] = value
            frame.at[idx, "status"] = "fixed"
        for key, (lower, upper) in spec["active"].items():
            idx = frame.index[keys.eq(key)]
            if len(idx) != 1:
                raise KeyError(f"{arm}: parameter {key} not found exactly once")
            i = idx[0]
            anchor_value = float(anchor.get(key, frame.at[i, "init"]))
            init = min(max(anchor_value, lower), upper)
            frame.loc[i, ["init", "lower", "upper", "status"]] = [init, lower, upper, "active"]
        bounds_id = f"eggplant_e02_v46_arm_{arm}_corrected_yield"
        bounds_path = BOUNDS_DIR / f"{bounds_id}.csv"
        frame.to_csv(bounds_path, index=False)
        assert_valid_frozen_bounds(bounds_path)

        design = json.loads(json.dumps(source_design))
        design["status"] = "multiarm_ready"
        design["design_id"] = f"e02_v46_arm_{arm}_{spec['label']}_60x3_20260830"
        design["stage"] = "v46_multiarm"
        design["purpose"] = spec["label"]
        design["bounds_id"] = bounds_id
        design["group_policy"] = f"configs/runs/{spec['policy']}"
        design["initial_condition_policy"] = "Measured treatment-specific IC; unified 180-cm Scheme4 soil; loam-reference SRGF; 25194 virtual harvest excluded from yield targets"
        design["acceptance"]["nitrogen_response"] = (
            "For each season use the mean of terminal fresh-yield N2-N0 and N1-N0 "
            "contrasts over all complete water strata; N3 is excluded from this hard gate"
        )
        design["acceptance"]["candidate_rule"] = "shortlist by Phi, then deterministic all-22 replay and hard-gate ranking"
        design["pest_ies"] = {"num_reals": 60, "noptmax": 3, "agents": 6, "random_seed": 42}
        design_path = CONFIG_DIR / f"e02_v46_arm_{arm}_{spec['label']}_60x3_20260830.json"
        design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest.append({
            "arm": arm, "label": spec["label"], "bounds_id": bounds_id,
            "bounds_path": str(bounds_path.relative_to(ROOT)),
            "design_path": str(design_path.relative_to(ROOT)),
            "group_policy": spec["policy"],
            "active_parameters": ";".join(sorted(spec["active"])),
            "soil_sha256": next(iter(soil_hashes.values())),
            "virtual_harvest": 25194, "observed_yield_cutoff": 25192,
            "n_gate": "mean(N2-N0,N1-N0)_by_season_over_complete_water_strata",
        })
    pd.DataFrame(manifest).to_csv(REPORT_DIR / "arm_configuration_manifest.csv", index=False)
    print(pd.DataFrame(manifest).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
