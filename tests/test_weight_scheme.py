"""Regression tests for the P0 raw-scale PEST weight policy."""

import math

import pandas as pd
import pytest

from src.calibration.weight_scheme import (
    WEIGHT_POLICY_ID,
    build_observation_weights,
    compute_balanced_weights,
    compute_cv_based_sigma,
    compute_phi,
    minmax_normalize,
    normalize_and_weight,
    weight_from_sigma,
)


def test_sigma_maps_to_pest_weight_not_inverse_variance():
    assert weight_from_sigma(10.0) == pytest.approx(0.1)
    assert weight_from_sigma(10.0, group_multiplier=2.0) == pytest.approx(0.2)


def test_hand_calculated_phi_and_quadratic_residual_scaling():
    weights = [weight_from_sigma(2.0), weight_from_sigma(4.0)]
    phi = compute_phi([10.0, 20.0], [12.0, 16.0], weights)
    assert phi == pytest.approx((2.0 / 2.0) ** 2 + (4.0 / 4.0) ** 2)
    doubled = compute_phi([10.0, 20.0], [14.0, 12.0], weights)
    assert doubled == pytest.approx(4.0 * phi)


@pytest.mark.parametrize("sigma", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_sigma_fails(sigma):
    with pytest.raises(ValueError):
        weight_from_sigma(sigma)


def test_raw_compatibility_entry_does_not_change_values():
    obs = pd.Series([100.0, 110.0, 120.0])
    sim = pd.Series([102.0, 108.0, 118.0])
    weight, out_obs, out_sim, effective_sigma = normalize_and_weight(obs, sim, 10.0)
    assert weight == pytest.approx(0.1)
    pd.testing.assert_series_equal(out_obs, obs)
    pd.testing.assert_series_equal(out_sim, sim)
    assert effective_sigma == 10.0


def test_dynamic_minmax_and_partial_log_are_rejected():
    obs = pd.Series([1.0, 2.0])
    sim = pd.Series([1.1, 2.2])
    with pytest.raises(ValueError, match="Min-Max"):
        minmax_normalize(obs, sim)
    with pytest.raises(ValueError, match="Log residuals"):
        normalize_and_weight(obs, sim, 1.0, use_log_transform=True)


def test_cv_based_sigma_uses_absolute_and_relative_components():
    sigma, cv = compute_cv_based_sigma(pd.Series([90.0, 100.0, 110.0]), sigma0=5.0, cv_override=0.1)
    assert cv == 0.1
    assert sigma == pytest.approx(math.sqrt(5.0**2 + 10.0**2))


def test_build_observation_weights_writes_audit_fields():
    observations = [
        {"obsnme": "lai_1", "obsval": 3.5, "weight": 1.0, "obgnme": "LAIXM", "sigma": 0.5},
        {"obsnme": "yield_1", "obsval": 8000.0, "weight": 1.0, "obgnme": "HWAMM", "sigma": 200.0},
    ]
    result = build_observation_weights(observations)
    by_name = {row["obsnme"]: row for row in result}
    assert by_name["lai_1"]["weight"] == pytest.approx(2.0)
    assert by_name["yield_1"]["weight"] == pytest.approx(0.005)
    assert all(row["weight_policy_id"] == WEIGHT_POLICY_ID for row in result)
    assert all(row["transform"] == "raw" for row in result)


def test_pwtadj1_requires_exact_group_mapping_and_baseline():
    obs = pd.DataFrame(
        {"obsnme": ["o1", "o2"], "obsval": [10.0, 20.0], "obgnme": ["a", "b"]}
    )
    sim = pd.DataFrame({"obsnme": ["o1", "o2"], "simulated": [12.0, 24.0]})
    with pytest.raises(ValueError, match="exactly match"):
        compute_balanced_weights(obs, sim, {"a": 1.0})
    weights, adjusted = compute_balanced_weights(obs, sim, {"a": 1.0, "b": 2.0})
    assert set(weights) == {"a", "b"}
    assert all(value > 0 for value in adjusted.values())


def test_improved_flags_do_not_silently_fallback():
    observations = [
        {"obsnme": "o1", "obsval": 1.0, "weight": 1.0, "obgnme": "LAIXM", "sigma": 0.5}
    ]
    with pytest.raises(ValueError, match="Min-Max"):
        build_observation_weights(observations, apply_normalization=True)
    with pytest.raises(ValueError, match="baseline"):
        build_observation_weights(observations, apply_pwtadj1=True)
