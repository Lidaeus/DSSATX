"""Formal two-spring robust water--nitrogen optimisation contract."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable


@dataclass(frozen=True)
class SpringSeason:
    season_id: str
    year: int
    weather_file: Path
    planting_date: int
    last_harvest_date: int
    actual_input_bundle: Path
    template_treatment: int


@dataclass(frozen=True)
class FormalManagementDesign:
    design_id: str
    seasons: tuple[SpringSeason, ...]
    objectives: tuple[str, ...]
    yield_floor_fraction: float
    optimizer: dict[str, Any]


def _weather_records(path: Path) -> list[tuple[int, float]]:
    """Return ``(YYYYDDD, RAIN)`` pairs from a DSSAT .WTH file.

    Records are the whitespace-separated data rows whose first field is a
    seven-digit year-day code. RAIN is the fifth column. Missing/non-data
    rows (headers, blanks) are skipped.
    """
    records: list[tuple[int, float]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        fields = line.split()
        if fields and fields[0].isdigit() and len(fields[0]) == 7:
            try:
                rain = float(fields[4]) if len(fields) >= 5 else 0.0
            except ValueError:
                rain = 0.0
            records.append((int(fields[0]), rain))
    return records


def _weather_dates(path: Path) -> list[int]:
    return [date for date, _rain in _weather_records(path)]


def _audit_zero_rainfall(path: Path) -> None:
    """The greenhouse has no rainfall input: every weather record must be RAIN=0.

    This enforces the v2 design's separation of weather (read by DSSAT) from
    management water supply (drip irrigation only). A non-zero day would mean
    the model is silently adding precipitation to the root zone and the formal
    run is no longer rainfall-free.
    """
    records = _weather_records(path)
    rainy_days = [(date, rain) for date, rain in records if rain > 0]
    if rainy_days:
        sample = ", ".join(f"{d}={r:g}" for d, r in rainy_days[:5])
        raise ValueError(
            f"weather file is not rainfall-free ({len(rainy_days)} non-zero days): "
            f"{path} -- first: {sample}"
        )


def _full_date(date_code: int) -> int:
    """Normalize DSSAT YYDDD FileX dates to the YYYYDDD weather convention."""
    text = str(int(date_code))
    if len(text) == 5:
        return int("20" + text)
    if len(text) == 7:
        return int(text)
    raise ValueError(f"unsupported DSSAT date code: {date_code}")


def load_formal_design(path: str | Path) -> FormalManagementDesign:
    config_path = Path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if payload.get("production_system") != "greenhouse_drip_eggplant":
        raise ValueError("formal design must target greenhouse drip eggplant")
    if payload.get("surrogate_model") is not False:
        raise ValueError("surrogate models are prohibited for this design")
    if payload.get("rainfall_as_management_input") is not False:
        raise ValueError("rainfall cannot be a greenhouse management input")
    seasons = []
    for row in payload.get("seasons", []):
        weather = Path(row["weather_file"])
        bundle = Path(row["actual_input_bundle"])
        if not weather.is_file() or not bundle.is_dir():
            raise FileNotFoundError(f"formal season inputs are unavailable: {row['season_id']}")
        dates = _weather_dates(weather)
        planting, harvest = int(row["planting_date"]), int(row["last_harvest_date"])
        if not dates or min(dates) > _full_date(planting) or max(dates) < _full_date(harvest):
            raise ValueError(f"weather coverage does not span planting-to-harvest: {row['season_id']}")
        # Greenhouse drip system: precipitation is never a management water source.
        _audit_zero_rainfall(weather)
        if planting // 1000 != int(row["year"]) % 100 or harvest // 1000 != int(row["year"]) % 100:
            raise ValueError(f"season date codes do not match year: {row['season_id']}")
        seasons.append(SpringSeason(str(row["season_id"]), int(row["year"]), weather, planting, harvest, bundle, int(row["template_treatment"])))
    if [season.year for season in seasons] != [2025, 2026]:
        raise ValueError("formal optimization must use exactly the 2025 and 2026 spring weather years")
    objective_names = tuple(item["name"] for item in payload.get("objectives", []))
    required = {"mean_fresh_yield", "worst_year_fresh_yield", "seasonal_irrigation_mm", "seasonal_nitrogen_kg_ha"}
    if set(objective_names) != required:
        raise ValueError("formal objective set is incomplete")
    return FormalManagementDesign(str(payload["design_id"]), tuple(seasons), objective_names, float(payload["hard_constraints"]["yield_floor_fraction_of_year_specific_reference"]), dict(payload["optimizer"]))


def aggregate_policy_evidence(season_rows: Iterable[dict[str, Any]], reference_yields: dict[str, float], yield_floor_fraction: float) -> dict[str, Any]:
    """Aggregate paired-year direct DSSAT results without hiding the weak year."""
    rows = list(season_rows)
    if len(rows) != 2 or {int(row["year"]) for row in rows} != {2025, 2026}:
        raise ValueError("one completed result is required for each spring weather year")
    if any(row.get("status") != "completed" or bool(row.get("rainfall_considered")) for row in rows):
        raise ValueError("formal aggregation accepts only completed rainfall-free direct DSSAT runs")
    yields = [float(row["chfpw"]) for row in rows]
    floors = {row["season_id"]: yield_floor_fraction * float(reference_yields[row["season_id"]]) for row in rows}
    feasible = all(float(row["chfpw"]) >= floors[row["season_id"]] for row in rows)
    mean_yield = fmean(yields)
    water = float(rows[0]["irrigation_mm"]); nitrogen = float(rows[0]["nitrogen_kg_ha"])
    if any(abs(float(row["irrigation_mm"]) - water) > 1e-9 or abs(float(row["nitrogen_kg_ha"]) - nitrogen) > 1e-9 for row in rows[1:]):
        raise ValueError("paired weather years must receive one common seasonal policy")
    return {
        "policy_id": rows[0]["policy_id"],
        "status": "feasible" if feasible else "yield_floor_failed",
        "mean_fresh_yield": mean_yield,
        "worst_year_fresh_yield": min(yields),
        "interannual_yield_gap_fraction": abs(yields[0] - yields[1]) / mean_yield if mean_yield else float("inf"),
        "seasonal_irrigation_mm": water,
        "seasonal_nitrogen_kg_ha": nitrogen,
        "irrigation_water_productivity": mean_yield / water if water > 0 else float("inf"),
        "partial_factor_productivity_of_nitrogen": mean_yield / nitrogen if nitrogen > 0 else None,
        "year_yields": {str(row["year"]): float(row["chfpw"]) for row in rows},
        "yield_floors": floors,
    }
