"""Tests for Scheme B photosynthetic acclimation coupling module."""

from __future__ import annotations

import math
import pytest

from subprojects.critical_n.scheme_b.acclimation import (
    AcclimationType,
    bounded_sigmoid_acclimation,
    hill_acclimation,
    michaelis_menten_acclimation,
    compute_nni_from_states,
    couple_photosynthesis,
    DEFAULT_GAMMA,
    DEFAULT_NNI_MIN,
    DEFAULT_S_MAX,
    DEFAULT_HILL_COEF,
    DEFAULT_HILL_K_HALF,
    DEFAULT_MM_KM,
    DEFAULT_CNC_A,
)


def test_bounded_sigmoid_acclimation_bounds_and_monotonicity():
    """Verify that bounded sigmoid acclimation stays within [nni_min, s_max] and is strictly increasing."""
    nni_min = 0.30
    s_max = 1.05
    gamma = 0.65

    # Check bounds across a wide domain
    test_points = [-10.0, 0.0, 0.2, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 10.0, 100.0]
    vals = [bounded_sigmoid_acclimation(x, gamma=gamma, nni_min=nni_min, s_max=s_max) for x in test_points]

    for val in vals:
        assert val >= nni_min - 1e-7
        assert val <= s_max + 1e-7

    # Strictly monotonic
    for i in range(len(vals) - 1):
        assert vals[i] <= vals[i + 1]

    # At NNI = 1.0, arg = 0 -> midpoint between nni_min and s_max
    mid = bounded_sigmoid_acclimation(1.0, gamma=gamma, nni_min=nni_min, s_max=s_max)
    assert abs(mid - (nni_min + (s_max - nni_min) / 2.0)) < 1e-6


def test_bounded_sigmoid_normalized_at_one_and_custom_mid():
    """Verify normalize_at_one anchors S(1.0) == 1.00 exactly while preserving bounds."""
    nni_min = 0.30
    s_max = 1.05
    gamma = 0.65

    # With normalize_at_one=True, S(1.0) must equal 1.00 exactly
    at_one = bounded_sigmoid_acclimation(
        1.0, gamma=gamma, nni_min=nni_min, s_max=s_max, normalize_at_one=True
    )
    assert abs(at_one - 1.00) < 1e-6

    # Test monotonicity with normalize_at_one
    test_points = [0.0, 0.3, 0.6, 0.8, 1.0, 1.2, 1.5, 3.0]
    vals = [
        bounded_sigmoid_acclimation(
            x, gamma=gamma, nni_min=nni_min, s_max=s_max, normalize_at_one=True
        )
        for x in test_points
    ]
    for i in range(len(vals) - 1):
        assert vals[i] <= vals[i + 1]
    assert vals[0] >= nni_min - 1e-7
    assert vals[-1] <= s_max + 1e-7

    # Custom x_mid shifts the inflection point
    custom_mid = bounded_sigmoid_acclimation(
        0.80, gamma=gamma, nni_min=nni_min, s_max=s_max, x_mid=0.80
    )
    assert abs(custom_mid - (nni_min + (s_max - nni_min) / 2.0)) < 1e-6


def test_hill_acclimation_bounds_and_monotonicity():
    """Verify Hill acclimation stays within bounds and is strictly non-decreasing."""
    s_min = 0.30
    s_max = 1.05

    test_points = [0.0, 0.2, 0.5, 0.7, 0.85, 1.0, 1.2, 2.0, 10.0]
    vals = [hill_acclimation(x, s_min=s_min, s_max=s_max) for x in test_points]

    for val in vals:
        assert val >= s_min - 1e-7
        assert val <= s_max + 1e-7

    for i in range(len(vals) - 1):
        assert vals[i] <= vals[i + 1]

    # Zero input returns minimum floor
    assert abs(hill_acclimation(0.0, s_min=s_min, s_max=s_max) - s_min) < 1e-6


def test_michaelis_menten_acclimation_bounds_and_monotonicity():
    """Verify Michaelis-Menten acclimation stays within bounds and is monotonic."""
    s_min = 0.30
    s_max = 1.05

    test_points = [0.0, 0.1, 0.35, 0.7, 1.0, 1.5, 5.0, 20.0]
    vals = [michaelis_menten_acclimation(x, s_min=s_min, s_max=s_max) for x in test_points]

    for val in vals:
        assert val >= s_min - 1e-7
        assert val <= s_max + 1e-7

    for i in range(len(vals) - 1):
        assert vals[i] <= vals[i + 1]

    assert abs(michaelis_menten_acclimation(0.0, s_min=s_min, s_max=s_max) - s_min) < 1e-6


def test_acclimation_invalid_inputs_error_handling():
    """Verify NaN, inf, and invalid parameters are properly rejected."""
    with pytest.raises(ValueError, match="NaN or infinite"):
        bounded_sigmoid_acclimation(float("nan"))

    with pytest.raises(ValueError, match="gamma must be positive"):
        bounded_sigmoid_acclimation(1.0, gamma=-0.5)

    with pytest.raises(ValueError, match="nni_min must be in"):
        bounded_sigmoid_acclimation(1.0, nni_min=1.2, s_max=1.05)

    with pytest.raises(ValueError, match="hill_coef must be positive"):
        hill_acclimation(1.0, hill_coef=0.0)

    with pytest.raises(ValueError, match="k_half must be positive"):
        hill_acclimation(1.0, k_half=-1.0)

    with pytest.raises(ValueError, match="km must be positive"):
        michaelis_menten_acclimation(1.0, km=0.0)


def test_compute_nni_from_states_seedling_and_dilution():
    """Verify compute_nni_from_states handles seedling neutrality and Greenwood-Lemaire dilution."""
    # Seedling stage (< 5.0 g/m^2 leaf biomass): Returns neutral NNI = 1.0
    w_eff, nc, pcnl, nni = compute_nni_from_states(
        wtlf=2.0, wtnlf=0.08, cwad=10.0, cum_harvest_dry=0.0
    )
    assert nni == 1.0
    assert nc == DEFAULT_CNC_A

    # Active canopy stage: W_eff = 2.0 t DM/ha (> W0 = 1.0)
    # Nc = 4.85 * (2.0)^(-0.38) = 3.726%
    # Leaf N% = (0.75 / 20.0) * 100 = 3.75%
    # NNI = 3.75 / 3.726 = 1.0064
    w_eff, nc, pcnl, nni = compute_nni_from_states(
        wtlf=20.0, wtnlf=0.75, cwad=2000.0, cum_harvest_dry=0.0
    )
    assert abs(w_eff - 2.0) < 1e-4
    assert abs(nc - 4.85 * (2.0 ** -0.38)) < 1e-4
    assert abs(pcnl - 3.75) < 1e-4
    assert abs(nni - (3.75 / nc)) < 1e-4


def test_couple_photosynthesis_multi_functional_types():
    """Verify couple_photosynthesis supports all three functional types."""
    native_agefac = 0.85

    for ftype in [AcclimationType.SIGMOID, AcclimationType.HILL, AcclimationType.MICHAELIS_MENTEN]:
        coupled_low = couple_photosynthesis(native_agefac, nni=0.20, acclimation_type=ftype)
        coupled_high = couple_photosynthesis(native_agefac, nni=1.50, acclimation_type=ftype)

        # Severe deficit decreases photosynthesis
        assert coupled_low < native_agefac
        # High N increases photosynthesis (capped by s_max * native_agefac)
        assert coupled_high > native_agefac
        assert coupled_high <= native_agefac * DEFAULT_S_MAX + 1e-6
