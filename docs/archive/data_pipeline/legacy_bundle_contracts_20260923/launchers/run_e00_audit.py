#!/usr/bin/env python
"""CLI: run the E00 input/observation/parameter-set freeze audit.

E00 is a read-only audit that runs **before** any calibration.  It verifies
input manifests, CHPDT harvest alignment, parameter profiles, and frozen
bounds, producing ``E00_audit_receipt.json`` and ``E00_harvest_alignment_audit.csv``.

Usage::

    python tools/calibration/run_e00_audit.py \\
        --spec configs/experiments/specs/E00_input_audit.json \\
        --out-dir workspace/runs/E00_audit
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.e00_audit import run_e00_audit
from src.calibration.experiment_spec import ExperimentSpecError


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the E00 input/observation/parameter freeze audit.")
    parser.add_argument(
        "--spec",
        default="configs/experiments/specs/E00_input_audit.json",
        help="Path to the E00 experiment spec JSON.",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory for the audit receipt and alignment CSV.",
    )
    args = parser.parse_args()

    print(f"[E00] Running input/observation/parameter-set freeze audit...")
    print(f"  spec: {args.spec}")
    try:
        receipt = run_e00_audit(args.spec, args.out_dir)
    except ExperimentSpecError as exc:
        print(f"FAILED: spec contract violation: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"FAILED: file not found: {exc}", file=sys.stderr)
        return 2

    print(f"\n[E00] Audit status: {receipt['status'].upper()}")
    print(f"  seasons: {receipt['seasons']}")
    print(f"  bounds: {receipt['bounds_id']} (sha {receipt['bounds_sha256'][:12]}…)")
    print(f"  findings: {receipt['n_findings_total']} total, {receipt['n_findings_failed']} failed")
    print(f"  harvest alignment rows: {receipt['harvest_alignment_rows']}")
    print(f"  receipt: {Path(args.out_dir) / 'E00_audit_receipt.json'}")
    if receipt['harvest_alignment_csv']:
        print(f"  alignment CSV: {receipt['harvest_alignment_csv']}")

    if receipt["status"] == "fail":
        print("\n  FAILED findings:")
        for f in receipt["findings"]:
            if f["status"] == "fail":
                print(f"    - [{f['check']}] {f['detail']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
