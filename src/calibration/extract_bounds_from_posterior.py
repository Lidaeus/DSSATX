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
from pathlib import Path

import pandas as pd

from src.common.param_registry import PHYSICAL_BOUNDS, clamp_to_physical


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
