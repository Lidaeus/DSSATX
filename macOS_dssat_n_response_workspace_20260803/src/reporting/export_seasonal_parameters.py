"""Export posterior parameters on the actual season-specific DSSAT scale.

PEST++ estimates shared values and PEST-only offset terms.  This exporter is
the reporting counterpart of ``run_multiseason``: it derives the values that
were injected into spring and autumn DSSAT simulations, so posterior tables,
correlation analysis, and model evaluation never mistake an offset for an
independent cultivar coefficient.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.calibration.multiseason_design import MultiSeasonDesign


def _latest_parameter_ensemble(run_dir: Path, prefix: str) -> tuple[int, Path]:
    candidates: list[tuple[int, float, Path]] = []
    for path in run_dir.glob(f"{prefix}.*.par.csv"):
        pieces = path.name.split(".")
        if len(pieces) >= 4 and pieces[-3].isdigit():
            candidates.append((int(pieces[-3]), path.stat().st_mtime, path))
    if not candidates:
        raise FileNotFoundError(f"no PEST++ parameter ensemble for {prefix!r} in {run_dir}")
    iteration, _, path = max(candidates, key=lambda item: (item[0], item[1]))
    return iteration, path


def export_seasonal_parameter_ensemble(
    *, run_dir: str | Path, prefix: str, design_path: str | Path, out_dir: str | Path | None = None
) -> tuple[Path, Path]:
    """Write realization-level and posterior-summary seasonal parameter tables."""
    run_path = Path(run_dir).expanduser().resolve()
    design = MultiSeasonDesign.load(design_path)
    if design.seasonal_parameterization is None:
        raise ValueError("design has no seasonal_parameterization block")
    iteration, ensemble_path = _latest_parameter_ensemble(run_path, prefix)
    ensemble = pd.read_csv(ensemble_path, index_col=0)
    destination = Path(out_dir).expanduser().resolve() if out_dir else run_path
    destination.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    for realization, series in ensemble.iterrows():
        values = {str(name).strip().upper(): float(value) for name, value in series.items()}
        for season in design.seasons:
            _, audit = design.seasonal_parameterization.project(values, season.season_id)
            for record in audit:
                rows.append(
                    {
                        "iteration": iteration,
                        "realization": str(realization),
                        "season_role": season.role,
                        **record,
                    }
                )
    result = pd.DataFrame(rows)
    if result.empty:
        raise RuntimeError("seasonal projection produced no rows")
    long_path = destination / f"{prefix}_seasonal_parameter_ensemble.csv"
    result.to_csv(long_path, index=False, encoding="utf-8-sig")

    summary = (
        result.groupby(["season_id", "season_role", "parameter", "offset_name", "transform", "rationale"], dropna=False)
        .agg(
            n=("season_value", "count"),
            season_value_mean=("season_value", "mean"),
            season_value_sd=("season_value", "std"),
            season_value_q025=("season_value", lambda x: x.quantile(0.025)),
            season_value_q500=("season_value", "median"),
            season_value_q975=("season_value", lambda x: x.quantile(0.975)),
            shared_value_mean=("shared_value", "mean"),
            offset_value_mean=("offset_value", "mean"),
            offset_value_q025=("offset_value", lambda x: x.quantile(0.025)),
            offset_value_q975=("offset_value", lambda x: x.quantile(0.975)),
        )
        .reset_index()
    )
    summary_path = destination / f"{prefix}_seasonal_parameter_summary.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    return long_path, summary_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export shared + seasonal-offset posterior parameters")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--design", required=True)
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args(argv)
    long_path, summary_path = export_seasonal_parameter_ensemble(
        run_dir=args.run_dir,
        prefix=args.prefix,
        design_path=args.design,
        out_dir=args.out_dir or None,
    )
    print(f"seasonal parameter ensemble -> {long_path}")
    print(f"seasonal parameter summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
