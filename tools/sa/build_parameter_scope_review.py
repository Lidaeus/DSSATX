"""Generate ``parameter_scope_review.csv`` — the parameter-scope audit table.

Implements W1 of ``docs/敏感性分析方案与图表优化_协作实施计划_20260729.md``
(§3.2, §10 W1).  The table records, for every parameter in the frozen v4
bounds, its current status, scientific role, and a Morris-scope decision:

* ``primary_morris`` — ``include`` (the 55 active parameters),
  ``excluded_forbidden`` (structurally inapplicable, e.g. ``FRCNOD``),
  ``excluded_fixed_by_decision`` (kept fixed by scientific decision),
  ``excluded_disabled`` (out of scope),
  ``excluded_structural_scenario`` (needs a discrete scenario, e.g. ``FL-LF``).
* ``hypothesis_test_decision`` — whether the parameter may enter a future
  hypothesis-test pool (never automatic promotion to Morris).

The tool is **read-only** with respect to frozen bounds: it never modifies
the v4 CSV, never promotes a fixed/disabled parameter, and never writes to
``bounds_frozen/``.  It is a documentation/audit artefact only.

Exit code is non-zero if the frozen bounds fail the main-parameter-space
contract (e.g. active count != 55, or a forbidden parameter is active), so a
CI gate can consume it.
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
    FIXED_BY_DECISION,
    FORBIDDEN_MORRIS_PARAMETERS,
    SAContractError,
    V4_FROZEN_BOUNDS_FILENAME,
    read_frozen_bounds,
    validate_main_parameter_space,
)

# Discrete-structural-scenario parameters: continuous sampling is meaningless
# because they encode growth-habit flags (e.g. 400 = indeterminate).
_STRUCTURAL_SCENARIO_PARAMETERS: frozenset[str] = frozenset({"FL-LF", "SD-PM"})

OUTPUT_COLUMNS = [
    "parameter",
    "current_status",            # active | fixed | disabled
    "scientific_role",           # from frozen bounds decision_role / pargp
    "current_evidence",          # from frozen bounds evidence_basis
    "primary_morris_decision",   # include | excluded_* (see module docstring)
    "hypothesis_test_decision",  # eligible_pool | not_applicable | scenario_only
    "reason",
]


def _scientific_role(row) -> str:
    """Best-available scientific role label from the frozen-bounds metadata."""
    role = (row.decision_role or "").strip()
    if role:
        return role
    # fall back to pargp / location grouping
    return f"{row.pargp}/{row.location}".strip("/")


def _classify(row) -> tuple[str, str, str]:
    """Return ``(primary_morris_decision, hypothesis_test_decision, reason)``."""
    name = row.name
    status = row.status

    if name in _STRUCTURAL_SCENARIO_PARAMETERS:
        return (
            "excluded_structural_scenario",
            "scenario_only",
            f"{name} encodes a discrete growth-habit flag; study as a scenario, not continuous sampling.",
        )
    if name in FORBIDDEN_MORRIS_PARAMETERS:
        kind = (
            "non-legume inapplicable"
            if name == "FRCNOD"
            else "discrete structural flag"
        )
        return (
            "excluded_forbidden",
            "not_applicable",
            f"{name} is {kind}; must never enter main Morris (plan §3.2).",
        )
    if status == "active":
        return (
            "include",
            "eligible_pool",
            "Active in the v4 frozen main SA space.",
        )
    if status == "fixed":
        if name in FIXED_BY_DECISION:
            return (
                "excluded_fixed_by_decision",
                "eligible_pool",
                f"Fixed by decision: {FIXED_BY_DECISION[name]}",
            )
        return (
            "excluded_fixed_by_decision",
            "eligible_pool",
            "Fixed; may enter a future hypothesis-test pool but never auto-promoted to Morris.",
        )
    # disabled
    return (
        "excluded_disabled",
        "not_applicable",
        "Disabled in the frozen bounds; out of the current SA scope.",
    )


def build_scope_review(bounds_path: str | Path) -> list[dict[str, str]]:
    """Build the scope-review rows from a frozen bounds CSV.

    Raises :class:`SAContractError` if the active set violates the contract
    (so callers can gate on it).
    """
    # First enforce the main-space contract (55 active, no forbidden active).
    validate_main_parameter_space(bounds_path)

    rows = read_frozen_bounds(bounds_path)
    out: list[dict[str, str]] = []
    for r in rows:
        morris_dec, hypo_dec, reason = _classify(r)
        out.append({
            "parameter": r.name,
            "current_status": r.status,
            "scientific_role": _scientific_role(r),
            "current_evidence": r.evidence_basis,
            "primary_morris_decision": morris_dec,
            "hypothesis_test_decision": hypo_dec,
            "reason": reason,
        })
    # Stable order: include first (the main space), then by name within each decision.
    decision_order = {
        "include": 0,
        "excluded_fixed_by_decision": 1,
        "excluded_structural_scenario": 2,
        "excluded_disabled": 3,
        "excluded_forbidden": 4,
    }
    out.sort(key=lambda d: (decision_order.get(d["primary_morris_decision"], 9), d["parameter"]))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate parameter_scope_review.csv (W1, plan §3.2/§10)."
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
                    / "parameter_scope_review.csv"),
        help="Output CSV path.",
    )
    args = parser.parse_args(argv)

    try:
        rows = build_scope_review(args.bounds)
    except SAContractError as exc:
        print(f"FAIL: SA contract violation: {exc}", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    bounds_sha = sha256_file(args.bounds)
    meta = git_metadata()
    print(f"parameter_scope_review.csv written: {out_path}")
    print(f"  rows: {len(rows)}")
    from collections import Counter
    decision_counts = Counter(r["primary_morris_decision"] for r in rows)
    for dec, n in sorted(decision_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {dec}: {n}")
    print(f"  source bounds: {Path(args.bounds).name} (sha256 {bounds_sha[:12]}…)")
    print(f"  git: {meta.get('git_commit', '?')[:12]} dirty={meta.get('git_dirty', '?')}")
    print("  NOTE: read-only — frozen bounds were not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
