"""Prepare the user-directed Arm-A/B formal E02 calibration.

The formal case keeps the corrected Arm-B observation inputs, activates the
full Arm-A/B crop parameter pool, permits only narrow soil movement around the
audited profile, and normalises terminal-yield residuals to seasonal RRMSE.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[2]
BOUNDS_DIR = ROOT / "data/parameter_registry/bounds_frozen/eggplant"
SOURCE_BOUNDS = BOUNDS_DIR / "eggplant_e02_joint_fused_s1_s2_bounds_20260828.csv"
PGEFF_BOUNDS = BOUNDS_DIR / "eggplant_e02_s1_canopy_fixed_pgeff_bounds_20260828.csv"
BOUNDS_ID = "eggplant_e02_formal_armab_rrmse_widescope_20260828"
CONFIG = ROOT / "configs/runs/e02_formal_armab_rrmse_200x6_20260828.json"

ARM_A_PAR = ROOT / "workspace/runs/e02_arm_a_fixed_pgeff_20260828/e02_arm_a.5.par.csv"
ARM_B_PAR = ROOT / "workspace/runs/e02_arm_b_clean_measuredn_fixed_pgeff_20260828/e02_arm_b.5.par.csv"

BUNDLES = {
    "25SP": (
        "xxql2501_clean_measuredn_0_4_60cm_20260828",
        "xxql2501_formal_armab_rrmse_20260828",
        "XXQL2501", [2, 5, 10, 13], [3, 4, 9, 11, 12, 14], "calibration",
    ),
    "26SP": (
        "xxql2601_clean_measuredn_0_4_60cm_20260828",
        "xxql2601_formal_armab_rrmse_20260828",
        "XXQL2601", [1, 3, 9, 12], [2, 4, 5, 6, 7, 8, 10, 11], "calibration",
    ),
    "25FA": (
        "xxfa_clean_measuredn_0_4_60cm_20260828",
        "xxfa_formal_armab_rrmse_20260828",
        "XXQL2502", [], [], "validation",
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rebuild_bundle(spec: tuple[str, str, str, list[int], list[int], str], season: str) -> Path:
    source_name, target_name, excode, calibration, diagnostic, role = spec
    source = ROOT / "data/user/experiments" / source_name
    target = ROOT / "data/user/experiments" / target_name
    if target.exists():
        raise FileExistsError(f"refusing to overwrite frozen bundle: {target}")
    source_manifest_path = source / "input_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    shutil.copytree(source, target)

    files = []
    for path in sorted(target.iterdir()):
        if path.is_file() and path.name != "input_manifest.json":
            files.append({"name": path.name, "sha256": sha256(path), "bytes": path.stat().st_size})
    manifest = {
        "bundle_id": target_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "derived_from_bundle": source_name,
        "derived_from_manifest_sha256": sha256(source_manifest_path),
        "season_id": season,
        "excode": excode,
        "intended_use": (
            "parameter_calibration" if role == "calibration"
            else "validation_against_observed_treatment_initial_conditions"
        ),
        "prohibited_use": ["parameter_calibration"] if role == "validation" else [],
        "scenario_role": role,
        "treatment_roles": {
            "calibration": calibration,
            "diagnostic": diagnostic,
            "validation": list(range(1, 13)) if role == "validation" else [],
        },
        "initial_condition_policy": (
            "treatment-specific measured mineral N and sequential measured soil water; "
            "copied byte-for-byte from corrected Arm-B source bundle"
        ),
        "uncertainty_policy": "replicate filtering with minimum CV=5%; FileA/FileT synchronized",
        "soil_scheme": source_manifest.get("soil_scheme", {"id": "0-4/4-60cm Arm-B profile"}),
        "data_corrections": source_manifest.get("data_corrections", {}),
        "manifest_repair": {
            "wrong_cross_season_identity_removed": True,
            "payload_hashes_regenerated": True,
            "source_payload_modified": False,
        },
        "files": files,
    }
    (target / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target


def arm_anchor(path: Path, member: str) -> pd.Series:
    frame = pd.read_csv(path).set_index("real_name")
    frame.index = frame.index.astype(str)
    return pd.to_numeric(frame.loc[member], errors="coerce")


def build_bounds() -> tuple[Path, int, int]:
    bounds = pd.read_csv(SOURCE_BOUNDS)
    bounds["name"] = bounds["name"].astype(str).str.lower()
    if "pgeff" not in set(bounds["name"]):
        pgeff = pd.read_csv(PGEFF_BOUNDS)
        pgeff["name"] = pgeff["name"].astype(str).str.lower()
        bounds = pd.concat([bounds, pgeff.loc[pgeff["name"].eq("pgeff")]], ignore_index=True)

    a = arm_anchor(ARM_A_PAR, "71")
    b = arm_anchor(ARM_B_PAR, "9")
    a.index = a.index.astype(str).str.lower()
    b.index = b.index.astype(str).str.lower()
    crop_anchor = pd.concat([a.rename("a"), b.rename("b")], axis=1).median(axis=1, skipna=True)

    soil_active = 0
    crop_active = 0
    for idx, row in bounds.iterrows():
        name = str(row["name"])
        location = str(row.get("location", "")).upper()
        if name == "fl-vs" or str(row["status"]).lower() == "fixed":
            bounds.loc[idx, ["status", "lower", "upper"]] = ["fixed", row["init"], row["init"]]
            continue
        if name.startswith("soil_"):
            if name == "soil_slpf":
                init, lower, upper = float(row["init"]), 0.86, 0.93
            else:
                try:
                    layer = int(name.rsplit("_", 1)[1])
                except ValueError:
                    layer = 99
                if layer > 6:
                    bounds.loc[idx, ["status", "lower", "upper"]] = ["fixed", row["init"], row["init"]]
                    continue
                init = float(row["init"])
                delta = 0.04 if "sbdm" in name else (0.008 if "slll" in name else (0.012 if "sdul" in name else 0.015))
                lower, upper = init - delta, init + delta
            bounds.loc[idx, ["init", "lower", "upper", "status"]] = [init, lower, upper, "active"]
            soil_active += 1
            continue

        # Keep the full Arm-A/B crop pool active. Initial values use the robust
        # midpoint of their two best members, clipped inside the explored bounds.
        init = float(crop_anchor.get(name, row["init"]))
        lower, upper = float(row["lower"]), float(row["upper"])
        if name == "pgeff":
            init, lower, upper = 0.0573454, 0.03, 0.09
        elif name == "phtmax":
            lower, upper = 45.0, 75.0
        elif name == "podur":
            lower, upper = 12.0, 58.0
        margin = max((upper - lower) * 1.0e-4, 1.0e-8)
        init = min(max(init, lower + margin), upper - margin)
        bounds.loc[idx, ["init", "lower", "upper", "status"]] = [init, lower, upper, "active"]
        crop_active += 1

    path = BOUNDS_DIR / f"{BOUNDS_ID}.csv"
    bounds.to_csv(path, index=False, encoding="utf-8")
    metadata = {
        "bounds_id": BOUNDS_ID,
        "crop": "eggplant",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "frozen_for_user_directed_formal_calibration",
        "source": "Arm A #71 and Arm B #9 midpoint within fused S1/S2 bounds",
        "crop_active": crop_active,
        "soil_active": soil_active,
        "soil_rule": "SLPF and layers 1-6 only; narrow movement around audited profile",
        "terminal_yield_metric": "seasonal treatment-level RRMSE; no terminal-yield NSE gate",
    }
    (BOUNDS_DIR / f"{BOUNDS_ID}.yaml").write_text(
        yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return path, crop_active, soil_active


def main() -> int:
    created = {season: rebuild_bundle(spec, season) for season, spec in BUNDLES.items()}
    bounds_path, crop_active, soil_active = build_bounds()
    hashes = {season: sha256(path / "input_manifest.json") for season, path in created.items()}
    config = {
        "schema_version": 1,
        "status": "formal_user_directed_calibration",
        "design_id": "e02_formal_armab_rrmse_200x6_20260828",
        "stage": "S5",
        "purpose": "Formal Arm-A/B continuation with terminal-yield RRMSE and narrow soil calibration",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "full Arm-A/B crop pool plus narrow audited soil profile movement",
        "bounds_id": BOUNDS_ID,
        "observation_policy": "configs/runs/e02_from_scratch_objective_contract_20260826.csv",
        "group_policy": "configs/runs/e02_from_scratch_group_policy_20260826.csv",
        "initial_condition_policy": "corrected Arm-B bundles; treatment IC fixed; soil profile parameters narrowly adjustable",
        "nitrogen_response_objective": {
            "enabled": True,
            "mapping_csv": "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv",
            "weighting": "season_nse", "nse_lambda": 1.0, "sigma_floor": 50.0,
            "contrast": "N3_minus_N0_within_same_water", "contrast_scale": "raw_difference",
            "response_target": "observed_shape", "levels": ["N3"], "harvest_scope": "all",
            "sst_scope": "season_x_response_stratum",
        },
        "water_response_objective": {
            "enabled": True,
            "mapping_csv": "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv",
            "weighting": "season_nse", "nse_lambda": 0.5, "sigma_floor": 50.0,
            "contrast": "W3_minus_W1_within_same_nitrogen", "contrast_scale": "raw_difference",
            "response_target": "observed_shape", "levels": ["N3"], "nitrogen_levels": ["N0", "N3"],
            "harvest_scope": "all",
            "season_contrasts": {
                "25SP": {"high_water": "W3", "low_water": "W1"},
                "26SP": {"high_water": "W3", "low_water": "W1"},
                "25FA": {"high_water": "W3", "low_water": "W1"},
            },
            "sst_scope": "season_x_response_stratum",
        },
        "harvest_dry_objective": {
            "enabled": True, "mode": "increment_plus_terminal",
            "increment_source": "measured_hpodw", "variable": "CHPDT",
            "terminal_weighting": "season_rrmse", "rrmse_lambda": 25.0,
            "acceptance_metric": "RRMSE_pct", "acceptance_threshold_pct": 25.0,
        },
        "process_state_objective": {
            "enabled": True, "mode": "signed_difference_plus_terminal",
            "variables": ["LAID", "LWAD", "SWAD"],
        },
        "seasons": [
            {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(created["25SP"].relative_to(ROOT)).replace("\\", "/"), "bundle_manifest_sha256": hashes["25SP"], "role": "calibration", "treatments": [2, 5, 10, 13]},
            {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(created["26SP"].relative_to(ROOT)).replace("\\", "/"), "bundle_manifest_sha256": hashes["26SP"], "role": "calibration", "treatments": [1, 3, 9, 12]},
            {"season_id": "25FA", "experiment_code": "XXQL2502", "bundle_path": str(created["25FA"].relative_to(ROOT)).replace("\\", "/"), "bundle_manifest_sha256": hashes["25FA"], "role": "validation", "treatments": list(range(1, 13))},
        ],
        "diagnostic_only": {
            "25SP": [3, 4, 9, 11, 12, 14],
            "26SP": [2, 4, 5, 6, 7, 8, 10, 11],
            "25FA": "locked validation; never used for tuning or bounds",
        },
        "acceptance": {
            "terminal_yield": "RRMSE <= 25% in each spring season; NSE is descriptive only",
            "cumulative_dry": "NSE decline <= 0.05 relative to accepted Arm-A/B anchor",
            "lai": "NSE >= 0.60 in each spring season",
        },
        "pest_ies": {"num_reals": 200, "noptmax": 6, "agents": 6, "random_seed": 42},
    }
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "config": str(CONFIG), "bounds": str(bounds_path),
        "crop_active": crop_active, "soil_active": soil_active,
        "bundle_manifest_sha256": hashes,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
