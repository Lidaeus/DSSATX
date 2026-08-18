"""Deterministic, direct-DSSAT candidate generation and Pareto extraction."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import random
from typing import Any

from .core import ManagementScenario, load_design


def _lhs(n: int, dimensions: int, seed: int) -> list[list[float]]:
    rng = random.Random(seed); columns = []
    for _ in range(dimensions):
        values = [(i + rng.random()) / n for i in range(n)]; rng.shuffle(values); columns.append(values)
    return [[columns[col][row] for col in range(dimensions)] for row in range(n)]


def _simplex(values: list[float], count: int, floor: float) -> tuple[float, ...]:
    raw = [-math.log(max(value, 1e-12)) for value in values[:count]]; denominator = sum(raw)
    return tuple(floor + (1 - count * floor) * value / denominator for value in raw)


def generate_candidates(design_path: str | Path, parameter_set_id: str, target_treatment: int, n: int, seed: int) -> list[ManagementScenario]:
    """Generate reproducible water/N schedules; rainfall is intentionally absent."""
    payload = json.loads(Path(design_path).read_text(encoding="utf-8")); design = load_design(design_path); bounds = payload["demo_search_bounds"]
    if n < 1: raise ValueError("candidate count must be positive")
    water_lo, water_hi = map(float, bounds["irrigation_mm"]); n_lo, n_hi = map(float, bounds["nitrogen_kg_ha"]); floor = float(bounds["stage_share_floor"])
    if floor * 4 >= 1: raise ValueError("stage share floor leaves no variable mass")
    result = []
    for index, values in enumerate(_lhs(n, 9, seed), 1):
        result.append(ManagementScenario(f"DEMO_lhs_{index:03d}", parameter_set_id, design.management_design_id, water_lo + values[0] * (water_hi - water_lo), n_lo + values[1] * (n_hi - n_lo), _simplex(values[2:6], 4, floor), (*_simplex(values[6:9], 3, floor), 0.0), target_treatment))
    return result


def nondominated(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First front: maximize CHFPW, minimize seasonal irrigation and N."""
    valid = [row for row in rows if row.get("status") == "completed"]
    return [row for row in valid if not any(other is not row and float(other["chfpw"]) >= float(row["chfpw"]) and float(other["irrigation_mm"]) <= float(row["irrigation_mm"]) and float(other["nitrogen_kg_ha"]) <= float(row["nitrogen_kg_ha"]) and (float(other["chfpw"]) > float(row["chfpw"]) or float(other["irrigation_mm"]) < float(row["irrigation_mm"]) or float(other["nitrogen_kg_ha"]) < float(row["nitrogen_kg_ha"])) for other in valid)]


def write_candidate_table(candidates: list[ManagementScenario], destination: str | Path, seed: int) -> Path:
    destination = Path(destination); destination.parent.mkdir(parents=True, exist_ok=True)
    fields = ["scenario_id", "parameter_set_id", "irrigation_mm", "nitrogen_kg_ha", "w_s1", "w_s2", "w_s3", "w_s4", "n_s1", "n_s2", "n_s3", "n_s4", "seed", "rainfall_considered"]
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for item in candidates: writer.writerow({"scenario_id": item.scenario_id, "parameter_set_id": item.parameter_set_id, "irrigation_mm": item.total_irrigation_mm, "nitrogen_kg_ha": item.total_nitrogen_kg_ha, **{f"w_s{i+1}": value for i, value in enumerate(item.irrigation_stage_shares)}, **{f"n_s{i+1}": value for i, value in enumerate(item.nitrogen_stage_shares)}, "seed": seed, "rainfall_considered": "false"})
    return destination
