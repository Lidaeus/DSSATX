"""Unit tests for symmetrical physiological tolerance interval objective penalty."""

import pytest

from subprojects.critical_n.core.objective_penalty import (
    PHYSIOLOGICAL_NNI_INTERVALS,
    compute_cnc_objective_penalty,
    tolerance_interval_loss,
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


def test_n3_luxury_consumption_defense():
    """Demonstrate that biological luxury consumption in N3 is not falsely penalized."""
    # Greenhouse eggplant under high N reaches NNI in [1.10, 1.25] with zero yield penalty
    sim_nni_luxury = [1.05, 1.15, 1.25, 1.30]
    loss_luxury, comps = compute_cnc_objective_penalty(
        {"N3": sim_nni_luxury}, default_weight=1.0
    )
    # All values are within [1.00, 1.30], so penalty must be exactly 0.0!
    assert loss_luxury == 0.0

    # Toxic hyper-accumulation (NNI = 1.45 > 1.30) gets penalized:
    loss_toxic, _ = compute_cnc_objective_penalty({"N3": [1.45]}, default_weight=1.0)
    expected_toxic = (1.45 - 1.30) ** 2  # 0.15^2 = 0.0225
    assert loss_toxic == pytest.approx(expected_toxic, rel=1e-5)


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
