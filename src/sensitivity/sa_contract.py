"""Single source of truth for the sensitivity-analysis scientific contract.

This module captures the *scientific* contract that governs which parameters
and responses may enter the article sensitivity-analysis conclusions, as
defined in ``docs/敏感性分析方案与图表优化_协作实施计划_20260729.md``
(§3 parameter space, §4 response stratification).

It deliberately imports **no plotting library and no DSSAT/PEST runner** — it
only declares constants and validates contracts against frozen artefacts.
The constants here are the authoritative labels; downstream exporters
(``morris_multiseed``, ``export_sobol_stability_paper_data``, the R figures)
must align to them, never the reverse.

Design rules enforced here (from the implementation plan):

* The main Morris parameter space is exactly the 55 ``active`` parameters of
  the frozen v4 bounds — it must not be silently enlarged or narrowed.
* Fixed / disabled parameters never enter Morris automatically; a small set
  is explicitly forbidden (``FORBIDDEN_MORRIS_PARAMETERS``) because they are
  structurally inapplicable to eggplant (e.g. ``FRCNOD`` — nodulation in a
  non-legume) or require discrete structural scenarios rather than continuous
  sampling (e.g. ``FL-LF``, ``SD-PM``).
* Responses are stratified into ``main`` / ``supplement`` / ``diagnostic`` /
  ``excluded`` tiers.  ``HIAM`` and the default season-end ``HWAM`` are
  ``excluded`` because harvested-fruit continuous-picking has no applicable
  theoretical benchmark under this contract.
* The cumulative-harvest dry-mass response is published as
  "season-end cumulative harvested dry mass", never the ambiguous "fruit dry
  mass".
* Two ranking domains (``general_genetic``, ``water_nitrogen_response``) are
  kept strictly separate — raw ``mu*``/``sigma`` are never averaged across
  responses, and the two domains are never merged into one ranking.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Frozen-bounds source-of-truth
# ---------------------------------------------------------------------------

#: The only frozen bounds file the article SA may consume (plan §3.1).
#: 157 rows = 55 active + 52 fixed + 50 disabled.
V4_FROZEN_BOUNDS_FILENAME = "eggplant_formal_multiseason_candidate_v4_20260721.csv"
EXPECTED_ACTIVE_COUNT = 55

# ---------------------------------------------------------------------------
# Parameter scope rules (plan §3.2)
# ---------------------------------------------------------------------------

#: Parameters that must NEVER enter the main Morris sample, regardless of their
#: frozen status, because they are structurally inapplicable to eggplant or
#: require a discrete structural scenario instead of continuous sampling.
FORBIDDEN_MORRIS_PARAMETERS: frozenset[str] = frozenset({
    "FRCNOD",    # nodulation fraction — eggplant is a non-legume; never applicable
    "FL-LF",     # indeterminate structure flag (400 = infinite) — discrete scenario only
    "SD-PM",     # stem-termination flag — discrete scenario only
})

#: Parameters kept fixed by deliberate scientific decision (plan §3.2 table).
#: They may appear in a "hypothesis review pool" but never auto-promote to
#: Morris.  ``reason`` is the scientific justification.
FIXED_BY_DECISION: dict[str, str] = {
    "WTPSD": "reliable targets are fleshy-fruit cumulative dry/fresh harvest, not seed yield",
    "THRSH": "threshing composition needs seed-count/quality observations not collected",
    "CSDL": "no multi-photoperiod or multi-latitude evidence; greenhouse 3 seasons cannot identify daylength",
    "PPSEN": "no multi-photoperiod or multi-latitude evidence; greenhouse 3 seasons cannot identify daylength",
    "EVMODC": "no independent evaporation-process evidence to enable it",
    "V1-JU": "no independent juvenile-phase observations to support it",
}

#: Marker that a parameter is a seasonal-adaptation offset, not a genetic
#: parameter.  Such parameters belong to calibration seasonal-adaptation
#: hypotheses only and must never masquerade as genetic SA parameters.
SEASONAL_OFFSET_MARKERS: tuple[str, ...] = ("_AUTUMN", "_OFFSET", "_SEASON")

# ---------------------------------------------------------------------------
# Ranking domains (plan §5.2 rule 3 — never merge)
# ---------------------------------------------------------------------------

RANKING_DOMAIN_GENERAL = "general_genetic"
RANKING_DOMAIN_WATER_NITROGEN = "water_nitrogen_response"
RANKING_DOMAINS: tuple[str, ...] = (
    RANKING_DOMAIN_GENERAL,
    RANKING_DOMAIN_WATER_NITROGEN,
)

# ---------------------------------------------------------------------------
# Response tiers (plan §4.1 / §4.2 / §4.3)
# ---------------------------------------------------------------------------

#: Internal response-key suffix in sa_model.py (the computation source).
#: Main-text responses are the cross-treatment ``MEAN_<KEY>`` aggregates, plus
#: the water-nitrogen derived ``WN_*`` series.  Keys here are the bare suffix
#: (without the ``MEAN_`` / ``WN_`` prefix) so the contract reads like the plan.
@dataclass(frozen=True)
class ResponseSpec:
    """One response in the SA scientific contract."""

    response_id: str              # canonical SA response id, e.g. "MEAN_ADAPS"
    internal_field: str           # sa_model.py emit key (the computation source)
    paper_label: str              # publication name (plan §4.1)
    unit: str
    response_group: str           # maps to response_groups in the output contract
    ranking_domain: str           # general_genetic | water_nitrogen_response
    tier: str                     # main | supplement | diagnostic | excluded
    computation_source: str       # human-readable provenance line
    note: str = ""


# --- Main-text core responses (plan §4.1) ----------------------------------
_MAIN_RESPONSES: tuple[ResponseSpec, ...] = (
    ResponseSpec(
        response_id="MEAN_ADAPS", internal_field="MEAN_ADAPS",
        paper_label="Days to anthesis", unit="d",
        response_group="phenology", ranking_domain=RANKING_DOMAIN_GENERAL,
        tier="main",
        computation_source="sa_model.compute_indicators: _emit('MEAN_ADAPS', mean of TN*_ADAPS from Evaluate.OUT)",
        note="Phenology anchor; cross-treatment mean of anthesis day.",
    ),
    ResponseSpec(
        response_id="MEAN_LAI_AUC", internal_field="MEAN_LAI_AUC",
        paper_label="Seasonal LAI integral", unit="d·m²/m²",
        response_group="canopy", ranking_domain=RANKING_DOMAIN_GENERAL,
        tier="main",
        computation_source="sa_model.compute_indicators: _emit('MEAN_LAI_AUC', mean of TN*_LAI_AUC from PlantGro LAID trapezoid integral)",
    ),
    ResponseSpec(
        response_id="MEAN_AGB_END_CWAD", internal_field="MEAN_AGB_END_CWAD",
        paper_label="End-of-season aboveground biomass", unit="kg/ha",
        response_group="biomass", ranking_domain=RANKING_DOMAIN_GENERAL,
        tier="main",
        computation_source="sa_model.compute_indicators: _emit('MEAN_AGB_END_CWAD', mean of TN*_AGB_END_CWAD = last CWAD from PlantGro)",
    ),
    ResponseSpec(
        response_id="MEAN_FRUITD_END", internal_field="MEAN_FRUITD_END",
        paper_label="Season-end cumulative harvested dry mass", unit="kg/ha",
        response_group="yield_harvest", ranking_domain=RANKING_DOMAIN_GENERAL,
        tier="main",
        computation_source="sa_model.compute_indicators: _emit('MEAN_FRUITD_END', mean of TN*_FRUITD_END = end of cumulative CHPDT curve from FreshWt.OUT)",
        note="MUST be published as 'season-end cumulative harvested dry mass', never the ambiguous 'fruit dry mass' (plan §4.1 note).",
    ),
    ResponseSpec(
        response_id="WN_WATER_FRUITD_END", internal_field="WN_WATER_FRUITD_END",
        paper_label="Water contrast in cumulative harvested dry mass", unit="kg/ha",
        response_group="water_response", ranking_domain=RANKING_DOMAIN_WATER_NITROGEN,
        tier="main",
        computation_source="sa_model._derive_water_nitrogen: WN_WATER_<LEVEL>_FRUITD_END = TN(high)_FRUITD_END - TN(low)_FRUITD_END per water_pairs",
    ),
    ResponseSpec(
        response_id="WN_NSLOPE_FRUITD_END", internal_field="WN_NSLOPE_FRUITD_END",
        paper_label="Nitrogen-response slope of cumulative harvested dry mass", unit="(kg/ha)/(kg N/ha)",
        response_group="nitrogen_response", ranking_domain=RANKING_DOMAIN_WATER_NITROGEN,
        tier="main",
        computation_source="sa_model._derive_water_nitrogen: WN_NSLOPE_<W>_<FEATURE> = linear slope of FRUITD_END vs N rate within each water level",
        note="Reported per water level (W3, W1); the slope is conditional on the sampled N series.",
    ),
    ResponseSpec(
        response_id="WN_INTERACTION_FRUITD_END", internal_field="WN_INTERACTION_FRUITD_END",
        paper_label="Difference in nitrogen-response slopes between water levels", unit="(kg/ha)/(kg N/ha)",
        response_group="water_nitrogen_interaction", ranking_domain=RANKING_DOMAIN_WATER_NITROGEN,
        tier="main",
        computation_source="sa_model._derive_water_nitrogen: WN_INTERACTION_<FEATURE> = slope(W3) - slope(W1)",
        note="A model water×N response descriptor; not a pairwise parameter interaction.",
    ),
)

# --- Supplement / diagnostic responses (plan §4.2) -------------------------
_SUPPLEMENT_RESPONSES: tuple[ResponseSpec, ...] = (
    ResponseSpec("MEAN_PDFPS", "MEAN_PDFPS", "Days to first pod", "d",
                 "phenology", RANKING_DOMAIN_GENERAL, "supplement",
                 "sa_model: _emit('MEAN_PDFPS', ... PDFPS from Evaluate.OUT)"),
    ResponseSpec("MEAN_LAI_PEAK", "MEAN_LAI_PEAK", "Peak LAI", "m²/m²",
                 "canopy", RANKING_DOMAIN_GENERAL, "supplement",
                 "sa_model: _emit('MEAN_LAI_PEAK', peak of LAID curve)"),
    ResponseSpec("MEAN_LAI_END", "MEAN_LAI_END", "End-of-season LAI", "m²/m²",
                 "canopy", RANKING_DOMAIN_GENERAL, "supplement",
                 "sa_model: _emit('MEAN_LAI_END', last LAID)"),
    ResponseSpec("MEAN_LEAF_END_LWAD", "MEAN_LEAF_END_LWAD", "End-of-season leaf dry mass", "kg/ha",
                 "biomass", RANKING_DOMAIN_GENERAL, "supplement",
                 "sa_model: _emit('MEAN_LEAF_END_LWAD', last LWAD)"),
    ResponseSpec("MEAN_STEM_END_SWAD", "MEAN_STEM_END_SWAD", "End-of-season stem dry mass", "kg/ha",
                 "biomass", RANKING_DOMAIN_GENERAL, "supplement",
                 "sa_model: _emit('MEAN_STEM_END_SWAD', last SWAD)"),
)

_DIAGNOSTIC_RESPONSES: tuple[ResponseSpec, ...] = (
    ResponseSpec("MEAN_CUMHARVEST_DAP50", "MEAN_CUMHARVEST_DAP50",
                 "DAP at 50% cumulative harvest", "d",
                 "yield_harvest", RANKING_DOMAIN_GENERAL, "diagnostic",
                 "sa_model: _emit('MEAN_CUMHARVEST_DAP50', _cumulative_dap_fraction(CHPDT, 0.5))",
                 "Threshold-type time point; first-order index CIs are wide (plan §4.2) — diagnostic only, never used for interaction-strength claims."),
)

# --- Excluded responses (plan §4.3) ----------------------------------------
_EXCLUDED_RESPONSES: tuple[ResponseSpec, ...] = (
    ResponseSpec("MEAN_HIAMS", "MEAN_HIAMS",
                 "Harvest index (excluded)", "—",
                 "yield_harvest", RANKING_DOMAIN_GENERAL, "excluded",
                 "sa_model: _emit('MEAN_HIAMS', ...)",
                 "EXCLUDED: continuous-picking eggplant has no applicable theoretical harvest-index benchmark (plan §4.3)."),
    ResponseSpec("MEAN_YIELD_HWAMS", "MEAN_YIELD_HWAMS",
                 "Default season-end yield (excluded)", "kg/ha",
                 "yield_harvest", RANKING_DOMAIN_GENERAL, "excluded",
                 "sa_model: _emit('MEAN_YIELD_HWAMS', HWAMS from Evaluate.OUT)",
                 "EXCLUDED: DSSAT default season-end HWAM must not replace per-pick actual dry/fresh harvest (plan §4.3)."),
)

#: All declared responses, indexed by response_id.
ALL_RESPONSES: dict[str, ResponseSpec] = {
    r.response_id: r for r in (*_MAIN_RESPONSES, *_SUPPLEMENT_RESPONSES,
                                *_DIAGNOSTIC_RESPONSES, *_EXCLUDED_RESPONSES)
}

MAIN_RESPONSE_IDS: tuple[str, ...] = tuple(r.response_id for r in _MAIN_RESPONSES)
SUPPLEMENT_RESPONSE_IDS: tuple[str, ...] = tuple(r.response_id for r in _SUPPLEMENT_RESPONSES)
DIAGNOSTIC_RESPONSE_IDS: tuple[str, ...] = tuple(r.response_id for r in _DIAGNOSTIC_RESPONSES)
EXCLUDED_RESPONSE_IDS: tuple[str, ...] = tuple(r.response_id for r in _EXCLUDED_RESPONSES)

#: Responses allowed in main-text SA conclusions (main tier only).
ALLOWED_IN_MAIN_TEXT: frozenset[str] = frozenset(MAIN_RESPONSE_IDS)

#: Responses explicitly forbidden from main SA conclusions.
FORBIDDEN_IN_MAIN_TEXT: frozenset[str] = frozenset(EXCLUDED_RESPONSE_IDS)

#: The published cumulative-harvest dry-mass response.  Central to the yield
#: chain; its label is pinned here so every exporter/figure uses the same name.
CUMULATIVE_HARVEST_DRY_MASS_ID = "MEAN_FRUITD_END"
CUMULATIVE_HARVEST_DRY_MASS_LABEL = "Season-end cumulative harvested dry mass"

#: Forbidden phrase for the cumulative-harvest response (plan §4.1 note).
AMBIGUOUS_FRUIT_DRY_MASS_PHRASES: tuple[str, ...] = (
    "fruit dry mass",
    "dry fruit mass",
    "fruit dry matter",
)


# ---------------------------------------------------------------------------
# Frozen-bounds reading
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FrozenBoundRow:
    """One row of a frozen bounds CSV, normalised for contract checks."""

    name: str
    init: str
    lower: str
    upper: str
    status: str        # active | fixed | disabled (lower-cased)
    pargp: str
    location: str
    file: str
    review_note: str
    decision_role: str
    evidence_basis: str
    raw: dict[str, str] = field(default_factory=dict, repr=False)


def read_frozen_bounds(path: str | Path) -> list[FrozenBoundRow]:
    """Read a frozen bounds CSV into normalised rows.

    Tolerant of the UTF-8-BOM header (``\\ufeffname``) that DSSAT-bound CSVs
    carry.  Raises ``ValueError`` if the file is empty or missing required
    columns.
    """
    p = Path(path)
    required = {"name", "status"}
    with p.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        missing = required - {f.lstrip("\ufeff") for f in fieldnames}
        if missing:
            raise ValueError(f"frozen bounds {p.name} missing columns: {sorted(missing)}")
        rows: list[FrozenBoundRow] = []
        for raw in reader:
            # normalise the BOM-prefixed key if present
            raw = {(k.lstrip("\ufeff") if k else k): v for k, v in raw.items()}
            name = str(raw.get("name", "")).strip().upper()
            if not name:
                continue
            rows.append(FrozenBoundRow(
                name=name,
                init=str(raw.get("init", "")).strip(),
                lower=str(raw.get("lower", "")).strip(),
                upper=str(raw.get("upper", "")).strip(),
                status=str(raw.get("status", "")).strip().lower(),
                pargp=str(raw.get("pargp", "")).strip(),
                location=str(raw.get("location", "")).strip(),
                file=str(raw.get("file", "")).strip(),
                review_note=str(raw.get("review_note", "")).strip(),
                decision_role=str(raw.get("decision_role", "")).strip(),
                evidence_basis=str(raw.get("evidence_basis", "")).strip(),
                raw=dict(raw),
            ))
    if not rows:
        raise ValueError(f"frozen bounds {p.name} is empty")
    return rows


def active_parameter_names(path: str | Path) -> list[str]:
    """Return the sorted list of ``active`` parameter names in a frozen CSV."""
    rows = read_frozen_bounds(path)
    return sorted(r.name for r in rows if r.status == "active")


# ---------------------------------------------------------------------------
# Contract validation
# ---------------------------------------------------------------------------

class SAContractError(Exception):
    """Raised when a parameter or response configuration violates the SA contract."""


def validate_main_parameter_space(path: str | Path) -> list[str]:
    """Validate that the frozen bounds supply exactly the expected 55 active
    parameters and contain no forbidden Morris parameters among them.

    Returns the sorted list of active parameter names on success.  Raises
    :class:`SAContractError` on any violation.
    """
    rows = read_frozen_bounds(path)
    active = [r for r in rows if r.status == "active"]
    active_names = sorted(r.name for r in active)
    if len(active) != EXPECTED_ACTIVE_COUNT:
        raise SAContractError(
            f"Main SA parameter space must be exactly {EXPECTED_ACTIVE_COUNT} active "
            f"parameters, but {Path(path).name} has {len(active)}. "
            f"The active set must not be silently enlarged or narrowed (plan §3.1)."
        )
    forbidden_present = sorted(set(active_names) & FORBIDDEN_MORRIS_PARAMETERS)
    if forbidden_present:
        raise SAContractError(
            f"Forbidden parameters found in active Morris space: {forbidden_present}. "
            f"These are structurally inapplicable or require discrete scenarios (plan §3.2)."
        )
    # Seasonal-offset parameters must never appear as genetic SA parameters.
    seasonal_leaked = sorted(
        n for n in active_names
        if any(marker in n.upper() for marker in SEASONAL_OFFSET_MARKERS)
    )
    if seasonal_leaked:
        raise SAContractError(
            f"Seasonal-adaptation offsets leaked into genetic SA space: {seasonal_leaked}. "
            f"These belong to calibration seasonal hypotheses only (plan §3.2)."
        )
    return active_names


def assert_response_not_excluded(response_id: str) -> None:
    """Raise if *response_id* is an excluded response (HIAM/HWAM family)."""
    rid = response_id.strip().upper()
    spec = ALL_RESPONSES.get(rid)
    if spec is not None and spec.tier == "excluded":
        raise SAContractError(
            f"Response {rid!r} is excluded from main SA conclusions: {spec.note}"
        )


def validate_response_tier_consistency(response_ids: Iterable[str], *, allow_diagnostic: bool = False) -> None:
    """Validate that a collection of response ids is consistent with the contract.

    * Main-text effect tables may only contain ``main`` responses (plus
      ``supplement`` if explicitly opted in); ``excluded`` is always rejected.
    * ``diagnostic`` responses (e.g. ``CUMHARVEST_DAP50``) are rejected for
      interaction-strength claims unless ``allow_diagnostic=True``.
    """
    ids = [r.strip().upper() for r in response_ids]
    unknown = sorted(set(ids) - set(ALL_RESPONSES))
    if unknown:
        raise SAContractError(
            f"Response ids not declared in the SA contract: {unknown}. "
            f"Every SA response must be declared in sa_contract.ALL_RESPONSES."
        )
    for rid in ids:
        spec = ALL_RESPONSES[rid]
        if spec.tier == "excluded":
            raise SAContractError(
                f"Excluded response {rid!r} cannot enter SA conclusions (plan §4.3)."
            )
        if spec.tier == "diagnostic" and not allow_diagnostic:
            raise SAContractError(
                f"Diagnostic response {rid!r} cannot enter quantitative conclusions "
                f"without allow_diagnostic=True (plan §4.2)."
            )


def validate_ranking_domains_separate(domain_assignments: dict[str, str]) -> None:
    """Validate that response→domain assignments keep the two ranking domains
    strictly separate and that every domain is a known one.

    *domain_assignments* maps ``response_id -> ranking_domain``.  Raises if any
    domain is unknown, or if a single response is assigned to both domains
    (which would merge them — forbidden by plan §5.2 rule 3).
    """
    unknown = sorted(set(domain_assignments.values()) - set(RANKING_DOMAINS))
    if unknown:
        raise SAContractError(
            f"Unknown ranking domains: {unknown}. Allowed: {list(RANKING_DOMAINS)}"
        )
    seen: dict[str, set[str]] = {}
    for rid, dom in domain_assignments.items():
        seen.setdefault(rid.strip().upper(), set()).add(dom)
    dual = {r for r, doms in seen.items() if len(doms) > 1}
    if dual:
        raise SAContractError(
            f"Responses assigned to both ranking domains (merge forbidden, plan §5.2): {sorted(dual)}"
        )


__all__ = [
    # constants
    "V4_FROZEN_BOUNDS_FILENAME", "EXPECTED_ACTIVE_COUNT",
    "FORBIDDEN_MORRIS_PARAMETERS", "FIXED_BY_DECISION", "SEASONAL_OFFSET_MARKERS",
    "RANKING_DOMAINS", "RANKING_DOMAIN_GENERAL", "RANKING_DOMAIN_WATER_NITROGEN",
    "ALL_RESPONSES", "MAIN_RESPONSE_IDS", "SUPPLEMENT_RESPONSE_IDS",
    "DIAGNOSTIC_RESPONSE_IDS", "EXCLUDED_RESPONSE_IDS",
    "ALLOWED_IN_MAIN_TEXT", "FORBIDDEN_IN_MAIN_TEXT",
    "CUMULATIVE_HARVEST_DRY_MASS_ID", "CUMULATIVE_HARVEST_DRY_MASS_LABEL",
    "AMBIGUOUS_FRUIT_DRY_MASS_PHRASES",
    # dataclasses
    "ResponseSpec", "FrozenBoundRow",
    # functions
    "read_frozen_bounds", "active_parameter_names",
    "validate_main_parameter_space",
    "assert_response_not_excluded",
    "validate_response_tier_consistency",
    "validate_ranking_domains_separate",
    # exceptions
    "SAContractError",
]
