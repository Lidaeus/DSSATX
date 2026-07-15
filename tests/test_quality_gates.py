"""Failure-injection tests for process-vs-science quality states."""

import pandas as pd
import pytest

from src.common.quality import (
    ScientificQualityError,
    assess_ies,
    assess_morris,
    assess_numeric_matrix,
    assess_sobol,
)


def test_all_zero_morris_is_process_complete_but_scientifically_failed(tmp_path):
    report = assess_morris(pd.DataFrame({"par": ["A", "B"], "score": [0.0, 0.0]}), run_id="zero")
    assert report.process_completed
    assert not report.science_validated
    assert report.status == "fail"
    json_path, md_path = report.write(tmp_path)
    assert json_path.exists() and md_path.exists()
    with pytest.raises(ScientificQualityError):
        report.require_pass()


def test_nonzero_morris_passes():
    report = assess_morris(pd.DataFrame({"score": [0.0, 0.25]}))
    assert report.science_validated


def test_constant_forward_outputs_fail():
    report = assess_numeric_matrix(
        pd.DataFrame({"yield": [100.0, 100.0], "lai": [2.0, 2.0]}), run_type="forward_smoke"
    )
    assert not report.science_validated


def test_missing_sentinel_is_not_finite_output():
    report = assess_numeric_matrix(
        pd.DataFrame({"yield": [100.0, -99.0]}), run_type="forward_smoke", max_invalid_fraction=0.0
    )
    assert report.status == "fail"


def test_all_zero_sobol_fails():
    report = assess_sobol(pd.DataFrame({"Si": [0.0], "STi": [0.0]}))
    assert not report.science_validated


def test_ies_requires_simulation_variation_phi_and_parameter_update():
    initial = pd.DataFrame({"p1": [1.0, 2.0]}, index=["r1", "r2"])
    observations = pd.DataFrame({"o1": [10.0, 10.0]}, index=["r1", "r2"])
    final = initial.copy()
    report = assess_ies(initial, observations, parameter_final=final, phi_values=[100.0, 100.0])
    assert report.process_completed
    assert not report.science_validated
    failed = {check.check_id for check in report.checks if check.status == "fail"}
    assert {"ies_simulation_variation", "ies_phi_variation", "ies_parameter_update"}.issubset(failed)


def test_valid_micro_ies_passes():
    initial = pd.DataFrame({"p1": [1.0, 2.0]}, index=["r1", "r2"])
    observations = pd.DataFrame({"o1": [10.0, 12.0]}, index=["r1", "r2"])
    final = pd.DataFrame({"p1": [1.2, 1.8]}, index=["r1", "r2"])
    report = assess_ies(initial, observations, parameter_final=final, phi_values=[4.0, 9.0])
    assert report.science_validated
