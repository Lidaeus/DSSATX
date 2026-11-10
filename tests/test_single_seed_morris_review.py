"""Scientific edge cases for recovery of a partially rejected Morris campaign."""
import numpy as np
import pytest

from src.reporting.export_single_seed_morris_review import dap50, elementary_effects, knee


def test_effects_use_serialized_normalized_step():
    nominal = np.array([[0.0], [1.0]])
    written = np.array([[0.0], [0.8]])
    effects, steps = elementary_effects(nominal, written, 3 * written, np.ones(1))
    assert effects[0, 0, 0] == pytest.approx(3.0)
    assert steps[0]["actual_delta"] == pytest.approx(0.8)


def test_treatment_mean_effect_preserves_opposing_response_cancellation():
    x = np.array([[0.0], [1.0]])
    y = np.array([[0.0, 5.0], [2.0, 3.0]])
    per_treatment, _ = elementary_effects(x, x, y, np.ones(1))
    of_mean, _ = elementary_effects(x, x, y.mean(axis=1), np.ones(1))
    assert np.abs(per_treatment).mean() == pytest.approx(2.0)
    assert np.abs(of_mean).mean() == pytest.approx(0.0)


def test_collateral_written_parameter_change_is_rejected():
    x = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
    written = x.copy()
    written[1, 1] = 0.1
    with pytest.raises(AssertionError):
        elementary_effects(x, written, x.sum(axis=1), np.ones(2))


def test_signed_steps_recover_same_linear_effect_in_multiple_trajectories():
    x = np.array([[0.0], [0.6], [1.0], [0.4]])
    effects, _ = elementary_effects(x, x, 7 * x[:, 0], np.ones(1))
    np.testing.assert_allclose(effects[:, 0], [7.0, 7.0])


def test_zero_yield_has_no_fictitious_half_harvest_date():
    assert np.isnan(dap50(np.array([0, 1, 2]), np.zeros(3)))
    assert np.isnan(dap50(np.array([]), np.array([])))


def test_half_harvest_interpolates_but_rejects_decreasing_cumulative_mass():
    assert dap50(np.array([0, 2, 4]), np.array([0, 2, 8])) == pytest.approx(8 / 3)
    assert np.isnan(dap50(np.array([0, 2, 4]), np.array([0, 8, 7])))


def test_chord_knee_detects_known_break_and_handles_flat_scores():
    assert knee([10.0, 5.0, 1.0, 0.8, 0.6, 0.4, 0.2, 0.0]) == 3
    assert knee([1.0, 1.0, 1.0]) == 1
