"""Generate and enforce an engineering quality report for a persisted run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.reporting.quality_gate import assess_ies_run


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
    engineering_checks = {
        "process_completed", "ies_ensemble_size", "ies_unique_realizations",
        "ies_parameter_finite", "ies_observation_finite", "ies_realization_alignment",
        "ies_final_realization_alignment", "ies_final_parameter_finite",
        "ies_iteration_progress", "ies_member_status_table",
    }
    engineering_failures = [
        c.check_id for c in report.checks
        if c.check_id in engineering_checks and c.status == "fail"
    ]
    print(f"Engineering status: {'engineering_validated' if not engineering_failures else 'engineering_failed'}")
    print(f"Quality report: {json_path}")
    print(f"Quality summary: {md_path}")
    if not args.allow_fail and engineering_failures:
        raise SystemExit("Engineering quality gate failed: " + ", ".join(engineering_failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
