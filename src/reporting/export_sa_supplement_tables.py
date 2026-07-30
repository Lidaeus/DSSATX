"""Create frozen source tables for the sensitivity-analysis supplement.

The two tables deliberately preserve the distinction between the broad Morris
sampling space and the smaller Sobol *screening* set.  They are not a
calibration-parameter registry and must not be used to release parameters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


# Boundary-source classification (P2#7).  Maps the frozen-bounds evidence_basis
# text onto a transparent source type so Table S1 does not present 38 inherited
# ranges as uniformly-justified "boundary basis".  No citation is fabricated.
_BOUNDARY_SOURCE_KEYWORDS = (
    (("physical", "numerical", "safety", "valid regime", "missing anthesis",
      "anthesis=-99", "forward check"), "physical_numeric_safety"),
    (("literature", "eggplant", "tomato baseline", "strawberry",
      "near-relative", "photothermal-day"), "crop_literature"),
    (("greenhouse", "cultivar", "trial", "experiment", "observed"), "current_cultivar_trial"),
    (("calibration", "posterior", "v14", "historical", "prior"), "historical_calibration"),
)


def _classify_boundary_source(evidence_basis: str) -> str:
    """Classify a boundary-basis text into a transparent source type."""
    text = str(evidence_basis).lower()
    for keywords, source_type in _BOUNDARY_SOURCE_KEYWORDS:
        if any(kw in text for kw in keywords):
            return source_type
    return "inherited_pending_review"


# Definitions are transcribed from the shipped CUL/ECO headers where they are
# available.  For named SPE coefficients, the label identifies the model
# process rather than claiming a field-measured biological quantity.
PARAMETER_METADATA: dict[str, tuple[str, str]] = {
    "LFMAX": ("Maximum leaf photosynthesis rate at 30 °C, 350 vpm CO₂ and high light", "mg CO₂ m⁻² s⁻¹"),
    "SIZLF": ("Maximum area of a fully expanded leaf", "cm²"),
    "SLAVR": ("Specific leaf area under standard growth conditions", "cm² g⁻¹"),
    "XFRT": ("Maximum fraction of daily growth partitioned to reproductive organs", "fraction"),
    "EM-FL": ("Emergence to first flower (R1) duration", "photothermal days"),
    "FL-SD": ("First flower to first seed (R5) duration", "photothermal days"),
    "FL-SH": ("First flower to first pod (R3) duration", "photothermal days"),
    "PODUR": ("Duration to final pod load under optimal conditions", "photothermal days"),
    "SDPDV": ("Average seeds per pod under standard conditions", "seeds pod⁻¹"),
    "SFDUR": ("Seed-filling duration per reproductive cohort", "photothermal days"),
    "RHGHT": ("Relative canopy height per node versus the species-file standard", "dimensionless ratio"),
    "RWDTH": ("Relative canopy width per node versus the species-file standard", "dimensionless ratio"),
    "TRIFL": ("Main-stem leaf appearance rate", "leaves thermal-day⁻¹"),
    "EM-V1": ("Emergence to first true leaf (V1) duration", "thermal days"),
    "FL-VS": ("First flower to last main-stem leaf duration", "photothermal days"),
    "JU-R0": ("Minimum duration for floral induction", "photothermal days"),
    "LNGSH": ("Individual shell growth duration", "photothermal days"),
    "PL-EM": ("Planting to emergence duration", "thermal days"),
    "PM06": ("Proportion of first-flower-to-first-pod interval for the first reproductive organ", "fraction"),
    "PM09": ("Proportion of first-seed-to-maturity interval during which the last seed can form", "fraction"),
    "XFINT": ("Multi-harvest fruit-partitioning intensity coefficient", "dimensionless coefficient"),
    "XFPHT": ("Photothermal timing control for multi-harvest fruit partitioning", "photothermal days"),
    "XMAGE": ("Photothermal timing control for multi-harvest initiation", "photothermal days"),
    "KCAN": ("Canopy light-extinction coefficient", "dimensionless coefficient"),
    "KC_SLOPE": ("Slope coefficient for the canopy light-extinction response", "dimensionless coefficient"),
    "PARMAX": ("Species-file maximum canopy photosynthesis coefficient", "model coefficient"),
    "PHTMAX": ("Species-file photosynthesis response coefficient", "model coefficient"),
    "ATOP": ("Vegetative partitioning-top coefficient", "dimensionless coefficient"),
    "FRLFF": ("Fractional leaf allocation control in vegetative partitioning", "fraction"),
    "FRSTMF": ("Fractional stem allocation control in vegetative partitioning", "fraction"),
    "PORPT": ("Vegetative partitioning/root-process coefficient", "dimensionless coefficient"),
    "RTNO3": ("Root nitrate uptake coefficient", "model coefficient"),
    "RTNH4": ("Root ammonium uptake coefficient", "model coefficient"),
    "RTEXF": ("Root extraction-factor coefficient", "model coefficient"),
    "WTFSD": ("Seed-weighting factor in vegetative partitioning", "dimensionless coefficient"),
    "FINREF": ("Reference final leaf number", "leaf number"),
    "SIZREF": ("Reference maximum leaf size", "cm²"),
    "SLAREF": ("Reference specific leaf area", "cm² g⁻¹"),
    "VSSINK": ("Vegetative-stage sink coefficient for leaf growth", "dimensionless coefficient"),
    "TB1": ("Base temperature for vegetative development", "°C"),
    "TB2": ("Base temperature for early reproductive development", "°C"),
    "TB3": ("Base temperature for late reproductive development", "°C"),
    "TM1": ("Ceiling temperature for vegetative development", "°C"),
    "TM2": ("Ceiling temperature for early reproductive development", "°C"),
    "TM3": ("Ceiling temperature for late reproductive development", "°C"),
    "TO11": ("Lower optimum temperature for vegetative development", "°C"),
    "TO12": ("Lower optimum temperature for early reproductive development", "°C"),
    "TO13": ("Lower optimum temperature for late reproductive development", "°C"),
    "TO21": ("Upper optimum temperature for vegetative development", "°C"),
    "TO22": ("Upper optimum temperature for early reproductive development", "°C"),
    "TO23": ("Upper optimum temperature for late reproductive development", "°C"),
    "NSTFAC": ("Nitrogen-stress factor for reproductive development", "dimensionless coefficient"),
    "NMOBMX": ("Maximum nitrogen mobilization fraction", "fraction day⁻¹"),
    "NVSMOB": ("Vegetative nitrogen mobilization fraction", "fraction"),
    "NRCVR": ("Nitrogen recovery coefficient", "dimensionless coefficient"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path, required: set[str]) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")
    return frame


def build_supplement_tables(*, bounds_csv: Path, sobol_candidates_csv: Path, out_dir: Path) -> Path:
    """Freeze Table S1/S2 and a small manifest; return the manifest path."""
    bounds_csv = bounds_csv.resolve()
    sobol_candidates_csv = sobol_candidates_csv.resolve()
    bounds = _read_csv(bounds_csv, {"name", "init", "lower", "upper", "status", "location", "file", "evidence_basis"})
    active = bounds.loc[bounds["status"].astype(str).str.lower().eq("active")].copy()
    if len(active) != 55:
        raise ValueError(f"Table S1 requires exactly 55 active Morris parameters; found {len(active)}")
    unknown = sorted(set(active["name"]) - set(PARAMETER_METADATA))
    if unknown:
        raise ValueError(f"Table S1 metadata is missing active parameters: {unknown}")
    active[["definition", "unit"]] = active["name"].map(PARAMETER_METADATA).apply(pd.Series)
    active["template_relative_path"] = active["file"].map({
        "TMGRO048.CUL.base": "data/templates/genotype/TMGRO048.CUL.base",
        "TMGRO048.ECO": "data/templates/genotype/TMGRO048.ECO.base",
        "TMGRO048.SPE": "data/templates/genotype/TMGRO048.SPE.base",
    })
    if active["template_relative_path"].isna().any():
        raise ValueError("Table S1 cannot resolve one or more template file locations")
    active.insert(0, "table", "Table S1")
    active.insert(1, "sampling_space", "Independent Morris candidate range; uniform grid sampling (p=6)")
    active = active.rename(columns={
        "name": "parameter", "file": "template_file", "location": "file_family",
        "init": "initial_value", "lower": "lower_bound", "upper": "upper_bound",
        "evidence_basis": "boundary_basis",
    })
    # P2#7: classify the boundary basis into a transparent source type so the
    # published table distinguishes literature/physical/inherited sources rather
    # than presenting 38 inherited-pending-review ranges as if they were all
    # equally justified "boundary basis".  No literature citation is fabricated;
    # inherited ranges are honestly labelled as pending per-parameter review.
    active["boundary_source_type"] = active["boundary_basis"].map(_classify_boundary_source)
    table_s1 = active[[
        "table", "sampling_space", "parameter", "definition", "file_family", "template_file", "template_relative_path",
        "initial_value", "lower_bound", "upper_bound", "unit", "boundary_basis", "boundary_source_type",
    ]].sort_values(["file_family", "parameter"], kind="stable")

    candidates = _read_csv(sobol_candidates_csv, {
        "parameter", "selection_order", "top15_domain_count", "minimum_domain_rank", "selection_class", "approval_status",
    }).copy()
    if len(candidates) != 23 or candidates["parameter"].duplicated().any():
        raise ValueError("Table S2 requires 23 unique Sobol screening candidates")
    candidates.insert(0, "table", "Table S2")
    candidates.insert(1, "candidate_set_role", "Candidate set for subsequent calibration-design review; not a final calibration-parameter table")
    candidates = candidates.rename(columns={
        "selection_order": "selection_order", "top15_domain_count": "season_domain_top15_count",
        "minimum_domain_rank": "minimum_rank", "selection_class": "retention_category",
        "approval_status": "screening_status",
    })
    table_s2 = candidates[[
        "table", "candidate_set_role", "selection_order", "parameter", "season_domain_top15_count",
        "minimum_rank", "retention_category", "screening_status",
    ]].sort_values("selection_order", kind="stable")

    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    s1_path = out_dir / "Table_S1_morris_sampling_space.csv"
    s2_path = out_dir / "Table_S2_sobol_candidate_reduction.csv"
    table_s1.to_csv(s1_path, index=False, encoding="utf-8")
    table_s2.to_csv(s2_path, index=False, encoding="utf-8")
    notes = out_dir / "Supplementary_tables_README.md"
    notes.write_text(
        "# Sensitivity-analysis supplementary tables\n\n"
        "- **Table S1** defines the 55-parameter Morris sampling space. Candidate intervals are frozen development/research ranges, not posterior distributions or final calibration bounds. Morris used independent p=6 grid sampling within these rectangular bounds; inter-parameter order constraints (XMAGE < XFPHT and TB < TO1 < TO2 < TM) were guaranteed by the ranges.\n"
        "- **Table S2** records the prespecified 23-parameter Sobol screening set. `season_domain_top15_count` is the number of appearances among the six season × ranking-domain Top-15 lists; `minimum_rank` is the best such rank. It is a candidate set for subsequent calibration-design review, **not** the final calibration-parameter table.\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "bundle_type": "sa_supplementary_tables",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": [
            {"role": "frozen_morris_bounds", "path": str(bounds_csv), "sha256": _sha256(bounds_csv)},
            {"role": "sobol_screening_candidates", "path": str(sobol_candidates_csv), "sha256": _sha256(sobol_candidates_csv)},
        ],
        "artifacts": [
            {"role": "table_s1", "path": s1_path.name, "sha256": _sha256(s1_path), "rows": len(table_s1)},
            {"role": "table_s2", "path": s2_path.name, "sha256": _sha256(s2_path), "rows": len(table_s2)},
            {"role": "readme", "path": notes.name, "sha256": _sha256(notes)},
        ],
    }
    manifest_path = out_dir / "supplementary_tables_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def build_table_s3(*, effect_case: Path, season: str, out_dir: Path,
                   replicates: int = 1000, seed: int = 20260729) -> Path:
    """Freeze Table S3: the full Sobol effect decomposition for the convergence-
    validated season.

    Table S3 carries, for every core response × Sobol candidate parameter, the
    S1 / ST point estimates, their 95% paired-bootstrap intervals, the
    interaction-involving remainder (ST-S1) with its interval and a boolean
    ``interaction_supported`` flag (true iff the interval lower bound > 0), and
    the response scale (SD / min / max).  This is the complete, auditable
    decomposition that the figure (Fig. S2) summarises.

    Only the convergence-validated season (XXQL2502) should be passed here; the
    plan (§4.3) prohibits pooling quantitative Sobol indices across seasons
    whose numerical gates have not all passed.
    """
    from src.reporting.export_sobol_stability_paper_data import _effect_decomposition
    effects, scales = _effect_decomposition(
        effect_case, season, replicates=replicates, seed=seed)
    # Keep the response scale attached to every effect row (plan §6.3: response
    # SD/min/max must accompany the indices so a high relative share on a
    # near-zero-variance response is not misread as a large agronomic effect).
    merged = effects.merge(
        scales[["season", "response_id", "response_sd", "response_min", "response_max", "unit"]],
        on=["season", "response_id"], how="left", validate="many_to_one")
    merged.insert(0, "table", "Table S3")
    merged.insert(1, "interpretation_note",
                  "S1 = first-order variance share; ST = total effect (includes interactions); "
                  "interaction_remainder = ST-S1 (aggregate interaction-involving remainder, not a "
                  "pairwise interaction); interaction_supported true iff paired-bootstrap lower bound > 0.")
    out_dir.mkdir(parents=True, exist_ok=True)
    s3_path = out_dir / "table_s3_sobol_effect_decomposition.csv"
    merged.to_csv(s3_path, index=False, encoding="utf-8")
    return s3_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze sensitivity-analysis Tables S1, S2 and (optionally) S3")
    parser.add_argument("--bounds-csv", required=True)
    parser.add_argument("--sobol-candidates-csv", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--effect-case", default=None,
                        help="Optional Sobol effect case dir (with sa_sen_sobol.sobol.par/obs.csv) "
                             "to also build Table S3. Pass only the convergence-validated season.")
    parser.add_argument("--effect-season", default=None,
                        help="Season label for Table S3 (required with --effect-case).")
    args = parser.parse_args(argv)
    try:
        print(build_supplement_tables(
            bounds_csv=Path(args.bounds_csv), sobol_candidates_csv=Path(args.sobol_candidates_csv), out_dir=Path(args.out_dir)
        ))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    if args.effect_case:
        if not args.effect_season:
            parser.error("--effect-season is required when --effect-case is given")
            return 2
        try:
            s3 = build_table_s3(
                effect_case=Path(args.effect_case), season=args.effect_season, out_dir=Path(args.out_dir))
            print(f"Table S3 written: {s3}")
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
