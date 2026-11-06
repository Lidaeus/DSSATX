"""CLI compatibility entry point for the approval-gated Sobol case builder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from src.common.project import PROJECT_ROOT
from src.sensitivity.sobol_case import build_sobol_case


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an isolated approved Top-K Sobol case")
    parser.add_argument("--bounds", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--output-profile", required=True)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--samples", required=True, type=int)
    parser.add_argument("--random-seed", required=True, type=int)
    parser.add_argument(
        "--run-type",
        choices=("sensitivity_sobol_preflight_case", "sensitivity_sobol_formal_case"),
        default="sensitivity_sobol_preflight_case",
    )
    parser.add_argument("--cultivar", default="TM0008")
    args = parser.parse_args()
    result = build_sobol_case(
        bounds_csv=args.bounds,
        approval_json=args.approval,
        case_dir=args.case_dir,
        workspace_dir=PROJECT_ROOT,
        output_profile=args.output_profile,
        input_dir=args.input_dir,
        samples=args.samples,
        random_seed=args.random_seed,
        run_type=args.run_type,
        cultivar=args.cultivar,
    )
    print(f"Wrote: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
