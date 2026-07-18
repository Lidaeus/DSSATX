"""Quality-gate adapters for persisted PEST++ run directories."""

from __future__ import annotations

import glob
import json
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
    rec_text = ""
    for rec_path in run_dir.glob(f"{prefix}*.rec"):
        try:
            rec_text += rec_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass
    screened: dict[str, str] = {}
    for line in rec_text.splitlines():
        if "dropping par:obs realizations:" not in line.lower():
            continue
        payload = re.split(r"dropping\s+par:obs\s+realizations:", line, maxsplit=1, flags=re.IGNORECASE)[1]
        for match in re.finditer(r"\d+\s*:\s*([^\s,]+)", payload):
            screened[str(match.group(1))] = "REC: explicit PEST++ realization drop"
    model_failed: dict[str, str] = {}
    for evidence_path in (run_dir / "member_failure_evidence.json", run_dir / "agent_failure_evidence.json"):
        if not evidence_path.is_file():
            continue
        try:
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            entries = payload if isinstance(payload, list) else payload.get("members", [])
            for item in entries:
                if isinstance(item, dict) and item.get("real_name") is not None:
                    model_failed[str(item["real_name"])] = str(item.get("evidence_source") or evidence_path.name)
        except Exception:
            continue
    phi_cols = []
    if phi_frame is not None:
        summary = {"iteration", "total_runs", "mean", "standard_deviation", "std", "min", "max", "base"}
        phi_cols = [c for c in phi_frame.columns if c not in summary]
    rows = []
    for real_name in initial.index.astype(str):
        values = pd.to_numeric(phi_frame[real_name], errors="coerce") if phi_frame is not None and real_name in phi_frame else pd.Series(dtype=float)
        finite_phi = int(values.notna().sum())
        first_seen = ""
        last_seen = ""
        if phi_frame is not None and real_name in phi_frame and "iteration" in phi_frame.columns:
            finite_rows = pd.to_numeric(phi_frame[real_name], errors="coerce").notna()
            iterations = pd.to_numeric(phi_frame.loc[finite_rows, "iteration"], errors="coerce").dropna()
            if not iterations.empty:
                first_seen = str(int(iterations.min()))
                last_seen = str(int(iterations.max()))
        in_final = real_name in set(final.index.astype(str))
        in_obs = real_name in set(observations.index.astype(str))
        if in_final and in_obs:
            state = "retained"
            reason = "member present in final parameter and observation ensembles"
            evidence = "parameter/observation ensemble files"
        elif real_name in screened:
            state = "high_phi_screened"
            reason = "explicit PEST++ high-Phi realization drop"
            evidence = screened[real_name]
        elif real_name in model_failed:
            state = "model_failed"
            reason = "model failure recorded by manager/agent evidence"
            evidence = model_failed[real_name]
        else:
            state = "other_dropped"
            reason = "member missing without explicit REC or agent failure evidence"
            evidence = "no qualifying evidence"
        rows.append({
            "real_name": real_name,
            "state": state,
            "final_status": state,
            "reason": reason,
            "evidence_source": evidence,
            "first_seen_iteration": first_seen,
            "last_seen_iteration": last_seen,
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
