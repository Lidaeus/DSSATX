"""Unit tests for src/reporting/residual_diagnostics.py."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.reporting.residual_diagnostics import (
    MIN_RUNS_TEST_N,
    build_residual_trajectory,
    runs_test,
    treatment_bootstrap_mbe,
)


def test_runs_test_alternating_signs_significant():
    # 8 alternating residuals -> max runs, significant departure from random
    r = runs_test([1, -1, 1, -1, 1, -1, 1, -1])
    assert r["status"] == "tested"
    assert r["n_runs"] == 8
    assert r["p_value"] < 0.05


def test_runs_test_clustered_signs_significant():
    r = runs_test([1, 1, 1, 1, 1, -1, -1, -1, -1, -1])
    assert r["status"] == "tested"
    assert r["n_runs"] == 2
    assert r["p_value"] < 0.05


def test_runs_test_short_sequence_not_tested():
    r = runs_test([1, -1, 1, -1])
    assert r["status"] == "not_tested"
    assert f"n=4 < {MIN_RUNS_TEST_N}" in r["note"]


def test_runs_test_all_one_sign_not_tested():
    r = runs_test([1, 2, 3, 4, 5, 6, 7, 8])
    assert r["status"] == "not_tested"
    assert "share one sign" in r["note"]


def test_runs_test_drops_zero_residuals():
    # 8 nonzero alternating + zeros interspersed
    r = runs_test([1, 0, -1, 0, 1, 0, -1, 0, 1, -1, 1, -1])
    assert r["n_zero"] == 4
    assert r["n"] == 8  # only nonzero counted


def test_treatment_bootstrap_mbe_ci_brackets_point_estimate():
    rng = np.random.default_rng(0)
    treatments = np.repeat(np.arange(10), 3)
    obs = rng.normal(100, 5, size=30)
    sim = obs + rng.normal(2.0, 1.0, size=30)  # positive bias ~ +2
    df = pd.DataFrame({"treatment": treatments, "observed": obs, "simulated": sim})
    b = treatment_bootstrap_mbe(df, n_bootstrap=1000, min_treatments=8, seed=1)
    assert b["status"] == "tested"
    assert b["n_treatments"] == 10
    assert b["ci_lower"] <= b["MBE"] <= b["ci_upper"]
    assert b["small_sample"] is False


def test_treatment_bootstrap_small_sample_reports_permutation():
    df = pd.DataFrame({
        "treatment": [1, 1, 2, 2, 3, 3],
        "observed": [10, 10, 10, 10, 10, 10],
        "simulated": [12, 12, 9, 9, 13, 13],
    })
    b = treatment_bootstrap_mbe(df, min_treatments=8, n_bootstrap=500, seed=1)
    assert b["small_sample"] is True
    assert not math.isnan(b["permutation_p_value"])


def test_residual_trajectory_flags_cumulative_non_independence():
    df = pd.DataFrame({
        "season": ["25SP"] * 4,
        "treatment": [1, 1, 2, 2],
        "variable": ["DRY_CUM"] * 4,
        "harvest_number": [1, 2, 1, 2],
        "observed": [100, 200, 100, 200],
        "simulated": [110, 190, 105, 195],
    })
    traj = build_residual_trajectory(df)
    assert traj["is_cumulative_non_independent"].all()
    assert "final_cumulative_residual" in traj.columns
    # trajectory preserves grouping keys
    assert set(["season", "treatment", "variable"]).issubset(traj.columns)


def test_residual_trajectory_non_cumulative_not_flagged():
    df = pd.DataFrame({
        "season": ["25SP"] * 2,
        "treatment": [1, 1],
        "variable": ["LWAD", "LWAD"],
        "harvest_number": [1, 2],
        "observed": [100, 200],
        "simulated": [110, 190],
    })
    traj = build_residual_trajectory(df)
    assert not traj["is_cumulative_non_independent"].any()
