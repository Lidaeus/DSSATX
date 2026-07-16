import json

from src.common.run_state import canonical_status, classify_manager_exit, normalize_exit_code
from tools.parallel import run_parallel


def test_windows_exit_codes_are_normalized_and_classified():
    assert normalize_exit_code(-1073741510) == 0xC000013A
    assert classify_manager_exit(0) == ("completed", "manager_exit_zero")
    assert classify_manager_exit(3221225786)[0] == "aborted"
    assert classify_manager_exit(7)[0] == "runtime_failed"
    assert canonical_status("failed (exit 3221225786)", exit_code=3221225786) == "aborted"


def test_graceful_stop_records_intent_without_killing_processes(tmp_path, monkeypatch):
    (tmp_path / "run_status.json").write_text(
        json.dumps({"status": "running", "manager_pid": 123}), encoding="utf-8"
    )
    monkeypatch.setattr(run_parallel, "_find_manager_pid", lambda _run_dir: 123)
    monkeypatch.setattr(run_parallel, "_is_pid_alive", lambda _pid: True)

    assert run_parallel.cmd_stop(str(tmp_path))
    assert (tmp_path / "pest.stp").read_text(encoding="ascii") == "1\n"
    status = json.loads((tmp_path / "run_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "stopping"
    assert status["stop_mode"] == "pest.stp"
    assert status["state_schema_version"] == 2


def test_offline_finalize_requires_complete_evidence_and_writes_science_status(tmp_path, monkeypatch):
    (tmp_path / "sa_sen_morris.pst").write_text(
        "++gsa_method(morris)\n", encoding="utf-8"
    )
    (tmp_path / "sa_sen_morris.sen.par.csv").write_text(
        "run_id,a,b\n0,0,0\n1,1,0\n2,1,1\n3,0,0\n4,1,0\n5,1,1\n",
        encoding="utf-8",
    )
    (tmp_path / "sa_sen_morris.rmr").write_text(
        "\n".join(f"00:00:00->run {run_id} processed" for run_id in range(6)),
        encoding="utf-8",
    )
    (tmp_path / "sa_sen_morris.rec").write_text(
        "pestpp-sen analysis complete\n", encoding="utf-8"
    )
    (tmp_path / "sa_sen_morris.mio").write_text(
        "observation_name,parameter_name,n_samples,sen_mean_abs\n"
        "tn2_yield_hwams,a,2,0.2\n"
        "tn2_yield_hwams,b,2,0.1\n",
        encoding="utf-8",
    )
    (tmp_path / "run_status.json").write_text(
        json.dumps({"status": "running", "manager_pid": 123}), encoding="utf-8"
    )
    monkeypatch.setattr(run_parallel, "_find_manager_pid", lambda _run_dir: 123)
    monkeypatch.setattr(run_parallel, "_is_pid_alive", lambda _pid: False)

    assert run_parallel.cmd_finalize(str(tmp_path), "sa_sen_morris", mode="sen")
    status = json.loads((tmp_path / "run_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed"
    assert status["scientific_status"] == "validated"
    assert status["termination_reason"] == "offline_finalize_verified_complete"
    assert status["controller_error"] == ""
    assert (tmp_path / "morris_audit" / "morris_result_quality.json").is_file()


def test_offline_finalize_routes_sobol_to_sobol_audit(tmp_path, monkeypatch):
    (tmp_path / "sa_sen_sobol.pst").write_text("++gsa_method(sobol)\n", encoding="utf-8")
    (tmp_path / "run_manifest.yaml").write_text(
        "run_id: synthetic\n"
        "run_type: sensitivity_sobol_preflight_case\n"
        "sensitivity_method: sobol\n"
        "observation_count: 1\n"
        "sobol_parameter_count: 1\n"
        "sobol_expected_model_runs: 3\n",
        encoding="utf-8",
    )
    (tmp_path / "run_status.json").write_text(
        json.dumps({"status": "running", "manager_pid": 123}), encoding="utf-8"
    )
    (tmp_path / "sa_obs_order.txt").write_text("yield\n", encoding="utf-8")
    (tmp_path / "sa_sen_sobol.rec").write_text(
        "pestpp-sen analysis complete\n", encoding="utf-8"
    )
    (tmp_path / "sa_sen_sobol.sobol.par.csv").write_text(
        "run_id,p1\n0,1\n1,2\n2,3\n", encoding="utf-8"
    )
    (tmp_path / "sa_sen_sobol.sobol.obs.csv").write_text(
        "run_id,failed_flag,yield\n0,0,10\n1,0,12\n2,0,14\n", encoding="utf-8"
    )
    (tmp_path / "sa_sen_sobol.sobol.si.csv").write_text(
        "output,p1\nyield,0.2\n", encoding="utf-8"
    )
    (tmp_path / "sa_sen_sobol.sobol.sti.csv").write_text(
        "output,p1\nyield,0.4\n", encoding="utf-8"
    )
    monkeypatch.setattr(run_parallel, "_find_manager_pid", lambda _run_dir: 123)
    monkeypatch.setattr(run_parallel, "_is_pid_alive", lambda _pid: False)

    assert run_parallel.cmd_finalize(str(tmp_path), "sa_sen_sobol", mode="sen")
    status = json.loads((tmp_path / "run_status.json").read_text(encoding="utf-8"))
    assert status["scientific_status"] == "validated"
    assert (tmp_path / "sobol_audit" / "sobol_run_quality.json").is_file()
    assert not (tmp_path / "morris_audit").exists()
