"""Build the best71 nitrogen-response local A--E experiment.

This setup is intentionally narrow and causal.  The v46 best71 parameter
vector is frozen first, then only one nitrogen mechanism family is released in
each arm.  All 22 spring treatments are included so that N2-N0 and N1-N0
contrasts have complete same-water pairs; 25FA remains outside the calibration
experiment.
"""

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


BASE_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v37_formal_source_sink_balanced_bounds.csv"
BASE_DESIGN = ROOT / "configs/runs/e02_formal_v46_step20_custom26sp_20260831_200x4.json"
ANCHOR = ROOT / "workspace/runs/e02_formal_v46_step20_custom26sp_20260831_200x4/best_member_71_deterministic_20260831/best_member_71_params.csv"
CONFIG_DIR = ROOT / "configs/runs"
BOUNDS_DIR = BASE_BOUNDS.parent
REPORT_DIR = ROOT / "workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831"

POLICY = "configs/runs/e02_v46_best71_n12_objective_contract_20260831.csv"
GROUP_POLICY = "configs/runs/e02_v46_best71_n12_group_policy_20260831.csv"
MAPPING = "configs/runs/e02_mapping_25sp_w3w1_26sp_w2w1_n2n0_20260830.csv"

SEASON_TREATMENTS = {"25SP": list(range(2, 15)), "26SP": list(range(1, 13))}
# 25SP has no TN6--8 in the source experiment; retain the actual 10 treatments.
SEASON_TREATMENTS["25SP"] = [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]

ARMS: dict[str, dict[str, object]] = {
    # A/B deliberately have a small, non-zero local parameter channel so that
    # the IES engineering test is meaningful rather than a zero-variation run.
    "a": {
        "label": "local_n_baseline_lambda1",
        "nse_lambda": 1.0,
        "active": {
            "FNPGN1": (0.88, 0.92),
            "FNPGN2": (4.05, 4.20),
            "RTNO3": (0.032, 0.034),
        },
    },
    "b": {
        "label": "local_n_baseline_lambda2",
        "nse_lambda": 2.0,
        "active": {
            "FNPGN1": (0.88, 0.92),
            "FNPGN2": (4.05, 4.20),
            "RTNO3": (0.032, 0.034),
        },
    },
    "c": {
        "label": "local_n_supply_rtno3",
        "nse_lambda": 1.0,
        "active": {"RTNO3": (0.025, 0.040)},
    },
    "d": {
        "label": "local_n_demand_mobilization",
        "nse_lambda": 1.0,
        "active": {
            "PROLFI": (0.90 * 0.20871, 1.05 * 0.20871),
            "PROSTI": (0.90 * 0.244543, 1.05 * 0.244543),
            "PRORTI": (0.90 * 0.153614, 1.05 * 0.153614),
            "NMOBMX": (0.20, 0.45),
            "NVSMOB": (0.55, 0.80),
        },
    },
    "e": {
        "label": "local_n_leaf_photosynthesis",
        "nse_lambda": 1.0,
        "active": {
            "FNPGN1": (0.90, 1.10),
            "FNPGN2": (4.15, 4.50),
            "LNREF": (3.50, 4.20),
            "NSLOPE": (0.08, 0.14),
        },
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    base = pd.read_csv(BASE_BOUNDS)
    base["key"] = base["name"].astype(str).str.strip().str.lower()
    anchor_frame = pd.read_csv(ANCHOR)
    anchor = dict(zip(anchor_frame["name"].astype(str).str.strip().str.lower(), pd.to_numeric(anchor_frame["value"])))
    source_design = json.loads(BASE_DESIGN.read_text(encoding="utf-8"))

    manifest: list[dict[str, object]] = []
    for arm, spec in ARMS.items():
        frame = base.drop(columns=["key"]).copy()
        keys = frame["name"].astype(str).str.strip().str.lower()
        # Freeze every parameter to the deterministic best71 anchor first.
        for idx, key in keys.items():
            value = float(anchor.get(key, frame.at[idx, "init"]))
            frame.loc[idx, ["init", "lower", "upper", "status"]] = [value, value, value, "fixed"]

        active = spec["active"]
        assert isinstance(active, dict)
        for key, bounds in active.items():
            norm = str(key).strip().lower()
            idx = frame.index[keys.eq(norm)]
            if len(idx) != 1:
                raise KeyError(f"{arm}: parameter {key} not found exactly once")
            i = idx[0]
            lower, upper = map(float, bounds)
            value = float(anchor.get(norm, frame.at[i, "init"]))
            init = min(max(value, lower), upper)
            frame.loc[i, ["init", "lower", "upper", "status"]] = [init, lower, upper, "active"]

        bounds_id = f"eggplant_e02_v46_best71_n_{arm}_20260831"
        bounds_path = BOUNDS_DIR / f"{bounds_id}.csv"
        frame.to_csv(bounds_path, index=False)
        assert_valid_frozen_bounds(bounds_path)

        design = json.loads(json.dumps(source_design))
        design.update({
            "status": "multiarm_ready",
            "design_id": f"e02_v46_best71_n_{arm}_{spec['label']}_60x3_20260831",
            "stage": "v46_best71_local_n_response",
            "purpose": str(spec["label"]),
            "shared_parameter_scope": "best71 frozen; only local nitrogen mechanism family released",
            "bounds_id": bounds_id,
            "observation_policy": POLICY,
            "group_policy": GROUP_POLICY,
            "initial_condition_policy": "v46 best71 bundles; treatment-specific measured IC; no soil or water release",
            "nitrogen_response_objective": {
                "enabled": True,
                "mapping_csv": MAPPING,
                "weighting": "season_nse",
                "nse_lambda": float(spec["nse_lambda"]),
                "sigma_floor": 50.0,
                "contrast": "N2_and_N1_minus_N0_within_same_water",
                "contrast_scale": "raw_difference",
                "response_target": "observed_shape",
                "source_variable": "CHFPW",
                "levels": ["N1", "N2"],
                "harvest_scope": "all",
                "sst_scope": "season_x_response_stratum",
            },
            "water_response_objective": {
                "enabled": True,
                "mapping_csv": MAPPING,
                "weighting": "season_nse",
                "nse_lambda": 0.5,
                "sigma_floor": 50.0,
                "contrast": "W_high_minus_W_low_within_same_nitrogen",
                "contrast_scale": "raw_difference",
                "response_target": "observed_shape",
                "source_variable": "CHFPW",
                # ``levels`` is the non-zero response-level argument used by
                # load_n_response_mapping; N0 is supplied separately as the
                # reference through nitrogen_levels.
                "levels": ["N1", "N2"],
                "nitrogen_levels": ["N0", "N1", "N2"],
                "harvest_scope": "all",
                "season_contrasts": {
                    "25SP": {"high_water": "W3", "low_water": "W1"},
                    "26SP": {"high_water": "W2", "low_water": "W1"},
                },
                "sst_scope": "season_x_response_stratum",
            },
            "harvest_dry_objective": {"enabled": False},
            "harvest_fresh_objective": {
                "enabled": True,
                "mode": "increment_plus_terminal",
                "increment_source": "measured_hfpow",
                "variable": "CHFPW",
                "terminal_weighting": "season_rrmse",
                "rrmse_lambda": 750.0,
                "acceptance_metric": "RRMSE_pct",
                "acceptance_threshold_pct": 25.0,
                "acceptance_enforcement": "deterministic_postrun_hard_gate",
            },
            "seasons": [
                {
                    "season_id": "25SP",
                    "experiment_code": "XXQL2501",
                    "bundle_path": "data/user/experiments/xxql2501_formal_scheme4_soil_20260830",
                    "role": "calibration",
                    "treatments": SEASON_TREATMENTS["25SP"],
                },
                {
                    "season_id": "26SP",
                    "experiment_code": "XXQL2601",
                    "bundle_path": "data/user/experiments/xxql2601_formal_scheme4_soil_20260830",
                    "role": "calibration",
                    "treatments": SEASON_TREATMENTS["26SP"],
                },
            ],
            "diagnostic_only": {"25SP": [], "26SP": []},
            "acceptance": {
                "terminal_yield": "RRMSE <= 25% per season; NSE descriptive only",
                "nitrogen_response": "25SP mean N2-N0 > 0 and mean N1-N0 > 0; 26SP N-response absolute error improves >=30% versus A",
                "response_layers": "at least 3 complete season x water x N layers improve",
                "protected_fit": "fresh yield scale, LAI and W_RESPONSE do not decline by >0.05 versus A",
                "candidate_rule": "engineering gate, then deterministic all-22 replay and hard gates before Phi ranking",
            },
            "pest_ies": {"num_reals": 60, "noptmax": 3, "agents": 6, "random_seed": 42},
        })
        design_path = CONFIG_DIR / f"e02_v46_best71_n_{arm}_{spec['label']}_60x3_20260831.json"
        design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest.append({
            "arm": arm,
            "label": spec["label"],
            "nse_lambda": spec["nse_lambda"],
            "bounds_id": bounds_id,
            "bounds_path": str(bounds_path.relative_to(ROOT)),
            "design_path": str(design_path.relative_to(ROOT)),
            "active_parameters": ";".join(sorted(str(k).upper() for k in active)),
            "n_active": int(sum(frame["status"].eq("active"))),
            "bundle_25sp": "data/user/experiments/xxql2501_formal_scheme4_soil_20260830",
            "bundle_26sp": "data/user/experiments/xxql2601_formal_scheme4_soil_20260830",
            "soil_25sp_sha256": sha256(ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830/SOIL.SOL"),
            "soil_26sp_sha256": sha256(ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830/SOIL.SOL"),
            "mapping": MAPPING,
        })

    out = pd.DataFrame(manifest)
    out.to_csv(REPORT_DIR / "arm_configuration_manifest.csv", index=False, encoding="utf-8-sig")
    out.to_json(REPORT_DIR / "arm_configuration_manifest.json", orient="records", force_ascii=False, indent=2)
    print(out.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
