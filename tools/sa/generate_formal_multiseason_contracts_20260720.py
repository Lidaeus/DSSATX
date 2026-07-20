"""Generate the three per-season formal-SA output contracts (T2 deliverable B).

Reads each controlled bundle's FileX, derives the MI/MF treatment mapping and
the per-MF N rate (kg N/ha) via fertilizer_n_total_kg_ha, and writes one
output-contract JSON per season to configs/sa/. The three contracts share the
same features / time points / response_groups / ranking_domains so the same
metric name means the same thing across seasons (handoff T2 requirement).
XXQL2601 uses the user-corrected TN12=W1/N0 assignment, giving the same
complete 2-water × 4-nitrogen factorial as the other seasons.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.experiment_inputs import parse_filex
from src.sensitivity.treatment_factor_attribution import fertilizer_n_total_kg_ha

SEASONS = [
    {"exp": "XXQL2501", "bundle": "xxql2501_sa_controlled_candidate_20260720", "season": "2025_spring"},
    {"exp": "XXQL2502", "bundle": "xxql2502_sa_controlled_candidate_20260720", "season": "2025_autumn"},
    {"exp": "XXQL2601", "bundle": "xxql2601_sa_controlled_tn12_w1_candidate_20260721", "season": "2026_spring"},
]

RETAINED = {
    "XXQL2501": [2, 3, 4, 5, 10, 11, 12, 13],
    "XXQL2502": [1, 3, 4, 6, 7, 9, 10, 12],
    "XXQL2601": [1, 3, 4, 6, 7, 9, 10, 12],
}

# MI -> W label mapping used by derive_water_nitrogen_responses (hardcoded
# {"W3","W1"} in output_contract.py / sa_model.py). The contract must use these
# exact keys: the high-water arm is "W3" (MI=3), the low-water arm is "W1" (MI=1).
MI_TO_W = {1: "W1", 3: "W3"}

# MF -> N-class label used to key water_pairs (N3/N2/N1/N0 = highest -> zero).
MF_TO_NCLASS = {1: "N3", 2: "N2", 3: "N1", 4: "N0"}


# Shared (semantic-consistency) fields — identical across all three contracts.
SHARED_FEATURES = [
    "YIELD_HWAMS", "LAIXS", "CWAMS", "ADAPS", "PDFPS",
    "LAI_AUC", "LAI_PEAK", "LAI_END",
    "FRUITD_END", "CUMHARVEST_DAP50",
    "LEAF_END_LWAD", "STEM_END_SWAD", "AGB_END_CWAD",
]
SHARED_LAI_TIME_POINTS = [45, 67, 95, 119]
SHARED_FRUIT_TIME_POINTS = []  # cumulative fruit only at event + season-end
SHARED_RESPONSE_GROUPS = {
    "phenology": ["ADAPS", "PDFPS"],
    "canopy": ["LAIXS", "LAI_AUC", "LAI_PEAK", "LAI_END", "LAI_DAP"],
    "biomass": ["CWAMS", "LEAF_END_LWAD", "STEM_END_SWAD", "AGB_END_CWAD"],
    "yield_harvest": ["YIELD_HWAMS", "FRUITD_END", "CUMHARVEST_DAP50"],
    "water_response": ["WATER_LAI_AUC", "WATER_AGB_END_CWAD", "WATER_FRUITD_END", "WATER_CUMHARVEST_DAP50"],
    "nitrogen_response": ["NITROGEN_LAI_AUC", "NITROGEN_AGB_END_CWAD", "NITROGEN_FRUITD_END", "NITROGEN_CUMHARVEST_DAP50"],
    "water_nitrogen_interaction": ["INTERACTION_LAI_AUC", "INTERACTION_AGB_END_CWAD", "INTERACTION_FRUITD_END", "INTERACTION_CUMHARVEST_DAP50"],
}
SHARED_RANKING_DOMAINS = {
    "general_genetic": ["phenology", "canopy", "biomass", "yield_harvest"],
    "water_nitrogen_response": ["water_response", "nitrogen_response", "water_nitrogen_interaction"],
}
CONTRAST_FEATURES = ["LAI_AUC", "AGB_END_CWAD", "FRUITD_END", "CUMHARVEST_DAP50"]


def build_water_nitrogen_design(parsed_filex: dict, filex_text: str, exp: str) -> dict:
    """Build water_pairs + nitrogen_series from the FileX MI/MF mapping + N rates.

    water_pairs keyed by N-class (N3/N2/N1/N0): each value is [W3_tn, W1_tn].
    nitrogen_series keyed by W arm (W3/W1): each a list of {treatment, n_kg_ha}.
    DSSAT's WN-contract validator requires exactly the keys {"W3","W1"} and
    unique n_kg_ha doses per series.
    """

    treatments = parsed_filex["treatments"]
    retained = RETAINED[exp]

    # Group retained treatments by (MI -> W, MF -> N-class). Detect duplicate
    # (W, N-class) assignments (e.g. XXQL2601 TN9 and TN12 are both W3/N0) and
    # keep the LAST TN in retained-order (so the contract's water_pairs /
    # nitrogen_series reference exactly one TN per (W, N-class) cell). The
    # earlier duplicate is recorded explicitly — the SA must not silently lose
    # a retained treatment.
    by_wn: dict[tuple[str, str], int] = {}
    duplicate_wn_assignments: list[str] = []
    n_rate_by_mf: dict[int, float] = {}
    for mf in (1, 2, 3, 4):
        n_rate_by_mf[mf] = fertilizer_n_total_kg_ha(filex_text, mf)

    for tn in retained:
        f = treatments.get(tn)
        if not f:
            raise ValueError(f"TN{tn} absent from {exp} FileX")
        mi = int(f["MI"])
        mf = int(f["MF"])
        if mi not in MI_TO_W:
            raise ValueError(f"TN{tn} has MI={mi}, expected 1 (W1) or 3 (W3)")
        w = MI_TO_W[mi]
        nclass = MF_TO_NCLASS[mf]
        key = (w, nclass)
        if key in by_wn:
            earlier = by_wn[key]
            duplicate_wn_assignments.append(
                f"{exp} TN{tn}: duplicate (W, N-class)={key} with TN{earlier}; "
                f"both share MI={mi} MF={mf}. TN{tn} (later in retained order) is KEPT in the "
                f"contract's water_pairs and nitrogen_series; TN{earlier} is DROPPED from those "
                f"WN structures to satisfy the unique-dose validator. TN{earlier} still appears "
                f"in the per-treatment base-feature observations; only the derived WN_* "
                f"contrast/slope/interaction responses drop it."
            )
        by_wn[key] = tn

    # water_pairs: {N3: [W3_tn, W1_tn], ...}; omit levels where W1 is absent.
    water_pairs: dict[str, list[int]] = {}
    water_pairs_notes: list[str] = []
    for nclass in ("N3", "N2", "N1", "N0"):
        w3_tn = by_wn.get(("W3", nclass))
        w1_tn = by_wn.get(("W1", nclass))
        if w3_tn is None and w1_tn is None:
            water_pairs_notes.append(f"{nclass}: neither W3 nor W1 present in retained set")
            continue
        if w3_tn is None or w1_tn is None:
            missing = "W3" if w3_tn is None else "W1"
            water_pairs_notes.append(
                f"{nclass}: {missing} absent in {exp} retained set; "
                f"W1-vs-W3 contrast at this N level is not estimable "
                f"(W3={w3_tn}, W1={w1_tn})"
            )
            # The validator requires pairs of length 2; skip this level entirely
            # rather than emit a malformed single-element pair.
            continue
        water_pairs[nclass] = [w3_tn, w1_tn]

    # nitrogen_series: {W3: [{treatment, n_kg_ha}, ...], W1: [...]}
    # Build one entry per (W, MF) where the treatment exists. Drop duplicates
    # by n_kg_ha (validator rejects duplicate doses) keeping the first TN.
    nitrogen_series: dict[str, list[dict[str, object]]] = {"W3": [], "W1": []}
    seen_doses: dict[str, set[float]] = {"W3": set(), "W1": set()}
    dropped_duplicates: list[str] = []
    # Process MF in descending N-rate order so the highest-dose TN is kept when
    # two TNs share a dose (cosmetic; the validator just needs uniqueness).
    for w in ("W3", "W1"):
        for mf in (1, 2, 3, 4):
            tn = by_wn.get((w, MF_TO_NCLASS[mf]))
            if tn is None:
                continue
            dose = float(n_rate_by_mf[mf])
            if dose in seen_doses[w]:
                dropped_duplicates.append(
                    f"{exp} {w} MF{mf} TN{tn}: dropped (duplicate n_kg_ha={dose:g} "
                    f"already contributed by another {w} treatment)"
                )
                continue
            seen_doses[w].add(dose)
            nitrogen_series[w].append({"treatment": int(tn), "n_kg_ha": dose})
        # sort each series by dose ascending (matches existing contract layout)
        nitrogen_series[w].sort(key=lambda row: float(row["n_kg_ha"]))

    return {
        "contrast_features": CONTRAST_FEATURES,
        "water_pairs": water_pairs,
        "nitrogen_series": nitrogen_series,
        "_notes": {
            "water_pairs_omissions": water_pairs_notes,
            "dropped_duplicate_wn_assignments": duplicate_wn_assignments,
            "dropped_duplicate_dose_treatments": dropped_duplicates,
            "mf_to_nclass": MF_TO_NCLASS,
            "mi_to_w": MI_TO_W,
        },
    }


def build_contract(season_entry: dict) -> dict:
    exp = season_entry["exp"]
    bundle = season_entry["bundle"]
    bundle_dir = PROJECT_ROOT / "data" / "user" / "experiments" / bundle
    filex_path = bundle_dir / f"{exp}.TMX"
    filex_text = filex_path.read_text(encoding="utf-8", errors="ignore")
    parsed = parse_filex(filex_path)
    treatments = RETAINED[exp]
    wn_design = build_water_nitrogen_design(parsed, filex_text, exp)

    contract = {
        "profile_id": (
            "eggplant_formal_xxql2601_outputs_v2_20260721"
            if exp == "XXQL2601"
            else f"eggplant_formal_{exp.lower()}_outputs_v1_20260720"
        ),
        "experiment_bundle": bundle,
        "season": season_entry["season"],
        "experiment": exp,
        "treatments": treatments,
        "features": SHARED_FEATURES,
        "lai_time_points": SHARED_LAI_TIME_POINTS,
        "fruit_time_points": SHARED_FRUIT_TIME_POINTS,
        "include_treatment_mean": False,
        "response_groups": SHARED_RESPONSE_GROUPS,
        "ranking_domains": SHARED_RANKING_DOMAINS,
        "water_nitrogen_design": wn_design,
        "design_notes": [
            f"Formal per-season sensitivity output contract for {exp} ({season_entry['season']}).",
            "Features, lai_time_points, fruit_time_points, response_groups and ranking_domains are "
            "IDENTICAL across the three season contracts so the same metric name has the same meaning.",
            "MDAPS is omitted because the uncalibrated baseline returns the DSSAT -99 missing sentinel.",
            "Nitrogen doses (n_kg_ha) are derived from this season's FileX *FERTILIZERS (INORGANIC) "
            "FAMN column via fertilizer_n_total_kg_ha, NOT from a hardcoded ladder; the three seasons "
            "differ (2501: 399/271/130/0; 2502: 360/240/120/0; 2601: 361/240/120/0 kg N/ha).",
            "LAI DAP points 45/67/95/119 lie inside every season's PlantGro DAP window "
            "(2501: 8-141; 2502: DAP 0-147; 2601: 2-131).",
        ],
    }
    if exp == "XXQL2601":
        contract["water_nitrogen_design"]["_notes"]["input_corrections"] = [
            "User correction 2026-07-21: TN12 is W1/N0 (MI=1, MF=4), not W3/N0. "
            "The corrected design is a complete 2 water x 4 nitrogen factorial."
        ]
        contract["design_notes"].append(
            "TN12 irrigation was corrected by the user on 2026-07-21 from MI=3 to MI=1; "
            "XXQL2601 now provides the complete W1/W3 by N0/N1/N2/N3 factorial."
        )

    # Season-specific notes for known structural issues.
    notes = wn_design.get("_notes", {})
    omissions = notes.get("water_pairs_omissions", [])
    dropped = notes.get("dropped_duplicate_dose_treatments", [])
    if omissions:
        contract["design_notes"].append(
            "W1-vs-W3 contrast omissions: " + "; ".join(omissions)
        )
    if dropped:
        contract["design_notes"].append(
            "Duplicate-dose treatments dropped from nitrogen_series: " + "; ".join(dropped)
        )
    return contract


def main():
    out_dir = PROJECT_ROOT / "configs" / "sa"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for entry in SEASONS:
        contract = build_contract(entry)
        out_path = out_dir / f"eggplant_formal_{entry['exp'].lower()}_outputs_20260720.json"
        out_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        written.append(out_path)
        wn = contract["water_nitrogen_design"]
        print(f"{entry['exp']}: {out_path.name}")
        print(f"  treatments: {contract['treatments']}")
        print(f"  water_pairs: {wn['water_pairs']}")
        for w in ("W3", "W1"):
            series = wn["nitrogen_series"][w]
            doses = [row["n_kg_ha"] for row in series]
            tns = [row["treatment"] for row in series]
            print(f"  nitrogen_series.{w}: TN{tns} doses={doses}")
        notes = wn["_notes"]
        if notes["water_pairs_omissions"]:
            for n in notes["water_pairs_omissions"]:
                print(f"  NOTE: {n}")
        if notes["dropped_duplicate_dose_treatments"]:
            for n in notes["dropped_duplicate_dose_treatments"]:
                print(f"  NOTE: {n}")

    print(f"\nWrote {len(written)} contracts:")
    for p in written:
        print(f"  {p}")


if __name__ == "__main__":
    main()
