"""Freeze the S1/S2 spring-validated formal E02 bounds and design."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[2]
BOUNDS_ID = "eggplant_e02_formal_s1s2_springvalidated_bounds_20260828"
BOUNDS_DIR = ROOT / "data/parameter_registry/bounds_frozen/eggplant"
CONFIG_PATH = ROOT / "configs/runs/e02_formal_s1s2_springvalidated_200x6_20260828.json"

S1_BOUNDS = BOUNDS_DIR / "eggplant_e02_s1_canopy_parallel_bounds_20260827.csv"
S2_BOUNDS = BOUNDS_DIR / "eggplant_e02_s2_yield_parallel_bounds_20260827.csv"
S1_PAR = ROOT / "workspace/runs/e02_s1_canopy_corrected_v2_0_4_60cm_100x5_20260828/e02_s1_canopy_corrected_v2_20260828.5.par.csv"
S2_PAR = ROOT / "workspace/runs/e02_from_scratch_s2_yield_parallel_0_4_60cm_20260827/e02_s2_par_yield.5.par.csv"
S2_ANCHOR = ROOT / "workspace/reports/e02_formal_candidate_validation_20260828/candidates/s2_ordered51_params.csv"
VALIDATION_METRICS = ROOT / "workspace/reports/e02_formal_candidate_validation_20260828/metrics_by_candidate_role.csv"

ACTIVE = {
    "cadstf", "csdl", "dswbar", "em-fl", "em-v1", "frlff", "frstmf",
    "kc_slope", "kcan", "kdif", "lfmax", "parmax", "pgeff", "pm06",
    "podur", "pormin", "porpt", "rtexf", "rwumx", "sdpdv", "sfdur",
    "shlag", "sizlf", "sizref", "slaref", "slavr", "tb1", "tb2",
    "thrsh", "tm2", "to11", "trifl", "vssink", "wtfsd", "xfint",
    "xfpht", "xfrmax", "xfrt", "xmage",
}

BUNDLES = {
    "25SP": "xxql2501_from_scratch_0_4_60cm_formalprep_20260828",
    "26SP": "xxql2601_from_scratch_0_4_60cm_formalprep_20260828",
    "25FA": "xxfa_from_scratch_0_4_60cm_formalprep_20260828",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _posterior_evidence(
    bounds: pd.DataFrame, ensemble: pd.DataFrame
) -> dict[str, dict[str, float]]:
    evidence = {}
    for _, row in bounds[bounds["status"].eq("active")].iterrows():
        name = str(row["name"]).lower()
        values = pd.to_numeric(ensemble[name], errors="coerce").dropna()
        span = float(row["upper"] - row["lower"])
        evidence[name] = {
            "q05": float(values.quantile(0.05)),
            "q95": float(values.quantile(0.95)),
            "lower_edge": float((((values - row["lower"]) / span) < 0.05).mean()),
            "upper_edge": float((((row["upper"] - values) / span) < 0.05).mean()),
        }
    return evidence


def main() -> int:
    if not VALIDATION_METRICS.is_file():
        raise FileNotFoundError("spring validation metrics must exist before bounds freeze")

    b1 = pd.read_csv(S1_BOUNDS)
    b2 = pd.read_csv(S2_BOUNDS)
    p1 = pd.read_csv(S1_PAR)
    p2 = pd.read_csv(S2_PAR)
    e1 = _posterior_evidence(b1, p1)
    e2 = _posterior_evidence(b2, p2)
    anchor = pd.read_csv(S2_ANCHOR)
    anchor_values = dict(zip(anchor["name"].str.lower(), anchor["value"]))

    base = b1.copy()
    base["name"] = base["name"].astype(str).str.lower()
    lookup2 = b2.assign(name=b2["name"].astype(str).str.lower()).set_index("name")
    decisions = []
    for idx, row in base.iterrows():
        name = row["name"]
        init = float(anchor_values.get(name, row["init"]))
        base.at[idx, "init"] = init
        if name not in ACTIVE:
            base.at[idx, "status"] = "fixed"
            base.at[idx, "lower"] = init
            base.at[idx, "upper"] = init
            continue

        source_rows = [row]
        if name in lookup2.index:
            source_rows.append(lookup2.loc[name])
        prior_lower = min(float(item["lower"]) for item in source_rows)
        prior_upper = max(float(item["upper"]) for item in source_rows)
        prior_span = prior_upper - prior_lower
        arms = [evidence[name] for evidence in (e1, e2) if name in evidence]
        if not arms or prior_span <= 0:
            raise ValueError(f"active parameter lacks posterior/prior span: {name}")
        q05 = min(item["q05"] for item in arms)
        q95 = max(item["q95"] for item in arms)
        lower = max(prior_lower, q05 - 0.10 * prior_span)
        upper = min(prior_upper, q95 + 0.10 * prior_span)
        if any(item["lower_edge"] >= 0.10 for item in arms):
            lower = prior_lower
        if any(item["upper_edge"] >= 0.10 for item in arms):
            upper = prior_upper
        if not lower < init < upper:
            lower = min(lower, init - 0.02 * prior_span)
            upper = max(upper, init + 0.02 * prior_span)
            lower = max(prior_lower, lower)
            upper = min(prior_upper, upper)
        base.at[idx, "status"] = "active"
        base.at[idx, "lower"] = lower
        base.at[idx, "upper"] = upper
        decisions.append(
            {
                "name": name, "init": init, "lower": lower, "upper": upper,
                "prior_lower": prior_lower, "prior_upper": prior_upper,
                "posterior_q05_union": q05, "posterior_q95_union": q95,
            }
        )

    if set(base.loc[base.status.eq("active"), "name"]) != ACTIVE:
        raise AssertionError("formal active parameter set mismatch")
    for name, fixed_value in {"soil_slpf": 0.90, "soil_slnf": 3.20, "fl-vs": 100.0}.items():
        mask = base["name"].eq(name)
        if mask.any():
            base.loc[mask, ["init", "lower", "upper"]] = fixed_value
            base.loc[mask, "status"] = "fixed"

    # Enforce the stage-order constraint for every ensemble draw, not only the
    # centre vector.  Use the midpoint of the validated ordered anchor and a
    # small gap so independent parameter sampling cannot produce XMAGE>=XFPHT.
    xmage_init = float(anchor_values["xmage"])
    xfpht_init = float(anchor_values["xfpht"])
    split = (xmage_init + xfpht_init) / 2.0
    xmage_mask = base["name"].eq("xmage")
    xfpht_mask = base["name"].eq("xfpht")
    base.loc[xmage_mask, "upper"] = min(float(base.loc[xmage_mask, "upper"].iloc[0]), split - 0.05)
    base.loc[xfpht_mask, "lower"] = max(float(base.loc[xfpht_mask, "lower"].iloc[0]), split + 0.05)
    for decision in decisions:
        if decision["name"] in {"xmage", "xfpht"}:
            selected = base.loc[base["name"].eq(decision["name"])].iloc[0]
            decision["lower"] = float(selected["lower"])
            decision["upper"] = float(selected["upper"])

    bounds_csv = BOUNDS_DIR / f"{BOUNDS_ID}.csv"
    bounds_yaml = BOUNDS_DIR / f"{BOUNDS_ID}.yaml"
    base.to_csv(bounds_csv, index=False, encoding="utf-8")
    metadata = {
        "bounds_id": BOUNDS_ID,
        "crop": "eggplant",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "frozen_user_approved",
        "active_parameter_count": len(ACTIVE),
        "init_anchor": "s2_ordered51 current-soil deterministic candidate; best low-Phi S2 member satisfying XMAGE < XFPHT",
        "boundary_rule": "S1/S2 Q05-Q95 union plus 10% prior-span padding; pressured side retains prior bound",
        "validation_priority": "25SP/26SP held-out spring treatments; 25FA locked",
        "history_decision": "excluded after current-soil replay",
        "source_bounds": [str(S1_BOUNDS), str(S2_BOUNDS)],
        "validation_metrics_sha256": _sha(VALIDATION_METRICS),
    }
    bounds_yaml.write_text(yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False), encoding="utf-8")

    experiment_root = ROOT / "data/user/experiments"
    hashes = {
        season: _sha(experiment_root / bundle / "input_manifest.json")
        for season, bundle in BUNDLES.items()
    }
    config = {
        "schema_version": 1,
        "status": "formal_approved_calibration",
        "design_id": "e02_formal_s1s2_springvalidated_200x6_20260828",
        "stage": "S5",
        "purpose": "Formal joint calibration from corrected parallel S1/S2 with held-out spring validation",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "genetic_and_approved_crop_physiology_only; soil_and_IC_fixed",
        "bounds_id": BOUNDS_ID,
        "observation_policy": "configs/runs/e02_from_scratch_objective_contract_20260826.csv",
        "group_policy": "configs/runs/e02_from_scratch_group_policy_20260826.csv",
        "initial_condition_policy": "frozen 0-4/4-60cm current soil; measured treatment IC; soil_slpf=0.90; soil_slnf=3.20",
        "nitrogen_response_objective": {
            "enabled": True, "mapping_csv": "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv",
            "weighting": "season_nse", "nse_lambda": 1.0, "sigma_floor": 50.0,
            "contrast": "N3_minus_N0_within_same_water", "contrast_scale": "raw_difference",
            "response_target": "observed_shape", "levels": ["N3"], "harvest_scope": "all",
            "sst_scope": "season_x_family",
        },
        "water_response_objective": {
            "enabled": True, "mapping_csv": "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv",
            "weighting": "season_nse", "nse_lambda": 0.5, "sigma_floor": 50.0,
            "contrast": "W3_minus_W1_within_same_nitrogen", "contrast_scale": "raw_difference",
            "response_target": "observed_shape", "levels": ["N3"], "nitrogen_levels": ["N0", "N3"],
            "harvest_scope": "all", "season_contrasts": {
                "25SP": {"high_water": "W3", "low_water": "W1"},
                "26SP": {"high_water": "W3", "low_water": "W1"},
                "25FA": {"high_water": "W3", "low_water": "W1"},
            }, "sst_scope": "season_x_family",
        },
        "harvest_dry_objective": {
            "enabled": True, "mode": "increment_plus_terminal",
            "increment_source": "measured_hpodw", "variable": "CHPDT",
        },
        "process_state_objective": {
            "enabled": True, "mode": "signed_difference_plus_terminal",
            "variables": ["LAID", "LWAD", "SWAD"],
        },
        "seasons": [
            {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": f"data/user/experiments/{BUNDLES['25SP']}", "bundle_manifest_sha256": hashes["25SP"], "role": "calibration", "treatments": [2, 5, 10, 13]},
            {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": f"data/user/experiments/{BUNDLES['26SP']}", "bundle_manifest_sha256": hashes["26SP"], "role": "calibration", "treatments": [1, 3, 9, 12]},
            {"season_id": "25FA", "experiment_code": "XXQL2502", "bundle_path": f"data/user/experiments/{BUNDLES['25FA']}", "bundle_manifest_sha256": hashes["25FA"], "role": "validation", "treatments": list(range(1, 13))},
        ],
        "diagnostic_only": {
            "25SP": [3, 4, 9, 11, 12, 14],
            "26SP": [2, 4, 5, 6, 7, 8, 10, 11],
            "25FA": "locked; not used for tuning, bounds, or candidate selection",
        },
        "pest_ies": {"num_reals": 200, "noptmax": 6, "agents": 6, "random_seed": 42, "status": "approved"},
    }
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    decision_path = ROOT / "workspace/reports/e02_formal_candidate_validation_20260828/formal_bounds_decisions.csv"
    pd.DataFrame(decisions).to_csv(decision_path, index=False, encoding="utf-8-sig")
    print(json.dumps({"bounds_csv": str(bounds_csv), "config": str(CONFIG_PATH), "active": len(ACTIVE)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
