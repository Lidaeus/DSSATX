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
