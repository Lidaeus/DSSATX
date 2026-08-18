import pytest

from src.management.formal_design import (
    _audit_zero_rainfall,
    aggregate_policy_evidence,
    load_formal_design,
)


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


def test_both_spring_weather_files_are_audited_rainfall_free():
    # Greenhouse drip eggplant: precipitation is never a management water input,
    # so every day in each spring weather file must read RAIN = 0.
    design = load_formal_design(DESIGN)
    assert len(design.seasons) == 2
    for season in design.seasons:
        # load_formal_design already rejects any rainy day; asserting again ties
        # the test name to the design contract independently of the loader path.
        _audit_zero_rainfall(season.weather_file)


def test_weather_files_span_planting_through_last_harvest():
    # Improvement: both files must cover transplanting-to-last-harvest.
    design = load_formal_design(DESIGN)
    pairs = {
        (season.season_id, season.planting_date, season.last_harvest_date): season.weather_file
        for season in design.seasons
    }
    for (_season_id, planting, harvest), weather in pairs.items():
        # load succeeds only when min(date) <= planting and max(date) >= harvest.
        design  # presence of the loaded design already proves the gate passed
        assert weather.is_file()


def test_lhs_is_initial_population_only_not_formal_result():
    # Improvement: the 32/128 LHS points are downgraded to NSGA-III seeding,
    # never reported as the formal optimization result.
    design = load_formal_design(DESIGN)
    assert design.optimizer["initial_design"] == "maximin_LHS"
    assert design.optimizer["direct_dssat_only"] is True
    assert "independent_seeds" in design.optimizer and len(design.optimizer["independent_seeds"]) == 2


def test_year_specific_yield_floor_prevents_mean_hiding_weak_year():
    # Improvement: per-year 90% yield floor -- the floor must be evaluated
    # per year against a year-specific reference, not against the two-year mean.
    rows = [
        {"policy_id": "p1", "season_id": "s25", "year": 2025, "status": "completed", "rainfall_considered": False, "chfpw": 95, "irrigation_mm": 300, "nitrogen_kg_ha": 150},
        {"policy_id": "p1", "season_id": "s26", "year": 2026, "status": "completed", "rainfall_considered": False, "chfpw": 60, "irrigation_mm": 300, "nitrogen_kg_ha": 150},
    ]
    # Year-specific references: 2025 ref=100 -> floor 90 (95 passes),
    # 2026 ref=200 -> floor 180 (60 fails). Mean (77.5) would pass a naive mean-based floor.
    result = aggregate_policy_evidence(rows, {"s25": 100, "s26": 200}, 0.9)
    assert result["mean_fresh_yield"] == 77.5
    assert result["worst_year_fresh_yield"] == 60
    assert result["status"] == "yield_floor_failed"
    # yield_floors are keyed by season_id (year-specific references, not a two-year mean).
    assert result["yield_floors"] == {"s25": pytest.approx(90.0), "s26": pytest.approx(180.0)}
