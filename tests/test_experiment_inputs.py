import json
from pathlib import Path

import pandas as pd

from src.common.experiment_inputs import parse_filex, validate_input_bundle
from src.sensitivity.output_contract import load_output_contract, observation_names


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data" / "user" / "experiments" / "xxql2501_20260715"
FROZEN = ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_p1_xxql2501_v2_20260715.csv"


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
    assert manifest["science_status"] == "pass"
    assert manifest["authoritative_coordinates"] == [35.16, 113.8]


def test_tn2_tn3_do_not_cover_water_nitrogen_design():
    parsed = parse_filex(BUNDLE / "XXQL2501.TMX")
    factors = parsed["treatments"]
    assert {factors[tn]["MI"] for tn in (2, 3)} == {1}
    assert {factors[tn]["MI"] for tn in factors} == {1, 2, 3, 4}
    assert {factors[tn]["MF"] for tn in factors} == {1, 2, 3, 4}


def test_p1_output_contract_is_full_design_nonredundant_and_observed_time_aligned():
    contract = load_output_contract()
    names = observation_names(contract)
    assert len(names) == contract["observation_count"] == 240
    assert contract["time_points"] == [45, 67, 95, 119]
    assert not any(name.startswith("MEAN_") for name in names)
    assert not any("MDAPS" in name for name in names)


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
