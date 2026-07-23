import pytest

from src.management.formal_design import aggregate_policy_evidence, load_formal_design


DESIGN = "configs/management/eggplant_greenhouse_drip_formal_v2.json"


def test_formal_design_uses_two_spring_weather_years_and_no_surrogate():
    design = load_formal_design(DESIGN)
    assert [season.year for season in design.seasons] == [2025, 2026]
    assert design.optimizer["algorithm"] == "NSGA-III"
    assert design.optimizer["direct_dssat_only"] is True


def test_robust_aggregation_preserves_worst_year_and_common_policy():
    rows = [
        {"policy_id": "p1", "season_id": "s25", "year": 2025, "status": "completed", "rainfall_considered": False, "chfpw": 100, "irrigation_mm": 300, "nitrogen_kg_ha": 150},
        {"policy_id": "p1", "season_id": "s26", "year": 2026, "status": "completed", "rainfall_considered": False, "chfpw": 80, "irrigation_mm": 300, "nitrogen_kg_ha": 150},
    ]
    result = aggregate_policy_evidence(rows, {"s25": 100, "s26": 100}, 0.9)
    assert result["mean_fresh_yield"] == 90
    assert result["worst_year_fresh_yield"] == 80
    assert result["status"] == "yield_floor_failed"
    with pytest.raises(ValueError, match="common seasonal policy"):
        aggregate_policy_evidence([rows[0], {**rows[1], "irrigation_mm": 301}], {"s25": 100, "s26": 100}, 0.9)
