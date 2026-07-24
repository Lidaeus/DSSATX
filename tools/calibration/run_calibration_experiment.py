#!/usr/bin/env python
"""CLI entry point for calibration experiments.

Usage::

    # Build-only (validate spec, write receipt, generate PST)
    python tools/calibration/run_calibration_experiment.py \\
        --spec configs/experiments/specs/E04_joint55_25sp_25fa.json \\
        --run-dir workspace/runs/E04_smoke \\
        --smoke

    # Full execution (after P0-C removes global state)
    python tools/calibration/run_calibration_experiment.py \\
        --spec configs/experiments/specs/E04_joint55_25sp_25fa.json \\
        --run-dir workspace/runs/E04_formal \\
        --execute

This entry point does **not** modify global state or call legacy modes.
It delegates to :mod:`src.calibration.experiment_runner` for spec validation
and receipt generation, then to the existing builder for PST generation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure src/ is importable
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.experiment_runner import prepare_experiment_run, run_build
from src.calibration.experiment_spec import ExperimentSpecError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a calibration experiment from a spec JSON."
    )
    parser.add_argument(
        "--spec",
        required=True,
        help="Path to the experiment spec JSON file.",
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Target run directory (will be created if absent).",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Override to 20 realisations / 1 update for interface smoke testing.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="After building, launch PEST++ execution (requires P0-C completion).",
    )
    parser.add_argument(
        "--build-only",
        action="store_true",
        default=True,
        help="Only validate spec, write receipt, and generate PST (default).",
    )

    args = parser.parse_args()

    # Step 1: Load spec, validate contract, write receipt
    print(f"[1/3] Loading experiment spec: {args.spec}")
    try:
        result = prepare_experiment_run(
            spec_path=args.spec,
            run_dir=args.run_dir,
            smoke=args.smoke,
        )
    except ExperimentSpecError as exc:
        print(f"FAILED: Spec contract violation: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"FAILED: File not found: {exc}", file=sys.stderr)
        return 2

    print(f"  experiment_id: {result.experiment_id}")
    print(f"  run_dir: {result.run_dir}")
    print(f"  receipt: {result.receipt_path}")
    print(f"  parameter_set: {result.spec.parameter_set.set_id} "
          f"({result.spec.parameter_set.declared_count} params)")
    print(f"  bounds: {result.spec.bounds_id} "
          f"({result.spec.bounds_active_count} active)")
    print(f"  observation_profile: {result.spec.observation_profile.profile_id}")
    print(f"  active_phi_targets: "
          f"{list(result.spec.observation_profile.active_phi_targets)}")
    print(f"  seasons: "
          f"{[(s.season_id, s.role) for s in result.spec.season_inputs]}")
    print(f"  execution: {result.spec.execution.ies_num_reals} reals / "
          f"{result.spec.execution.noptmax} updates "
          f"(seed={result.spec.execution.seed})")
    if args.smoke:
        print("  [SMOKE MODE] 20 reals / 1 update")

    # Step 2: Build PST (delegate to existing builder via subprocess)
    print(f"\n[2/3] Building PST via build_pest.py...")
    try:
        run_build(result.spec, result.run_dir, prefix=result.experiment_id)
    except ValueError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 3
    pst_path = result.run_dir / f"{result.experiment_id}.pst"
    if pst_path.is_file():
        print(f"  PST generated: {pst_path}")
    else:
        print(f"  WARNING: expected PST not found at {pst_path}", file=sys.stderr)

    # Step 3: Execute (optional)
    if args.execute:
        print(f"\n[3/3] Launching PEST++ execution...")
        print("  NOTE: Full execution requires P0-C (global state removal).")
        print("  The existing run_parallel.py / run_multiseason.py can be")
        print("  invoked with the prepared run_dir once P0-C is complete.")
        # TODO: After P0-C, delegate to run_parallel.py with the prepared args
        return 0
    else:
        print(f"\n[3/3] Build-only mode complete.")
        print(f"  Receipt: {result.receipt_path}")
        print(f"  PST: {pst_path}")
        print("  To execute: add --execute flag (requires P0-C completion)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
