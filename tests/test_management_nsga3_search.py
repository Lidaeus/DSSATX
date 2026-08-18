"""Tests for the maximin-LHS seeder and NSGA-III two-spring robust search.

These exercise the search machinery with an injected mock DSSAT evaluator so no
real DSSAT licence or binary is required.  They verify the v2 design's core
mechanisms: LHS reproducibility (seeding only, not result), four-objective
directions, per-year yield-floor constraints, failed-run penalties, and the
parameter-set science gate.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.management.dap_policy import CandidatePolicy
from src.management.nsga3_search import (
    DecisionBounds,
    N_DECISIONS,
    TwoYearRobustProblem,
    build_nsga3,
    decode_to_candidate,
    evaluate_objectives,
    maximin_lhs_initial_population,
)


BOUNDS = DecisionBounds(
    irrigation_mm=(240.0, 500.0),
    nitrogen_kg_ha=(0.0, 320.0),
    irrigation_share_floor=0.08,
    nitrogen_share_floor=0.05,
)
REFS = {"2025": 100.0, "2026": 100.0}
FLOOR = 0.9


def test_lhs_is_reproducible_and_seeding_only():
    # Improvement: LHS is downgraded to a reproducible initial population.
    a = maximin_lhs_initial_population(128, BOUNDS, seed=20260723)
    b = maximin_lhs_initial_population(128, BOUNDS, seed=20260723)
    assert a.shape == (128, N_DECISIONS)
    assert np.array_equal(a, b)
    # All samples inside the unit box.
    assert np.all(a >= 0.0) and np.all(a <= 1.0)
    # Different seed -> different population.
    c = maximin_lhs_initial_population(128, BOUNDS, seed=20260806)
    assert not np.array_equal(a, c)


def test_decode_to_candidate_satisfies_simplex_and_s4_nitrogen_zero():
    candidate = decode_to_candidate(np.full(N_DECISIONS, 0.5), BOUNDS, "x")
    assert abs(sum(candidate.irrigation_stage_shares) - 1.0) < 1e-8
    assert abs(sum(candidate.nitrogen_stage_shares) - 1.0) < 1e-8
    assert candidate.nitrogen_stage_shares[3] == 0.0
    assert all(s >= BOUNDS.irrigation_share_floor - 1e-9 for s in candidate.irrigation_stage_shares[:3])


def test_evaluate_objectives_negates_yields_and_flags_infeasible_year():
    # Both years completed; 2026 below its 90 floor -> infeasible.
    candidate = decode_to_candidate(np.full(N_DECISIONS, 0.5), BOUNDS, "x")
    per_year = {
        "2025": {"chfpw": 95.0, "status": "completed"},
        "2026": {"chfpw": 80.0, "status": "completed"},
    }
    r = evaluate_objectives(per_year, candidate, REFS, FLOOR)
    # Yields maximised -> minimised as negatives.
    assert r.mean_fresh_yield == pytest.approx(-87.5)
    assert r.worst_year_fresh_yield == pytest.approx(-80.0)
    assert r.seasonal_irrigation_mm == candidate.seasonal_irrigation_mm
    assert r.seasonal_nitrogen_kg_ha == candidate.seasonal_nitrogen_kg_ha
    assert r.feasible is False  # 2026 floor 90 > 80
    assert r.failed is False


def test_evaluate_objectives_penalises_failed_dssat_runs():
    candidate = decode_to_candidate(np.full(N_DECISIONS, 0.5), BOUNDS, "x")
    per_year = {
        "2025": {"chfpw": 95.0, "status": "completed"},
        "2026": {"chfpw": float("nan"), "status": "failed"},
    }
    r = evaluate_objectives(per_year, candidate, REFS, FLOOR)
    assert r.failed is True
    assert r.feasible is False
    assert r.mean_fresh_yield > 1e8  # penalty dominates real objective magnitudes


def test_two_year_robust_problem_emits_four_objectives_and_two_constraints():
    # Mock evaluator: yield proportional to irrigation (higher water -> higher yield).
    def evaluator(candidate: CandidatePolicy):
        base = (candidate.seasonal_irrigation_mm - 240.0) / (500.0 - 240.0) * 60.0 + 40.0
        return {
            "2025": {"chfpw": base, "status": "completed"},
            "2026": {"chfpw": base * 0.9, "status": "completed"},
        }

    problem = TwoYearRobustProblem(BOUNDS, evaluator, REFS, FLOOR)
    X = np.array([[0.8] * N_DECISIONS, [0.2] * N_DECISIONS])
    out: dict = {}
    problem._evaluate(X, out)
    assert out["F"].shape == (2, 4)
    assert out["G"].shape == (2, 2)
    # Objective 3 (irrigation) and 4 (nitrogen) are minimised -> lower vector has smaller water.
    assert out["F"][1, 2] < out["F"][0, 2]  # more irrigation -> larger objective


def test_build_nsga3_accepts_lhs_initial_population():
    initial = maximin_lhs_initial_population(64, BOUNDS, seed=1)
    algo = build_nsga3(BOUNDS, {"population_size": 64}, initial_population=initial)
    assert algo.pop_size >= 1


def test_run_formal_nsga3_blocks_without_validated_parameters(tmp_path):
    # Improvement: the formal search is gated on a science_validated parameter set.
    from src.management.robust_orchestrator import run_formal_nsga3

    param_dir = tmp_path / "parameter_set"
    param_dir.mkdir()
    (param_dir / "parameter_set_manifest.json").write_text(
        json.dumps({"parameter_set_id": "p1", "science_validated": False}), encoding="utf-8"
    )
    with pytest.raises(PermissionError, match="science_validated"):
        run_formal_nsga3(
            design_path="configs/management/eggplant_greenhouse_drip_formal_v2.json",
            parameter_set_dir=param_dir,
            work_root=tmp_path / "work",
            generations=1,
            population_size=12,
            initial_candidates=12,
        )


def test_run_formal_nsga3_precheck_runs_with_mock_evaluator(tmp_path, monkeypatch):
    # Engineering precheck must run end-to-end with a mocked evaluator and write Pareto CSVs.
    import src.management.robust_orchestrator as orch

    def mock_evaluator_factory(*args, **kwargs):
        def evaluator(candidate: CandidatePolicy):
            base = (candidate.seasonal_irrigation_mm - 240.0) / (500.0 - 240.0) * 60.0 + 40.0
            return {
                "2025": {"chfpw": base, "status": "completed"},
                "2026": {"chfpw": base * 0.9, "status": "completed"},
            }
        return evaluator

    monkeypatch.setattr(orch, "_make_evaluator", mock_evaluator_factory)

    param_dir = tmp_path / "parameter_set"
    param_dir.mkdir()
    (param_dir / "parameter_set_manifest.json").write_text(
        json.dumps({"parameter_set_id": "p1", "science_validated": False}), encoding="utf-8"
    )
    manifest = orch.run_formal_nsga3(
        design_path="configs/management/eggplant_greenhouse_drip_formal_v2.json",
        parameter_set_dir=param_dir,
        work_root=tmp_path / "work",
        seeds=[123],
        generations=2,
        population_size=12,
        initial_candidates=12,
        allow_engineering_precheck=True,
    )
    assert manifest["approval_scope"] == "engineering_precheck"
    assert manifest["science_validated"] is False
    assert len(manifest["per_seed_outputs"]) == 1
    pareto_csv = Path(manifest["per_seed_outputs"][0]["pareto_csv"])
    assert pareto_csv.is_file()
    # Pareto CSV has the decoded policy columns.
    header = pareto_csv.read_text(encoding="utf-8").splitlines()[0]
    assert "seasonal_irrigation_mm" in header
    assert "neg_mean_fresh_yield" in header
