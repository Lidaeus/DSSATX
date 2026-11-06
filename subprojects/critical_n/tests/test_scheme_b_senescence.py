"""Tests for Scheme B senescence rate limiter and avalanche governor module."""

from __future__ import annotations

import pytest

from subprojects.critical_n.scheme_b.senescence_limiter import (
    SenescenceGovernor,
    SenescenceGovernanceResult,
    apply_senescence_limiter,
    DEFAULT_SENESCENCE_GAMMA,
)


def test_senescence_governor_strict_ceiling():
    """Verify governor caps LFSEN strictly at gamma * WLDOTN."""
    gov = SenescenceGovernor(gamma=0.90)

    # Case 1: Native LFSEN is small -> passes through uninhibited
    res = gov.govern_senescence(native_lfsen=0.50, wldotn=2.00, wtlf=30.0)
    assert abs(res.governed_lfsen - 0.50) < 1e-6
    assert res.suppressed_loss == 0.0
    assert not res.avalanche_prevented
    assert res.net_leaf_growth == 2.00 - 0.50

    # Case 2: Native LFSEN exceeds ceiling (e.g. 3.0 > 0.90 * 2.0 = 1.8)
    res = gov.govern_senescence(native_lfsen=3.00, wldotn=2.00, wtlf=30.0)
    assert abs(res.governed_lfsen - 1.80) < 1e-6
    assert abs(res.suppressed_loss - 1.20) < 1e-6
    assert res.avalanche_prevented
    # Net leaf growth guaranteed >= 0.10 * 2.0 = 0.20
    assert abs(res.net_leaf_growth - 0.20) < 1e-6


def test_senescence_governor_gamma_range():
    """Verify governor across standard parameter range [0.85, 0.95]."""
    for gamma in [0.85, 0.88, 0.90, 0.92, 0.95]:
        gov = SenescenceGovernor(gamma=gamma)
        wldotn = 1.50
        native_lfsen = 5.00  # Extreme mobilization demand
        res = gov.govern_senescence(native_lfsen=native_lfsen, wldotn=wldotn, wtlf=20.0)

        expected_governed = gamma * wldotn
        assert abs(res.governed_lfsen - expected_governed) < 1e-6
        # Mathematical invariant: ALFDOT >= (1 - gamma) * WLDOTN >= 0
        assert res.net_leaf_growth >= (1.0 - gamma) * wldotn - 1e-7
        assert res.net_leaf_growth >= 0.0


def test_senescence_governor_zero_growth_edge_case():
    """Verify governor when daily new leaf growth is zero (WLDOTN = 0)."""
    gov = SenescenceGovernor(gamma=0.90)
    res = gov.govern_senescence(native_lfsen=2.50, wldotn=0.0, wtlf=15.0)

    # When no new leaves are grown, N-mobilization senescence cannot destroy the canopy
    assert res.governed_lfsen == 0.0
    assert res.net_leaf_growth == 0.0
    assert res.suppressed_loss == 2.50


def test_senescence_governor_zero_growth_with_standing_buffer():
    """Verify that when WLDOTN = 0, standing leaf buffer allows controlled baseline turnover."""
    gov = SenescenceGovernor(gamma=0.90, standing_buffer_ratio=0.015)
    wtlf = 50.0
    # Ceiling = 0.90 * 0.0 + 0.015 * 50.0 = 0.75 g DM/m^2/d
    res = gov.govern_senescence(native_lfsen=3.00, wldotn=0.0, wtlf=wtlf)

    assert abs(res.governed_lfsen - 0.75) < 1e-6
    assert abs(res.suppressed_loss - (3.00 - 0.75)) < 1e-6
    assert res.avalanche_prevented


def test_senescence_governor_standing_leaf_buffer():
    """Verify composite buffer gamma * WLDOTN + delta * WTLF."""
    gov = SenescenceGovernor(gamma=0.85, standing_buffer_ratio=0.015)
    wldotn = 1.00
    wtlf = 40.0
    # Ceiling = 0.85 * 1.0 + 0.015 * 40.0 = 0.85 + 0.60 = 1.45
    res = gov.govern_senescence(native_lfsen=2.00, wldotn=wldotn, wtlf=wtlf)
    assert abs(res.governed_lfsen - 1.45) < 1e-6


def test_senescence_governor_post_maturity_unclamp():
    """Verify that physiological maturity allows full natural season-end defoliation."""
    gov = SenescenceGovernor(gamma=0.90, allow_post_maturity_unclamp=True)
    res = gov.govern_senescence(native_lfsen=5.00, wldotn=0.50, wtlf=10.0, is_mature=True)

    # Post-maturity unclamp allows full native senescence up to wtlf
    assert res.governed_lfsen == 5.00


def test_senescence_governor_invalid_parameters():
    """Verify error checking for out-of-range gamma and NaN inputs."""
    with pytest.raises(ValueError, match="gamma must be in physiological range"):
        SenescenceGovernor(gamma=0.50)

    with pytest.raises(ValueError, match="gamma must be in physiological range"):
        SenescenceGovernor(gamma=1.05)

    with pytest.raises(ValueError, match="standing_buffer_ratio"):
        SenescenceGovernor(standing_buffer_ratio=-0.1)

    gov = SenescenceGovernor()
    with pytest.raises(ValueError, match="Inputs must not be NaN"):
        gov.govern_senescence(native_lfsen=float("nan"), wldotn=1.0, wtlf=10.0)


def test_apply_senescence_limiter_functional_helper():
    """Verify functional helper apply_senescence_limiter."""
    val = apply_senescence_limiter(native_lfsen=3.0, wldotn=1.0, wtlf=20.0, gamma=0.90)
    assert abs(val - 0.90) < 1e-6
