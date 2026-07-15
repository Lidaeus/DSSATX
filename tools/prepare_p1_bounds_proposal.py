"""Prepare a review-only P1 proposal from the V14 design bounds.

This tool does not freeze or approve bounds. It applies only the decisions
already accepted for P1 preparation: SOIL/IC remain fixed, and temperature
ranges must preserve DSSAT stage ordering for every sampled combination.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.param_registry import assert_valid_frozen_bounds
from src.common.project import sha256_file


DEFAULT_SOURCE = (
    PROJECT_ROOT
    / "data"
    / "parameter_registry"
    / "bounds_proposals"
    / "eggplant"
    / "proposal_from_sa_v14.csv"
)

TEMPERATURE_RANGES = {
    **{name: (8.0, 12.0) for name in ("TB1", "TB2", "TB3")},
    **{name: (22.0, 27.5) for name in ("TO11", "TO12", "TO13")},
    **{name: (28.0, 32.0) for name in ("TO21", "TO22", "TO23")},
    "TM1": (33.0, 41.0),
    "TM2": (33.0, 40.0),
    "TM3": (33.0, 41.0),
}

STAGE_RANGES = {
    "XMAGE": (5.0, 20.0),
    "XFPHT": (25.0, 40.0),
}


def prepare_proposal(source: str | Path, destination: str | Path) -> tuple[Path, Path, Path]:
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"V14 design proposal not found: {source_path}")
    frame = pd.read_csv(source_path)
    required = {
        "name", "init", "lower", "upper", "status", "pargp", "location",
        "file", "cultivar", "ecotype", "mode",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Source proposal missing columns: {sorted(missing)}")

    output = frame.copy()
    output["name"] = output["name"].astype(str).str.strip().str.upper()
    output["location"] = output["location"].astype(str).str.strip().str.upper()
    output["review_note"] = "retained from V14 design; requires user review"
    changes: list[dict[str, object]] = []

    def record_change(index: int, reason: str, **updates: object) -> None:
        before = output.loc[index].copy()
        for column, value in updates.items():
            output.at[index, column] = value
        after = output.loc[index]
        changes.append(
            {
                "name": after["name"],
                "reason": reason,
                "old_status": before["status"],
                "new_status": after["status"],
                "old_lower": before["lower"],
                "new_lower": after["lower"],
                "old_upper": before["upper"],
                "new_upper": after["upper"],
                "old_mode": before["mode"],
                "new_mode": after["mode"],
            }
        )

    invalid_mode = output["mode"].astype(str).str.strip().str.lower() != "both"
    for index in output.index[invalid_mode]:
        record_change(
            index,
            "Normalize malformed V14 mode label to the reviewed shared SA context",
            mode="both",
            review_note="V14 mode label normalized; requires user review",
        )

    nuisance = output["location"].isin({"SOIL", "IC", "INIT"})
    for index in output.index[nuisance]:
        initial = float(output.at[index, "init"])
        record_change(
            index,
            "SOIL/IC fixed by default for P1; release requires separate evidence and approval",
            status="fixed",
            lower=initial,
            upper=initial,
            review_note="P1 default fixed; interface testing does not authorize calibration",
        )

    for name, (lower, upper) in TEMPERATURE_RANGES.items():
        matches = output.index[output["name"] == name]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one V14 temperature parameter {name}, found {len(matches)}")
        index = int(matches[0])
        initial = float(output.at[index, "init"])
        if not lower <= initial <= upper:
            raise ValueError(f"V14 initial value for {name}={initial:g} not in proposed range [{lower:g}, {upper:g}]")
        record_change(
            index,
            "Ranges separated so all independent Morris samples preserve TB < TO1 < TO2 < TM",
            lower=lower,
            upper=upper,
            review_note="P1 ordered temperature range; requires user review",
        )

    for name, (lower, upper) in STAGE_RANGES.items():
        matches = output.index[output["name"] == name]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one V14 stage parameter {name}, found {len(matches)}")
        index = int(matches[0])
        initial = float(output.at[index, "init"])
        if not lower <= initial <= upper:
            raise ValueError(f"V14 initial value for {name}={initial:g} not in proposed range [{lower:g}, {upper:g}]")
        record_change(
            index,
            "Ranges separated so all independent Morris samples preserve XMAGE < XFPHT",
            lower=lower,
            upper=upper,
            review_note="P1 ordered stage range; requires user review",
        )

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(destination_path, index=False, encoding="utf-8-sig")
    assert_valid_frozen_bounds(destination_path)

    audit_path = destination_path.with_name(f"{destination_path.stem}.audit.csv")
    pd.DataFrame(changes).to_csv(audit_path, index=False, encoding="utf-8-sig")
    metadata_path = destination_path.with_suffix(".yaml")
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata_path.write_text(
        "\n".join(
            [
                f'proposal_id: "{destination_path.stem}"',
                'crop: "eggplant"',
                f'created_at: "{created_at}"',
                'review_status: "pending"',
                f'derived_from: "{source_path.name}"',
                f'derived_from_sha256: "{sha256_file(source_path)}"',
                f'proposal_sha256: "{sha256_file(destination_path)}"',
                f"parameter_count: {len(output)}",
                f"active_parameter_count: {(output['status'].str.lower() == 'active').sum()}",
                f"fixed_nuisance_count: {nuisance.sum()}",
                'automatic_repairs: 0',
                'notes: "Review-only P1 candidate; not a frozen calibration input"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return destination_path, audit_path, metadata_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a pending P1 bounds proposal from V14 design ranges")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    destination = Path(args.out).resolve()
    if destination.exists() or destination.with_suffix(".yaml").exists():
        parser.error(f"Refusing to overwrite an existing proposal: {destination}")
    proposal, audit, metadata = prepare_proposal(args.source, destination)
    print(f"Proposal: {proposal}")
    print(f"Audit: {audit}")
    print(f"Metadata: {metadata}")
    print("Status: pending user review; not frozen and not authorized for formal P1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
