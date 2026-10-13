"""Unit tests for symmetrical physiological tolerance interval objective penalty."""

import pytest

from subprojects.critical_n.core.objective_penalty import (
    PHYSIOLOGICAL_NNI_INTERVALS,
    compute_cnc_objective_penalty,
    pseudo_huber_loss,
    relaxed_pseudo_huber_residual,
    tolerance_interval_loss,
    tolerance_relaxation_operator,
)


def test_tolerance_interval_loss_inside_and_outside():
    """Verify quadratic loss behavior inside and outside the interval."""
    lower, upper = 0.40, 0.70

    # Inside interval: loss is strictly zero
    assert tolerance_interval_loss(0.40, lower, upper) == 0.0
    assert tolerance_interval_loss(0.55, lower, upper) == 0.0
    assert tolerance_interval_loss(0.70, lower, upper) == 0.0

    # Below lower bound: quadratic penalty (lower - val)^2
    loss_low = tolerance_interval_loss(0.30, lower, upper)
    assert loss_low == pytest.approx((0.40 - 0.30) ** 2, rel=1e-5)

    # Above upper bound: quadratic penalty (val - upper)^2
    loss_high = tolerance_interval_loss(0.80, lower, upper)
    assert loss_high == pytest.approx((0.80 - 0.70) ** 2, rel=1e-5)


def test_tolerance_relaxation_operator_exact_zero():
    """Verify one-sided relaxation projection operator r_tol returns exact 0.000000 within intervals."""
    # N3 interval: [1.00, 1.30]
    for val in [1.00, 1.05, 1.15, 1.25, 1.30]:
        r = tolerance_relaxation_operator(val, 1.00, 1.30)
        assert r == 0.0, f"Expected 0.0 for N3 luxury NNI={val}, got {r}"

    # N0 interval: [0.40, 0.70]
    for val in [0.40, 0.45, 0.55, 0.65, 0.70]:
        r = tolerance_relaxation_operator(val, 0.40, 0.70)
        assert r == 0.0, f"Expected 0.0 for N0 deficit NNI={val}, got {r}"

    # Deficit violation: negative signed distance
    r_def = tolerance_relaxation_operator(0.30, 0.40, 0.70)
    assert r_def == pytest.approx(-0.10, rel=1e-6)

    # Excess violation: positive signed distance
    r_exc = tolerance_relaxation_operator(1.45, 1.00, 1.30)
    assert r_exc == pytest.approx(0.15, rel=1e-6)


def test_pseudo_huber_properties():
    """Verify mathematical properties of smooth Pseudo-Huber loss."""
    delta = 0.50
    # At zero: exact 0.000000
    assert pseudo_huber_loss(0.0, delta) == 0.0

    # Small residual: quadratic asymptotic behavior ~ 0.5 * r^2
    r_small = 0.01
    h_small = pseudo_huber_loss(r_small, delta)
    quad_approx = 0.5 * (r_small ** 2)
    assert h_small == pytest.approx(quad_approx, rel=1e-3)

    # Large residual: linear asymptotic behavior ~ delta * |r| - delta^2
    r_large = 100.0
    h_large = pseudo_huber_loss(r_large, delta)
    linear_approx = delta * r_large - (delta ** 2)
    assert h_large == pytest.approx(linear_approx, rel=1e-2)


def test_relaxed_pseudo_huber_residual():
    """Verify signed Pseudo-Huber smoothed residual for PEST++ fitting."""
    # Inside interval: exact 0.000000
    assert relaxed_pseudo_huber_residual(1.15, 1.00, 1.30) == 0.0
    assert relaxed_pseudo_huber_residual(0.55, 0.40, 0.70) == 0.0

    # Outside: squared residual equals 2 * pseudo_huber_loss
    r_tol = relaxed_pseudo_huber_residual(1.45, 1.00, 1.30, delta=0.50)
    z = 1.45 - 1.30  # 0.15
    expected_sq = 2.0 * pseudo_huber_loss(z, delta=0.50)
    assert r_tol > 0.0
    assert (r_tol ** 2) == pytest.approx(expected_sq, rel=1e-6)

    # Negative violation has negative sign
    r_tol_neg = relaxed_pseudo_huber_residual(0.30, 0.40, 0.70, delta=0.50)
    assert r_tol_neg < 0.0
    z_neg = 0.30 - 0.40  # -0.10
    assert (r_tol_neg ** 2) == pytest.approx(2.0 * pseudo_huber_loss(z_neg, delta=0.50), rel=1e-6)


def test_invalid_interval_bounds_rejected():
    """Verify exception when lower > upper, or on NaN/Inf inputs."""
    with pytest.raises(ValueError, match="cannot exceed upper bound"):
        tolerance_interval_loss(0.5, 0.8, 0.4)

    with pytest.raises(ValueError, match="must not be NaN or infinite"):
        tolerance_interval_loss(float("nan"), 0.4, 0.7)

    with pytest.raises(ValueError, match="must not be NaN or infinite"):
        tolerance_interval_loss(float("inf"), 0.4, 0.7)


def test_n0_lower_bound_defense():
    """Demonstrate that symmetrical penalty eliminates blindness to N0 plant collapse."""
    # Deficient plant: NNI = 0.50 inside [0.40, 0.70] -> zero penalty
    loss_normal, _ = compute_cnc_objective_penalty({"N0": [0.50]}, default_weight=1.0)
    assert loss_normal == 0.0

    # Catastrophic collapse: NNI = 0.05 -> properly penalized!
    loss_dead, comps = compute_cnc_objective_penalty({"N0": [0.05]}, default_weight=1.0)
    expected_penalty = (0.40 - 0.05) ** 2  # 0.35^2 = 0.1225
    assert loss_dead == pytest.approx(expected_penalty, rel=1e-5)
    assert comps[0].weighted_penalty > 0.10
    assert comps[0].relaxed_residual < 0.0  # negative residual recorded


def test_n3_luxury_consumption_defense():
    """Demonstrate that biological luxury consumption in N3 is not falsely penalized."""
    # Greenhouse eggplant under high N reaches NNI in [1.10, 1.25] with zero yield penalty
    sim_nni_luxury = [1.05, 1.15, 1.25, 1.30]
    loss_luxury, comps = compute_cnc_objective_penalty(
        {"N3": sim_nni_luxury}, default_weight=1.0
    )
    # All values are within [1.00, 1.30], so penalty must be exactly 0.0!
    assert loss_luxury == 0.0
    for c in comps:
        assert c.relaxed_residual == 0.0

    # Toxic hyper-accumulation (NNI = 1.45 > 1.30) gets penalized:
    loss_toxic, comps_toxic = compute_cnc_objective_penalty({"N3": [1.45]}, default_weight=1.0)
    expected_toxic = (1.45 - 1.30) ** 2  # 0.15^2 = 0.0225
    assert loss_toxic == pytest.approx(expected_toxic, rel=1e-5)
    assert comps_toxic[0].relaxed_residual > 0.0


def test_weight_scaling_and_sentinel_skipping():
    """Verify observation weight scaling (w^2) and skipping of -99.0 sentinels."""
    # Two points: one sentinel, one violating bound
    sim_data = {"N3": [-99.0, 1.40]}  # 1.40 violates 1.30 by 0.10, unweighted = 0.01
    weight = 0.50  # w^2 = 0.25

    total_loss, comps = compute_cnc_objective_penalty(
        sim_data, weights={"N3": weight}
    )
    # Only the non-sentinel point is recorded
    assert len(comps) == 1
    assert total_loss == pytest.approx(0.25 * 0.01, rel=1e-5)


def test_pseudo_huber_method_in_compute_cnc_objective_penalty():
    """Verify compute_cnc_objective_penalty with method='pseudo_huber'."""
    # Inside interval: penalty is 0.0
    loss_in, _ = compute_cnc_objective_penalty(
        {"N3": [1.15]}, default_weight=1.0, method="pseudo_huber", delta=0.50
    )
    assert loss_in == 0.0

    # Outside interval: smooth positive penalty
    loss_out, comps = compute_cnc_objective_penalty(
        {"N3": [1.40]}, default_weight=1.0, method="pseudo_huber", delta=0.50
    )
    expected = 2.0 * pseudo_huber_loss(1.40 - 1.30, delta=0.50)
    assert loss_out == pytest.approx(expected, rel=1e-6)
    assert comps[0].relaxed_residual == pytest.approx(relaxed_pseudo_huber_residual(1.40, 1.00, 1.30, delta=0.50), rel=1e-6)
