"""Promote an explicitly approved bounds proposal to a frozen bounds ID."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.param_registry import assert_valid_frozen_bounds
from src.common.project import sha256_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve a validated bounds proposal as a frozen bounds ID")
    parser.add_argument("--proposal", required=True, help="Reviewed proposal CSV")
    parser.add_argument("--crop", required=True, help="Crop name, for example tomato or eggplant")
    parser.add_argument("--bounds-id", required=True, help="Unique frozen bounds ID")
    parser.add_argument("--notes", default="", help="Approval notes")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--operator", default=os.environ.get("USERNAME", "unknown"))
    args = parser.parse_args()

    proposal = Path(args.proposal).resolve()
    if not proposal.is_file():
        parser.error(f"Proposal file does not exist: {proposal}")

    # Approval must never mutate, clamp, swap, or otherwise repair the proposal.
    issues = assert_valid_frozen_bounds(proposal)
    for warning in (issue for issue in issues if issue.severity == "warning"):
        print(f"WARNING: {warning.message}")

    with proposal.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames or []
    if not rows:
        parser.error("Proposal CSV is empty")

    output_dir = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / args.crop
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    frozen_csv = output_dir / f"{args.bounds_id}.csv"
    metadata = output_dir / f"{args.bounds_id}.yaml"
    if frozen_csv.exists() or metadata.exists():
        parser.error(f"Frozen bounds ID already exists: {args.bounds_id}")

    with frozen_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata.write_text(
        "\n".join(
            [
                f'bounds_id: "{args.bounds_id}"',
                f'crop: "{args.crop}"',
                f'created_at: "{created_at}"',
                f'approved_at: "{created_at}"',
                f'approved_by: "{args.operator}"',
                'review_status: "approved"',
                f'derived_from: "{proposal.name}"',
                f'derived_from_sha256: "{sha256_file(proposal)}"',
                f'bounds_sha256: "{sha256_file(frozen_csv)}"',
                f"parameter_count: {len(rows)}",
                'automatic_repairs: 0',
                f'notes: "{args.notes}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Frozen bounds created: {frozen_csv}")
    print(f"Metadata: {metadata}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
