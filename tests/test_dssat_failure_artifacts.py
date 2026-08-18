"""Regression coverage for opt-in preservation of native DSSAT failures."""

from __future__ import annotations

import json

from src.calibration import run_multiseason


def test_archive_failed_dssat_artifacts_copies_isolated_inputs(tmp_path):
    season_dir = tmp_path / "_seasons" / "25SP"
    failed = season_dir / "_iso_runs" / "run_deadbeef"
    failed.mkdir(parents=True)
    (failed / "TMGRO048.SPE").write_text("SPE evidence\n", encoding="utf-8")
    (failed / "failure_context.json").write_text(
        json.dumps({"returncode": 1}), encoding="utf-8"
    )

    archived = run_multiseason._archive_failed_dssat_artifacts(
        tmp_path, season_dir, "25SP"
    )

    assert archived is not None
    assert (archived / "run_deadbeef" / "TMGRO048.SPE").read_text(encoding="utf-8") == "SPE evidence\n"
    assert json.loads(
        (archived / "run_deadbeef" / "failure_context.json").read_text(encoding="utf-8")
    )["returncode"] == 1
