"""Failure-injection tests for process-vs-science quality states."""

import pandas as pd
import pyemu
import pytest

from src.common.quality import (
    ScientificQualityError,
    assess_ies,
    load_morris_summary,
    assess_morris,
    assess_numeric_matrix,
    assess_sobol,
)
from src.reporting.quality_gate import assess_ies_run


def test_alphabetic_uppercase_rec_members_distinguish_failures_and_screening(tmp_path):
    names = ['real_000', 'real_001', 'base']
    pd.DataFrame({'p': [1., 2., 3.]}, index=names).to_csv(tmp_path/'case.0.par.csv')
    pd.DataFrame({'p': [2.9]}, index=['BASE']).to_csv(tmp_path/'case.1.par.csv')
    pd.DataFrame({'o': [4.]}, index=['base']).to_csv(tmp_path/'case.1.obs.csv')
    pd.DataFrame({'iteration': [0,1], 'real_000': [1.,None], 'real_001': [2.,None], 'base': [3.,2.]}).to_csv(tmp_path/'case.phi.actual.csv', index=False)
    (tmp_path/'case.rec').write_text('...dropping par:obs realizations: REAL_001 : REAL_001 ,\n')
    agents = tmp_path/'_agents/agent_01'
    agents.mkdir(parents=True)
    (agents/'panther_worker.rec').write_text('run failed for run_id: 4 ITERATION:0 REALIZATION:REAL_000\n')
    report = assess_ies_run(tmp_path, 'case')
    states = pd.read_csv(tmp_path/'ies_quality/case.member_status.csv').set_index('real_name').state.to_dict()
    assert states == {'real_000': 'model_failed', 'real_001': 'high_phi_screened', 'base': 'retained'}
    assert report.status == 'fail'  # Classification never relaxes the loss gate.


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


def test_ies_allows_only_a_predeclared_small_fraction_of_missing_phi_slots():
    initial = pd.DataFrame({"p1": [1.0, 2.0, 3.0]}, index=["r1", "r2", "r3"])
    observations = pd.DataFrame({"o1": [10.0, 11.0, 12.0]}, index=["r1", "r2", "r3"])
    final = pd.DataFrame({"p1": [1.1, 2.1, 2.9]}, index=["r1", "r2", "r3"])
    accepted = assess_ies(
        initial,
        observations,
        parameter_final=final,
        phi_values=[4.0, 5.0, float("nan"), 6.0],
        max_phi_invalid_fraction=0.25,
    )
    assert next(check for check in accepted.checks if check.check_id == "ies_phi_finite").status == "pass"

    rejected = assess_ies(
        initial,
        observations,
        parameter_final=final,
        phi_values=[4.0, 5.0, float("nan"), 6.0],
        max_phi_invalid_fraction=0.20,
    )
    assert next(check for check in rejected.checks if check.check_id == "ies_phi_finite").status == "fail"


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


def test_persisted_ies_ignores_missing_zero_weight_diagnostic_columns(tmp_path):
    """A diagnostic missing sentinel is not a failed model realization."""
    prefix = "case"
    pd.DataFrame({"p": [1.0, 2.0]}, index=["0", "1"]).to_csv(tmp_path / f"{prefix}.0.par.csv")
    pd.DataFrame({"p": [1.1, 1.9]}, index=["0", "1"]).to_csv(tmp_path / f"{prefix}.1.par.csv")
    pd.DataFrame(
        {"active": [10.0, 12.0], "diagnostic_missing": [-99.0, -99.0]},
        index=["0", "1"],
    ).to_csv(tmp_path / f"{prefix}.1.obs.csv")
    pd.DataFrame({"iteration": [0, 1], "0": [6.0, 4.0], "1": [8.0, 5.0]}).to_csv(
        tmp_path / f"{prefix}.phi.actual.csv", index=False
    )
    pst = pyemu.Pst.from_par_obs_names(["p"], ["active", "diagnostic_missing"])
    pst.control_data.noptmax = 1
    pst.observation_data.loc["diagnostic_missing", "weight"] = 0.0
    pst.write(tmp_path / f"{prefix}.pst")

    report = assess_ies_run(tmp_path, prefix)
    finite = next(check for check in report.checks if check.check_id == "ies_observation_finite")
    assert finite.status == "pass"


def test_persisted_ies_allows_predeclared_small_active_observation_failure_fraction(tmp_path):
    prefix = "case"
    realizations = [str(index) for index in range(100)]
    pd.DataFrame({"p": range(100)}, index=realizations).to_csv(tmp_path / f"{prefix}.0.par.csv")
    pd.DataFrame({"p": [value + 0.1 for value in range(100)]}, index=realizations).to_csv(
        tmp_path / f"{prefix}.1.par.csv"
    )
    observations = pd.DataFrame(
        {"active_a": [10.0] * 100, "active_b": [12.0] * 100},
        index=realizations,
    )
    observations.loc["0", "active_a"] = -99.0
    observations.to_csv(tmp_path / f"{prefix}.1.obs.csv")
    pd.DataFrame(
        {
            "iteration": [0, 1],
            **{realization: [6.0, 4.0 + index / 100.0] for index, realization in enumerate(realizations)},
        }
    ).to_csv(tmp_path / f"{prefix}.phi.actual.csv", index=False)
    pst = pyemu.Pst.from_par_obs_names(["p"], ["active_a", "active_b"])
    pst.control_data.noptmax = 1
    pst.write(tmp_path / f"{prefix}.pst")

    accepted = assess_ies_run(tmp_path, prefix, max_observation_invalid_fraction=0.005)
    accepted_finite = next(
        check for check in accepted.checks if check.check_id == "ies_observation_finite"
    )
    assert accepted_finite.status == "pass"
    assert accepted_finite.actual == pytest.approx(0.005)

    rejected = assess_ies_run(tmp_path, prefix, max_observation_invalid_fraction=0.004)
    rejected_finite = next(
        check for check in rejected.checks if check.check_id == "ies_observation_finite"
    )
    assert rejected_finite.status == "fail"
