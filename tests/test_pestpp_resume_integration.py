"""Opt-in integration test against the bundled PEST++ 5.2.16 binary."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pyemu
import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "parallel" / "run_parallel.py"


def _wait_for(predicate, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.2)
    raise TimeoutError("condition was not met")


def _status(case_dir):
    path = case_dir / "run_status.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _build_tiny_case(case_dir: Path):
    (case_dir / "params.csv.tpl").write_text(
        "ptf ~\nname,value\na,~ a ~\nb,~ b ~\n", encoding="utf-8"
    )
    (case_dir / "params.csv").write_text("name,value\na,1\nb,1\n", encoding="utf-8")
    (case_dir / "out.txt.ins").write_text("pif ~\nl1 w !obs!\n", encoding="utf-8")
    (case_dir / "out.txt").write_text("value 2\n", encoding="utf-8")
    (case_dir / "model.py").write_text(
        "import csv,time\n"
        "time.sleep(0.4)\n"
        "with open('params.csv', newline='') as f:\n"
        "    rows=list(csv.DictReader(f))\n"
        "value=sum(float(row['value']) for row in rows)\n"
        "with open('out.txt','w') as f: f.write(f'value {value}\\n')\n",
        encoding="utf-8",
    )
    old = Path.cwd()
    try:
        os.chdir(case_dir)
        pst = pyemu.Pst.from_io_files(
            tpl_files=["params.csv.tpl"],
            in_files=["params.csv"],
            ins_files=["out.txt.ins"],
            out_files=["out.txt"],
        )
        pst.control_data.noptmax = 0
        pst.parameter_data.loc[:, "partrans"] = "none"
        pst.parameter_data.loc[:, "parlbnd"] = 0.5
        pst.parameter_data.loc[:, "parubnd"] = 1.5
        pst.model_command = [f'"{sys.executable}" model.py']
        pst.pestpp_options["gsa_method"] = "morris"
        pst.pestpp_options["gsa_morris_r"] = 8
        pst.pestpp_options["gsa_morris_p"] = 4
        pst.pestpp_options["gsa_morris_obs_sen"] = True
        pst.pestpp_options["rand_seed"] = 42
        pst.write("tiny.pst")
    finally:
        os.chdir(old)
    (case_dir / "out.txt").unlink(missing_ok=True)


@pytest.mark.skipif(
    os.environ.get("RUN_PESTPP_INTEGRATION") != "1",
    reason="set RUN_PESTPP_INTEGRATION=1 to exercise bundled PEST++ interruption/resume",
)
def test_interrupted_morris_can_resume_from_rns(tmp_path):
    _build_tiny_case(tmp_path)
    common = [
        sys.executable, str(RUNNER), "--run-dir", str(tmp_path), "--case", "tiny",
        "--mode", "sen", "--n-agents", "1",
    ]
    subprocess.run([*common, "--no-wait"], cwd=ROOT, check=True)
    _wait_for(lambda: (_status(tmp_path).get("status") == "running"))
    _wait_for(
        lambda: (tmp_path / "tiny.rmr").is_file()
        and "processed" in (tmp_path / "tiny.rmr").read_text(encoding="utf-8", errors="ignore"),
    )
    subprocess.run([*common, "--force-stop"], cwd=ROOT, check=True)
    _wait_for(lambda: _status(tmp_path).get("status") == "aborted")
    assert (tmp_path / "tiny.rns").is_file()

    subprocess.run([*common, "--resume", "--no-wait"], cwd=ROOT, check=True)
    final = _wait_for(
        lambda: (
                status if (status := _status(tmp_path)).get("attempt", 0) >= 2
                and status.get("status") in {"completed", "runtime_failed"}
                and status.get("scientific_status") != "pending"
                else None
        ),
        timeout=60.0,
    )
    assert final["status"] == "completed", final
    assert final["resumed"] is True
    assert (tmp_path / "tiny.mio").is_file()
    # PEST++ may not requeue the candidate that was in flight at interruption.
    # The resume is operationally successful, but the trajectory-aware gate
    # must prevent an incomplete design from becoming a formal result.
    assert final["scientific_status"] == "failed"
    quality = json.loads(
        (tmp_path / "morris_audit" / "morris_run_quality.json").read_text(encoding="utf-8")
    )
    assert quality["science_validated"] is False
    assert any(
        item["check_id"] == "morris_balanced_effect_coverage" and item["status"] == "fail"
        for item in quality["checks"]
    )


@pytest.mark.skipif(
    os.environ.get("RUN_PESTPP_INTEGRATION") != "1",
    reason="set RUN_PESTPP_INTEGRATION=1 to exercise bundled PEST++",
)
def test_clean_morris_is_scientifically_validated(tmp_path):
    _build_tiny_case(tmp_path)
    command = [
        sys.executable, str(RUNNER), "--run-dir", str(tmp_path), "--case", "tiny",
        "--mode", "sen", "--n-agents", "2", "--no-wait",
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    final = _wait_for(
        lambda: (
            status if (status := _status(tmp_path)).get("status") in {"completed", "runtime_failed"}
            and status.get("scientific_status") != "pending"
            else None
        ),
        timeout=60.0,
    )
    assert final["status"] == "completed", final
    assert final["scientific_status"] == "validated", final
