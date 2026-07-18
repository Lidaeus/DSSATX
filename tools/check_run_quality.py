"""Generate and enforce an engineering quality report for a persisted run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.reporting.quality_gate import assess_ies_run
from src.calibration.engineering_gate import engineering_failures, profile_for_run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--type", choices=["ies"], default="ies")
    parser.add_argument("--allow-fail", action="store_true")
    args = parser.parse_args()

    report = assess_ies_run(args.run_dir, args.prefix)
    json_path, md_path = report.write(args.run_dir)
    print(f"Quality status: {report.status}")
    print(f"Process completed: {report.process_completed}")
    print(f"Science validated: {report.science_validated} (finalize-only authority)")
    profile = profile_for_run(args.run_dir, args.prefix)
    failures = engineering_failures(report, profile)
    print(f"Engineering profile: {profile}")
    print(f"Engineering status: {'engineering_validated' if not failures else 'engineering_failed'}")
    print(f"Quality report: {json_path}")
    print(f"Quality summary: {md_path}")
    if not args.allow_fail and failures:
        raise SystemExit("Engineering quality gate failed: " + ", ".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
