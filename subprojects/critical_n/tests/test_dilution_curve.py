"""Unit tests for critical nitrogen dilution curve and NNI formulations."""

import math
import pytest

from subprojects.critical_n.core.dilution_curve import (
    DEFAULT_CNC_A,
    DEFAULT_CNC_B,
    DEFAULT_CNC_NC_INF,
    DEFAULT_CNC_W0,
    SENTINEL_VALUE,
    critical_n_concentration,
    nni,
    scheme_b_sigmoid_gate,
    scheme_b_vegetative_denominator,
)


def test_standard_nc_evaluation():
    """Verify critical N calculation at known reference values with asymptotic lower bound."""
    # At W == W0 = 1.0, Nc = nc_inf + (a - nc_inf) * 1.0^(-b) = a
    nc_w0 = critical_n_concentration(1.0, a=4.85, b=0.38, w0=1.0, nc_inf=1.70)
    assert nc_w0 == pytest.approx(4.85, rel=1e-5)

    # At W = 10.0 t/ha, Nc = 1.70 + (4.85 - 1.70) * (10.0)^(-0.38)
    expected_10 = 1.70 + (4.85 - 1.70) * (10.0 ** (-0.38))
    nc_10 = critical_n_concentration(10.0, a=4.85, b=0.38, w0=1.0, nc_inf=1.70)
    assert nc_10 == pytest.approx(expected_10, rel=1e-5)
    assert nc_10 < nc_w0, "Critical N must monotonically decrease with biomass W"

    # Classic power law recovered when nc_inf == 0.0
    classic_10 = 4.85 * (10.0 ** (-0.38))
    nc_classic = critical_n_concentration(10.0, a=4.85, b=0.38, w0=1.0, nc_inf=0.0)
    assert nc_classic == pytest.approx(classic_10, rel=1e-5)

    # Asymptotic floor behavior: as W -> inf, Nc -> nc_inf (1.70%)
    nc_large = critical_n_concentration(1e8, a=4.85, b=0.38, w0=1.0, nc_inf=1.70)
    assert nc_large == pytest.approx(1.70, abs=1e-2)
    assert nc_large >= 1.70, "Nc must never drop below asymptotic lower bound"


def test_w_zero_boundary_singularity_clamp():
    """Verify that W0 clamp strictly protects against W -> 0 divergence."""
    # Under unclamped formulation, Nc diverges to infinity as W -> 0
    w_zeros = [0.5, 0.1, 0.01, 1e-5, 0.0]
    for w in w_zeros:
        val = critical_n_concentration(w, a=4.85, b=0.38, w0=1.0, nc_inf=1.70)
        assert val == pytest.approx(4.85, rel=1e-5), f"W={w} must clamp to a=4.85"


def test_nc_parameter_validation():
    """Verify defensive exceptions on illegal parameter values."""
    with pytest.raises(ValueError, match="non-negative"):
        critical_n_concentration(-0.5)

    with pytest.raises(ValueError, match="Parameter a must be positive"):
        critical_n_concentration(2.0, a=-1.0)

    with pytest.raises(ValueError, match="Parameter b must be non-negative"):
        critical_n_concentration(2.0, b=-0.38)

    with pytest.raises(ValueError, match="Threshold w0 must be positive"):
        critical_n_concentration(2.0, w0=-1.0)

    with pytest.raises(ValueError, match="nc_inf must be non-negative"):
        critical_n_concentration(2.0, nc_inf=-0.5)

    with pytest.raises(ValueError, match="cannot exceed seedling maximum"):
        critical_n_concentration(2.0, a=3.0, nc_inf=3.5)

    with pytest.raises(ValueError, match="must not be NaN"):
        critical_n_concentration(float("nan"))

    with pytest.raises(ValueError, match="must not be infinite"):
        critical_n_concentration(float("inf"))


def test_nni_calculation_and_guards():
    """Verify NNI computation, positive returns, and division guards."""
    # Normal case: actual N = 3.5%, Nc = 3.5% -> NNI = 1.0
    assert nni(3.5, 3.5) == pytest.approx(1.0, rel=1e-5)

    # Luxury consumption: N_act = 4.2%, Nc = 3.5% -> NNI = 1.2
    assert nni(4.2, 3.5) == pytest.approx(1.2, rel=1e-5)

    # Deficiency: N_act = 1.75%, Nc = 3.5% -> NNI = 0.5
    assert nni(1.75, 3.5) == pytest.approx(0.5, rel=1e-5)

    # Zero critical N raises ValueError unless sentinel requested
    with pytest.raises(ValueError, match="must be positive"):
        nni(3.5, 0.0)

    assert nni(3.5, 0.0, sentinel_on_invalid=True) == SENTINEL_VALUE

    # NaN / Inf handling
    with pytest.raises(ValueError, match="must not be NaN or infinite"):
        nni(float("nan"), 3.5)

    assert nni(float("nan"), 3.5, sentinel_on_invalid=True) == SENTINEL_VALUE
    assert nni(3.5, float("nan"), sentinel_on_invalid=True) == SENTINEL_VALUE

    # Negative actual N raises ValueError
    with pytest.raises(ValueError, match="must be non-negative"):
        nni(-1.0, 3.5)


def test_scheme_b_sigmoid_gate_bounds_and_overflow():
    """Verify that Scheme B gating is strictly bounded in [nni_min, 1.05] without overflow."""
    # At NNI = 1.0, gate = nni_min + (1.05 - nni_min) / 2
    gate_mid = scheme_b_sigmoid_gate(1.0, gamma=0.65, nni_min=0.30)
    assert gate_mid == pytest.approx(0.30 + 0.75 / 2.0, rel=1e-5)

    # Extreme high NNI (e.g. 100.0): clamps cleanly at 1.05
    gate_high = scheme_b_sigmoid_gate(100.0)
    assert gate_high == pytest.approx(1.05, rel=1e-5)

    # Extreme low NNI (e.g. -100.0): clamps cleanly at nni_min=0.30
    gate_low = scheme_b_sigmoid_gate(-100.0)
    assert gate_low == pytest.approx(0.30, rel=1e-5)

    # Verify monotonicity
    nni_vals = [0.2, 0.5, 0.8, 1.0, 1.2, 1.5]
    gates = [scheme_b_sigmoid_gate(x) for x in nni_vals]
    assert all(gates[i] <= gates[i+1] for i in range(len(gates)-1))


def test_scheme_b_vegetative_denominator_guard():
    """Verify that vegetative denominator prevents ZeroDivisionError at seedling stage."""
    # At emergence before new structural growth:
    wtlf = 5.0
    stmwt = 3.0
    wcrlf = 5.0  # 100% non-structural carbon
    wcrst = 3.0

    denom = scheme_b_vegetative_denominator(wtlf, stmwt, wcrlf, wcrst, min_denom=10.0)
    assert denom == 10.0, "Denominator must clamp to min_denom=10.0 when net structural DM is 0"
