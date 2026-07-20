"""T2 acceptance tests for the three per-season formal-SA output contracts.

Covers the handoff T2 requirements:
  * "三个 season profile" — three contract JSONs exist and load.
  * "统一 DAP 45/67/95/119" — lai_time_points identical across all three.
  * "处理映射从显式配置读取" — each contract's treatments match its bundle batch.
  * "相同指标名在三季含义一致" — features / response_groups / ranking_domains identical.
  * "非伪重复" — XXQL2601's duplicate TN12 is excluded from the derived bundle;
    no MDAPS / MEAN_* in observation names.
  * N-rates are derived from FileX, not hardcoded — the frozen doses match a
    fresh fertilizer_n_total_kg_ha call on the bundle FileX.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common.experiment_inputs import batch_entries, parse_filex
from src.sensitivity.output_contract import load_output_contract, observation_names
from src.sensitivity.treatment_factor_attribution import fertilizer_n_total_kg_ha


ROOT = Path(__file__).resolve().parents[1]
SA_CONFIGS = ROOT / "configs" / "sa"

CONTRACTS = {
    "XXQL2501": {
        "json": SA_CONFIGS / "eggplant_formal_xxql2501_outputs_20260720.json",
        "bundle": ROOT / "data" / "user" / "experiments" / "xxql2501_sa_controlled_candidate_20260720",
        "treatments": [2, 3, 4, 5, 10, 11, 12, 13],
        "expected_n_mf1": 399.0,
    },
    "XXQL2502": {
        "json": SA_CONFIGS / "eggplant_formal_xxql2502_outputs_20260720.json",
        "bundle": ROOT / "data" / "user" / "experiments" / "xxql2502_sa_controlled_candidate_20260720",
        "treatments": [1, 3, 4, 6, 7, 9, 10, 12],
        "expected_n_mf1": 360.0,
    },
    "XXQL2601": {
        "json": SA_CONFIGS / "eggplant_formal_xxql2601_outputs_20260720.json",
        "bundle": ROOT / "data" / "user" / "experiments" / "xxql2601_sa_controlled_7t_candidate_20260720",
        "treatments": [1, 3, 4, 6, 7, 9, 10],
        "expected_n_mf1": 361.0,
    },
}


@pytest.fixture(scope="module")
def loaded_contracts():
    return {exp: load_output_contract(spec["json"]) for exp, spec in CONTRACTS.items()}


def test_three_season_contracts_exist_and_load():
    for exp, spec in CONTRACTS.items():
        assert spec["json"].is_file(), f"contract JSON missing for {exp}: {spec['json']}"
    # load_output_contract must not raise for any of the three
    for exp, spec in CONTRACTS.items():
        load_output_contract(spec["json"])


def test_shared_features_time_points_and_domains_are_identical(loaded_contracts):
    """Same metric name must mean the same thing across the three seasons."""
    shared_keys = ["features", "lai_time_points", "fruit_time_points",
                   "response_groups", "ranking_domains", "include_treatment_mean"]
    base = {k: loaded_contracts["XXQL2501"][k] for k in shared_keys}
    for exp in ("XXQL2502", "XXQL2601"):
        for k in shared_keys:
            assert loaded_contracts[exp][k] == base[k], (
                f"{exp} differs from XXQL2501 on shared field {k!r}: "
                f"{loaded_contracts[exp][k]!r} vs {base[k]!r}"
            )
    # MDAPS must never appear in features (baseline returns the -99 sentinel).
    for exp in CONTRACTS:
        assert "MDAPS" not in loaded_contracts[exp]["features"]
    # The LAI time points must be exactly the handoff's frozen set.
    assert loaded_contracts["XXQL2501"]["lai_time_points"] == [45, 67, 95, 119]


def test_per_season_treatments_match_bundle_batch(loaded_contracts):
    for exp, spec in CONTRACTS.items():
        bundle = spec["bundle"]
        batch = bundle / "DSSBatch.v48"
        entries = batch_entries(batch)
        batch_tns = {tn for _, tn in entries}
        assert loaded_contracts[exp]["treatments"] == spec["treatments"]
        assert set(loaded_contracts[exp]["treatments"]).issubset(batch_tns), (
            f"{exp} contract treatments not in bundle batch: {loaded_contracts[exp]['treatments']}"
        )


def test_n_rates_derived_from_filex_match_frozen_contract(loaded_contracts):
    """The frozen n_kg_ha must match a fresh FileX-derived total — catches silent FileX edits."""
    for exp, spec in CONTRACTS.items():
        filex = spec["bundle"] / f"{exp}.TMX"
        text = filex.read_text(encoding="utf-8", errors="ignore")
        contract = loaded_contracts[exp]
        # Collect every (treatment, n_kg_ha) the contract references.
        referenced = {}
        for w in ("W3", "W1"):
            for row in contract["water_nitrogen_design"]["nitrogen_series"][w]:
                referenced[int(row["treatment"])] = float(row["n_kg_ha"])
        # For each referenced treatment, derive the dose from its MF level and compare.
        parsed = parse_filex(filex)
        for tn, expected_dose in referenced.items():
            mf = int(parsed["treatments"][tn]["MF"])
            derived = fertilizer_n_total_kg_ha(text, mf)
            assert abs(derived - expected_dose) < 1e-9, (
                f"{exp} TN{tn}: contract froze n_kg_ha={expected_dose} but FileX MF{mf} sums to {derived}"
            )


def test_season_specific_n_ladder_reflected_in_contract(loaded_contracts):
    """The three seasons have DIFFERENT N ladders — confirm the contracts capture that."""
    mf1_by_season = {}
    for exp, spec in CONTRACTS.items():
        filex = spec["bundle"] / f"{exp}.TMX"
        mf1_by_season[exp] = fertilizer_n_total_kg_ha(filex.read_text(encoding="utf-8", errors="ignore"), 1)
    # 2501's top rate is heavier than 2502/2601
    assert mf1_by_season["XXQL2501"] == pytest.approx(399.0)
    assert mf1_by_season["XXQL2502"] == pytest.approx(360.0)
    assert mf1_by_season["XXQL2601"] == pytest.approx(361.0)
    # And the contracts' N3 (MF1) entries must reflect each season's actual dose
    for exp, expected in mf1_by_season.items():
        contract = loaded_contracts[exp]
        n3_doses = {
            float(row["n_kg_ha"])
            for w in ("W3", "W1")
            for row in contract["water_nitrogen_design"]["nitrogen_series"][w]
        }
        assert expected in n3_doses, f"{exp}: MF1 dose {expected} not in contract nitrogen_series"


def test_xxql2601_unbalanced_factorial_documents_excluded_duplicate(loaded_contracts):
    contract = loaded_contracts["XXQL2601"]
    notes = contract["water_nitrogen_design"].get("_notes", {})

    # N0 (MF4) lacks a W1 treatment in XXQL2601 — water_pairs must omit N0.
    assert "N0" not in contract["water_nitrogen_design"]["water_pairs"], (
        "XXQL2601 N0 water_pair must be omitted (W1 MF4 absent in retained set)"
    )
    # The omission is explicitly documented.
    omissions = notes.get("water_pairs_omissions", [])
    assert any("N0" in note and "W1" in note for note in omissions), (
        f"XXQL2601 must document the N0/W1 omission; got {omissions}"
    )

    # TN9 and TN12 are both W3/MF4. The derived bundle retains TN9 and excludes
    # TN12 before both base and WN observations are generated.
    wn_tns = set()
    for pair in contract["water_nitrogen_design"]["water_pairs"].values():
        wn_tns.update(pair)
    for w in ("W3", "W1"):
        for row in contract["water_nitrogen_design"]["nitrogen_series"][w]:
            wn_tns.add(int(row["treatment"]))
    # Exactly one of {9, 12} appears in the WN structures.
    assert len({9, 12} & wn_tns) == 1, (
        f"Exactly one of TN9/TN12 must appear in XXQL2601 WN structures; got {wn_tns}"
    )
    dup_notes = notes.get("dropped_duplicate_wn_assignments", [])
    assert dup_notes, "XXQL2601 must document the TN9/TN12 duplicate handling"

    names = observation_names(contract)
    assert any(n.startswith("TN9_") for n in names), (
        "TN9 must contribute per-treatment base observations"
    )
    assert not any(n.startswith("TN12_") for n in names)


def test_all_formal_bundles_use_approved_nonlegume_options():
    for exp, spec in CONTRACTS.items():
        manifest = json.loads((spec["bundle"] / "input_manifest.json").read_text(encoding="utf-8"))
        options = manifest["summary"]["simulation_options"]
        assert options, f"{exp}: simulation options were not audited"
        assert {row["SYMBI"] for row in options.values()} == {"N"}
        assert {row["POTAS"] for row in options.values()} == {"N"}


def test_no_mdaps_or_mean_in_observation_names(loaded_contracts):
    for exp in CONTRACTS:
        names = observation_names(loaded_contracts[exp])
        assert not any("MDAPS" in n for n in names), f"{exp}: MDAPS must not appear in observation names"
        assert not any(n.startswith("MEAN_") for n in names), f"{exp}: MEAN_* observations must not be emitted"


def test_observation_counts_are_consistent_with_factorial_balance(loaded_contracts):
    """XXQL2501/XXQL2502 are balanced 2x4 (full WN design); XXQL2601 loses one
    N level from water_pairs, so its observation count is lower."""
    c2501 = len(observation_names(loaded_contracts["XXQL2501"]))
    c2502 = len(observation_names(loaded_contracts["XXQL2502"]))
    c2601 = len(observation_names(loaded_contracts["XXQL2601"]))
    # The two balanced seasons have the same count.
    assert c2501 == c2502
    # 2601 has one fewer water_pairs level (N0 omitted) -> fewer WN_WATER_* /
    # WN_NSLOPE_* / WN_INTERACTION_* names. Each lost level removes:
    #   1 WATER + 2 NSLOPE (W3,W1) + 1 INTERACTION = 4 names per contrast feature.
    # The WN_NSLOPE_W1 for N0 is also gone because W1 has no N0 treatment.
    assert c2601 < c2501, "XXQL2601 must have fewer observations than the balanced seasons"
    print(f"\nobservation counts: 2501={c2501}, 2502={c2502}, 2601={c2601}")
