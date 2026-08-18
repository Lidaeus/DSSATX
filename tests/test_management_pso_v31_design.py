from __future__ import annotations

from pathlib import Path

from src.management.pso_design import (
    estimate_run_budget,
    load_and_validate_pso_design,
)


DESIGN = Path(
    "configs/management/eggplant_greenhouse_drip_pso_sequence_v3_1.json"
)


def test_v31_contract_is_valid_and_uses_current_two_spring_inputs():
    payload = load_and_validate_pso_design(DESIGN)
    assert [row["year"] for row in payload["seasons"]] == [2025, 2026]
    assert payload["surrogate_model"] is False
    assert payload["rainfall_as_management_input"] is False
    assert payload["status"] == "implementation_contract_ready_runner_pending"


def test_v31_reduces_primary_search_and_avoids_stability_double_counting():
    payload = load_and_validate_pso_design(DESIGN)
    assert payload["primary_parameterization"]["dimension_count"] == 13
    criteria = [row["name"] for row in payload["ahp"]["criteria"]]
    assert criteria == [
        "mean_fresh_yield",
        "worst_year_fresh_yield",
        "seasonal_irrigation_mm",
        "seasonal_nitrogen_kg_ha",
    ]
    assert "interannual_yield_gap_fraction" in payload["diagnostic_indicators"]


def test_v31_budget_is_explicit_and_matches_algorithm_phases():
    payload = load_and_validate_pso_design(DESIGN)
    budget = estimate_run_budget(payload)
    assert budget.preflight_runs == 320
    assert budget.minimum_total_runs == 7120
    assert budget.maximum_total_runs == 14640
    assert payload["execution_budget"]["prohibited"].startswith("launch_maximum")


def test_v31_exposes_all_implementation_exit_artifacts():
    payload = load_and_validate_pso_design(DESIGN)
    phases = payload["implementation_phases"]
    assert [row["id"] for row in phases] == ["P0", "P1", "P2", "P3", "P4", "P5", "P6"]
    assert all(row["exit_artifacts"] for row in phases)
    assert next(row for row in phases if row["id"] == "P1")["status"] == "pending"
