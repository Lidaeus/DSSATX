"""Audited sensitivity-output contracts shared by case building and runs."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = PROJECT_ROOT / "configs" / "sa" / "eggplant_p1_outputs.json"


def load_output_contract(path: str | Path = DEFAULT_PROFILE) -> dict[str, object]:
    profile_path = Path(path).resolve()
    contract = json.loads(profile_path.read_text(encoding="utf-8"))
    treatments = [int(value) for value in contract.get("treatments", [])]
    features = [str(value).strip().upper() for value in contract.get("features", []) if str(value).strip()]
    legacy_time_points = [int(value) for value in contract.get("time_points", [])]
    lai_time_points = [
        int(value) for value in contract.get("lai_time_points", legacy_time_points)
    ]
    fruit_time_points = [
        int(value) for value in contract.get("fruit_time_points", legacy_time_points)
    ]
    if not treatments or len(treatments) != len(set(treatments)):
        raise ValueError("Output contract treatments must be a non-empty unique list")
    if not features or len(features) != len(set(features)):
        raise ValueError("Output contract features must be a non-empty unique list")
    for field_name, values in (
        ("lai_time_points", lai_time_points),
        ("fruit_time_points", fruit_time_points),
    ):
        if any(value <= 0 for value in values) or len(values) != len(set(values)):
            raise ValueError(f"Output contract {field_name} must be positive and unique")
    if "MDAPS" in features:
        raise ValueError("MDAPS is unavailable for the reviewed XXQL2501 case")
    design = contract.get("water_nitrogen_design")
    if design is not None:
        if not isinstance(design, dict):
            raise ValueError("water_nitrogen_design must be an object")
        water_pairs = design.get("water_pairs")
        nitrogen_series = design.get("nitrogen_series")
        contrast_features = [
            str(value).strip().upper()
            for value in design.get("contrast_features", [])
            if str(value).strip()
        ]
        if not isinstance(water_pairs, dict) or not water_pairs:
            raise ValueError("water_nitrogen_design must declare water_pairs")
        if not isinstance(nitrogen_series, dict) or set(nitrogen_series) != {"W3", "W1"}:
            raise ValueError("water_nitrogen_design nitrogen_series must declare W3 and W1")
        if not contrast_features or len(contrast_features) != len(set(contrast_features)):
            raise ValueError("water_nitrogen_design contrast_features must be non-empty and unique")
        unavailable = sorted(set(contrast_features) - set(features))
        if unavailable:
            raise ValueError(f"Contrast features are absent from base features: {unavailable}")
        used_treatments: set[int] = set()
        normalized_pairs: dict[str, list[int]] = {}
        for nitrogen_level, pair in water_pairs.items():
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError(f"Water pair {nitrogen_level} must contain [W3, W1]")
            normalized = [int(value) for value in pair]
            normalized_pairs[str(nitrogen_level).upper()] = normalized
            used_treatments.update(normalized)
        normalized_series: dict[str, list[dict[str, float | int]]] = {}
        for water_level, rows in nitrogen_series.items():
            if not isinstance(rows, list) or len(rows) < 2:
                raise ValueError(f"Nitrogen series {water_level} must contain at least two doses")
            normalized_rows = []
            for row in rows:
                if not isinstance(row, dict) or "treatment" not in row or "n_kg_ha" not in row:
                    raise ValueError(f"Invalid nitrogen series row in {water_level}")
                treatment = int(row["treatment"])
                normalized_rows.append({"treatment": treatment, "n_kg_ha": float(row["n_kg_ha"])})
                used_treatments.add(treatment)
            doses = [float(row["n_kg_ha"]) for row in normalized_rows]
            if len(doses) != len(set(doses)):
                raise ValueError(f"Nitrogen series {water_level} contains duplicate doses")
            normalized_series[str(water_level)] = normalized_rows
        if not used_treatments.issubset(set(treatments)):
            raise ValueError("Water-nitrogen design references treatments outside the output contract")
        design["water_pairs"] = normalized_pairs
        design["nitrogen_series"] = normalized_series
        design["contrast_features"] = contrast_features
    contract["treatments"] = treatments
    contract["features"] = features
    contract["lai_time_points"] = lai_time_points
    contract["fruit_time_points"] = fruit_time_points
    contract["time_points"] = sorted(set(lai_time_points) | set(fruit_time_points))
    contract["path"] = str(profile_path)
    return contract


def observation_names(contract: dict[str, object]) -> list[str]:
    names: list[str] = []
    for treatment in contract["treatments"]:
        prefix = f"TN{int(treatment)}_"
        names.extend(prefix + feature for feature in contract["features"])
        names.extend(
            f"{prefix}LAI_DAP{int(dap):03d}" for dap in contract["lai_time_points"]
        )
        names.extend(
            f"{prefix}FRUITD_DAP{int(dap):03d}"
            for dap in contract["fruit_time_points"]
        )
    if contract.get("include_treatment_mean", False):
        names.extend("MEAN_" + feature for feature in contract["features"])
        names.extend(
            f"MEAN_LAI_DAP{int(dap):03d}" for dap in contract["lai_time_points"]
        )
        names.extend(
            f"MEAN_FRUITD_DAP{int(dap):03d}"
            for dap in contract["fruit_time_points"]
        )
    design = contract.get("water_nitrogen_design")
    if isinstance(design, dict):
        for feature in design["contrast_features"]:
            names.extend(
                f"WN_WATER_{str(level).upper()}_{feature}"
                for level in design["water_pairs"]
            )
            names.extend(f"WN_NSLOPE_{water}_{feature}" for water in ("W3", "W1"))
            names.append(f"WN_INTERACTION_{feature}")
    return names


__all__ = ["DEFAULT_PROFILE", "load_output_contract", "observation_names"]
