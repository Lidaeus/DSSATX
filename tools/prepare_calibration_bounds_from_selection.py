"""Prepare (never freeze) a calibration-bounds proposal from an SA selection.

Selected parameters retain their reviewed source ranges.  Other adjustable
parameters are fixed at their source initial values.  Disabled environmental
or treatment-specific rows remain disabled.  The command refuses to overwrite
an existing proposal and never starts DSSAT/PEST++.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.param_registry import assert_valid_frozen_bounds
from src.common.project import sha256_file


def build_proposal(
    source_bounds: str | Path,
    selection_csv: str | Path,
    output_csv: str | Path,
    *,
    allow_provisional_selection: bool = False,
) -> pd.DataFrame:
    source = Path(source_bounds).resolve()
    selection_path = Path(selection_csv).resolve()
    output = Path(output_csv).resolve()
    if output.exists() or output.with_suffix(".yaml").exists():
        raise FileExistsError(f"refusing to overwrite existing proposal: {output}")

    frame = pd.read_csv(source, encoding="utf-8-sig")
    selection = pd.read_csv(selection_path, encoding="utf-8-sig")
    required = {"parameter", "evidence_status"}
    missing = required - set(selection.columns)
    if missing:
        raise ValueError(f"selection is missing columns: {sorted(missing)}")
    statuses = sorted(set(selection["evidence_status"].astype(str).str.strip()))
    if statuses != ["science_validated"] and not allow_provisional_selection:
        raise ValueError(
            f"selection evidence is not science_validated ({statuses}); "
            "pass --allow-provisional-selection for a review-only proposal"
        )
    selected = set(selection["parameter"].astype(str).str.strip().str.upper())
    available = set(frame["name"].astype(str).str.strip().str.upper())
    absent = sorted(selected - available)
    if absent:
        raise ValueError(f"selected parameters are absent from source bounds: {absent}")

    names = frame["name"].astype(str).str.strip().str.upper()
    originally_active = frame["status"].astype(str).str.lower().eq("active")
    selected_mask = names.isin(selected)
    if not selected_mask.sum() == len(selected):
        raise ValueError("selection contains duplicate or ambiguous parameter names")
    not_adjustable = selected_mask & ~originally_active
    if not_adjustable.any():
        raise ValueError(
            "selected parameters are not active in source bounds: "
            f"{sorted(names.loc[not_adjustable].tolist())}"
        )

    # Only source-active rows are changed. Existing fixed structural constants
    # and disabled IC rows preserve their semantics exactly.
    fix_mask = originally_active & ~selected_mask
    frame.loc[fix_mask, "status"] = "fixed"
    frame.loc[fix_mask, "lower"] = frame.loc[fix_mask, "init"]
    frame.loc[fix_mask, "upper"] = frame.loc[fix_mask, "init"]
    frame.loc[selected_mask, "status"] = "active"
    if "decision_role" not in frame:
        frame["decision_role"] = ""
    if "evidence_basis" not in frame:
        frame["evidence_basis"] = ""
    frame.loc[selected_mask, "decision_role"] = "t7_dual_domain_90pct_candidate"
    frame.loc[fix_mask, "decision_role"] = "fixed_outside_t7_90pct_union"
    frame.loc[selected_mask, "evidence_basis"] = (
        "Selected by per-domain 90% cumulative contribution after applicability screening; "
        "identifiability and bounds still require review"
    )
    frame.loc[fix_mask, "evidence_basis"] = (
        "Fixed because parameter is outside the approved T7 90% union or is inapplicable"
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, encoding="utf-8-sig")
    assert_valid_frozen_bounds(output)
    metadata = [
        f'proposal_id: "{output.stem}"',
        'crop: "eggplant"',
        f'created_at: "{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}"',
        'review_status: "proposed"',
        'ready_for_formal_run: false',
        f'derived_from_bounds: "{source.name}"',
        f'derived_from_bounds_sha256: "{sha256_file(source)}"',
        f'selection_csv: "{selection_path.name}"',
        f'selection_sha256: "{sha256_file(selection_path)}"',
        f'selection_evidence_status: "{";".join(statuses)}"',
        f'proposal_sha256: "{sha256_file(output)}"',
        f'parameter_count: {len(frame)}',
        f'active_parameter_count: {int(selected_mask.sum())}',
        'automatic_bound_changes: 0',
        'notes: "Selected ranges are inherited unchanged; non-selected active rows are fixed at source init; user review required before freeze"',
        "",
    ]
    output.with_suffix(".yaml").write_text("\n".join(metadata), encoding="utf-8")
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bounds", required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--allow-provisional-selection", action="store_true")
    args = parser.parse_args(argv)
    frame = build_proposal(
        args.source_bounds,
        args.selection,
        args.out,
        allow_provisional_selection=args.allow_provisional_selection,
    )
    print(f"proposal={Path(args.out).resolve()}")
    print(f"active={int(frame['status'].astype(str).str.lower().eq('active').sum())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
