from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "calibration"
    / "launch_fixed_soil_joint_20260813_fix.py"
)


def _load_launcher():
    spec = importlib.util.spec_from_file_location("fixed_soil_launcher", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_completed_run_requires_engineering_validation(tmp_path: Path) -> None:
    launcher = _load_launcher()
    status_path = tmp_path / "run_status.json"
    status_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "manager_exit_code": 0,
                "engineering_status": "engineering_validated",
                "science_status": "science_pending",
            }
        ),
        encoding="utf-8",
    )
    assert launcher._completed_run_status(tmp_path) is not None

    status_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "manager_exit_code": 0,
                "engineering_status": "engineering_failed",
            }
        ),
        encoding="utf-8",
    )
    assert launcher._completed_run_status(tmp_path) is None


def test_invalid_status_is_not_treated_as_complete(tmp_path: Path) -> None:
    launcher = _load_launcher()
    (tmp_path / "run_status.json").write_text("not-json", encoding="utf-8")
    assert launcher._completed_run_status(tmp_path) is None


def test_20260814_builder_keeps_observation_transform_argument() -> None:
    builder = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "calibration"
        / "build_fixed_soil_joint_v3_20260813.py"
    ).read_text(encoding="utf-8")
    assert "--observation-transform-config {transform_path.name}" in builder
