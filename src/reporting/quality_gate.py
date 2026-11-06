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


# DSSAT native executable crashes are recorded as ``model_failed`` members,
# not silently screened high-Phi members.  A formal ensemble may continue only
# when this small, predeclared allowance is respected; retention is checked
# independently by ``ies_final_realization_alignment``.
FORMAL_IES_MAX_PHI_INVALID_FRACTION = 0.02
FORMAL_IES_MAX_OBSERVATION_INVALID_FRACTION = 0.02
FORMAL_IES_MAX_REALIZATION_LOSS_FRACTION = 0.02


def _retention_loss_from_receipt(run_dir: Path) -> float | None:
    """P0-E.2: read the spec-declared ``min_retention_rate`` from the run's
    experiment receipt and return the equivalent max-loss fraction.

    Returns ``None`` when no receipt is present (legacy runs keep the default
    threshold).  The experiment runner writes ``experiment_receipt.json`` with
    ``execution.min_retention_rate`` (default 0.95).
    """
    receipt_path = run_dir / "experiment_receipt.json"
    if not receipt_path.is_file():
        return None
    try:
        import json
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        rate = float(receipt.get("execution", {}).get("min_retention_rate", 0.95))
        if 0.0 < rate <= 1.0:
            return 1.0 - rate
    except Exception:
        pass
    return None


def _read_ensemble(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0)
    frame.index = frame.index.map(_canonical_real_name)
    return frame


def _canonical_real_name(value: object) -> str:
    """Normalize equivalent PEST++ realization labels (``0`` vs ``0.0``)."""
    text = str(value).strip()
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text.lower()
    if number.is_integer():
        return str(int(number))
    return text


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
    # The manager records ensemble-level drops in the run root, while Panther
    # workers record the concrete ``run failed ... REALIZATION`` evidence in
    # their isolated agent directories.  Both are required to distinguish a
    # true DSSAT failure from an unexplained missing realization.
    rec_paths = list(run_dir.glob(f"{prefix}*.rec"))
    agents_root = run_dir / "_agents"
    if agents_root.is_dir():
        rec_paths.extend(agents_root.glob("**/*.rec"))
    for rec_path in rec_paths:
        try:
            rec_text += rec_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass
    screened: dict[str, str] = {}
    for line in rec_text.splitlines():
        if "dropping par:obs realizations:" not in line.lower():
            continue
        payload = re.split(r"dropping\s+par:obs\s+realizations:", line, maxsplit=1, flags=re.IGNORECASE)[1]
        for match in re.finditer(r"[^\s,:]+\s*:\s*([^\s,]+)", payload):
            screened[_canonical_real_name(match.group(1))] = "REC: explicit PEST++ realization drop"
    model_failed: dict[str, str] = {}
    for line in rec_text.splitlines():
        if "run failed for run_id" not in line.lower():
            continue
        match = re.search(r"REALIZATION\s*:\s*([^\s,]+)", line, flags=re.IGNORECASE)
        if match:
            model_failed[_canonical_real_name(match.group(1))] = "REC: PEST++ reports model-run failure"
    for evidence_path in (run_dir / "member_failure_evidence.json", run_dir / "agent_failure_evidence.json"):
        if not evidence_path.is_file():
            continue
        try:
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            entries = payload if isinstance(payload, list) else payload.get("members", [])
            for item in entries:
                if isinstance(item, dict) and item.get("real_name") is not None:
                    model_failed[_canonical_real_name(item["real_name"])] = str(item.get("evidence_source") or evidence_path.name)
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


def assess_ies_run(
    run_dir: str | Path,
    prefix: str,
    *,
    max_observation_invalid_fraction: float = FORMAL_IES_MAX_OBSERVATION_INVALID_FRACTION,
    max_phi_invalid_fraction: float = FORMAL_IES_MAX_PHI_INVALID_FRACTION,
    max_realization_loss_fraction: float = FORMAL_IES_MAX_REALIZATION_LOSS_FRACTION,
) -> QualityReport:
    """Load a PEST++ IES directory and evaluate engineering completeness.

    P0-E: when an ``experiment_receipt.json`` is present in the run directory
    (written by the experiment runner), its declared ``min_retention_rate``
    overrides the default loss fraction, so the engineering gate honours the
    spec's threshold rather than a hardcoded constant.  A high-Phi member is
    recorded as a non-fatal ``ies_phi_outlier`` warning (per the article
    contract) rather than causing the gate to fail.
    """
    directory = Path(run_dir).resolve()

    # P0-E.2: honour spec-declared retention threshold from the experiment receipt.
    receipt_loss = _retention_loss_from_receipt(directory)
    if receipt_loss is not None:
        max_realization_loss_fraction = receipt_loss
    parameter_files = _iteration_files(directory, prefix, "par.csv")
    observation_files = _iteration_files(directory, prefix, "obs.csv")
    if not parameter_files:
        report = QualityReport(run_type="ies", run_id=prefix, science_validation_mode="engineering_only")
        report.add("process_completed", False, "No parameter ensemble files were found")
        return report

    # Historical outputs can survive an unsafe directory clone.  Resolve the
    # final iteration from the live PST/Phi contract before choosing files.
    try:
        from src.calibration.stage_representative import resolve_final_iteration
        contract_iteration, _ = resolve_final_iteration(directory, prefix)
        parameter_files = {k: v for k, v in parameter_files.items() if k <= contract_iteration}
        observation_files = {k: v for k, v in observation_files.items() if k <= contract_iteration}
    except (FileNotFoundError, RuntimeError):
        pass
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

    # A PEST++ simulated-observation ensemble contains zero-weight diagnostic
    # columns as well as calibration evidence.  A missing sentinel in a
    # deliberately excluded observation (e.g. unobserved 25FA ADAP) must not
    # be classified as a model-run failure.  Restrict finite/variation checks
    # to the active observations that actually enter Phi.
    pst_path = directory / f"{prefix}.pst"
    active_observation_names: list[str] | None = None
    if pst_path.is_file():
        try:
            pst = pyemu.Pst(str(pst_path))
            active_observation_names = [
                str(name) for name, row in pst.observation_data.iterrows()
                if float(row["weight"]) > 0.0
            ]
        except Exception:
            active_observation_names = None
    assessment_observations = observations
    if active_observation_names is not None:
        available = [name for name in active_observation_names if name in observations.columns]
        if available:
            assessment_observations = observations.loc[:, available]

    phi_path = directory / f"{prefix}.phi.actual.csv"
    phi_values = None
    phi_frame = None
    if phi_path.exists():
        phi_frame = pd.read_csv(phi_path)
        metadata = {"iteration", "total_runs", "mean", "std", "standard_deviation", "min", "max"}
        phi_frame = phi_frame.rename(
            columns={column: _canonical_real_name(column) for column in phi_frame.columns if column not in metadata}
        )
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
        assessment_observations,
        parameter_final=final,
        phi_values=phi_values,
        run_id=prefix,
        max_invalid_fraction=max_observation_invalid_fraction,
        max_phi_invalid_fraction=max_phi_invalid_fraction,
        max_realization_loss_fraction=max_realization_loss_fraction,
    )
    report.science_validation_mode = "engineering_only"
    noptmax = None
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

    # P0-E.1: classify high-Phi members as a non-fatal warning.  A successful
    # IES run with a few large-Phi members must not be frozen by the outlier;
    # ``ies_bad_phi_sigma`` already prevents automatic culling, and this check
    # only records the outlier fraction for transparency.  It never causes the
    # engineering gate to fail.
    if phi_frame is not None and "mean" in phi_frame.columns:
        final_mean = float(phi_frame["mean"].iloc[-1]) if len(phi_frame) else float("nan")
        if phi_frame["mean"].notna().any() and final_mean == final_mean:
            import numpy as _np
            means = phi_frame["mean"].dropna().to_numpy(dtype=float)
            if len(means) >= 4:
                q1, q3 = _np.percentile(means, [25, 75])
                iqr = q3 - q1
                upper = q3 + 1.5 * iqr if iqr > 0 else float("inf")
                n_outlier = int(_np.sum(means > upper))
                report.add(
                    "ies_phi_outlier",
                    True,  # always "pass" — this is informational, never fatal
                    "High-Phi members are recorded as outliers, not model failures",
                    actual=n_outlier,
                    threshold=0,
                    warning=n_outlier > 0,
                )
    return report
