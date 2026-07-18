"""Quality-gate adapters for persisted PEST++ run directories."""

from __future__ import annotations

import glob
import os
import re
from pathlib import Path

import pandas as pd

from src.common.quality import QualityReport, assess_ies


def _read_ensemble(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0)
    frame.index = frame.index.astype(str)
    return frame


def _iteration_files(run_dir: Path, prefix: str, suffix: str) -> dict[int, Path]:
    found: dict[int, Path] = {}
    pattern = re.compile(rf"^{re.escape(prefix)}\.(\d+)\.{re.escape(suffix)}$")
    for path in run_dir.glob(f"{prefix}.*.{suffix}"):
        match = pattern.match(path.name)
        if match:
            found[int(match.group(1))] = path
    return found


def assess_ies_run(run_dir: str | Path, prefix: str) -> QualityReport:
    """Load a PEST++ IES directory and evaluate the P0 scientific gates."""
    directory = Path(run_dir).resolve()
    parameter_files = _iteration_files(directory, prefix, "par.csv")
    observation_files = _iteration_files(directory, prefix, "obs.csv")
    if not parameter_files:
        report = QualityReport(run_type="ies", run_id=prefix, science_validation_mode="engineering_only")
        report.add("process_completed", False, "No parameter ensemble files were found")
        return report

    first_iteration = min(parameter_files)
    last_iteration = max(parameter_files)
    initial = _read_ensemble(parameter_files[first_iteration])
    final = _read_ensemble(parameter_files[last_iteration])

    observation_path = observation_files.get(last_iteration)
    if observation_path is None and observation_files:
        observation_path = observation_files[max(observation_files)]
    if observation_path is None:
        report = QualityReport(run_type="ies", run_id=prefix, science_validation_mode="engineering_only")
        report.add("process_completed", False, "No simulated-observation ensemble files were found")
        return report
    observations = _read_ensemble(observation_path)

    phi_path = directory / f"{prefix}.phi.actual.csv"
    phi_values = None
    if phi_path.exists():
        phi_frame = pd.read_csv(phi_path)
        metadata = {"iteration", "total_runs", "mean", "std", "standard_deviation", "min", "max"}
        realization_columns = [column for column in phi_frame.columns if column.lower() not in metadata]
        if realization_columns:
            phi_values = phi_frame[realization_columns]
        elif "mean" in phi_frame:
            phi_values = phi_frame[["mean"]]

    report = assess_ies(
        initial,
        observations,
        parameter_final=final,
        phi_values=phi_values,
        run_id=prefix,
    )
    report.science_validation_mode = "engineering_only"
    report.add(
        "ies_iteration_progress",
        last_iteration > first_iteration,
        "At least one assimilation iteration was persisted",
        actual=last_iteration,
        threshold=first_iteration + 1,
    )
    return report
