from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pyemu

from src.common.project import sha256_file
from src.sensitivity.sa_build_sen_case import build_case


ROOT = Path(__file__).resolve().parents[1]


def test_formal_case_uses_case_local_hash_checked_runtime(tmp_path):
    case_dir = tmp_path / "case"
    pst_path = build_case(
        ROOT
        / "data"
        / "parameter_registry"
        / "bounds_frozen"
        / "eggplant"
        / "eggplant_formal_multiseason_candidate_v4_20260721.csv",
        case_dir=case_dir,
        workspace_dir=ROOT,
        cultivar="TM0008",
        morris_r=10,
        morris_p=6,
        random_seed=20260729,
        output_profile=ROOT / "configs" / "sa" / "eggplant_formal_xxql2501_outputs_20260720.json",
        input_dir=ROOT
        / "data"
        / "user"
        / "experiments"
        / "xxql2501_sa_controlled_candidate_20260720",
    )

    command = pyemu.Pst(pst_path).model_command[0]
    assert "runtime/src/sensitivity/sa_model.py" in command
    assert '--input-dir "runtime/input"' in command
    assert '--output-profile "runtime/config/output_profile.json"' in command
    assert str(ROOT) not in command

    runtime = case_dir / "runtime"
    manifest_path = runtime / "runtime_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["files"]
    frozen_paths = {item["path"] for item in manifest["files"]}
    assert {
        "src/dssat/run_dssat.py",
        "src/common/param_registry.py",
        "src/calibration/observation_policy.py",
    }.issubset(frozen_paths)
    for item in manifest["files"]:
        assert sha256_file(runtime / item["path"]) == item["sha256"]

    clean = subprocess.run(
        [sys.executable, str(runtime / "src" / "sensitivity" / "sa_model.py"), "--help"],
        cwd=case_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert clean.returncode == 0, clean.stderr

    profile = runtime / "config" / "output_profile.json"
    profile.write_text(profile.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    tampered = subprocess.run(
        [sys.executable, str(runtime / "src" / "sensitivity" / "sa_model.py"), "--help"],
        cwd=case_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tampered.returncode != 0
    assert "Frozen runtime hash mismatch" in tampered.stderr
