"""CLI entry point for the v2 formal two-spring NSGA-III water--nitrogen search.

Examples
--------
Engineering precheck (uses a non-science-validated parameter snapshot)::

    python tools/run_formal_optimization.py \\
        --design configs/management/eggplant_greenhouse_drip_formal_v2.json \\
        --parameter-set-dir workspace/runs/<run_id>/parameter_set \\
        --work-root workspace/runs/<run_id>/management_v2 \\
        --allow-engineering-precheck --generations 3 --population-size 56

Formal run (blocked until the parameter set is science_validated)::

    python tools/run_formal_optimization.py \\
        --design configs/management/eggplant_greenhouse_drip_formal_v2.json \\
        --parameter-set-dir <frozen_validated_parameter_set_dir> \\
        --work-root workspace/runs/<run_id>/management_v2_formal
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as a script from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.management.robust_orchestrator import run_formal_nsga3


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the v2 two-spring direct-DSSAT NSGA-III water--nitrogen search."
    )
    parser.add_argument(
        "--design",
        default="configs/management/eggplant_greenhouse_drip_formal_v2.json",
        help="Path to the v2 formal design JSON.",
    )
    parser.add_argument(
        "--parameter-set-dir",
        required=True,
        help="Directory containing parameter_set_manifest.json and parameters.csv.",
    )
    parser.add_argument(
        "--work-root",
        required=True,
        help="Output directory for the NSGA-III run (Pareto CSVs + manifest).",
    )
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=None,
        help="Optimizer seeds (defaults to the design's independent_seeds).",
    )
    parser.add_argument(
        "--generations",
        type=int,
        default=None,
        help="NSGA-III generations (defaults to the design).",
    )
    parser.add_argument(
        "--population-size",
        type=int,
        default=None,
        help="NSGA-III population size (defaults to the design).",
    )
    parser.add_argument(
        "--initial-candidates",
        type=int,
        default=None,
        help="Number of maximin-LHS initial candidates (defaults to the design).",
    )
    parser.add_argument(
        "--allow-engineering-precheck",
        action="store_true",
        help="Permit a non-citable engineering precheck on a non-validated parameter set.",
    )
    args = parser.parse_args()

    manifest = run_formal_nsga3(
        design_path=args.design,
        parameter_set_dir=args.parameter_set_dir,
        work_root=args.work_root,
        seeds=args.seeds,
        allow_engineering_precheck=args.allow_engineering_precheck,
        generations=args.generations,
        population_size=args.population_size,
        initial_candidates=args.initial_candidates,
    )
    print(json.dumps({k: v for k, v in manifest.items() if k != "per_seed_outputs"}, ensure_ascii=True, indent=2))
    print(f"Per-seed Pareto CSVs: {len(manifest['per_seed_outputs'])} written under {args.work_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
