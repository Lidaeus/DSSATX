import numpy as np
import pytest

from src.reporting.metrics import compute_metrics, valid_pair_mask


def test_raw_sentinel_before_conversion():
    o = np.array([-99.0000001, 10000, 20000])
    s = np.array([1000, 10000, 20000])
    mask = valid_pair_mask(o, s, value_kind="state")
    assert compute_metrics(o[mask] / 1000, s[mask] / 1000)["n"] == 2
    assert valid_pair_mask(o, s).tolist() == [False, True, True]


def test_signed_differences_keep_negative_and_minus99():
    assert compute_metrics([-200, -99, 300], [-150, -99, 280], value_kind="signed")["n"] == 3
    assert compute_metrics([-200, 100, 300], [-150, 90, 280])["n"] == 3


def test_states_reject_any_negative_and_infinite():
    assert valid_pair_mask([-0.1, 0, np.inf, 2], [0, 0, 1, np.nan], value_kind="state").tolist() == [False, True, False, False]
    with pytest.raises(ValueError):
        valid_pair_mask([1], [2], value_kind="guessed")
