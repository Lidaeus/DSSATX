import json
from pathlib import Path

import pandas as pd

from src.common.experiment_inputs import management_event_order_findings, parse_filex, validate_input_bundle
from src.sensitivity.output_contract import load_output_contract, observation_names


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data" / "user" / "experiments" / "xxql2501_20260716"
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


def test_p1_output_contract_is_full_design_nonredundant_and_observed_time_aligned():
    contract = load_output_contract()
    names = observation_names(contract)
    assert contract["profile_id"] == "eggplant_p1_all_treatments_v3"
    assert contract["experiment_bundle"] == "xxql2501_20260716"
    assert len(names) == contract["observation_count"] == 230
    assert contract["time_points"] == [45, 67, 95, 119]
    assert contract["lai_time_points"] == [45, 67, 95, 119]
    assert contract["fruit_time_points"] == [67, 95, 119]
    assert not any(name.startswith("MEAN_") for name in names)
    assert not any("MDAPS" in name for name in names)
    assert not any("LAIXM" in name for name in names)
    assert not any("FRUITD_DAP045" in name for name in names)
    assert any("LAI_DAP045" in name for name in names)


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
