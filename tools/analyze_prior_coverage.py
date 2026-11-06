"""Create an auditable prior-data coverage report from a PEST++ PDC file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.prior_coverage import write_prior_coverage_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--pdc", default=None, help="Explicit PDC CSV; defaults to latest iteration PDC")
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    pdc = Path(args.pdc) if args.pdc else None
    if pdc is None:
        files = sorted(
            list(run_dir.glob(f"{args.prefix}.*.pdc.csv"))
            + list(run_dir.glob(f"{args.prefix}pdc.csv"))
        )
        if not files:
            raise FileNotFoundError("no PEST++ PDC CSV found")
        pdc = files[-1]
    audit = run_dir / f"{args.prefix}.weights.audit.csv"
    if not audit.is_file():
        # Compatibility with pre-contract runs, where PEST++ could overwrite
        # the policy audit after startup.
        audit = run_dir / f"{args.prefix}.weights.csv"
    out_dir = Path(args.out_dir) if args.out_dir else run_dir / "prior_coverage"
    report = write_prior_coverage_report(pdc, audit, out_dir)
    print(f"Prior coverage report written to {out_dir}")
    print(f"Conflict fraction: {report['conflict_fraction']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
