"""Tests for shared-parameter plus autumn-offset projection."""

from __future__ import annotations

import csv
import math
import json

import pytest

from src.calibration.seasonal_parameters import (
    SeasonalParameterization,
    SeasonalParameterizationError,
    validate_projected_physical_bounds,
    write_projected_parameter_csv,
)
from src.reporting.export_seasonal_parameters import export_seasonal_parameter_ensemble


def _parameterization() -> SeasonalParameterization:
    value = SeasonalParameterization.from_dict(
        {
            "reference_season_id": "25SP",
            "offsets": [
                {"offset_name": "DLFMAX_AUT", "parameter_name": "LFMAX", "transform": "log_multiplier", "target_season_ids": ["25FA"]},
                {"offset_name": "DXFRT_AUT", "parameter_name": "XFRT", "transform": "logit_additive", "target_season_ids": ["25FA"]},
                {"offset_name": "DTB1_AUT", "parameter_name": "TB1", "transform": "additive", "target_season_ids": ["25FA"]},
            ],
        },
        season_ids=("25SP", "25FA", "26SP"),
    )
    assert value is not None
    return value


def test_reference_and_unrelated_seasons_use_the_shared_value():
    design = _parameterization()
    values = {"LFMAX": 1.2, "DLFMAX_AUT": math.log(1.1), "XFRT": 0.8, "DXFRT_AUT": 0.2, "TB1": 9.0, "DTB1_AUT": 1.0}
    spring, spring_audit = design.project(values, "25SP")
    validation, validation_audit = design.project(values, "26SP")
    assert spring["LFMAX"] == pytest.approx(1.2)
    assert validation["TB1"] == pytest.approx(9.0)
    assert all(not bool(row["offset_applied"]) for row in spring_audit + validation_audit)
    assert "DLFMAX_AUT" not in spring


def test_autumn_projection_uses_the_declared_transform_only():
    design = _parameterization()
    values = {"LFMAX": 1.2, "DLFMAX_AUT": math.log(1.1), "XFRT": 0.8, "DXFRT_AUT": 0.2, "TB1": 9.0, "DTB1_AUT": 1.0}
    autumn, audit = design.project(values, "25FA")
    assert autumn["LFMAX"] == pytest.approx(1.32)
    assert autumn["TB1"] == pytest.approx(10.0)
    assert autumn["XFRT"] == pytest.approx(1.0 / (1.0 + math.exp(-(math.log(4.0) + 0.2))))
    assert all(bool(row["offset_applied"]) for row in audit)


def test_projection_rejects_duplicate_offsets_for_one_parameter():
    with pytest.raises(SeasonalParameterizationError, match="one offset"):
        SeasonalParameterization.from_dict(
            {
                "reference_season_id": "25SP",
                "offsets": [
                    {"offset_name": "D1", "parameter_name": "LFMAX", "transform": "additive", "target_season_ids": ["25FA"]},
                    {"offset_name": "D2", "parameter_name": "LFMAX", "transform": "additive", "target_season_ids": ["25FA"]},
                ],
            }, season_ids=("25SP", "25FA"),
        )


def test_rectangular_bounds_must_be_physical_before_building():
    design = _parameterization()
    parameters = [
        {"name": "LFMAX", "lower": 0.9, "upper": 1.5},
        {"name": "DLFMAX_AUT", "lower": -0.16, "upper": 0.14},
        {"name": "XFRT", "lower": 0.7, "upper": 0.98},
        {"name": "DXFRT_AUT", "lower": -0.35, "upper": 0.35},
        {"name": "TB1", "lower": 6.0, "upper": 13.0},
        {"name": "DTB1_AUT", "lower": -2.0, "upper": 2.0},
    ]
    validate_projected_physical_bounds(parameters, design)
    parameters[-2]["upper"] = 14.0
    with pytest.raises(SeasonalParameterizationError, match="outside physical"):
        validate_projected_physical_bounds(parameters, design)


def test_projected_csv_retains_dssat_values_and_drops_pest_only_offsets(tmp_path):
    source = tmp_path / "pest_params.csv"
    source.write_text(
        "name,value\nLFMAX,1.2\nDLFMAX_AUT,0.0953101798\nXFRT,0.8\nDXFRT_AUT,0.2\nTB1,9\nDTB1_AUT,1\n",
        encoding="utf-8",
    )
    destination = tmp_path / "autumn_params.csv"
    audit = write_projected_parameter_csv(source, destination, _parameterization(), "25FA")
    with destination.open(encoding="utf-8", newline="") as handle:
        values = {row["name"]: float(row["value"]) for row in csv.DictReader(handle)}
    assert values["LFMAX"] == pytest.approx(1.32)
    assert values["TB1"] == pytest.approx(10.0)
    assert "DLFMAX_AUT" not in values
    assert len(audit) == 3


def test_no_seasonal_design_preserves_the_parameter_file_byte_for_byte(tmp_path):
    source = tmp_path / "shared.csv"
    source.write_bytes(b"name,value\r\nLFMAX,1.20\r\n")
    target = tmp_path / "copied.csv"
    assert write_projected_parameter_csv(source, target, None, "25SP") == []
    assert target.read_bytes() == source.read_bytes()


def test_posterior_export_reports_actual_autumn_values(tmp_path, monkeypatch):
    design_path = tmp_path / "design.json"
    design_path.write_text(json.dumps({
        "schema_version": 1,
        "design_id": "seasonal-test",
        "observation_policy": "configs/runs/assumption_based_sigma_v2.csv",
        "group_policy": "configs/runs/t8_group_policy_v1.csv",
        "seasonal_parameterization": {
            "reference_season_id": "25SP",
            "offsets": [{
                "offset_name": "DTB1_AUT", "parameter_name": "TB1", "transform": "additive",
                "target_season_ids": ["25FA"],
            }],
        },
        "seasons": [
                {"season_id": "25SP", "experiment_code": "A", "bundle_path": "data/user/experiments/xxql2501_actual_trial_calibration_v5_adap21_moisturefix_page25_20260729", "role": "calibration", "treatments": [2]},
                {"season_id": "25FA", "experiment_code": "B", "bundle_path": "data/user/experiments/xxql2502_actual_trial_calibration_v3_page25_20260728", "role": "calibration", "treatments": [3]},
        ],
    }), encoding="utf-8")
    # The tested design intentionally uses project-relative bundles.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "case.4.par.csv").write_text(
        ",TB1,DTB1_AUT\nreal_0,9.0,1.0\nreal_1,10.0,-1.0\n", encoding="utf-8"
    )
    long_path, summary_path = export_seasonal_parameter_ensemble(
        run_dir=run_dir, prefix="case", design_path=design_path
    )
    long = __import__("pandas").read_csv(long_path, encoding="utf-8-sig")
    autumn = long.loc[(long["season_id"] == "25FA") & (long["realization"] == "real_0")].iloc[0]
    assert autumn["season_value"] == pytest.approx(10.0)
    assert summary_path.is_file()
