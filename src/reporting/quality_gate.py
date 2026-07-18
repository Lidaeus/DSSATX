"""Quality-gate adapters for persisted PEST++ run directories."""

from __future__ import annotations

import glob
import os
import re
from pathlib import Path

import pandas as pd
import pyemu

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


def _write_member_status(
    run_dir: Path,
    prefix: str,
    initial: pd.DataFrame,
    final: pd.DataFrame,
    observations: pd.DataFrame,
    phi_frame: pd.DataFrame | None,
) -> Path:
    """Persist a conservative member-state table for engineering diagnosis."""
    phi_cols = []
    if phi_frame is not None:
        summary = {"iteration", "total_runs", "mean", "standard_deviation", "std", "min", "max", "base"}
        phi_cols = [c for c in phi_frame.columns if c not in summary]
    rows = []
    for real_name in initial.index.astype(str):
        values = pd.to_numeric(phi_frame[real_name], errors="coerce") if phi_frame is not None and real_name in phi_frame else pd.Series(dtype=float)
        finite_phi = int(values.notna().sum())
        in_final = real_name in set(final.index.astype(str))
        in_obs = real_name in set(observations.index.astype(str))
        if in_final and in_obs:
            state = "retained"
        elif finite_phi > 0:
            state = "high_phi_screened"
        elif not in_obs:
            state = "model_failed"
        else:
            state = "other_dropped"
        rows.append({
            "real_name": real_name,
            "state": state,
            "initial_present": True,
            "final_parameter_present": in_final,
            "final_observation_present": in_obs,
            "finite_phi_count": finite_phi,
            "phi_column_present": real_name in phi_cols,
        })
    out = run_dir / "ies_quality" / f"{prefix}.member_status.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    return out


def assess_ies_run(run_dir: str | Path, prefix: str) -> QualityReport:
    """Load a PEST++ IES directory and evaluate engineering completeness."""
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
    phi_frame = None
    if phi_path.exists():
        phi_frame = pd.read_csv(phi_path)
        metadata = {"iteration", "total_runs", "mean", "std", "standard_deviation", "min", "max"}
        realization_columns = [column for column in phi_frame.columns if column.lower() not in metadata]
        if realization_columns:
            phi_values = phi_frame[realization_columns]
        elif "mean" in phi_frame:
            phi_values = phi_frame[["mean"]]

    member_status_path = _write_member_status(
        directory, prefix, initial, final, observations, phi_frame
    )

    report = assess_ies(
        initial,
        observations,
        parameter_final=final,
        phi_values=phi_values,
        run_id=prefix,
    )
    report.science_validation_mode = "engineering_only"
    noptmax = None
    pst_path = directory / f"{prefix}.pst"
    if pst_path.is_file():
        try:
            noptmax = int(pyemu.Pst(str(pst_path)).control_data.noptmax)
        except Exception:
            noptmax = None
    report.add(
        "ies_iteration_progress",
        last_iteration > first_iteration or (noptmax is not None and noptmax <= 0),
        "At least one assimilation iteration was persisted (or prior-only mode was explicitly requested)",
        actual=last_iteration,
        threshold=first_iteration + 1,
    )
    report.add(
        "ies_member_status_table",
        member_status_path.is_file(),
        "Member state table distinguishes retained, model failure, high-Phi screening and other drops",
        actual=str(member_status_path),
        threshold=True,
    )
    return report
