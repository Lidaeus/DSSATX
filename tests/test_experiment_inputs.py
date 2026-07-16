import json
from pathlib import Path

import pandas as pd

from src.common.experiment_inputs import management_event_order_findings, parse_filex, validate_input_bundle
from src.sensitivity.counterfactual_inputs import CORE_TREATMENTS, pooled_median_initial_profile
from src.sensitivity.output_contract import load_output_contract, observation_names


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data" / "user" / "experiments" / "xxql2501_20260716"
SA_BUNDLE = ROOT / "data" / "user" / "experiments" / "xxql2501_sa_counterfactual_v1_20260716"
OLD_BUNDLE = ROOT / "data" / "user" / "experiments" / "xxql2501_20260715"
FROZEN = ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_p1_xxql2501_v2_20260715.csv"
V3_PROPOSAL = ROOT / "data" / "parameter_registry" / "bounds_proposals" / "eggplant" / "eggplant_p1_xxql2501_v3_candidate_20260716.csv"


def test_versioned_xxql2501_bundle_passes_cross_file_gates():
    summary, findings = validate_input_bundle(BUNDLE)
    assert not [item for item in findings if item.severity == "error"]
    warning_codes = {item.code for item in findings if item.severity == "warning"}
    assert {
        "SOIL_HYDRAULIC_CONDUCTIVITY_MISSING",
        "SOIL_TEXTURE_MISSING",
    }.issubset(warning_codes)
    assert summary["soil_id"] == "IBTM910017"
    assert summary["treatments"] == [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]
    manifest = json.loads((BUNDLE / "input_manifest.json").read_text(encoding="utf-8"))
    assert manifest["science_status"] == "pass_with_warnings"
    assert manifest["derived_from_bundle"] == "xxql2501_20260715"
    assert manifest["authoritative_coordinates"] == [35.16, 113.8]


def test_tn2_tn3_do_not_cover_water_nitrogen_design():
    parsed = parse_filex(BUNDLE / "XXQL2501.TMX")
    factors = parsed["treatments"]
    assert {factors[tn]["MI"] for tn in (2, 3)} == {1}
    assert {factors[tn]["MI"] for tn in factors} == {1, 2, 3, 4}
    assert {factors[tn]["MF"] for tn in factors} == {1, 2, 3, 4}


def test_noncontiguous_fertilizer_factor_rows_are_rejected():
    findings = management_event_order_findings(OLD_BUNDLE / "XXQL2501.TMX")
    codes = {item.code for item in findings}
    assert "FILEX_FACTOR_ROWS_NONCONTIGUOUS" in codes
    assert "FILEX_FACTOR_DATES_UNSORTED" in codes
    assert not management_event_order_findings(BUNDLE / "XXQL2501.TMX")


def test_p1_output_contract_is_controlled_factorial_nonredundant_and_observed_time_aligned():
    contract = load_output_contract()
    names = observation_names(contract)
    assert contract["profile_id"] == "eggplant_p1_controlled_wn_v4"
    assert contract["experiment_bundle"] == "xxql2501_sa_counterfactual_v1_20260716"
    assert contract["treatments"] == list(CORE_TREATMENTS)
    assert len(names) == contract["observation_count"] == 164
    assert contract["time_points"] == [45, 67, 95, 119]
    assert contract["lai_time_points"] == [45, 67, 95, 119]
    assert contract["fruit_time_points"] == []
    assert not any(name.startswith("MEAN_") for name in names)
    assert not any("MDAPS" in name for name in names)
    assert not any("LAIXM" in name for name in names)
    assert not any("FRUITD_DAP067" in name or "FRUITD_DAP095" in name or "FRUITD_DAP119" in name for name in names)
    assert any("LAI_DAP045" in name for name in names)
    assert "WN_WATER_N3_FRUITD_END" in names
    assert "WN_NSLOPE_W3_FRUITD_END" in names
    assert "WN_INTERACTION_FRUITD_END" in names
    assert set(contract["ranking_domains"]) == {"general_genetic", "water_nitrogen_response"}


def test_sa_counterfactual_bundle_unifies_initial_conditions_but_calibration_bundle_does_not():
    summary, findings = validate_input_bundle(SA_BUNDLE)
    assert not [item for item in findings if item.severity == "error"]
    assert summary["treatments"] == list(CORE_TREATMENTS)
    factors = summary["treatment_factors"]
    assert {factors[treatment]["IC"] for treatment in CORE_TREATMENTS} == {2}
    assert {(factors[treatment]["MI"], factors[treatment]["MF"]) for treatment in CORE_TREATMENTS} == {
        (1, 1), (1, 2), (1, 3), (1, 4),
        (3, 1), (3, 2), (3, 3), (3, 4),
    }
    expected = pooled_median_initial_profile(BUNDLE / "XXQL2501.TMX")
    assert summary["initial_conditions"][2] == expected
    assert all(
        rows == expected
        for rows in summary["initial_conditions"].values()
    )
    assert max(
        row["sno3"]
        for rows in summary["initial_conditions"].values()
        for row in rows
    ) <= 100.0

    observed = parse_filex(BUNDLE / "XXQL2501.TMX")
    assert len({observed["treatments"][treatment]["IC"] for treatment in CORE_TREATMENTS}) == 8
    manifest = json.loads((SA_BUNDLE / "input_manifest.json").read_text(encoding="utf-8"))
    assert manifest["intended_use"] == "genetic_parameter_sensitivity_analysis_only"
    assert "parameter_calibration" in manifest["prohibited_use"]


def test_frozen_bounds_use_new_soil_and_treatment_specific_disabled_ic():
    frame = pd.read_csv(FROZEN, encoding="utf-8-sig")
    by_name = frame.set_index("name")
    assert float(by_name.loc["SOIL_SLLL_01", "init"]) == 0.148
    assert float(by_name.loc["SOIL_SDUL_08", "init"]) == 0.263
    assert float(by_name.loc["SOIL_SLRO", "init"]) == 81.0
    ic = frame[frame["name"].str.startswith("IC_SH2O_TN")]
    assert len(ic) == 50
    assert set(ic["status"].str.lower()) == {"disabled"}
    assert not frame["name"].isin({"IC_SH2O_01", "IC_SH2O_02"}).any()
    assert float(by_name.loc["XMAGE", "upper"]) < float(by_name.loc["XFPHT", "lower"])
    soil = frame[frame["file"].eq("SOIL.SOL")]
    assert set(soil["status"].str.lower()) == {"fixed"}
    assert not soil["name"].str.contains("SSKS|SLCL|SLSI", regex=True).any()


def test_v3_candidate_was_promoted_without_changing_approved_content():
    frame = pd.read_csv(V3_PROPOSAL, encoding="utf-8-sig").set_index("name")
    assert float(frame.loc["XMAGE", "lower"]) == 10.0
    assert float(frame.loc["SLAREF", "lower"]) == 260.0
    assert float(frame.loc["XMAGE", "lower"]) <= float(frame.loc["XMAGE", "init"])
    assert float(frame.loc["SLAREF", "lower"]) <= float(frame.loc["SLAREF", "init"])
    metadata = V3_PROPOSAL.with_suffix(".yaml").read_text(encoding="utf-8")
    assert 'review_status: "promoted"' in metadata
    assert 'promoted_to: "eggplant_p1_xxql2501_v3_20260716"' in metadata


def test_v3_frozen_bounds_are_approved_and_byte_identical_to_candidate():
    frozen = (
        ROOT
        / "data"
        / "parameter_registry"
        / "bounds_frozen"
        / "eggplant"
        / "eggplant_p1_xxql2501_v3_20260716.csv"
    )
    assert frozen.read_bytes() == V3_PROPOSAL.read_bytes()
    metadata = frozen.with_suffix(".yaml").read_text(encoding="utf-8")
    assert 'review_status: "approved"' in metadata
    assert 'automatic_repairs: 0' in metadata
