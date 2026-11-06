#!/usr/bin/env python3
"""Command-line utility to post-process DSSAT run outputs and generate PestCNC.OUT.

Usage:
    python -m subprojects.critical_n.scripts.run_cnc_postprocessor \
        --run-dir scratch/test_0.5 \
        --out-file scratch/test_0.5/PestCNC.OUT
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from subprojects.critical_n.adapters.pest_cnc_exporter import export_pest_cnc
from subprojects.critical_n.core.dilution_curve import (
    DEFAULT_CNC_A,
    DEFAULT_CNC_B,
    DEFAULT_CNC_NC_INF,
    DEFAULT_CNC_W0,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract DSSAT growth & N states, compute cumulative NNI, and write PestCNC.OUT."
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        required=True,
        help="Path to DSSAT run directory containing PlantGro.OUT, PlantN.OUT, FreshWt.OUT",
    )
    parser.add_argument(
        "--out-file",
        type=str,
        default=None,
        help="Target output path (default: <run-dir>/PestCNC.OUT)",
    )
    parser.add_argument(
        "--cnc-a",
        type=float,
        default=DEFAULT_CNC_A,
        help=f"Critical N concentration at W <= W0 (default: {DEFAULT_CNC_A})",
    )
    parser.add_argument(
        "--cnc-b",
        type=float,
        default=DEFAULT_CNC_B,
        help=f"Dilution curve exponent (default: {DEFAULT_CNC_B})",
    )
    parser.add_argument(
        "--cnc-w0",
        type=float,
        default=DEFAULT_CNC_W0,
        help=f"Biomass dilution threshold in t DM/ha (default: {DEFAULT_CNC_W0})",
    )
    parser.add_argument(
        "--cnc-nc-inf",
        type=float,
        default=DEFAULT_CNC_NC_INF,
        help=f"Asymptotic lower-bound nitrogen concentration (default: {DEFAULT_CNC_NC_INF})",
    )
    parser.add_argument(
        "--fruit-n-pct",
        type=float,
        default=1.78,
        help="Fruit dry basis N percentage (default: 1.78)",
    )
    parser.add_argument(
        "--include-r-tol",
        action="store_true",
        help="Include R_TOL relaxed Pseudo-Huber residual column (default: False)",
    )
    parser.add_argument(
        "--strict-treatment-mapping",
        action="store_true",
        help="Raise error if a treatment has no N level mapping (default: False)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"Error: run directory does not exist: {run_dir}", file=sys.stderr)
        return 1

    try:
        out_path = export_pest_cnc(
            run_dir=run_dir,
            out_file=args.out_file,
            cnc_a=args.cnc_a,
            cnc_b=args.cnc_b,
            cnc_w0=args.cnc_w0,
            cnc_nc_inf=args.cnc_nc_inf,
            default_fruit_n_pct=args.fruit_n_pct,
            include_r_tol=args.include_r_tol,
            strict_treatment_mapping=args.strict_treatment_mapping,
        )
        line_count = len(out_path.read_text(encoding="utf-8").splitlines())
        print(f"Successfully generated {out_path} ({line_count} lines)")
        return 0
    except Exception as exc:
        print(f"Error exporting PestCNC.OUT: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
