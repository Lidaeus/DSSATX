"""Generate ``parameter_range_audit.csv`` — the parameter-range audit table.

Implements W1 of ``docs/敏感性分析方案与图表优化_协作实施计划_20260729.md``
(§3.3, §10 W1).  For every active parameter the table records the bound
values, the relative half-width, the inferred source type, and any coupled
constraints — **without modifying the frozen bounds**.

The plan is explicit (§3.3): ranges must not be mechanically narrowed; the
audit only documents *why* each range is what it is, distinguishing:

* ``physical_numeric_safety`` — DSSAT numerical/physical safety boundary;
* ``crop_literature`` — eggplant or near-relative crop literature;
* ``current_cultivar_trial`` — current cultivar/greenhouse-trial experience;
* ``historical_calibration`` — prior calibration results;
* ``engineering_assumption`` — a placeholder range for testing only.

Source-type inference is conservative: it reads the frozen-bounds
``evidence_basis`` text and maps keywords to a source type.  Where the text
is the generic "Inherited as a proposal candidate; requires final per-
parameter review", the source is flagged ``engineering_assumption`` with
``range_review_status = needs_per_parameter_review`` — surfacing, not hiding,
the parameters whose range justification is weakest.

Coupled constraints (``XMAGE < XFPHT``, ``TB < TO1 < TO2 < TM``) are flagged
from the parameter name so the reviewer sees which ranges are not
independent.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.project import PROJECT_ROOT, git_metadata, sha256_file
from src.sensitivity.sa_contract import (
    EXPECTED_ACTIVE_COUNT,
    V4_FROZEN_BOUNDS_FILENAME,
    read_frozen_bounds,
)

OUTPUT_COLUMNS = [
    "parameter",
    "lower", "init", "upper",
    "source_type",
    "source_reference",
    "relative_half_width",
    "physical_constraint",
    "coupled_constraint",
    "boundary_risk",
    "range_review_status",
]

# Keyword → source-type mapping (order matters; first match wins).
_SOURCE_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("physical", "numerical", "safety", "stability", "valid regime",
      "missing anthesis", "anthesis=-99", "forward check"), "physical_numeric_safety"),
    (("literature", "eggplant lit", "tomato baseline", "strawberry",
      "near-relative", "photothermal-day"), "crop_literature"),
    (("greenhouse", "cultivar", "trial", "experiment", "observed"), "current_cultivar_trial"),
    (("calibration", "posterior", "v14", "historical", "prior"), "historical_calibration"),
]


def _infer_source_type(evidence_basis: str, decision_role: str) -> tuple[str, str]:
    """Return ``(source_type, source_reference)`` from frozen-bounds metadata.

    ``source_reference`` is the verbatim evidence-basis text (truncated for
    CSV friendliness), so a reviewer can trace the claim back to its source.
    """
    text = f"{evidence_basis} {decision_role}".lower()
    for keywords, source_type in _SOURCE_KEYWORDS:
        if any(kw in text for kw in keywords):
            return source_type, evidence_basis
    # The generic "Inherited as a proposal candidate" fallback.
    return "engineering_assumption", evidence_basis


def _relative_half_width(lower: float, upper: float, init: float) -> str:
    """Half-width relative to |init|, formatted for the CSV.

    Returns ``"nan"`` when init is zero (relative width undefined).  This is a
    descriptive statistic only — it is not used to narrow ranges.
    """
    if init == 0.0:
        return "nan"
    return f"{abs(upper - lower) / (2.0 * abs(init)):.6g}"


# Coupled-constraint families (plan §3.3).  Membership is inferred from name.
_TEMPERATURE_GROUP_NAMES = {"TB", "TO1", "TO2", "TM",
                            "TB1", "TO11", "TO21", "TM1",
                            "TB2", "TO12", "TO22", "TM2",
                            "TB3", "TO13", "TO23", "TM3"}
_PARTITION_PAIR_NAMES = {"XMAGE", "XFPHT"}


def _coupled_constraint(name: str) -> str:
    """Return the coupled-constraint label for *name*, or '' if independent."""
    if name in _TEMPERATURE_GROUP_NAMES:
        return "cardinal_temperature_ordering (TB<TO1<TO2<TM)"
    if name in _PARTITION_PAIR_NAMES:
        return "partition_ordering (XMAGE<XFPHT)"
    return ""


def _physical_constraint(name: str, evidence: str) -> str:
    """Return an explicit numerical/physical safety constraint, if documented."""
    if name.upper() == "XFINT":
        return "0.12<=XFINT<=0.50 (IPDMND numerical-safety envelope)"
    lowered = evidence.lower()
    safety_terms = (
        "physical", "numerical", "safety", "stability", "valid regime",
        "missing anthesis", "anthesis=-99", "forward check",
    )
    if any(term in lowered for term in safety_terms):
        return evidence
    return ""


def _boundary_risk(name: str, lower: float, upper: float, evidence: str) -> str:
    """Flag parameters whose range sits at a known numerical-safety edge.

    This is a *flag*, not a verdict: it surfaces parameters worth a second
    look.  Empty string means no flag raised.
    """
    risks: list[str] = []
    ev = evidence.lower()
    if "missing anthesis" in ev or "anthesis=-99" in ev or "valid regime" in ev:
        risks.append("anthesis_validity_edge")
    if "xfint" in name.lower() and (lower <= 0.12 or upper >= 0.50):
        # XFINT constrained to 0.12–0.50 to avoid IPDMND risk (AGENTS.md).
        risks.append("ipdmnd_risk_edge")
    if upper - lower <= 0:
        risks.append("degenerate_range")
    return "; ".join(risks)


def _range_review_status(source_type: str, evidence: str, boundary_risk: str) -> str:
    """Conservative review-status label.

    * ``ok_documented`` — source is literature/physical/trial/calibration;
    * ``needs_per_parameter_review`` — engineering-assumption fallback;
    * ``flagged_boundary_risk`` — a numerical-safety edge was detected.
    """
    if boundary_risk:
        return "flagged_boundary_risk"
    if source_type == "engineering_assumption":
        return "needs_per_parameter_review"
    return "ok_documented"


def build_range_audit(bounds_path: str | Path) -> list[dict[str, str]]:
    """Build the range-audit rows from a frozen bounds CSV (active params only)."""
    rows = read_frozen_bounds(bounds_path)
    active = [r for r in rows if r.status == "active"]
    if len(active) != EXPECTED_ACTIVE_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_ACTIVE_COUNT} active parameters, got {len(active)}; "
            f"the audit targets the main v4 SA space only."
        )

    out: list[dict[str, str]] = []
    for r in active:
        try:
            lower = float(r.lower)
            upper = float(r.upper)
            init = float(r.init)
        except ValueError:
            lower = upper = init = float("nan")
        source_type, source_ref = _infer_source_type(r.evidence_basis, r.decision_role)
        boundary_risk = _boundary_risk(r.name, lower, upper, r.evidence_basis)
        out.append({
            "parameter": r.name,
            "lower": r.lower,
            "init": r.init,
            "upper": r.upper,
            "source_type": source_type,
            "source_reference": source_ref,
            "relative_half_width": _relative_half_width(lower, upper, init),
            "physical_constraint": _physical_constraint(r.name, r.evidence_basis),
            "coupled_constraint": _coupled_constraint(r.name),
            "boundary_risk": boundary_risk,
            "range_review_status": _range_review_status(source_type, r.evidence_basis, boundary_risk),
        })
    out.sort(key=lambda d: d["parameter"])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate parameter_range_audit.csv (W1, plan §3.3/§10)."
    )
    parser.add_argument(
        "--bounds",
        default=str(PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen"
                    / "eggplant" / V4_FROZEN_BOUNDS_FILENAME),
        help="Frozen bounds CSV (default: the v4 main SA bounds).",
    )
    parser.add_argument(
        "--out",
        default=str(PROJECT_ROOT / "workspace" / "sa" / "contract"
                    / "parameter_range_audit.csv"),
        help="Output CSV path.",
    )
    args = parser.parse_args(argv)

    try:
        rows = build_range_audit(args.bounds)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    bounds_sha = sha256_file(args.bounds)
    meta = git_metadata()
    from collections import Counter
    source_counts = Counter(r["source_type"] for r in rows)
    status_counts = Counter(r["range_review_status"] for r in rows)
    print(f"parameter_range_audit.csv written: {out_path}")
    print(f"  active parameters audited: {len(rows)}")
    print(f"  by source_type:")
    for st, n in source_counts.most_common():
        print(f"    {st}: {n}")
    print(f"  by range_review_status:")
    for st, n in status_counts.most_common():
        print(f"    {st}: {n}")
    flagged = [r["parameter"] for r in rows if r["boundary_risk"]]
    if flagged:
        print(f"  flagged boundary_risk: {flagged}")
    print(f"  source bounds: {Path(args.bounds).name} (sha256 {bounds_sha[:12]}…)")
    print(f"  git: {meta.get('git_commit', '?')[:12]} dirty={meta.get('git_dirty', '?')}")
    print("  NOTE: read-only — frozen bounds were not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
