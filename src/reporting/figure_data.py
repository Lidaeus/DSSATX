"""Canonical figure-data contracts and adapters for historical outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


COMPARISON_COLUMNS = [
    "run_id",
    "data_status",
    "dataset_role",
    "variable",
    "variable_label",
    "unit",
    "treatment",
    "time",
    "time_label",
    "observed",
    "simulated",
    "source_file",
]


VARIABLE_SPECS: dict[str, dict[str, str]] = {
    "LAID": {"label": "Leaf area index", "unit": "m$^2$ m$^{-2}$", "domain": "canopy"},
    "LWAD": {"label": "Leaf dry mass", "unit": "kg ha$^{-1}$", "domain": "biomass"},
    "SWAD": {"label": "Stem dry mass", "unit": "kg ha$^{-1}$", "domain": "biomass"},
    "DRY_INC": {"label": "Incremental dry harvest", "unit": "kg ha$^{-1}$", "domain": "harvest"},
    "FRESH_INC": {"label": "Incremental fresh harvest", "unit": "kg ha$^{-1}$", "domain": "harvest"},
    "DRY_CUM": {"label": "Cumulative dry harvest", "unit": "kg ha$^{-1}$", "domain": "diagnostic"},
    "FRESH_CUM": {"label": "Cumulative fresh harvest", "unit": "kg ha$^{-1}$", "domain": "diagnostic"},
}


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def validate_comparison_table(data: pd.DataFrame) -> pd.DataFrame:
    missing = set(COMPARISON_COLUMNS) - set(data.columns)
    if missing:
        raise ValueError(f"Comparison table missing columns: {sorted(missing)}")
    result = data[COMPARISON_COLUMNS].copy()
    allowed_roles = {"calibration", "validation", "diagnostic", "legacy_unsplit"}
    invalid_roles = set(result["dataset_role"].astype(str)) - allowed_roles
    if invalid_roles:
        raise ValueError(f"Unsupported dataset_role values: {sorted(invalid_roles)}")
    for column in ("run_id", "data_status", "variable", "variable_label", "unit", "treatment"):
        if result[column].isna().any() or (result[column].astype(str).str.strip() == "").any():
            raise ValueError(f"Comparison table requires non-empty {column}")
    for column in ("observed", "simulated", "time"):
        result[column] = _numeric(result[column])
    valid = np.isfinite(result["observed"]) & np.isfinite(result["simulated"])
    valid &= (result["observed"] != -99) & (result["simulated"] != -99)
    result = result.loc[valid].reset_index(drop=True)
    if result.empty:
        raise ValueError("Comparison table has no finite observed-simulated pairs")
    return result


def read_comparison_table(path: str | Path) -> pd.DataFrame:
    return validate_comparison_table(pd.read_csv(path))


def _legacy_records(
    frame: pd.DataFrame,
    *,
    path: Path,
    run_id: str,
    variables: Iterable[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    treatment = frame.get("TN", frame.get("RUN", pd.Series(index=frame.index, dtype=float)))
    raw_time = frame.get("DATE", frame.get("HNO", pd.Series(index=frame.index, dtype=float)))
    raw_time = _numeric(raw_time)
    # DSSAT date codes are YYDDD; plot a physically readable day-of-year axis.
    time = raw_time.where(raw_time < 1000, raw_time % 1000)
    time_label = "Harvest number" if "HNO" in frame and "DATE" not in frame else "Day of year"
    for variable in variables:
        obs_col = f"OBS_{variable}"
        sim_col = f"SIM_{variable}"
        if obs_col not in frame or sim_col not in frame:
            continue
        spec = VARIABLE_SPECS[variable]
        for index in frame.index:
            observed = pd.to_numeric(frame.at[index, obs_col], errors="coerce")
            simulated = pd.to_numeric(frame.at[index, sim_col], errors="coerce")
            if not np.isfinite(observed) or not np.isfinite(simulated):
                continue
            if float(observed) == -99 or float(simulated) == -99:
                continue
            records.append(
                {
                    "run_id": run_id,
                    "data_status": "legacy_unvalidated",
                    "dataset_role": "legacy_unsplit",
                    "variable": variable,
                    "variable_label": spec["label"],
                    "unit": spec["unit"],
                    "treatment": str(treatment.loc[index]),
                    "time": float(time.loc[index]) if np.isfinite(time.loc[index]) else np.nan,
                    "time_label": time_label,
                    "observed": float(observed),
                    "simulated": float(simulated),
                    "source_file": str(path.resolve()),
                }
            )
    return records


def adapt_legacy_comparison_outputs(results_dir: str | Path, prefix: str) -> pd.DataFrame:
    """Convert old wide deterministic comparison CSVs into the future tidy API."""
    results_dir = Path(results_dir)
    sources = [
        (
            results_dir / f"{prefix}_deterministic_process_compare.csv",
            ("LAID", "LWAD", "SWAD"),
        ),
        (
            results_dir / f"{prefix}_deterministic_harvest_compare.csv",
            ("DRY_INC", "FRESH_INC", "DRY_CUM", "FRESH_CUM"),
        ),
    ]
    records: list[dict[str, Any]] = []
    found: list[Path] = []
    for path, variables in sources:
        if not path.is_file():
            continue
        found.append(path)
        records.extend(
            _legacy_records(pd.read_csv(path), path=path, run_id=prefix, variables=variables)
        )
    if not found:
        raise FileNotFoundError(
            f"No legacy comparison CSVs found for prefix {prefix!r} in {results_dir}"
        )
    return validate_comparison_table(pd.DataFrame(records))


def read_phi_ensemble(path: str | Path) -> pd.DataFrame:
    """Read PEST++ wide Phi history into iteration-realization long form."""
    source = Path(path)
    frame = pd.read_csv(source)
    if "iteration" not in frame:
        raise ValueError(f"Phi history lacks iteration: {source}")
    summary = {"iteration", "total_runs", "mean", "standard_deviation", "min", "max"}
    realization_columns = [column for column in frame.columns if column not in summary]
    if not realization_columns:
        raise ValueError(f"Phi history has no realization columns: {source}")
    long = frame.melt(
        id_vars=["iteration"],
        value_vars=realization_columns,
        var_name="realization",
        value_name="phi",
    )
    long["iteration"] = pd.to_numeric(long["iteration"], errors="raise").astype(int)
    long["phi"] = pd.to_numeric(long["phi"], errors="coerce")
    long = long[np.isfinite(long["phi"]) & (long["phi"] >= 0)].copy()
    long["source_file"] = str(source.resolve())
    if long.empty:
        raise ValueError(f"Phi history has no finite non-negative values: {source}")
    return long.reset_index(drop=True)


def performance_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    observed = frame["observed"].to_numpy(dtype=float)
    simulated = frame["simulated"].to_numpy(dtype=float)
    residual = simulated - observed
    return {
        "n": int(len(frame)),
        "rmse": float(np.sqrt(np.mean(np.square(residual)))),
        "mae": float(np.mean(np.abs(residual))),
        "bias": float(np.mean(residual)),
    }


__all__ = [
    "COMPARISON_COLUMNS",
    "VARIABLE_SPECS",
    "adapt_legacy_comparison_outputs",
    "performance_metrics",
    "read_comparison_table",
    "read_phi_ensemble",
    "validate_comparison_table",
]
