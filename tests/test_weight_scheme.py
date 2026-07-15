"""tests/test_weight_scheme.py - Unit tests for weight_scheme module."""

import os
import sys

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
from src.calibration.weight_scheme import (
    normalize_and_weight,
    compute_cv_based_sigma,
    compute_balanced_weights,
    build_observation_weights,
    VARIABLE_TREATMENT,
    LOG_TRANSFORM_VARS,
)


def test_normalize_non_cumulative():
    obs = pd.Series([100.0, 110.0, 120.0])
    sim = pd.Series([102.0, 108.0, 118.0])
    w, no, ns, eff_sig = normalize_and_weight(obs, sim, sigma_original=10.0, use_log_transform=False)
    assert 0.1 < w < 10.0, f"Unexpected weight: {w}"
    assert no.min() >= 0.0 and no.max() <= 1.0, "Normalized obs should be in [0,1]"
    print("  PASS: normalize_non_cumulative")


def test_normalize_cumulative_log_transform():
    obs_cum = pd.Series([500.0, 1500.0, 5000.0, 8000.0])
    sim_cum = pd.Series([480.0, 1550.0, 4900.0, 8200.0])
    w2, no2, ns2, eff_sig2 = normalize_and_weight(obs_cum, sim_cum, sigma_original=0.1, use_log_transform=True)
    assert w2 > 0, f"Weight should be positive: {w2}"
    print("  PASS: normalize_cumulative_log_transform")


def test_normalize_handles_missing():
    obs = pd.Series([-99.0, 100.0, 110.0])
    sim = pd.Series([100.0, 102.0, 108.0])
    w, no, ns, eff_sig = normalize_and_weight(obs, sim, sigma_original=10.0, use_log_transform=False)
    assert w > 0
    print("  PASS: normalize_handles_missing")


def test_cv_based_sigma():
    obs_data = pd.Series([100, 110, 105, 115, 90])
    sigma, cv = compute_cv_based_sigma(obs_data, sigma0=5.0)
    assert sigma > 0
    assert 0.0 < cv < 1.0
    print(f"  PASS: cv_based_sigma (sigma={sigma:.4f}, cv={cv:.4f})")


def test_cv_based_sigma_override():
    obs_data = pd.Series([100, 110, 105, 115, 90])
    sigma, cv = compute_cv_based_sigma(obs_data, sigma0=5.0, cv_override=0.1)
    assert sigma > 0
    assert cv == 0.1
    print("  PASS: cv_based_sigma_override")


def test_balanced_weights():
    obs_df = pd.DataFrame({
        'obsnme': ['o1', 'o2', 'o3'],
        'obsval': [100.0, 200.0, 150.0],
        'obgnme': ['grp_a', 'grp_a', 'grp_b']
    })
    sim_df = pd.DataFrame({
        'obsnme': ['o1', 'o2', 'o3'],
        'simulated': [102.0, 195.0, 155.0]
    })
    original_sigmas = {'grp_a': 10.0, 'grp_b': 20.0}
    bw, adj_s = compute_balanced_weights(obs_df, sim_df, original_sigmas)
    assert all(v > 0 for v in bw.values()), f"Balanced weights should be positive: {bw}"
    assert all(v > 0 for v in adj_s.values()), f"Adjusted sigmas should be positive: {adj_s}"
    print(f"  PASS: balanced_weights {bw}")


def test_build_observation_weights():
    obs_data = [
        {'obsnme': 'laixs_r1', 'obsval': 3.5, 'weight': 1.0, 'obgnme': 'LAIXM'},
        {'obsnme': 'hwams_r1', 'obsval': 8000.0, 'weight': 1.0, 'obgnme': 'HWAMM'},
        {'obsnme': 'adaps_r1', 'obsval': 70.0, 'weight': 1.0, 'obgnme': 'ADAPM'},
    ]
    result = build_observation_weights(
        obs_data,
        df_override=None,
        sim_baseline=None,
        apply_normalization=True,
        apply_log_transform=True,
        apply_pwtadj1=False,
        cv_based_sigma=False,
    )
    assert len(result) == 3
    for r in result:
        assert 'weight' in r
        assert r['weight'] > 0
    print("  PASS: build_observation_weights")


def test_variable_treatment_definitions():
    assert 'ADAPM' in VARIABLE_TREATMENT
    assert 'LWADM' in VARIABLE_TREATMENT
    assert 'HIAMM' in VARIABLE_TREATMENT
    assert VARIABLE_TREATMENT['ADAPM']['log_transform'] is False
    assert VARIABLE_TREATMENT['LWADM']['log_transform'] is True
    assert VARIABLE_TREATMENT['HIAMM']['log_transform'] is False
    print("  PASS: variable_treatment_definitions")


def test_log_transform_vars():
    assert 'LWADM' in LOG_TRANSFORM_VARS
    assert 'SWADM' in LOG_TRANSFORM_VARS
    assert 'ADAPM' not in LOG_TRANSFORM_VARS
    assert 'HIAMM' not in LOG_TRANSFORM_VARS
    print("  PASS: log_transform_vars")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed (total {passed + failed})")
    sys.exit(1 if failed else 0)
