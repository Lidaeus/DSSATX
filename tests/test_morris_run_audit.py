import json
from pathlib import Path

from src.common.quality import assess_morris_audit
from src.sensitivity.morris_audit import audit_morris_case, write_morris_audit


def _write_case(root: Path, *, interrupted: bool = False) -> None:
    (root / "_agents" / "agent_01").mkdir(parents=True)
    (root / "sa_sen_morris.sen.par.csv").write_text(
        "run_id,a,b\n"
        "0,0,0\n"
        "1,1,0\n"
        "2,1,1\n"
        "3,0,1\n"
        "4,0,0\n"
        "5,1,0\n",
        encoding="utf-8",
    )
    success_ids = [0, 1] if interrupted else [0, 1, 3, 4, 5]
    rmr = "\n".join(f"07/16/26 00:00:01->run {run_id} processed" for run_id in success_ids)
    rmr += (
        "\n07/16/26 00:00:02-> run_id:2 failed on agent:HOST$C:\\case\\_agents\\agent_01 "
        "group_id:2 group_id:2 run_id:2 par_name:b concurrent:1 worker_message:test\n"
    )
    (root / "sa_sen_morris.rmr").write_text(rmr, encoding="utf-8")
    if interrupted:
        error = "RuntimeError: DSSAT sensitivity run failed with exit code 3221226091\n"
        status = {"status": "failed (exit 3221225786)", "manager_exit_code": 3221225786}
    else:
        error = (
            "DSSAT execution failed with exit code 73.\n"
            "forrtl: error (73): floating divide by zero\n"
            "RuntimeError: DSSAT sensitivity run failed with exit code 1\n"
        )
        status = {"status": "completed", "manager_exit_code": 0}
        (root / "sa_sen_morris.mio").write_text("placeholder\n", encoding="utf-8")
    (root / "_agents" / "agent_01" / "panther_agent.stderr.log").write_text(error, encoding="utf-8")
    (root / "run_status.json").write_text(json.dumps(status), encoding="utf-8")


def test_audit_separates_model_failure_and_effect_coverage(tmp_path):
    _write_case(tmp_path)
    audit = audit_morris_case(tmp_path)
    summary = audit["summary"]
    assert summary["process_state"] == "completed"
    assert summary["planned_runs"] == 6
    assert summary["successful_runs"] == 5
    assert summary["model_failed_runs"] == 1
    assert summary["runtime_failed_runs"] == 0
    assert summary["fully_valid_trajectories"] == 1
    coverage = {row["parameter"]: row for row in audit["effect_coverage"]}
    assert coverage["a"]["valid_effects"] == 2
    assert coverage["b"]["valid_effects"] == 1
    assert coverage["b"]["model_failed_endpoint"] == 1

    report = assess_morris_audit(audit)
    assert report.process_completed
    assert not report.science_validated
    failed = {item.check_id for item in report.checks if item.status == "fail"}
    assert {"morris_no_model_failures", "morris_complete_trajectories", "morris_balanced_effect_coverage"}.issubset(failed)

    paths = write_morris_audit(audit, tmp_path / "audit")
    assert all(path.is_file() for path in paths.values())


def test_audit_does_not_misclassify_interruption_as_model_failure(tmp_path):
    _write_case(tmp_path, interrupted=True)
    audit = audit_morris_case(tmp_path)
    summary = audit["summary"]
    assert summary["process_state"] == "aborted"
    assert summary["model_failed_runs"] == 0
    assert summary["runtime_failed_runs"] == 1
    assert summary["not_finalized_runs"] == 3
    assert audit["failures"][0]["outer_exit_code_hex"] == "0xC000026B"


def test_audit_can_fallback_to_mio_when_rmr_is_missing(tmp_path):
    (tmp_path / "sa_sen_morris.sen.par.csv").write_text(
        "run_id,a,b\n"
        "0,0,0\n"
        "1,1,0\n"
        "2,1,1\n"
        "3,0,1\n"
        "4,0,0\n"
        "5,1,0\n",
        encoding="utf-8",
    )
    (tmp_path / "sa_sen_morris.mio").write_text(
        "observation_name,parameter_name,n_samples,sen_mean_abs\n"
        "tn2_fwc_end,a,4,1.0\n"
        "tn2_fwc_end,b,4,0.5\n",
        encoding="utf-8",
    )
    (tmp_path / "run_status.json").write_text(
        json.dumps({"status": "completed", "manager_exit_code": 0}), encoding="utf-8"
    )
    audit = audit_morris_case(tmp_path)
    summary = audit["summary"]
    assert summary["mio_exists"] is True
    assert summary["rmr_exists"] is False
    assert summary["process_state"] == "completed"
    assert summary["fully_valid_trajectories"] == 2
    assert audit["design_warnings"]
