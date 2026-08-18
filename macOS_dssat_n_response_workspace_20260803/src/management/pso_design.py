"""Validation and run-budget accounting for the v3.1 PSO sequence design."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

from src.management.formal_design import load_formal_design
from src.management.nitrogen_sequence import ahp_priority_weights


@dataclass(frozen=True)
class RunBudget:
    preflight_runs: int
    minimum_total_runs: int
    maximum_total_runs: int


def estimate_run_budget(payload: dict[str, Any]) -> RunBudget:
    """Return worst-case no-cache counts of single-season DSSAT executions."""
    seasons = len(payload["seasons"])
    optimizer = payload["optimizer"]
    selected = int(payload["local_refinement_parameterization"]["candidate_limit"])
    perturbations = 10

    preflight = int(optimizer["initial_design"]["candidates"]) * seasons
    balanced = optimizer["balanced_discovery"]
    balanced_min = (
        len(balanced["independent_seeds"])
        * int(balanced["swarm_size"])
        * int(balanced["minimum_iterations"])
        * seasons
    )
    balanced_max = (
        len(balanced["independent_seeds"])
        * int(balanced["swarm_size"])
        * int(balanced["maximum_iterations"])
        * seasons
    )
    refinement = optimizer["preference_refinement"]
    profiles = len(refinement["profiles"])
    refinement_min = (
        profiles
        * len(refinement["initial_seeds"])
        * int(refinement["swarm_size"])
        * int(refinement["minimum_iterations"])
        * seasons
    )
    # Maximum budget confirms every preference profile with the extra seed.
    refinement_max = (
        profiles
        * (len(refinement["initial_seeds"]) + 1)
        * int(refinement["swarm_size"])
        * int(refinement["maximum_iterations"])
        * seasons
    )
    local = selected * perturbations * seasons
    return RunBudget(
        preflight_runs=preflight,
        minimum_total_runs=preflight + balanced_min + refinement_min + local,
        maximum_total_runs=preflight + balanced_max + refinement_max + local,
    )


def load_and_validate_pso_design(path: str | Path) -> dict[str, Any]:
    """Load v3.1 and fail early on methodological or execution-contract drift."""
    config_path = Path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    load_formal_design(config_path)  # weather, years, objectives, rainfall, surrogate gates

    if payload.get("supersedes") != "eggplant_greenhouse_drip_pso_sequence_v3":
        raise ValueError("v3.1 must declare the v3 design it supersedes")
    if payload["primary_parameterization"]["dimension_count"] != (
        len(payload["primary_parameterization"]["water_variables"])
        + len(payload["primary_parameterization"]["nitrogen_variables"])
    ):
        raise ValueError("primary decision dimension does not match declared variables")

    objective_names = [row["name"] for row in payload["objectives"]]
    criterion_names = [row["name"] for row in payload["ahp"]["criteria"]]
    if criterion_names != objective_names:
        raise ValueError("AHP criteria must match the four primary objectives in order")
    if "interannual_yield_gap_fraction" in criterion_names:
        raise ValueError("interannual yield gap must remain diagnostic to avoid double counting")
    if "interannual_yield_gap_fraction" not in payload["diagnostic_indicators"]:
        raise ValueError("interannual yield gap diagnostic is missing")

    threshold = float(payload["ahp"]["consistency_ratio_max"])
    for name, profile in payload["ahp"]["profiles"].items():
        matrix = profile["pairwise_matrix"]
        if len(matrix) != len(criterion_names):
            raise ValueError(f"AHP profile {name} has the wrong matrix size")
        ahp_priority_weights(matrix, threshold)

    if payload["reference_policy"]["freeze_before_search"] is not True:
        raise ValueError("reference policy must be frozen before search")
    reference_floor = float(payload["reference_policy"]["yield_floor_fraction"])
    constraint_floor = float(
        payload["hard_constraints"]["yield_floor_fraction_of_year_specific_reference"]
    )
    if not math.isclose(reference_floor, constraint_floor, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("reference-policy and hard-constraint yield floors must match")
    if payload["optimizer"]["direct_dssat_only"] is not True:
        raise ValueError("v3.1 prohibits surrogate-model objective evaluation")
    if payload["execution_budget"]["pilot_runtime_measurement_required"] is not True:
        raise ValueError("large-search budget requires a measured pilot runtime")

    budget = estimate_run_budget(payload)
    declared = payload["execution_budget"]
    if budget.preflight_runs != int(declared["preflight_runs"]):
        raise ValueError("declared preflight run budget is inconsistent")
    if budget.minimum_total_runs != int(declared["minimum_total_runs"]):
        raise ValueError("declared minimum run budget is inconsistent")
    if budget.maximum_total_runs != int(declared["maximum_total_runs"]):
        raise ValueError("declared maximum run budget is inconsistent")
    return payload
