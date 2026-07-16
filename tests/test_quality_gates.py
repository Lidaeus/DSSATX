"""Failure-injection tests for process-vs-science quality states."""

import pandas as pd
import pytest

from src.common.quality import (
    ScientificQualityError,
    assess_ies,
    load_morris_summary,
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


def test_morris_rejects_a_declared_output_with_only_zero_effects():
    report = assess_morris(
        pd.DataFrame(
            {
                "obs": ["yield", "yield", "fruit_early", "fruit_early"],
                "score": [0.1, 0.0, 0.0, 0.0],
            }
        )
    )
    check = next(
        item for item in report.checks if item.check_id == "morris_output_non_degenerate"
    )
    assert check.status == "fail"
    assert check.actual["degenerate_outputs"] == ["fruit_early"]


def test_load_morris_summary_accepts_pestpp_sen_columns(tmp_path):
    path = tmp_path / "case.mio"
    path.write_text(
        "observation_name,parameter_name,n_samples,sen_mean_abs\n"
        "yield,p1,8,0.25\n",
        encoding="utf-8",
    )
    frame = load_morris_summary(path)
    assert frame.loc[0, ["obs", "par", "score"]].tolist() == ["yield", "p1", 0.25]


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


def test_ies_rejects_failed_outputs_nonfinite_phi_and_lost_realizations():
    initial = pd.DataFrame({"p1": [1.0, 2.0, 3.0]}, index=["r1", "r2", "r3"])
    observations = pd.DataFrame({"o1": [10.0, -99.0]}, index=["r1", "r2"])
    final = pd.DataFrame({"p1": [1.1]}, index=["r1"])
    report = assess_ies(
        initial,
        observations,
        parameter_final=final,
        phi_values=[4.0, float("nan")],
    )
    failed = {check.check_id for check in report.checks if check.status == "fail"}
    assert {
        "ies_observation_finite",
        "ies_realization_alignment",
        "ies_phi_finite",
        "ies_final_realization_alignment",
    }.issubset(failed)


def test_ies_rejects_duplicate_realization_identifiers():
    initial = pd.DataFrame({"p1": [1.0, 2.0]}, index=["r1", "r1"])
    observations = pd.DataFrame({"o1": [10.0, 12.0]}, index=["r1", "r2"])
    final = pd.DataFrame({"p1": [1.2, 1.8]}, index=["r1", "r2"])
    report = assess_ies(initial, observations, parameter_final=final, phi_values=[4.0, 9.0])
    assert next(c for c in report.checks if c.check_id == "ies_unique_realizations").status == "fail"


def test_ies_rejects_nonfinite_final_parameters():
    initial = pd.DataFrame({"p1": [1.0, 2.0]}, index=["r1", "r2"])
    observations = pd.DataFrame({"o1": [10.0, 12.0]}, index=["r1", "r2"])
    final = pd.DataFrame({"p1": [float("nan"), 1.8]}, index=["r1", "r2"])
    report = assess_ies(initial, observations, parameter_final=final, phi_values=[4.0, 9.0])
    assert next(c for c in report.checks if c.check_id == "ies_final_parameter_finite").status == "fail"
