"""Tests for the experiment spec contract enforcer.

Validates that ExperimentSpec correctly enforces the article calibration
contract: parameter-count matching, forbidden Phi targets, 26SP role
enforcement, seasonal parameterization validation, and receipt generation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.experiment_spec import (
    ExperimentSpec,
    ExperimentSpecError,
    FORBIDDEN_PHI_TARGETS,
    REQUIRED_PHI_TARGET,
)
from src.calibration.experiment_runner import prepare_experiment_run

SPECS_DIR = PROJECT_ROOT / "configs" / "experiments" / "specs"


# ---------------------------------------------------------------------------
# Spec loading: valid specs
# ---------------------------------------------------------------------------

class TestValidSpecs:
    """Specs that should load successfully."""

    def test_e00_input_audit_loads(self):
        """E00 uses full55 + T9 bounds (55 active) — should match."""
        spec = ExperimentSpec.load(SPECS_DIR / "E00_input_audit.json")
        assert spec.experiment_id == "E00_input_audit"
        assert spec.parameter_set.declared_count == 55
        assert spec.bounds_active_count == 55
        assert spec.bounds_id == "eggplant_t9_highdim_v1_20260722"

    def test_e01_25sp_loads(self):
        """E01 25SP pre-calibration uses full55 + T9 bounds."""
        spec = ExperimentSpec.load(SPECS_DIR / "E01_pre_calibration_25sp_yield.json")
        assert spec.experiment_id == "E01_pre_calibration_25sp_yield"
        assert spec.parameter_set.declared_count == 55
        assert len(spec.season_inputs) == 1
        assert spec.season_inputs[0].season_id == "25SP"

    def test_e01_25fa_loads(self):
        """E01 25FA pre-calibration uses full55 + T9 bounds."""
        spec = ExperimentSpec.load(SPECS_DIR / "E01_pre_calibration_25fa_yield.json")
        assert spec.experiment_id == "E01_pre_calibration_25fa_yield"
        assert spec.parameter_set.declared_count == 55
        assert spec.season_inputs[0].season_id == "25FA"

    def test_e04_joint55_loads(self):
        """E04 uses full55 + T9 bounds, 25SP+25FA joint."""
        spec = ExperimentSpec.load(SPECS_DIR / "E04_joint55_25sp_25fa.json")
        assert spec.experiment_id == "E04_joint55_25sp_25fa"
        assert spec.parameter_set.declared_count == 55
        assert len(spec.season_inputs) == 2
        assert spec.execution.ies_num_reals == 200
        assert spec.execution.noptmax == 4
        assert spec.execution.seed == 20260723

    def test_e06_pool3season_loads(self):
        """E06 uses full55, 26SP as development_calibration (not validation)."""
        spec = ExperimentSpec.load(SPECS_DIR / "E06_pool3season.json")
        assert spec.experiment_id == "E06_pool3season"
        assert len(spec.season_inputs) == 3
        roles = {s.season_id: s.role for s in spec.season_inputs}
        assert roles["26SP"] == "development_calibration"


# ---------------------------------------------------------------------------
# Spec loading: template specs that should fail
# ---------------------------------------------------------------------------

class TestTemplateSpecsFail:
    """Template specs (E02, E03, E05) use sobol23 (23 params) with T9 bounds
    (55 active) — must fail with parameter-count mismatch until E01 produces
    23-active bounds."""

    @pytest.mark.parametrize("spec_name", [
        "E02_single23_25sp",
        "E02_single23_25fa",
        "E02_single23_26sp",
        "E03_joint23_25sp_25fa",
    ])
    def test_sobol23_specs_fail_count_mismatch(self, spec_name):
        with pytest.raises(ExperimentSpecError, match="Parameter count mismatch"):
            ExperimentSpec.load(SPECS_DIR / f"{spec_name}.json")


# ---------------------------------------------------------------------------
# Contract enforcement: forbidden Phi targets
# ---------------------------------------------------------------------------

class TestForbiddenPhiTargets:

    def test_forbidden_set_contents(self):
        assert FORBIDDEN_PHI_TARGETS == frozenset({"PWAD", "PWAI", "HWAM"})

    def test_spec_rejects_pwad_in_phi(self, tmp_path):
        spec = _make_minimal_spec(tmp_path, active_phi_targets=["CHPDT", "PWAD"])
        with pytest.raises(ExperimentSpecError, match="Forbidden variables"):
            ExperimentSpec.load(spec)

    def test_spec_rejects_hwam_in_phi(self, tmp_path):
        spec = _make_minimal_spec(tmp_path, active_phi_targets=["HWAM"])
        with pytest.raises(ExperimentSpecError, match="Forbidden variables"):
            ExperimentSpec.load(spec)

    def test_spec_requires_chpdt(self, tmp_path):
        """CHFPW alone (without CHPDT) must be rejected."""
        spec = _make_minimal_spec(tmp_path, active_phi_targets=["CHFPW"])
        with pytest.raises(ExperimentSpecError, match="must include 'CHPDT'"):
            ExperimentSpec.load(spec)


# ---------------------------------------------------------------------------
# Contract enforcement: 26SP role
# ---------------------------------------------------------------------------

class Test26SPRoleEnforcement:

    def test_26sp_validation_rejected(self, tmp_path):
        """26SP labelled 'validation' must be rejected (used in development)."""
        spec_path = _write_spec(tmp_path, {
            "experiment_id": "test_26sp_val",
            "scientific_role": "test",
            "season_inputs": [
                {"season_id": "25SP", "role": "calibration",
                 "input_manifest": "data/user/experiments/xxql2501_20260716/input_manifest.json",
                 "sha256": "5b7deac1502a5005cb46a1c2767a11d0567e13c094544f2faef3b9fdb950cb1b"},
                {"season_id": "26SP", "role": "validation",
                 "input_manifest": "data/user/experiments/xxql2601_actual_trial_validation_v1_20260721/input_manifest.json",
                 "sha256": "f62335c787d717bbb95eb832a7f34aca01574a9e8f55ca225aaa095102c7e2b5"},
            ],
            "parameter_set": "configs/experiments/parameter_sets/highdim55_dryonly_v1.json",
            "bounds_id": "eggplant_t9_highdim_v1_20260722",
            "observation_profile": "configs/experiments/observation_profiles/direct_chpdt_log_v1.json",
            "execution": {"ies_num_reals": 1, "noptmax": 0, "seed": 1},
            "representative_rule": "final_ensemble_median",
            "evaluation_profile": "article_rawscale_v1",
        })
        with pytest.raises(ExperimentSpecError, match="26SP.*labelled 'validation'"):
            ExperimentSpec.load(spec_path)

    def test_26sp_diagnostic_accepted(self, tmp_path):
        """26SP as 'diagnostic' is valid (E02 single-season)."""
        spec_path = _write_spec(tmp_path, {
            "experiment_id": "test_26sp_diag",
            "scientific_role": "single_season_diagnostic",
            "season_inputs": [
                {"season_id": "26SP", "role": "diagnostic",
                 "input_manifest": "data/user/experiments/xxql2601_actual_trial_validation_v1_20260721/input_manifest.json",
                 "sha256": "f62335c787d717bbb95eb832a7f34aca01574a9e8f55ca225aaa095102c7e2b5"},
            ],
            "parameter_set": "configs/experiments/parameter_sets/highdim55_dryonly_v1.json",
            "bounds_id": "eggplant_t9_highdim_v1_20260722",
            "observation_profile": "configs/experiments/observation_profiles/direct_chpdt_log_v1.json",
            "execution": {"ies_num_reals": 1, "noptmax": 0, "seed": 1},
            "representative_rule": "final_ensemble_median",
            "evaluation_profile": "article_rawscale_v1",
        })
        spec = ExperimentSpec.load(spec_path)
        assert spec.season_inputs[0].role == "diagnostic"


# ---------------------------------------------------------------------------
# Contract enforcement: seasonal parameterization (E05)
# ---------------------------------------------------------------------------

class TestSeasonalParameterization:

    def test_empty_offsets_rejected(self, tmp_path):
        """E05 with empty offsets must fail."""
        spec_path = _write_spec_with_seasonal(tmp_path, {"offsets": []})
        with pytest.raises(ExperimentSpecError, match="offsets is empty"):
            ExperimentSpec.load(spec_path)

    def test_too_many_offsets_rejected(self, tmp_path):
        """More than 3 offsets must fail."""
        offsets = [
            {"parameter": f"P{i}", "transform": "additive", "range": [0, 1],
             "physiological_basis": "test", "frozen_reason": "test",
             "target_season": "25FA"}
            for i in range(4)
        ]
        spec_path = _write_spec_with_seasonal(tmp_path, {"offsets": offsets})
        with pytest.raises(ExperimentSpecError, match="at most 3"):
            ExperimentSpec.load(spec_path)

    def test_dmc_offset_rejected(self, tmp_path):
        """DMC offset is forbidden under CHPDT-only contract."""
        offsets = [
            {"parameter": "DMC", "transform": "additive", "range": [0, 1],
             "physiological_basis": "test", "frozen_reason": "test",
             "target_season": "25FA"}
        ]
        spec_path = _write_spec_with_seasonal(tmp_path, {"offsets": offsets})
        with pytest.raises(ExperimentSpecError, match="DMC.*forbidden"):
            ExperimentSpec.load(spec_path)

    def test_invalid_transform_rejected(self, tmp_path):
        offsets = [
            {"parameter": "TB2", "transform": "quadratic", "range": [0, 1],
             "physiological_basis": "test", "frozen_reason": "test",
             "target_season": "25FA"}
        ]
        spec_path = _write_spec_with_seasonal(tmp_path, {"offsets": offsets})
        with pytest.raises(ExperimentSpecError, match="transform must be"):
            ExperimentSpec.load(spec_path)


# ---------------------------------------------------------------------------
# Receipt generation
# ---------------------------------------------------------------------------

class TestReceipt:

    def test_receipt_contains_all_hashes(self):
        spec = ExperimentSpec.load(SPECS_DIR / "E04_joint55_25sp_25fa.json")
        receipt = spec.receipt()
        assert "spec_sha256" in receipt
        assert receipt["parameter_set"]["sha256"]
        assert receipt["bounds"]["sha256"]
        assert receipt["observation_profile"]["sha256"]
        for s in receipt["season_inputs"]:
            assert s["input_manifest_sha256"]

    def test_receipt_parameter_list_matches(self):
        spec = ExperimentSpec.load(SPECS_DIR / "E04_joint55_25sp_25fa.json")
        receipt = spec.receipt()
        assert len(receipt["parameter_set"]["parameters"]) == 55
        assert receipt["bounds"]["active_count"] == 55


# ---------------------------------------------------------------------------
# Runner: prepare_experiment_run
# ---------------------------------------------------------------------------

class TestPrepareExperimentRun:

    def test_smoke_mode_overrides_execution(self, tmp_path):
        result = prepare_experiment_run(
            spec_path=SPECS_DIR / "E04_joint55_25sp_25fa.json",
            run_dir=tmp_path / "smoke_test",
            smoke=True,
        )
        assert result.spec.execution.ies_num_reals == 20
        assert result.spec.execution.noptmax == 1
        assert result.receipt_path.exists()

    def test_receipt_file_written(self, tmp_path):
        result = prepare_experiment_run(
            spec_path=SPECS_DIR / "E00_input_audit.json",
            run_dir=tmp_path / "receipt_test",
        )
        assert result.receipt_path.is_file()
        with result.receipt_path.open("r", encoding="utf-8") as fh:
            receipt = json.load(fh)
        assert receipt["experiment_id"] == "E00_input_audit"
        assert receipt["run_dir"] == str(tmp_path / "receipt_test")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_spec(tmp_path: Path, *, active_phi_targets: list[str]) -> Path:
    """Write a minimal observation profile and spec for contract testing."""
    profile = {
        "profile_id": "test_profile",
        "active_phi_targets": active_phi_targets,
        "diagnostic_targets": [],
        "transform": "ln(y+1)",
        "offset": 1.0,
        "reference": 1.0,
    }
    profile_path = tmp_path / "obs_profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    return _write_spec(tmp_path, {
        "experiment_id": "test_contract",
        "scientific_role": "test",
        "season_inputs": [
            {"season_id": "25SP", "role": "calibration",
             "input_manifest": "data/user/experiments/xxql2501_20260716/input_manifest.json",
             "sha256": "5b7deac1502a5005cb46a1c2767a11d0567e13c094544f2faef3b9fdb950cb1b"},
        ],
        "parameter_set": "configs/experiments/parameter_sets/highdim55_dryonly_v1.json",
        "bounds_id": "eggplant_t9_highdim_v1_20260722",
        "observation_profile": str(profile_path),
        "execution": {"ies_num_reals": 1, "noptmax": 0, "seed": 1},
        "representative_rule": "final_ensemble_median",
        "evaluation_profile": "article_rawscale_v1",
    })


def _write_spec(tmp_path: Path, spec_dict: dict) -> Path:
    spec_path = tmp_path / "test_spec.json"
    spec_path.write_text(json.dumps(spec_dict, indent=2), encoding="utf-8")
    return spec_path


def _write_spec_with_seasonal(tmp_path: Path, seasonal: dict) -> Path:
    return _write_spec(tmp_path, {
        "experiment_id": "test_seasonal",
        "scientific_role": "autumn_offset_comparison",
        "season_inputs": [
            {"season_id": "25SP", "role": "calibration",
             "input_manifest": "data/user/experiments/xxql2501_20260716/input_manifest.json",
             "sha256": "5b7deac1502a5005cb46a1c2767a11d0567e13c094544f2faef3b9fdb950cb1b"},
            {"season_id": "25FA", "role": "calibration",
             "input_manifest": "data/user/experiments/xxql2502_actual_trial_calibration_v1_20260721/input_manifest.json",
             "sha256": "b8ba5e8a83d3012e4684d9c2d84e15b2782817460ccf41cec2a533d362922856"},
        ],
        "parameter_set": "configs/experiments/parameter_sets/highdim55_dryonly_v1.json",
        "bounds_id": "eggplant_t9_highdim_v1_20260722",
        "observation_profile": "configs/experiments/observation_profiles/direct_chpdt_log_v1.json",
        "seasonal_parameterization": seasonal,
        "execution": {"ies_num_reals": 1, "noptmax": 0, "seed": 1},
        "representative_rule": "final_ensemble_median",
        "evaluation_profile": "article_rawscale_v1",
    })
