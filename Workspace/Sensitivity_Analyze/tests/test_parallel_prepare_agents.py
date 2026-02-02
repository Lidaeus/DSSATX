import os
import subprocess
import sys
import tempfile


def _repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", ".."))


def test_prepare_agents_generates_scripts_and_agents():
    repo = _repo_root()
    script = os.path.join(repo, "tools", "parallel", "prepare_agents.py")
    assert os.path.exists(script)

    with tempfile.TemporaryDirectory() as td:
        run_dir = os.path.join(td, "case")
        os.makedirs(run_dir, exist_ok=True)
        case = "case01"
        with open(os.path.join(run_dir, f"{case}.pst"), "w", encoding="utf-8") as f:
            f.write("pcf\n")

        proc = subprocess.run(
            [
                sys.executable,
                script,
                "--run-dir",
                run_dir,
                "--case",
                case,
                "--n-agents",
                "2",
                "--port",
                "0",
                "--mode",
                "ies",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )
        assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr

        for name in [
            "start_agents.ps1",
            "start_manager.ps1",
            "stop_agents.ps1",
            "stop_manager.ps1",
            "clean_agents.ps1",
        ]:
            assert os.path.exists(os.path.join(run_dir, name))

        a1 = os.path.join(run_dir, "_agents", "agent_01")
        a2 = os.path.join(run_dir, "_agents", "agent_02")
        assert os.path.exists(os.path.join(a1, f"{case}.pst"))
        assert os.path.exists(os.path.join(a2, f"{case}.pst"))

