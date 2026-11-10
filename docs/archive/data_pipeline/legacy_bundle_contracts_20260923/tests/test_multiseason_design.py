"""Tests for ``src.calibration.multiseason_design``."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.calibration.build_pest_multiseason import _design_observation_policies
from src.calibration.multiseason_design import (
    MultiSeasonDesign,
    MultiSeasonDesignError,
)


def _write_json(tmpdir: Path, filename: str, data: dict) -> Path:
    p = tmpdir / filename
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _valid_design(season_overrides=None):
    """Return a minimal valid two-season calibration design dict."""
    base = {
        "schema_version": 1,
        "design_id": "test_design",
        "observation_policy": "configs/runs/assumption_based_sigma_v2.csv",
        "group_policy": "configs/runs/t8_group_policy_v1.csv",
        "seasons": [
            {
                "season_id": "S1",
                "experiment_code": "XXQL2501",
                "bundle_path": "data/user/experiments/xxql2501_20260716",
                "bundle_manifest_sha256": "",
                "role": "calibration",
                "treatments": [2, 3, 4, 5, 10, 11, 12, 13],
            },
            {
                "season_id": "S2",
                "experiment_code": "XXQL2502",
                "bundle_path": "data/user/experiments/xxql2502_actual_trial_calibration_v1_20260721",
                "bundle_manifest_sha256": "",
                "role": "calibration",
                "treatments": [3, 4, 7, 9, 1, 6, 10, 12],
            },
        ],
    }
    if season_overrides:
        base["seasons"] = season_overrides
    return base


class TestValidation:
    def test_valid_two_seasons_passes(self, tmp_path):
        path = _write_json(tmp_path, "design.json", _valid_design())
        design = MultiSeasonDesign.load(path)
        assert design.design_id == "test_design"
        assert len(design.calibration_seasons) == 2
        assert len(design.validation_seasons) == 0

    def test_design_policy_is_loaded_when_cli_omits_it(self, tmp_path):
        policy = tmp_path / "policy.csv"
        policy.write_text(
            "group,transform,sigma,phi_role\n"
            "LAIXM,raw,0.8,diagnostic_only\n",
            encoding="utf-8",
        )
        design = type("Design", (), {"observation_policy": str(policy)})()
        loaded = _design_observation_policies(design, explicit_policies={})
        assert loaded["LAIXM"]["phi_role"] == "diagnostic_only"

        explicit = {"LAIDM": {"phi_role": "calibration"}}
        assert _design_observation_policies(design, explicit) is explicit

    def test_validation_season_not_counted_as_calibration(self, tmp_path):
        d = _valid_design()
        d["seasons"].append(
            {
                "season_id": "V1",
                "experiment_code": "XXQL2601",
                "bundle_path": "data/user/experiments/xxql2601_actual_trial_validation_v1_20260721",
                "role": "validation",
                "treatments": [1, 2, 3],
            }
        )
        path = _write_json(tmp_path, "design.json", d)
        design = MultiSeasonDesign.load(path)
        assert len(design.calibration_seasons) == 2
        assert len(design.validation_seasons) == 1

    def test_at_least_two_calibration_seasons_required(self, tmp_path):
        d = _valid_design()
        d["seasons"] = [
            {
                "season_id": "S1",
                "experiment_code": "XXQL2501",
                "bundle_path": "data/user/experiments/xxql2501_20260716",
                "role": "calibration",
                "treatments": [2, 3],
            },
            {
                "season_id": "V1",
                "experiment_code": "XXQL2601",
                "bundle_path": "data/user/experiments/xxql2601_actual_trial_validation_v1_20260721",
                "role": "validation",
                "treatments": [1, 2, 3],
            },
        ]
        path = _write_json(tmp_path, "design.json", d)
        with pytest.raises(MultiSeasonDesignError, match="at least two calibration"):
            MultiSeasonDesign.load(path)

    def test_explicit_single_season_diagnostic_is_allowed(self, tmp_path):
        d = _valid_design()
        d["diagnostic_single_season"] = True
        d["seasons"] = [d["seasons"][0]]
        path = _write_json(tmp_path, "design.json", d)
        design = MultiSeasonDesign.load(path)
        assert design.diagnostic_single_season is True
        assert [season.season_id for season in design.calibration_seasons] == ["S1"]

    def test_single_season_requires_explicit_diagnostic_opt_in(self, tmp_path):
        d = _valid_design()
        d["seasons"] = [d["seasons"][0]]
        path = _write_json(tmp_path, "design.json", d)
        with pytest.raises(MultiSeasonDesignError, match="at least two seasons"):
            MultiSeasonDesign.load(path)

    def test_duplicate_season_ids_fails(self, tmp_path):
        d = _valid_design()
        d["seasons"][1]["season_id"] = "S1"
        path = _write_json(tmp_path, "design.json", d)
        with pytest.raises(MultiSeasonDesignError, match="duplicate season_id"):
            MultiSeasonDesign.load(path)

    def test_duplicate_experiment_codes_fails(self, tmp_path):
        d = _valid_design()
        d["seasons"][1]["experiment_code"] = "XXQL2501"
        path = _write_json(tmp_path, "design.json", d)
        with pytest.raises(MultiSeasonDesignError, match="duplicate experiment_code"):
            MultiSeasonDesign.load(path)

    def test_duplicate_treatments_fails(self, tmp_path):
        d = _valid_design()
        d["seasons"][0]["treatments"] = [2, 2, 3]
        path = _write_json(tmp_path, "design.json", d)
        with pytest.raises(MultiSeasonDesignError, match="contain duplicates"):
            MultiSeasonDesign.load(path)

    def test_missing_bundle_dir_fails(self, tmp_path):
        d = _valid_design()
        d["seasons"][0]["bundle_path"] = str(tmp_path / "nonexistent")
        path = _write_json(tmp_path, "design.json", d)
        with pytest.raises(MultiSeasonDesignError, match="bundle_path does not exist"):
            MultiSeasonDesign.load(path)

    def test_missing_required_schema_fields_fails(self, tmp_path):
        path = _write_json(tmp_path, "design.json", {"schema_version": 1})
        with pytest.raises(MultiSeasonDesignError, match="missing required key"):
            MultiSeasonDesign.load(path)

    def test_season_by_id_and_code(self, tmp_path):
        path = _write_json(tmp_path, "design.json", _valid_design())
        design = MultiSeasonDesign.load(path)
        s1 = design.season_by_id("S1")
        assert s1.experiment_code == "XXQL2501"
        s2 = design.season_by_code("XXQL2502")
        assert s2.season_id == "S2"
