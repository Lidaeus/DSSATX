"""Compose a frozen-bounds CSV from selected parameter modules.

CLI entry point for the modular parameter system.  Selects one or more
parameter modules (from ``configs/sa/parameter_modules/``), composes them
with the existing v4 baseline (optional), validates constraints, and writes
a proposal CSV ready for ``freeze_bounds.py`` promotion.

Usage::

    # All 11 modules + v4 baseline
    python tools/sa/compose_parameter_bounds.py \\
        --out data/parameter_registry/bounds_proposals/eggplant/full_v1.csv

    # Only leaf senescence + fruit growth modules (no v4 baseline)
    python tools/sa/compose_parameter_bounds.py \\
        --modules leaf_senescence,fruit_growth \\
        --no-v4-baseline \\
        --out workspace/sa/composed_test.csv

    # List available modules
    python tools/sa/compose_parameter_bounds.py --list
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
from src.common.parameter_modules import (
    MODULES_DIR,
    ParameterModuleError,
    compose_bounds,
    load_all_modules,
)


BOUNDS_COLUMNS = [
    "name", "init", "lower", "upper", "status", "pargp", "location", "file",
    "cultivar", "ecotype", "mode", "review_note", "decision_role", "evidence_basis",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compose a frozen-bounds CSV from parameter modules."
    )
    parser.add_argument("--modules", default=None,
                        help="Comma-separated module IDs (default: all). "
                             "Use --list to see available modules.")
    parser.add_argument("--out", required=False,
                        help="Output CSV path (required unless --list).")
    parser.add_argument("--no-v4-baseline", action="store_true",
                        help="Exclude the existing v4 55-parameter baseline.")
    parser.add_argument("--baseline-bounds", default=None,
                        help="Baseline frozen bounds CSV to extend from. "
                             "Required unless --no-v4-baseline is set.")
    parser.add_argument("--v4-bounds", default=None,
                        help="Deprecated alias of --baseline-bounds.")
    parser.add_argument("--status-for-new", default="active",
                        help="Status for newly-added parameters (default: active). "
                             "Use 'fixed' to add as fixed candidates.")
    parser.add_argument("--activate", default=None,
                        help="Comma-separated parameter names to force active after composition.")
    parser.add_argument("--fix", default=None,
                        help="Comma-separated parameter names to force fixed after composition.")
    parser.add_argument("--list", action="store_true",
                        help="List available modules and exit.")
    parser.add_argument("--check-only", action="store_true",
                        help="Validate constraints without writing output.")
    args = parser.parse_args(argv)
    baseline_bounds = args.baseline_bounds or args.v4_bounds
    activate_parameters = [p.strip() for p in (args.activate or "").split(",") if p.strip()]
    fix_parameters = [p.strip() for p in (args.fix or "").split(",") if p.strip()]

    # --list mode
    if args.list:
        modules = load_all_modules()
        print(f"Available modules ({len(modules)}) in {MODULES_DIR}:")
        for mid, mod in sorted(modules.items()):
            new = sum(1 for p in mod.parameters if not p.existing_v4)
            print(f"  {mid:30} | {mod.priority:12} | "
                  f"{len(mod.parameters):2} params ({new} new) | "
                  f"{mod.display_name_zh} / {mod.display_name_en}")
        return 0

    # Determine module selection
    all_modules = load_all_modules()
    if args.modules:
        module_ids = [m.strip() for m in args.modules.split(",") if m.strip()]
        unknown = [m for m in module_ids if m not in all_modules]
        if unknown:
            print(f"ERROR: unknown modules: {unknown}", file=sys.stderr)
            print(f"Available: {sorted(all_modules.keys())}", file=sys.stderr)
            return 2
    else:
        module_ids = list(all_modules.keys())

    if not args.no_v4_baseline and not baseline_bounds:
        print(
            "ERROR: --baseline-bounds is required when extending an existing bounds "
            "domain; this avoids silently falling back to a historical v4 file",
            file=sys.stderr,
        )
        return 2

    # Compose
    try:
        rows, issues = compose_bounds(
            module_ids,
            include_existing_v4=not args.no_v4_baseline,
            v4_bounds_path=baseline_bounds,
            status_for_new=args.status_for_new,
            activate_parameters=activate_parameters,
            fix_parameters=fix_parameters,
        )
    except ParameterModuleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # Report constraint issues
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    print(f"Composed bounds: {len(rows)} parameters from {len(module_ids)} modules")
    print(f"  constraint errors: {len(errors)}")
    for e in errors:
        print(f"    ERROR: {e.message}")
    print(f"  constraint warnings: {len(warnings)}")
    for w in warnings:
        print(f"    WARN: {w.message}")

    if errors and not args.check_only:
        print("\n  NOTE: Constraint errors detected. The proposal is still written,")
        print("  but it must be corrected before freeze_bounds.py promotion.")

    if args.check_only:
        return 1 if errors else 0

    # Write output
    if not args.out:
        print("ERROR: --out is required (or use --check-only / --list)", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=BOUNDS_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in BOUNDS_COLUMNS})

    meta = git_metadata()
    print(f"\nProposal written: {out_path}")
    print(f"  rows: {len(rows)}")
    new_count = sum(1 for r in rows if "module_" in str(r.get("pargp", "")))
    print(f"  new (from modules): {new_count}")
    print(f"  from v4 baseline: {len(rows) - new_count}")
    print(f"  sha256: {sha256_file(out_path)[:16]}…")
    print(f"  git: {meta.get('git_commit', '?')[:12]} dirty={meta.get('git_dirty', '?')}")
    print(f"  NOTE: This is a proposal, not a frozen bounds file.")
    print(f"  Promote via: python tools/freeze_bounds.py "
          f"--proposal {out_path} --crop eggplant --bounds-id <id>")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
