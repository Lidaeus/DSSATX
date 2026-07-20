import pytest

from src.common.input_manifest import InputManifestError, verify_manifest_integrity
from src.sensitivity.output_contract import load_output_contract
from src.sensitivity.sa_model import (
    _cumulative_dap_fraction,
    derive_water_nitrogen_responses,
)


def test_cumulative_dap50_is_interpolated_from_the_monotone_harvest_curve():
    series = [
        {"DAP": 60, "CHPDT": 0.0},
        {"DAP": 80, "CHPDT": 20.0},
        {"DAP": 100, "CHPDT": 100.0},
    ]
    assert _cumulative_dap_fraction(series, "CHPDT", 0.5) == 87.5


def test_dap50_rejects_nonmonotone_cumulative_series():
    """A decreasing cumulative node marks DAP50 not estimable (None -> -99).

    The plan requires that a non-monotone cumulative harvest series never
    produces a fabricated DAP50; the response audit must catch it via the
    missing-value sentinel instead.
    """
    # Decreasing middle node: 0 -> 80 -> 50 is non-monotone.
    series = [
        {"DAP": 60, "CHPDT": 0.0},
        {"DAP": 80, "CHPDT": 80.0},
        {"DAP": 100, "CHPDT": 50.0},
    ]
    assert _cumulative_dap_fraction(series, "CHPDT", 0.5) is None

    # Non-positive final value is also not estimable.
    assert _cumulative_dap_fraction([{"DAP": 60, "CHPDT": 0.0}, {"DAP": 100, "CHPDT": 0.0}], "CHPDT", 0.5) is None

    # Empty series is not estimable.
    assert _cumulative_dap_fraction([], "CHPDT", 0.5) is None


def test_sa_rejects_wrong_bundle_id_or_treatment_set(tmp_path):
    """The SA case builder rejects (a) a manifest whose bundle_id != directory
    and (b) an input bundle whose treatment set disagrees with the output
    contract. Both are exercised through the shared integrity / coherence
    checks the builder calls."""
    # (a) A bundle whose directory name does not match its bundle_id fails the
    #     unified manifest integrity gate before any FileX parsing occurs.
    import json
    import hashlib

    bundle = tmp_path / "mismatched_dir"
    bundle.mkdir()
    (bundle / "DSSBatch.v48").write_text("x", encoding="utf-8")
    manifest = {
        "bundle_id": "different_id",  # != directory name
        "files": [
            {
                "name": "DSSBatch.v48",
                "sha256": hashlib.sha256(b"x").hexdigest(),
                "bytes": 1,
            }
        ],
    }
    (bundle / "input_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(InputManifestError, match="does not match manifest bundle_id"):
        verify_manifest_integrity(bundle)

    # (b) Treatment-set mismatch is enforced by sa_build_sen_case against the
    #     output contract. The symbi_n_candidate bundle (SYMBI=N, the correct
    #     non-legume setting) carries a 10-treatment set that disagrees with
    #     the SA output contract (which expects the counterfactual TN2-5,10-13
    #     set), so the SA build must reject it on treatment-set grounds.
    from src.sensitivity.sa_build_sen_case import build_case

    with pytest.raises(ValueError, match="treatments do not match"):
        build_case(
            param_review_csv="data/parameter_registry/bounds_frozen/eggplant/eggplant_p1_xxql2501_v3_20260716.csv",
            input_dir="data/user/experiments/xxql2501_symbi_n_candidate_20260719",
            output_profile="configs/sa/eggplant_p1_outputs.json",
            case_dir=str(tmp_path / "wrong_treatment_case"),
            workspace_dir=str(tmp_path / "wrong_treatment_case"),
            morris_r=4,
            morris_p=6,
            random_seed=1,
            run_type="sensitivity_preflight_case",
        )


def test_water_nitrogen_responses_use_paired_differences_actual_n_doses_and_slope_interaction():
    contract = load_output_contract()
    values = {}
    doses_by_treatment = {5: 0, 4: 130, 3: 271, 2: 399, 13: 0, 12: 130, 11: 271, 10: 399}
    for treatment, dose in doses_by_treatment.items():
        water_offset = 10.0 if treatment in {2, 3, 4, 5} else 0.0
        water_slope = 2.0 if treatment in {2, 3, 4, 5} else 1.0
        for feature in contract["water_nitrogen_design"]["contrast_features"]:
            values[f"TN{treatment}_{feature}"] = water_offset + water_slope * dose

    derived = derive_water_nitrogen_responses(values, contract)
    for feature in contract["water_nitrogen_design"]["contrast_features"]:
        assert derived[f"WN_WATER_N0_{feature}"] == 10.0
        assert derived[f"WN_WATER_N3_{feature}"] == 409.0
        assert abs(derived[f"WN_NSLOPE_W3_{feature}"] - 2.0) < 1e-12
        assert abs(derived[f"WN_NSLOPE_W1_{feature}"] - 1.0) < 1e-12
        assert abs(derived[f"WN_INTERACTION_{feature}"] - 1.0) < 1e-12
