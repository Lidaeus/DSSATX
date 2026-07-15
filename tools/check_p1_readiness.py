"""Write and enforce the bounds portion of the formal P1 preflight."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.sensitivity.p1_readiness import assess_p1_bounds


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether parameter bounds are ready for formal P1 SA")
    parser.add_argument("--bounds", required=True)
    parser.add_argument("--metadata", default=None)
    parser.add_argument("--max-active", type=int, default=60)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--technical-only", action="store_true")
    args = parser.parse_args()

    bounds = Path(args.bounds).resolve()
    report = assess_p1_bounds(
        bounds,
        metadata_path=args.metadata,
        max_active_parameters=args.max_active,
        require_approval=not args.technical_only,
    )
    output = Path(args.out_dir).resolve() if args.out_dir else bounds.parent
    json_path, md_path = report.write(output, stem=f"{bounds.stem}.p1_readiness")
    print(f"P1 bounds readiness: {report.status}")
    print(f"Science validated: {report.science_validated}")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    if not report.science_validated:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
