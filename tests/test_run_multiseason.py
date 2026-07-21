"""Tests for ``src.calibration.run_multiseason`` — the T8 thin scheduler.

These tests exercise the output merging logic and failure handling
without running actual DSSAT (which requires a full DSSAT installation).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.calibration.run_multiseason import _merge_tagged_outputs, _write_selected_batch


def _write_tmp_file(dir_path: Path, name: str, content: str) -> Path:
    p = dir_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _write_run_mapping(dir_path: Path, rows: list[dict]) -> Path:
    import csv
    p = dir_path / "run_mapping.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["global_run", "season_id", "experiment_code", "treatment", "local_run"])
        w.writeheader()
        w.writerows(rows)
    return p


def test_merge_renames_run_tags_correctly(tmp_path):
    """Two seasons, overlapping TN=3, merged output has correct RUN numbers."""
    season_dirs = {}
    for sid in ("S1", "S2"):
        d = tmp_path / sid
        d.mkdir()
        season_dirs[sid] = d

    # Season 1: RUN 1 (TN=2), RUN 2 (TN=3)
    _write_tmp_file(season_dirs["S1"], "PestEval.OUT",
        "RUN 1 TN 2 @ADAPS@ 43.0 @ADAPM@ 45.0\n"
        "RUN 2 TN 3 @ADAPS@ 44.0 @ADAPM@ 46.0\n")
    _write_tmp_file(season_dirs["S1"], "PestJoint.OUT", "RUN 1 TN 2 @HWAMS@ 5.0\nRUN 2 TN 3 @HWAMS@ 6.0\n")
    _write_tmp_file(season_dirs["S1"], "PestHarvest.OUT", "RUN 1 TN 2 @PWADM@ 10.0\nRUN 2 TN 3 @PWADM@ 12.0\n")
    _write_tmp_file(season_dirs["S1"], "PestTmtGrow.OUT", "RUN 1 TN 2 @LAIDM@ 0.5\nRUN 2 TN 3 @LAIDM@ 0.7\n")

    # Season 2: RUN 1 (TN=3) — same TN as S1, different experiment
    _write_tmp_file(season_dirs["S2"], "PestEval.OUT",
        "RUN 1 TN 3 @ADAPS@ 11.0 @ADAPM@ 12.0\n"
        "RUN 2 TN 4 @ADAPS@ 13.0 @ADAPM@ 14.0\n")
    _write_tmp_file(season_dirs["S2"], "PestJoint.OUT", "RUN 1 TN 3 @HWAMS@ 7.0\nRUN 2 TN 4 @HWAMS@ 8.0\n")
    _write_tmp_file(season_dirs["S2"], "PestHarvest.OUT", "RUN 1 TN 3 @PWADM@ 20.0\nRUN 2 TN 4 @PWADM@ 22.0\n")
    _write_tmp_file(season_dirs["S2"], "PestTmtGrow.OUT", "RUN 1 TN 3 @LAIDM@ 1.1\nRUN 2 TN 4 @LAIDM@ 1.3\n")

    run_map = [
        {"global_run": 1, "season_id": "S1", "experiment_code": "E1", "treatment": 2, "local_run": 1},
        {"global_run": 2, "season_id": "S1", "experiment_code": "E1", "treatment": 3, "local_run": 2},
        {"global_run": 3, "season_id": "S2", "experiment_code": "E2", "treatment": 3, "local_run": 1},
        {"global_run": 4, "season_id": "S2", "experiment_code": "E2", "treatment": 4, "local_run": 2},
    ]
    rm_path = _write_run_mapping(tmp_path, run_map)

    root = tmp_path / "root"
    root.mkdir()
    _merge_tagged_outputs(season_dirs, rm_path, root, "test")

    # Verify merged PestEval.OUT
    merged = (root / "PestEval.OUT").read_text(encoding="utf-8").splitlines()
    assert len(merged) == 4
    assert merged[0].startswith("RUN 1 TN 2")  # S1 run 1
    assert merged[1].startswith("RUN 2 TN 3")  # S1 run 2
    assert merged[2].startswith("RUN 3 TN 3")  # S2 run 1 (TN=3 but different season)
    assert merged[3].startswith("RUN 4 TN 4")  # S2 run 2

    # Verify values: S2 run 1 should have ADAPS=11.0 (from S2), not 44.0 (from S1)
    assert "@ADAPS@ 11.0" in merged[2]
    assert "@HWAMS@ 7.0" in (root / "PestJoint.OUT").read_text()


def test_merge_raises_on_missing_file(tmp_path):
    """Merge fails if a season is missing a required tagged output."""
    season_dirs = {}
    for sid in ("S1", "S2"):
        d = tmp_path / sid
        d.mkdir()
        season_dirs[sid] = d

    _write_tmp_file(season_dirs["S1"], "PestEval.OUT", "RUN 1 TN 2 @ADAPS@ 43.0\n")
    _write_tmp_file(season_dirs["S1"], "PestJoint.OUT", "RUN 1 TN 2 @HWAMS@ 5.0\n")
    _write_tmp_file(season_dirs["S1"], "PestHarvest.OUT", "RUN 1 TN 2 @PWADM@ 10.0\n")
    _write_tmp_file(season_dirs["S1"], "PestTmtGrow.OUT", "RUN 1 TN 2 @LAIDM@ 0.5\n")
    # S2: missing PestJoint.OUT
    _write_tmp_file(season_dirs["S2"], "PestEval.OUT", "RUN 1 TN 3 @ADAPS@ 11.0\n")
    # PestJoint.OUT deliberately absent

    run_map = [
        {"global_run": 1, "season_id": "S1", "experiment_code": "E1", "treatment": 2, "local_run": 1},
        {"global_run": 2, "season_id": "S2", "experiment_code": "E2", "treatment": 3, "local_run": 1},
    ]
    rm_path = _write_run_mapping(tmp_path, run_map)

    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(FileNotFoundError, match="PestJoint.OUT"):
        _merge_tagged_outputs(season_dirs, rm_path, root, "test")


def test_merge_raises_on_missing_run(tmp_path):
    """Merge fails if a tagged output has no line for a required local_run."""
    season_dirs = {}
    for sid in ("S1",):
        d = tmp_path / sid
        d.mkdir()
        season_dirs[sid] = d

    # Only RUN 1 exists, but run_mapping asks for RUN 2
    _write_tmp_file(season_dirs["S1"], "PestEval.OUT", "RUN 1 TN 2 @ADAPS@ 43.0\n")
    _write_tmp_file(season_dirs["S1"], "PestJoint.OUT", "RUN 1 TN 2 @HWAMS@ 5.0\n")
    _write_tmp_file(season_dirs["S1"], "PestHarvest.OUT", "RUN 1 TN 2 @PWADM@ 10.0\n")
    _write_tmp_file(season_dirs["S1"], "PestTmtGrow.OUT", "RUN 1 TN 2 @LAIDM@ 0.5\n")

    run_map = [
        {"global_run": 1, "season_id": "S1", "experiment_code": "E1", "treatment": 2, "local_run": 1},
        {"global_run": 2, "season_id": "S1", "experiment_code": "E1", "treatment": 3, "local_run": 2},
    ]
    rm_path = _write_run_mapping(tmp_path, run_map)

    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError, match="has no line for RUN 2"):
        _merge_tagged_outputs(season_dirs, rm_path, root, "test")


def test_merge_preserves_all_process_and_harvest_rows(tmp_path):
    d = tmp_path / "S1"
    d.mkdir()
    season_dirs = {"S1": d}
    _write_tmp_file(d, "PestEval.OUT", "RUN 1 TN 3 @ADAPM@ 43\n")
    _write_tmp_file(d, "PestJoint.OUT", "RUN 1 TN 3 @HWAMM@ 5\n")
    _write_tmp_file(d, "PestHarvest.OUT", "RUN 1 TN 3 @PWADM@ 10\nRUN 1 TN 3 @PWADM@ 20\n")
    _write_tmp_file(d, "PestTmtGrow.OUT", "RUN 1 TN 3 @LAIDM@ 0.5\nRUN 1 TN 3 @LAIDM@ 0.7\n")
    rm_path = _write_run_mapping(tmp_path, [{
        "global_run": 4, "season_id": "S1", "experiment_code": "E1",
        "treatment": 3, "local_run": 1,
    }])
    root = tmp_path / "root"
    root.mkdir()
    _merge_tagged_outputs(season_dirs, rm_path, root, "test")
    assert (root / "PestHarvest.OUT").read_text().count("RUN 4 TN 3") == 2
    assert (root / "PestTmtGrow.OUT").read_text().count("RUN 4 TN 3") == 2


def test_merge_rejects_treatment_mapping_mismatch(tmp_path):
    d = tmp_path / "S1"
    d.mkdir()
    for name in ("PestEval.OUT", "PestJoint.OUT", "PestHarvest.OUT", "PestTmtGrow.OUT"):
        _write_tmp_file(d, name, "RUN 1 TN 2 @X@ 1\n")
    rm_path = _write_run_mapping(tmp_path, [{
        "global_run": 1, "season_id": "S1", "experiment_code": "E1",
        "treatment": 3, "local_run": 1,
    }])
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError, match="expected TN3"):
        _merge_tagged_outputs({"S1": d}, rm_path, root, "test")


def test_selected_batch_follows_design_order_and_localizes_filex(tmp_path):
    source = tmp_path / "DSSBatch.v48"
    source.write_text(
        "$BATCH(TOMATO)\n@FILEX                                                                                        TRTNO RP SQ OP CO\n"
        f"{'C:/DSSAT48/TOMATO/E.TMX':<94}1 1 0 0 0\n"
        f"{'C:/DSSAT48/TOMATO/E.TMX':<94}3 1 0 0 0\n"
        f"{'C:/DSSAT48/TOMATO/E.TMX':<94}7 1 0 0 0\n",
        encoding="utf-8",
    )
    target = tmp_path / "selected.v48"
    _write_selected_batch(source, target, (7, 1, 3))
    data = [line.split() for line in target.read_text().splitlines()
            if line and not line.startswith(("$", "!", "@"))]
    assert [int(row[1]) for row in data] == [7, 1, 3]
    assert all(row[0] == "E.TMX" for row in data)
