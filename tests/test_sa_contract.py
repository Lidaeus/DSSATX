"""Tests for the SA scientific contract (W1, plan §10).

Covers the five W1 negative-test requirements:

1. main parameter count is exactly 55;
2. fixed / disabled parameters never silently enter Morris;
3. ``FRCNOD`` is rejected (non-legume, never applicable);
4. main response labels match the sa_model.py computation source;
5. the main response list contains no HIAM / HWAM.

Also covers the two ranking-domain separation rule (plan §5.2 rule 3) and the
cumulative-harvest dry-mass naming contract (plan §4.1 note).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.sensitivity import sa_contract as C
from tools.sa.build_parameter_range_audit import build_range_audit
from tools.sa.build_parameter_scope_review import build_scope_review


# ---------------------------------------------------------------------------
# Frozen-bounds fixture helpers
# ---------------------------------------------------------------------------

BOUNDS_COLUMNS = [
    "name", "init", "lower", "upper", "status", "pargp", "location", "file",
    "cultivar", "ecotype", "mode", "review_note", "decision_role", "evidence_basis",
]


def _write_bounds(path: Path, rows: list[dict[str, str]]) -> Path:
    """Write a minimal frozen-bounds CSV for testing."""
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=BOUNDS_COLUMNS)
        writer.writeheader()
        for r in rows:
            full = {c: r.get(c, "") for c in BOUNDS_COLUMNS}
            writer.writerow(full)
    return path


def _active(name: str, *, lower: str = "0.0", upper: str = "1.0", init: str = "0.5") -> dict[str, str]:
    return {"name": name, "init": init, "lower": lower, "upper": upper,
            "status": "active", "decision_role": "core_genetic_screen",
            "evidence_basis": "Inherited as a proposal candidate; requires final per-parameter review"}


@pytest.fixture
def real_v4_bounds() -> Path:
    """The actual v4 frozen bounds shipped with the repo."""
    from src.common.project import PROJECT_ROOT
    p = (PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant"
         / C.V4_FROZEN_BOUNDS_FILENAME)
    if not p.is_file():
        pytest.skip(f"v4 frozen bounds not present: {p}")
    return p


# ===========================================================================
# W1 test 1 + 2: main parameter space is exactly 55; fixed/disabled excluded
# ===========================================================================

def test_main_parameter_space_is_exactly_55(real_v4_bounds: Path) -> None:
    """The main Morris space must be exactly 55 active parameters (plan §3.1)."""
    names = C.validate_main_parameter_space(real_v4_bounds)
    assert len(names) == C.EXPECTED_ACTIVE_COUNT == 55


def test_fixed_and_disabled_neither_enter_morris(real_v4_bounds: Path) -> None:
    """Only ``active`` parameters enter the main Morris space."""
    active = set(C.active_parameter_names(real_v4_bounds))
    all_rows = C.read_frozen_bounds(real_v4_bounds)
    non_active = {r.name for r in all_rows if r.status != "active"}
    # No overlap: the main space is purely the active set.
    assert active.isdisjoint(non_active)
    # The non-active set is non-empty (the 102 fixed/disabled).
    assert len(non_active) == 102


def test_scope_review_distinguishes_structural_scenarios(real_v4_bounds: Path) -> None:
    rows = {row["parameter"]: row for row in build_scope_review(real_v4_bounds)}
    assert rows["FRCNOD"]["primary_morris_decision"] == "excluded_forbidden"
    assert rows["FL-LF"]["primary_morris_decision"] == "excluded_structural_scenario"
    assert rows["SD-PM"]["hypothesis_test_decision"] == "scenario_only"


def test_range_audit_separates_physical_and_coupled_constraints(real_v4_bounds: Path) -> None:
    rows = {row["parameter"]: row for row in build_range_audit(real_v4_bounds)}
    assert "IPDMND" in rows["XFINT"]["physical_constraint"]
    assert "partition_ordering" in rows["XMAGE"]["coupled_constraint"]
    assert rows["XMAGE"]["physical_constraint"] != rows["XMAGE"]["coupled_constraint"]


# ===========================================================================
# W1 test 3: FRCNOD rejected (and other forbidden parameters)
# ===========================================================================

def test_frcnod_is_forbidden() -> None:
    """FRCNOD (nodulation in a non-legume) is structurally forbidden (plan §3.2)."""
    assert "FRCNOD" in C.FORBIDDEN_MORRIS_PARAMETERS


def test_forbidden_active_parameter_rejected(tmp_path: Path) -> None:
    """A frozen CSV with a forbidden parameter among the active set is rejected."""
    rows = [_active(f"P{i:02d}") for i in range(54)] + [
        {**_active("FRCNOD"), "status": "active"}
    ]
    bounds = _write_bounds(tmp_path / "bad_bounds.csv", rows)
    with pytest.raises(C.SAContractError, match="Forbidden parameters"):
        C.validate_main_parameter_space(bounds)


def test_active_count_mismatch_rejected(tmp_path: Path) -> None:
    """A frozen CSV with the wrong active count is rejected (no silent resize)."""
    rows = [_active(f"P{i:02d}") for i in range(40)]  # only 40, not 55
    bounds = _write_bounds(tmp_path / "short_bounds.csv", rows)
    with pytest.raises(C.SAContractError, match="exactly 55 active"):
        C.validate_main_parameter_space(bounds)


def test_seasonal_offset_never_genetic_sa(tmp_path: Path) -> None:
    """Seasonal-adaptation offsets must never appear as genetic SA parameters."""
    rows = [_active(f"P{i:02d}") for i in range(54)] + [
        _active("TB2_AUTUMN_OFFSET")
    ]
    bounds = _write_bounds(tmp_path / "offset_bounds.csv", rows)
    with pytest.raises(C.SAContractError, match="Seasonal-adaptation offsets"):
        C.validate_main_parameter_space(bounds)


# ===========================================================================
# W1 test 4: main response labels match the computation source
# ===========================================================================

def test_main_response_internal_fields_match_computation_source() -> None:
    """Every main response's internal_field must be a real sa_model.py emit key.

    The main-text responses are the ``MEAN_<KEY>`` aggregates and the ``WN_*``
    water-nitrogen derivatives.  Each must carry a non-empty computation_source
    pointing at sa_model.compute_indicators / _derive_water_nitrogen.
    """
    for rid in C.MAIN_RESPONSE_IDS:
        spec = C.ALL_RESPONSES[rid]
        assert spec.internal_field, f"{rid} has empty internal_field"
        assert ("MEAN_" in spec.internal_field) or spec.internal_field.startswith("WN_"), (
            f"{rid} internal_field {spec.internal_field!r} is not a MEAN_/WN_ key")
        assert "sa_model" in spec.computation_source, (
            f"{rid} computation_source does not reference sa_model")


def test_main_response_ids_cover_phenology_canopy_biomass_harvest_water_nitrogen() -> None:
    """The main responses must span the full physiology chain (plan §4.1)."""
    groups = {C.ALL_RESPONSES[rid].response_group for rid in C.MAIN_RESPONSE_IDS}
    required = {"phenology", "canopy", "biomass", "yield_harvest",
                "water_response", "nitrogen_response", "water_nitrogen_interaction"}
    assert required <= groups, f"main responses missing groups: {required - groups}"


# ===========================================================================
# W1 test 5: main response list contains no HIAM / HWAM
# ===========================================================================

def test_hiam_and_hwam_excluded_from_main() -> None:
    """HIAM and default HWAM must not appear in main-text responses (plan §4.3)."""
    main_ids_upper = {r.upper() for r in C.MAIN_RESPONSE_IDS}
    assert not any("HIAM" in r for r in main_ids_upper), "HIAM leaked into main responses"
    assert not any("HWAM" in r for r in main_ids_upper), "HWAM leaked into main responses"


def test_hiam_hwam_are_in_excluded_tier() -> None:
    """HIAM / HWAM are explicitly declared as excluded."""
    excluded_ids = {r.upper() for r in C.EXCLUDED_RESPONSE_IDS}
    assert "MEAN_HIAMS" in excluded_ids
    assert "MEAN_YIELD_HWAMS" in excluded_ids


def test_excluded_response_rejected_for_main_conclusions() -> None:
    """An excluded response raises when checked for main-text use."""
    with pytest.raises(C.SAContractError, match="excluded"):
        C.assert_response_not_excluded("MEAN_HIAMS")
    with pytest.raises(C.SAContractError, match="excluded"):
        C.assert_response_not_excluded("MEAN_YIELD_HWAMS")


def test_validate_response_tier_rejects_excluded_and_diagnostic() -> None:
    """Tier validation rejects excluded always, and diagnostic without opt-in."""
    with pytest.raises(C.SAContractError, match="Excluded"):
        C.validate_response_tier_consistency(["MEAN_ADAPS", "MEAN_HIAMS"])
    with pytest.raises(C.SAContractError, match="Diagnostic"):
        C.validate_response_tier_consistency(["MEAN_CUMHARVEST_DAP50"])
    # diagnostic allowed with explicit opt-in
    C.validate_response_tier_consistency(["MEAN_CUMHARVEST_DAP50"], allow_diagnostic=True)


def test_unknown_response_rejected() -> None:
    """Undeclared responses are rejected — no silent acceptance."""
    with pytest.raises(C.SAContractError, match="not declared"):
        C.validate_response_tier_consistency(["MEAN_BOGUS_RESPONSE"])


# ===========================================================================
# W1 §5.2 rule 3: two ranking domains never merge
# ===========================================================================

def test_two_ranking_domains_present_and_distinct() -> None:
    assert C.RANKING_DOMAIN_GENERAL != C.RANKING_DOMAIN_WATER_NITROGEN
    assert len(C.RANKING_DOMAINS) == 2


def test_ranking_domain_merge_rejected() -> None:
    """A response assigned to both domains is rejected (merge forbidden)."""
    with pytest.raises(C.SAContractError, match="both ranking domains"):
        C.validate_ranking_domains_separate({
            "MEAN_ADAPS": C.RANKING_DOMAIN_GENERAL,
            "MEAN_ADAPS ": C.RANKING_DOMAIN_WATER_NITROGEN,  # trimmed collision
        })


def test_unknown_ranking_domain_rejected() -> None:
    with pytest.raises(C.SAContractError, match="Unknown ranking domains"):
        C.validate_ranking_domains_separate({"MEAN_ADAPS": "bogus_domain"})


def test_main_responses_partition_cleanly_across_two_domains() -> None:
    """Each main response belongs to exactly one ranking domain."""
    assignments = {rid: C.ALL_RESPONSES[rid].ranking_domain for rid in C.MAIN_RESPONSE_IDS}
    C.validate_ranking_domains_separate(assignments)  # must not raise
    # The general-genetic side covers phenology/canopy/biomass/harvest.
    general = {rid for rid, d in assignments.items() if d == C.RANKING_DOMAIN_GENERAL}
    wn = {rid for rid, d in assignments.items() if d == C.RANKING_DOMAIN_WATER_NITROGEN}
    assert len(general) >= 4   # anthesis, LAI, biomass, harvest
    assert len(wn) >= 3        # water, nitrogen, interaction


# ===========================================================================
# W1 §4.1 note: cumulative-harvest dry-mass naming contract
# ===========================================================================

def test_cumulative_harvest_dry_mass_label_is_unambiguous() -> None:
    """The yield-chain response uses the unambiguous published label (plan §4.1)."""
    spec = C.ALL_RESPONSES[C.CUMULATIVE_HARVEST_DRY_MASS_ID]
    assert spec.paper_label == C.CUMULATIVE_HARVEST_DRY_MASS_LABEL
    assert "season-end" in spec.paper_label.lower()
    assert "cumulative" in spec.paper_label.lower()
    assert "harvested dry mass" in spec.paper_label.lower()


def test_ambiguous_fruit_dry_mass_phrases_listed() -> None:
    """Ambiguous phrases are pinned so exporters/figures can reject them."""
    assert any("fruit dry mass" in p for p in C.AMBIGUOUS_FRUIT_DRY_MASS_PHRASES)
    # The published label must not contain any ambiguous phrase.
    for phrase in C.AMBIGUOUS_FRUIT_DRY_MASS_PHRASES:
        assert phrase.lower() not in C.CUMULATIVE_HARVEST_DRY_MASS_LABEL.lower()
