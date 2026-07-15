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
    time_points = [int(value) for value in contract.get("time_points", [])]
    if not treatments or len(treatments) != len(set(treatments)):
        raise ValueError("Output contract treatments must be a non-empty unique list")
    if not features or len(features) != len(set(features)):
        raise ValueError("Output contract features must be a non-empty unique list")
    if any(value <= 0 for value in time_points) or len(time_points) != len(set(time_points)):
        raise ValueError("Output contract time_points must be positive and unique")
    if "MDAPS" in features:
        raise ValueError("MDAPS is unavailable for the reviewed XXQL2501 case")
    contract["treatments"] = treatments
    contract["features"] = features
    contract["time_points"] = time_points
    contract["path"] = str(profile_path)
    return contract


def observation_names(contract: dict[str, object]) -> list[str]:
    names: list[str] = []
    for treatment in contract["treatments"]:
        prefix = f"TN{int(treatment)}_"
        names.extend(prefix + feature for feature in contract["features"])
        for dap in contract["time_points"]:
            names.extend((f"{prefix}LAI_DAP{int(dap):03d}", f"{prefix}FRUITD_DAP{int(dap):03d}"))
    if contract.get("include_treatment_mean", False):
        names.extend("MEAN_" + feature for feature in contract["features"])
        for dap in contract["time_points"]:
            names.extend((f"MEAN_LAI_DAP{int(dap):03d}", f"MEAN_FRUITD_DAP{int(dap):03d}"))
    return names


__all__ = ["DEFAULT_PROFILE", "load_output_contract", "observation_names"]
