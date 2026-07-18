"""Canonical figure-data contracts and adapters for historical outputs."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Iterable

import numpy as np
import pandas as pd


REQUIRED_COMPARISON_COLUMNS = [
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

OPTIONAL_COMPARISON_COLUMNS = [
    "date_code",
    "year",
    "doy",
    "dap",
    "harvest_number",
    "observed_sd",
    "observed_se",
    "n_rep",
]

COMPARISON_COLUMNS = REQUIRED_COMPARISON_COLUMNS + OPTIONAL_COMPARISON_COLUMNS

TRAJECTORY_COLUMNS = [
    "run_id",
    "data_status",
    "dataset_role",
    "variable",
    "variable_label",
    "unit",
    "treatment",
    "time",
    "time_label",
    "year",
    "doy",
    "date_code",
    "simulated",
    "statistic",
    "source_file",
]

TREATMENT_METADATA_COLUMNS = [
    "treatment",
    "treatment_label",
    "water_level",
    "nitrogen_level",
]


VARIABLE_SPECS: dict[str, dict[str, str]] = {
    "ADAP": {"label": "Anthesis date", "unit": "days after planting", "domain": "phenology"},
    "LAIX": {"label": "Maximum leaf area index", "unit": "m² m⁻²", "domain": "canopy"},
    "CNAM": {"label": "Canopy nitrogen at maturity", "unit": "kg N ha⁻¹", "domain": "nitrogen"},
    "LAID": {"label": "Leaf area index", "unit": "m² m⁻²", "domain": "canopy"},
    "LWAD": {"label": "Leaf dry mass", "unit": "kg ha⁻¹", "domain": "biomass"},
    "SWAD": {"label": "Stem dry mass", "unit": "kg ha⁻¹", "domain": "biomass"},
    "CWAD": {"label": "Aboveground dry mass", "unit": "kg ha⁻¹", "domain": "biomass"},
    "DRY_INC": {"label": "Incremental dry harvest", "unit": "kg ha⁻¹", "domain": "harvest"},
    "FRESH_INC": {"label": "Incremental fresh harvest", "unit": "kg ha⁻¹", "domain": "harvest"},
    "DRY_CUM": {"label": "Cumulative dry harvest", "unit": "kg ha⁻¹", "domain": "harvest"},
    "FRESH_CUM": {"label": "Cumulative fresh harvest", "unit": "kg ha⁻¹", "domain": "harvest"},
}


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _normalise_treatment(value: Any) -> str:
    text = str(value).strip()
    try:
        numeric = float(text)
    except ValueError:
        return text
    return str(int(numeric)) if numeric.is_integer() else text


def validate_comparison_table(data: pd.DataFrame) -> pd.DataFrame:
    missing = set(REQUIRED_COMPARISON_COLUMNS) - set(data.columns)
    if missing:
        raise ValueError(f"Comparison table missing columns: {sorted(missing)}")
    data = data.copy()
    for column in OPTIONAL_COMPARISON_COLUMNS:
        if column not in data:
            data[column] = np.nan
    result = data[COMPARISON_COLUMNS].copy()
    allowed_roles = {"calibration", "validation", "diagnostic", "legacy_unsplit"}
    invalid_roles = set(result["dataset_role"].astype(str)) - allowed_roles
    if invalid_roles:
        raise ValueError(f"Unsupported dataset_role values: {sorted(invalid_roles)}")
    for column in ("run_id", "data_status", "variable", "variable_label", "unit", "treatment"):
        if result[column].isna().any() or (result[column].astype(str).str.strip() == "").any():
            raise ValueError(f"Comparison table requires non-empty {column}")
    numeric_columns = [
        "observed", "simulated", "time", "date_code", "year", "doy", "dap",
        "harvest_number", "observed_sd", "observed_se", "n_rep",
    ]
    for column in numeric_columns:
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
    raw_date = _numeric(frame.get("DATE", pd.Series(index=frame.index, dtype=float)))
    harvest_number = _numeric(frame.get("HNO", pd.Series(index=frame.index, dtype=float)))
    raw_time = raw_date.where(raw_date.notna(), harvest_number)
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
            date_value = raw_date.loc[index]
            date_code = float(date_value) if np.isfinite(date_value) else np.nan
            year = 2000 + int(date_value) // 1000 if np.isfinite(date_value) and date_value >= 1000 else np.nan
            doy = int(date_value) % 1000 if np.isfinite(date_value) and date_value >= 1000 else np.nan
            records.append(
                {
                    "run_id": run_id,
                    "data_status": "legacy_unvalidated",
                    "dataset_role": "legacy_unsplit",
                    "variable": variable,
                    "variable_label": spec["label"],
                    "unit": spec["unit"],
                    "treatment": _normalise_treatment(treatment.loc[index]),
                    "time": float(time.loc[index]) if np.isfinite(time.loc[index]) else np.nan,
                    "time_label": time_label,
                    "observed": float(observed),
                    "simulated": float(simulated),
                    "source_file": str(path.resolve()),
                    "date_code": date_code,
                    "year": year,
                    "doy": doy,
                    "dap": np.nan,
                    "harvest_number": (
                        float(harvest_number.loc[index])
                        if np.isfinite(harvest_number.loc[index]) else np.nan
                    ),
                    "observed_sd": np.nan,
                    "observed_se": np.nan,
                    "n_rep": np.nan,
                }
            )
    return records


def adapt_legacy_comparison_outputs(results_dir: str | Path, prefix: str) -> pd.DataFrame:
    """Convert old wide deterministic comparison CSVs into the frozen tidy API."""
    results_dir = Path(results_dir)
    sources = [
        (results_dir / f"{prefix}_deterministic_process_compare.csv", ("LAID", "LWAD", "SWAD")),
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
        records.extend(_legacy_records(pd.read_csv(path), path=path, run_id=prefix, variables=variables))
    if not found:
        raise FileNotFoundError(f"No legacy comparison CSVs found for prefix {prefix!r} in {results_dir}")
    return validate_comparison_table(pd.DataFrame(records))


def validate_treatment_metadata(data: pd.DataFrame) -> pd.DataFrame:
    missing = set(TREATMENT_METADATA_COLUMNS) - set(data.columns)
    if missing:
        raise ValueError(f"Treatment metadata missing columns: {sorted(missing)}")
    result = data[TREATMENT_METADATA_COLUMNS].copy()
    for column in TREATMENT_METADATA_COLUMNS:
        if result[column].isna().any() or (result[column].astype(str).str.strip() == "").any():
            raise ValueError(f"Treatment metadata requires non-empty {column}")
        result[column] = result[column].astype(str).str.strip()
    result["treatment"] = result["treatment"].map(_normalise_treatment)
    if result["treatment"].duplicated().any():
        duplicated = sorted(result.loc[result["treatment"].duplicated(), "treatment"].unique())
        raise ValueError(f"Treatment metadata has duplicate treatments: {duplicated}")
    return result.reset_index(drop=True)


def read_treatment_metadata(path: str | Path) -> pd.DataFrame:
    return validate_treatment_metadata(pd.read_csv(path, dtype=str))


def _parse_dssat_trajectory_file(
    path: Path,
    *,
    run_id: str,
    data_status: str,
    role_by_treatment: dict[str, str],
    variable_map: dict[str, str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    current_treatment: str | None = None
    header: list[str] | None = None
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if raw_line.startswith("*RUN"):
                current_treatment = None
                header = None
                continue
            treatment_match = re.match(r"^TREATMENT\s+(\d+)\b", line)
            if treatment_match:
                current_treatment = treatment_match.group(1)
                continue
            if line.startswith("@YEAR"):
                header = line.split()
                continue
            if current_treatment is None or header is None:
                continue
            if not line or line.startswith(("*", "!", "@")):
                continue
            parts = line.split()
            if len(parts) < len(header):
                continue
            try:
                year = int(float(parts[header.index("@YEAR")]))
                doy = int(float(parts[header.index("DOY")]))
                dap = float(parts[header.index("DAP")])
            except (ValueError, IndexError):
                continue
            for source_variable, variable in variable_map.items():
                if source_variable not in header:
                    continue
                try:
                    value = float(parts[header.index(source_variable)])
                except (ValueError, IndexError):
                    continue
                if not np.isfinite(value) or value == -99:
                    continue
                spec = VARIABLE_SPECS[variable]
                records.append(
                    {
                        "run_id": run_id,
                        "data_status": data_status,
                        "dataset_role": role_by_treatment.get(current_treatment, "diagnostic"),
                        "variable": variable,
                        "variable_label": spec["label"],
                        "unit": spec["unit"],
                        "treatment": current_treatment,
                        "time": dap,
                        "time_label": "Days after planting",
                        "year": year,
                        "doy": doy,
                        "date_code": (year % 100) * 1000 + doy,
                        "simulated": value,
                        "statistic": "deterministic",
                        "source_file": str(path.resolve()),
                    }
                )
    return records


def read_dssat_trajectories(
    run_dir: str | Path,
    *,
    run_id: str,
    data_status: str,
    role_by_treatment: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Read deterministic daily trajectories without applying visual smoothing."""
    run_dir = Path(run_dir)
    roles = {_normalise_treatment(key): value for key, value in (role_by_treatment or {}).items()}
    sources = [
        (run_dir / "PlantGro.OUT", {"LAID": "LAID", "LWAD": "LWAD", "SWAD": "SWAD", "CWAD": "CWAD"}),
        (run_dir / "FreshWt.OUT", {"CHPDT": "DRY_CUM", "CHFPW": "FRESH_CUM"}),
    ]
    records: list[dict[str, Any]] = []
    for path, variable_map in sources:
        if path.is_file():
            records.extend(
                _parse_dssat_trajectory_file(
                    path,
                    run_id=run_id,
                    data_status=data_status,
                    role_by_treatment=roles,
                    variable_map=variable_map,
                )
            )
    if not records:
        raise FileNotFoundError(f"No readable PlantGro.OUT or FreshWt.OUT trajectories in {run_dir}")
    result = pd.DataFrame(records)[TRAJECTORY_COLUMNS]
    result = result[np.isfinite(result["time"]) & np.isfinite(result["simulated"])].copy()
    if result.empty:
        raise ValueError(f"DSSAT trajectory files contain no finite supported variables: {run_dir}")
    return result.sort_values(["variable", "treatment", "time"]).reset_index(drop=True)


def align_comparison_to_trajectory(comparison: pd.DataFrame, trajectory: pd.DataFrame) -> pd.DataFrame:
    """Replace legacy DOY axes with DAP where treatment and date both match."""
    result = comparison.copy()
    lookup = trajectory[["treatment", "date_code", "time"]].drop_duplicates(
        ["treatment", "date_code"]
    )
    dap_by_key = {
        (_normalise_treatment(row.treatment), int(row.date_code)): float(row.time)
        for row in lookup.itertuples(index=False)
        if np.isfinite(row.date_code) and np.isfinite(row.time)
    }
    for index in result.index:
        date_code = result.at[index, "date_code"]
        if not np.isfinite(date_code):
            continue
        key = (_normalise_treatment(result.at[index, "treatment"]), int(date_code))
        if key not in dap_by_key:
            continue
        result.at[index, "time"] = dap_by_key[key]
        result.at[index, "dap"] = dap_by_key[key]
        result.at[index, "time_label"] = "Days after planting"
    return validate_comparison_table(result)


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
    "TRAJECTORY_COLUMNS",
    "TREATMENT_METADATA_COLUMNS",
    "VARIABLE_SPECS",
    "adapt_legacy_comparison_outputs",
    "align_comparison_to_trajectory",
    "performance_metrics",
    "read_comparison_table",
    "read_dssat_trajectories",
    "read_phi_ensemble",
    "read_treatment_metadata",
    "validate_comparison_table",
    "validate_treatment_metadata",
]
