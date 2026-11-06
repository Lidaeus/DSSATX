"""Unit tests for src/reporting/metrics.py — hand-checked fixtures.

Verifies the OLS systematic/unsystematic MSE decomposition closes numerically
(MSE = MSE_s + MSE_u) and that all edge-case statuses are correct.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.reporting.metrics import compute_metrics, compute_metrics_grouped


def test_perfect_fit_gives_zero_decomposition_and_unit_nse():
    m = compute_metrics([1, 2, 3, 4], [1, 2, 3, 4])
    assert m["status"] == "ok"
    assert m["NSE"] == pytest.approx(1.0)
    assert m["MSE_s"] == pytest.approx(0.0)
    assert m["MSE_u"] == pytest.approx(0.0)
    assert m["R2"] == pytest.approx(1.0)


def test_constant_bias_is_fully_systematic():
    # sim = obs + 2  ->  sim_hat = obs + 2  ->  MSE_s = MSE, MSE_u = 0
    m = compute_metrics([1, 2, 3, 4], [3, 4, 5, 6])
    assert m["MBE"] == pytest.approx(2.0)
    assert m["MSE_u"] == pytest.approx(0.0)
    assert m["MSE_s_over_MSE"] == pytest.approx(1.0)
    assert m["MSE_u_over_MSE"] == pytest.approx(0.0)


def test_ols_coefficients_and_mse_closure_match_hand_calc():
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    sim = np.array([1.1, 1.9, 3.2, 3.8])
    m = compute_metrics(obs, sim)
    # hand-computed OLS: b = sum((o-2.5)(s-2.5))/sum((o-2.5)^2), a = mean_s - b*mean_o
    b = float(np.sum((obs - 2.5) * (sim - 2.5)) / np.sum((obs - 2.5) ** 2))
    a = float(sim.mean() - b * obs.mean())
    assert m["intercept"] == pytest.approx(a, abs=1e-9)
    assert m["slope"] == pytest.approx(b, abs=1e-9)
    sim_hat = a + b * obs
    mse_s = float(np.mean((sim_hat - obs) ** 2))
    mse_u = float(np.mean((sim - sim_hat) ** 2))
    assert m["MSE_s"] == pytest.approx(mse_s, abs=1e-9)
    assert m["MSE_u"] == pytest.approx(mse_u, abs=1e-9)
    # closure
    assert m["MSE"] == pytest.approx(m["MSE_s"] + m["MSE_u"], abs=1e-9)


def test_rmse_mae_mbe_basic_formulas():
    m = compute_metrics([10, 20, 30], [12, 18, 33])
    resid = np.array([2, -2, 3.0])
    assert m["MBE"] == pytest.approx(resid.mean())
    assert m["RMSE"] == pytest.approx(math.sqrt((resid ** 2).mean()))
    assert m["MAE"] == pytest.approx(np.abs(resid).mean())


def test_rrmse_and_nrmse_range():
    # observed mean=20, range=20; sim=obs -> rmse=0
    m = compute_metrics([10, 20, 30], [10, 20, 30])
    assert m["RRMSE_pct"] == pytest.approx(0.0)
    assert m["NRMSE_range_pct"] == pytest.approx(0.0)
    # nonzero: obs=[10,20,30] sim=[12,18,33], rmse=sqrt(17/3)
    m = compute_metrics([10, 20, 30], [12, 18, 33])
    rmse = math.sqrt(17.0 / 3.0)
    assert m["RRMSE_pct"] == pytest.approx(100 * rmse / 20.0)
    assert m["NRMSE_range_pct"] == pytest.approx(100 * rmse / 20.0)


def test_missing_minus99_and_nonfinite_are_dropped():
    m = compute_metrics([1, -99, 3, float("nan")], [1, 99, 3, 5])
    assert m["n"] == 2
    assert m["status"] in ("ok",)


def test_empty_returns_empty_status():
    m = compute_metrics([], [])
    assert m["status"] == "empty"
    assert m["n"] == 0
    assert math.isnan(m["RMSE"])


def test_single_pair_reports_basic_metrics_but_insufficient_status():
    m = compute_metrics([5], [7])
    assert m["status"] == "insufficient_n"
    assert m["RMSE"] == pytest.approx(2.0)
    assert m["MAE"] == pytest.approx(2.0)
    assert m["MBE"] == pytest.approx(2.0)
    assert math.isnan(m["NSE"])
    assert math.isnan(m["slope"])


def test_zero_mean_flags_rrmse_na():
    m = compute_metrics([0, 0, 0], [1, 2, 3])
    assert m["status"] == "zero_mean"
    assert math.isnan(m["RRMSE_pct"])


def test_zero_observed_range_and_constant_series_flags():
    # constant observed -> zero range, zero variance -> constant_series
    m = compute_metrics([5, 5, 5], [4, 5, 6])
    assert m["status"] == "constant_series"
    assert math.isnan(m["NRMSE_range_pct"])
    assert math.isnan(m["NSE"])
    assert math.isnan(m["R2"])


def test_compute_metrics_grouped_one_row_per_group():
    df = pd.DataFrame({
        "season": ["25SP", "25SP", "25FA", "25FA"],
        "variable": ["CHPDT", "CHPDT", "CHPDT", "CHPDT"],
        "observed": [100, 200, 150, 250],
        "simulated": [110, 190, 160, 240],
    })
    out = compute_metrics_grouped(df, ["season", "variable"])
    assert len(out) == 2
    assert set(out["season"]) == {"25SP", "25FA"}
    assert all(out["n"] == 2)
    # each group's MSE must close
    for _, row in out.iterrows():
        assert row["MSE"] == pytest.approx(row["MSE_s"] + row["MSE_u"], abs=1e-9)
