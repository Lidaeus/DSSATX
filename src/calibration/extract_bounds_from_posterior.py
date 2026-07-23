"""Extract a bounds proposal from an IES posterior.

After E01 pre-calibration (55-parameter high-dim), this tool projects the
posterior onto an approved parameter set (e.g. ``sobol23_dryonly_v1``),
computes percentile-based bounds clamped to physical hard limits, and emits a
``bounds_proposal`` CSV ready for :mod:`tools.freeze_bounds` approval.

The proposal is **not** a frozen bounds file.  It must pass human review and
be promoted via ``freeze_bounds.py`` before any downstream calibration
(E02/E03) may consume it.  This module never writes to ``bounds_frozen/``.

pestpp-ies posterior CSV convention (confirmed against
``workspace/runs/eggplant_t10_dryonly_*``): the first column is
``real_name`` and the remaining columns are lower-case parameter names
(e.g. ``em-fl``, ``tb2``).  Matching against the parameter set is
case-insensitive.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

import pandas as pd

from src.common.param_registry import PHYSICAL_BOUNDS, clamp_to_physical


logger = logging.getLogger(__name__)


# Temperature parameter groups that must satisfy strict cardinal ordering:
# TB < TO1 < TO2 < TM.  ``assert_valid_frozen_bounds`` enforces both init
# ordering and non-overlapping ranges for every complete group.  Independent
# per-parameter quantile extraction can violate this, so the extract tool
# must enforce the constraint before emitting the proposal.
_TEMPERATURE_GROUPS: tuple[tuple[str, str, str, str], ...] = (
    ("TB", "TO1", "TO2", "TM"),
    ("TB1", "TO11", "TO21", "TM1"),
    ("TB2", "TO12", "TO22", "TM2"),
    ("TB3", "TO13", "TO23", "TM3"),
)


def extract_bounds_proposal(
    posterior_csv: str | Path,
    parameter_set_json: str | Path,
    base_bounds_csv: str | Path,
    *,
    lower_quantile: float = 0.05,
    upper_quantile: float = 0.95,
    out_csv: str | Path | None = None,
) -> Path:
    """Generate a bounds proposal CSV from an IES posterior.

    Parameters
    ----------
    posterior_csv
        pestpp-ies posterior CSV (one row per realization, columns are
        parameter names, case-insensitive).
    parameter_set_json
        Parameter set JSON declaring which parameters to extract bounds for.
    base_bounds_csv
        Frozen bounds CSV used as the template — inherits metadata columns
        (pargp/location/file/cultivar/ecotype/mode) and fixed values for
        parameters outside the target set.
    lower_quantile, upper_quantile
        Posterior quantiles used as the proposal lower/upper bounds before
        clamping to physical hard limits.  Defaults: 0.05 / 0.95.
    out_csv
        Output proposal CSV path.  If None, writes next to
        ``base_bounds_csv`` with a ``.proposal.csv`` suffix.

    Returns
    -------
    Path
        Path to the written proposal CSV.

    Raises
    ------
    ValueError
        If a declared parameter is absent from the posterior, the base bounds
        CSV is empty, or a computed range is degenerate after clamping and no
        physical fallback exists.
    """
    if not 0.0 < lower_quantile < upper_quantile < 1.0:
        raise ValueError(
            f"Require 0 < lower_quantile < upper_quantile < 1, got "
            f"{lower_quantile}, {upper_quantile}"
        )

    # -- load parameter set ------------------------------------------------
    with open(parameter_set_json, "r", encoding="utf-8") as fh:
        pset = json.load(fh)
    target_params: set[str] = {str(p).strip().upper() for p in pset["parameters"]}

    # -- load posterior (case-insensitive column lookup) -------------------
    posterior = pd.read_csv(posterior_csv)
    col_map: dict[str, str] = {str(c).strip().upper(): c for c in posterior.columns}
    missing = target_params - set(col_map.keys())
    if missing:
        raise ValueError(
            f"Parameters declared in set '{pset.get('set_id', '?')}' but "
            f"absent from posterior: {sorted(missing)}"
        )

    # -- load base bounds template -----------------------------------------
    with open(base_bounds_csv, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        base_rows = list(reader)
    if not base_rows:
        raise ValueError(f"Base bounds CSV is empty: {base_bounds_csv}")

    # -- build proposal rows ------------------------------------------------
    proposal_rows: list[dict] = []
    for row in base_rows:
        name = str(row.get("name", "")).strip().upper()
        new_row = dict(row)
        if name in target_params:
            col = col_map[name]
            values = posterior[col].dropna().astype(float)
            if values.empty:
                raise ValueError(f"Posterior column '{col}' has no valid values")
            lo = float(values.quantile(lower_quantile))
            hi = float(values.quantile(upper_quantile))
            med = float(values.median())
            lo, hi = clamp_to_physical(name, lo, hi)
            if lo >= hi:
                # Degenerate after clamping (e.g. zero-variance posterior).
                # Fall back to the physical envelope, then the base row.
                phys = PHYSICAL_BOUNDS.get(name)
                if phys and phys[0] < phys[1]:
                    lo, hi = phys
                else:
                    base_lo = float(row.get("lower", lo))
                    base_hi = float(row.get("upper", hi))
                    lo, hi = base_lo, base_hi
                if lo >= hi:
                    raise ValueError(
                        f"Parameter '{name}': degenerate range (lower={lo}, "
                        f"upper={hi}) after clamping and fallback. Inspect "
                        f"the posterior for this parameter."
                    )
            new_row["init"] = _fmt(med)
            new_row["lower"] = _fmt(lo)
            new_row["upper"] = _fmt(hi)
            new_row["status"] = "active"
        else:
            # Non-target parameter: fix at its current init value.
            init_val = row.get("init", "")
            new_row["status"] = "fixed"
            new_row["lower"] = init_val
            new_row["upper"] = init_val
        proposal_rows.append(new_row)

    # -- enforce temperature ordering ---------------------------------------
    # Independent per-parameter quantiles can produce overlapping ranges or
    # reversed init medians within a temperature group (TB < TO1 < TO2 < TM).
    # ``assert_valid_frozen_bounds`` rejects such proposals, so the extract
    # tool must enforce the constraint here to keep the proposal freezable.
    _enforce_temperature_ordering(proposal_rows, base_rows)

    # -- write proposal -----------------------------------------------------
    if out_csv is None:
        base = Path(base_bounds_csv)
        out_csv = base.with_suffix(".proposal.csv")
    out_path = Path(out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(proposal_rows)
    return out_path


def _fmt(val: float) -> str:
    """Format a float for CSV output (6 significant digits)."""
    return f"{val:.6g}"


def _enforce_temperature_ordering(
    proposal_rows: list[dict],
    base_rows: list[dict],
) -> None:
    """Enforce TB < TO1 < TO2 < TM ordering on init and range values in-place.

    Independent per-parameter quantile extraction can produce:

    * **Range overlap** — ``left.upper >= right.lower`` for an adjacent
      temperature pair.  Fixed by splitting the overlap at its midpoint.
    * **Init reversal** — ``left.init >= right.init``.  Fixed by falling back
      to the already-approved base-bounds init for the violating pair.

    If a midpoint split produces a degenerate range (``lower >= upper``), the
    entire pair falls back to its base-bounds values.  All adjustments are
    logged as warnings so the human reviewer can inspect them before
    approving the proposal via ``freeze_bounds.py``.

    Only complete, fully-active groups are adjusted.  Groups with missing or
    fixed members are skipped — ``assert_valid_frozen_bounds`` also skips
    incomplete groups, so no constraint is violated.
    """
    base_by_name: dict[str, dict] = {
        str(r.get("name", "")).strip().upper(): r for r in base_rows
    }
    by_name: dict[str, dict] = {
        str(r.get("name", "")).strip().upper(): r for r in proposal_rows
    }

    for group in _TEMPERATURE_GROUPS:
        members = [by_name.get(n) for n in group]
        if any(m is None for m in members):
            continue
        if any(str(m.get("status", "")).lower() != "active" for m in members):
            continue

        # --- Range pass: fix overlapping ranges via midpoint split ----------
        for left, right in zip(members, members[1:]):
            lu = float(left["upper"])
            rl = float(right["lower"])
            if lu < rl:
                continue  # Already ordered

            # Split at the midpoint with a small gap so that left.upper <
            # right.lower (the validator uses strict ``>=`` comparison).
            midpoint = (lu + rl) / 2.0
            gap = max(abs(midpoint) * 1e-4, 1e-4)
            left["upper"] = _fmt(midpoint - gap)
            right["lower"] = _fmt(midpoint + gap)
            logger.warning(
                "Temperature range overlap: %s.upper=%g >= %s.lower=%g; "
                "split at midpoint=%g (gap=%g)",
                left["name"], lu, right["name"], rl, midpoint, gap,
            )

            # Degenerate range after split → fall back to base for this pair.
            if float(left["lower"]) >= float(left["upper"]):
                _restore_from_base(left, base_by_name)
            if float(right["lower"]) >= float(right["upper"]):
                _restore_from_base(right, base_by_name)

        # --- Init pass: fix reversed inits via base fallback ----------------
        for left, right in zip(members, members[1:]):
            li = float(left["init"])
            ri = float(right["init"])
            if li < ri:
                continue  # Already ordered

            logger.warning(
                "Temperature init reversal: %s.init=%g >= %s.init=%g; "
                "falling back to base bounds init for this pair",
                left["name"], li, right["name"], ri,
            )
            _restore_from_base(left, base_by_name)
            _restore_from_base(right, base_by_name)

        # --- Clamp pass: ensure init ∈ [lower, upper] after adjustments ------
        for member in members:
            init = float(member["init"])
            lo = float(member["lower"])
            hi = float(member["upper"])
            if init < lo:
                member["init"] = member["lower"]
            elif init > hi:
                member["init"] = member["upper"]


def _restore_from_base(row: dict, base_by_name: dict[str, dict]) -> None:
    """Restore init/lower/upper for *row* from the base bounds template."""
    name = str(row.get("name", "")).strip().upper()
    base = base_by_name.get(name)
    if not base:
        return
    for key in ("init", "lower", "upper"):
        if key in base:
            row[key] = base[key]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Extract a bounds proposal from an IES posterior. "
            "Output must be reviewed and promoted via freeze_bounds.py."
        )
    )
    parser.add_argument("--posterior", required=True, help="IES posterior CSV")
    parser.add_argument(
        "--parameter-set", required=True, help="Parameter set JSON (e.g. sobol23)"
    )
    parser.add_argument(
        "--base-bounds", required=True,
        help="Base frozen bounds CSV (template for metadata and fixed params)",
    )
    parser.add_argument("--lower-quantile", type=float, default=0.05)
    parser.add_argument("--upper-quantile", type=float, default=0.95)
    parser.add_argument("--out", default=None, help="Output proposal CSV path")
    args = parser.parse_args(argv)

    out = extract_bounds_proposal(
        posterior_csv=args.posterior,
        parameter_set_json=args.parameter_set,
        base_bounds_csv=args.base_bounds,
        lower_quantile=args.lower_quantile,
        upper_quantile=args.upper_quantile,
        out_csv=args.out,
    )

    active = sum(1 for r in csv.DictReader(open(out, encoding="utf-8-sig"))
                 if r.get("status", "").lower() == "active")
    print(f"Bounds proposal written: {out}")
    print(f"  active parameters: {active}")
    print(f"  NOTE: This is a proposal, not a frozen bounds file.")
    print(f"  Promote via: python tools/freeze_bounds.py "
          f"--proposal {out} --crop eggplant --bounds-id <id>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
