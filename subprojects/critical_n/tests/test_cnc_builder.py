"""Unit tests for calibration CNC builder, subsampling, and PyEMU Pst attachment."""

from pathlib import Path
import pyemu
import pytest

from subprojects.critical_n.adapters.stream_parser import DailyMergedRecord
from subprojects.critical_n.calibration.cnc_builder import (
    attach_cnc_to_pst,
    build_cnc_observation_targets,
    select_phenological_subsampling_dates,
)


def test_select_phenological_subsampling_dates():
    """Verify sparse subsampling selects 4 well-spaced post-emergence dates."""
    records = [
        DailyMergedRecord(run_id=1, treatment_id=1, year=2025, doy=70+i, das=i, cwad=10.0 + i*100.0, cnad=1.0)
        for i in range(1, 101)  # 100 days
    ]
    # At i=1, cwad = 110 kg/ha > 50 kg/ha threshold
    dates = select_phenological_subsampling_dates(records, n_points=4)
    assert len(dates) == 4
    # First should be early, last should be 100
    assert dates[0] == 1
    assert dates[-1] == 100
    assert dates == sorted(dates)


def test_build_cnc_observation_targets_and_attach_to_pst(tmp_path):
    """Verify target building and non-destructive injection into pyemu.Pst."""
    # Write synthetic inputs
    gro = tmp_path / "PlantGro.OUT"
    gro.write_text(
        "*RUN 1\n TREATMENT 1\n@YEAR DOY DAS CWAD\n"
        " 2025 075  8  10.0\n"
        " 2025 100 33 500.0\n"
        " 2025 120 53 1500.0\n"
        " 2025 140 73 3000.0\n"
        " 2025 160 93 4500.0\n",
        encoding="utf-8",
    )
    n = tmp_path / "PlantN.OUT"
    n.write_text(
        "*RUN 1\n@YEAR DOY DAS CNAD\n"
        " 2025 075  8   0.4\n"
        " 2025 100 33  20.0\n"
        " 2025 120 53  50.0\n"
        " 2025 140 73  95.0\n"
        " 2025 160 93 140.0\n",
        encoding="utf-8",
    )

    targets = build_cnc_observation_targets(
        tmp_path,
        treatment_n_levels={1: "N3"},
        n_points_per_treatment=3,
        weight=0.25,
    )
    assert len(targets) == 3
    assert targets[0].group == "cnc_nni"
    assert targets[0].target_value == 1.10  # N3 target
    assert targets[0].weight == 0.25

    # Create test Pst
    pst = pyemu.Pst.from_par_obs_names(["p1"], ["o1"])

    updated_pst = attach_cnc_to_pst(pst, targets)
    assert "PestCNC.OUT.ins" in updated_pst.instruction_files
    assert "PestCNC.OUT" in updated_pst.output_files
    assert len(updated_pst.observation_data) == 4  # 1 initial + 3 CNC
    assert "cnc_nni" in set(updated_pst.observation_data["obgnme"])


def test_select_phenological_subsampling_dates_boundaries():
    """Verify boundary conditions: n_points=1, n_points=0, empty records."""
    records = [
        DailyMergedRecord(run_id=1, treatment_id=1, year=2025, doy=100, das=30, cwad=500.0, cnad=20.0),
        DailyMergedRecord(run_id=1, treatment_id=1, year=2025, doy=120, das=50, cwad=1500.0, cnad=50.0),
    ]
    # n_points=1 must return the final date without ZeroDivisionError
    d1 = select_phenological_subsampling_dates(records, n_points=1)
    assert d1 == [50]

    # n_points=0 must return empty list
    d0 = select_phenological_subsampling_dates(records, n_points=0)
    assert d0 == []

    # empty records
    assert select_phenological_subsampling_dates([], n_points=4) == []


def test_resolve_treatment_n_levels_metadata(tmp_path):
    """Verify treatment metadata resolution from CSV file and auto-discovery."""
    from subprojects.critical_n.calibration.cnc_builder import resolve_treatment_n_levels
    import pandas as pd

    meta_csv = tmp_path / "treatment_metadata.csv"
    meta_csv.write_text("treatment,treatment_label,water_level,nitrogen_level\n2,TN2,W3,N3\n5,TN5,W3,N0\n", encoding="utf-8")

    # From file path
    res_path = resolve_treatment_n_levels(tmp_path, treatment_n_levels=meta_csv)
    assert res_path == {2: "N3", 5: "N0"}

    # From DataFrame
    df = pd.DataFrame([{"treatment": 3, "nitrogen_level": "N2"}])
    res_df = resolve_treatment_n_levels(tmp_path, treatment_n_levels=df)
    assert res_df == {3: "N2"}

    # Auto-discovery in directory
    res_auto = resolve_treatment_n_levels(tmp_path, treatment_n_levels=None)
    assert res_auto == {2: "N3", 5: "N0"}
