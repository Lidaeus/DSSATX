import json
from pathlib import Path

import pytest

from src.calibration.audit_observations import audit_observation_bundle
from src.common.experiment_inputs import parse_filex
from src.common.input_manifest import (
    InputUseProhibitedError,
    USE_VALIDATION_AGAINST_OBSERVED_IC,
    assert_use_allowed,
    verify_calibrated_input_bundle,
    verify_manifest_integrity,
)
from tools.import_experiment_bundle import _section_text


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "data" / "user" / "experiments"
CALIBRATION = EXPERIMENTS / "xxql2502_actual_trial_calibration_v1_20260721"
VALIDATION = EXPERIMENTS / "xxql2601_actual_trial_validation_v1_20260721"


def test_formal_bundles_pass_integrity_and_role_gates():
    calibration = verify_calibrated_input_bundle(CALIBRATION)
    assert calibration.raw["scenario_role"] == "calibration"
    assert calibration.raw["counterfactual_transformations"] == []

    validation = verify_manifest_integrity(VALIDATION)
    assert validation.raw["scenario_role"] == "validation"
    assert_use_allowed(validation, use=USE_VALIDATION_AGAINST_OBSERVED_IC)
    with pytest.raises(InputUseProhibitedError):
        verify_calibrated_input_bundle(VALIDATION)


def test_formal_bundles_preserve_measured_treatment_specific_ic_and_soil_analysis():
    for experiment, bundle in (("XXQL2502", CALIBRATION), ("XXQL2601", VALIDATION)):
        raw_filex = EXPERIMENTS / experiment / f"{experiment}.TMX"
        formal_filex = bundle / f"{experiment}.TMX"
        raw = parse_filex(raw_filex)
        formal = parse_filex(formal_filex)
        assert formal["initial_conditions"] == raw["initial_conditions"]
        assert len({v["IC"] for v in formal["treatments"].values()}) == 12
        assert len({v["SA"] for v in formal["treatments"].values()}) == 12
        for heading in ("*SOIL ANALYSIS", "*INITIAL CONDITIONS"):
            assert _section_text(formal_filex, heading) == _section_text(raw_filex, heading)
        manifest = json.loads((bundle / "input_manifest.json").read_text(encoding="utf-8"))
        assert manifest["initial_condition_policy"] == "observed_treatment_specific_no_counterfactual_pooling"
        assert manifest["soil_analysis_policy"] == "observed_treatment_specific_no_counterfactual_pooling"


def test_standard_filea_filet_use_treatment_numbers_and_are_audit_safe():
    for experiment, bundle in (("XXQL2502", CALIBRATION), ("XXQL2601", VALIDATION)):
        for suffix in (".TMA", ".TMT"):
            text = (bundle / f"{experiment}{suffix}").read_text(encoding="utf-8")
            assert "TRNO = DSSAT treatment number" in text
            assert "TRNO=PLOT NUMBER" not in text.upper()
            assert "@TRNO" in text
        report, harvest = audit_observation_bundle(bundle)
        assert report["error_count"] == 0
        assert report["safe_for_direct_formal_use"] is True
        assert "TRNO_DECLARED_AS_PLOT_NUMBER" not in {
            finding["code"] for finding in report["findings"]
        }
        assert not harvest.empty


def test_raw_filex_uses_nonlegume_symbi_n_and_complete_soil_asset():
    for experiment in ("XXQL2502", "XXQL2601"):
        root = EXPERIMENTS / experiment
        parsed = parse_filex(root / f"{experiment}.TMX")
        assert {values["SYMBI"] for values in parsed["simulation_options"].values()} == {"N"}
        assert (root / "SOIL.SOL").is_file()
