"""Machine-readable scientific quality gates for SA and calibration runs."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


class ScientificQualityError(RuntimeError):
    """Raised when a completed process is not scientifically usable."""


@dataclass(frozen=True)
class QualityCheck:
    check_id: str
    status: str
    message: str
    actual: Any = None
    threshold: Any = None

    def __post_init__(self) -> None:
        if self.status not in {"pass", "warn", "fail"}:
            raise ValueError(f"Unsupported quality status: {self.status}")


@dataclass
class QualityReport:
    run_type: str
    run_id: str = ""
    checks: list[QualityCheck] = field(default_factory=list)
    # Calibration IES reports are engineering audits.  They may contain only
    # operational checks and must never self-promote to scientific validity;
    # ``calibration_finalize.json`` is the sole authority for that decision.
    science_validation_mode: str = "quality_checks"
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    @property
    def status(self) -> str:
        statuses = {check.status for check in self.checks}
        if "fail" in statuses:
            return "fail"
        if "warn" in statuses:
            return "warn"
        return "pass"

    @property
    def process_completed(self) -> bool:
        check = next((c for c in self.checks if c.check_id == "process_completed"), None)
        return bool(check and check.status == "pass")

    @property
    def science_validated(self) -> bool:
        if self.science_validation_mode == "engineering_only":
            return False
        return self.process_completed and self.status == "pass"

    def add(
        self,
        check_id: str,
        passed: bool,
        message: str,
        *,
        actual: Any = None,
        threshold: Any = None,
        warning: bool = False,
    ) -> None:
        status = "pass" if passed else ("warn" if warning else "fail")
        self.checks.append(QualityCheck(check_id, status, message, actual, threshold))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run_type": self.run_type,
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "process_completed": self.process_completed,
            "science_validated": self.science_validated,
            "science_validation_mode": self.science_validation_mode,
            "status": self.status,
            "checks": [asdict(check) for check in self.checks],
        }

    def write(self, out_dir: str | Path, stem: str = "quality_report") -> tuple[Path, Path]:
        destination = Path(out_dir)
        destination.mkdir(parents=True, exist_ok=True)
        json_path = destination / f"{stem}.json"
        md_path = destination / f"{stem}.md"
        json_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=_json_default) + "\n",
            encoding="utf-8",
        )
        lines = [
            f"# Quality report: {self.run_id or self.run_type}",
            "",
            f"- Process completed: `{str(self.process_completed).lower()}`",
            f"- Science validated: `{str(self.science_validated).lower()}`",
            f"- Overall status: `{self.status}`",
            "",
            "| Check | Status | Actual | Threshold | Message |",
            "|---|---|---:|---:|---|",
        ]
        for check in self.checks:
            message = str(check.message).replace("|", "\\|")
            lines.append(
                f"| `{check.check_id}` | {check.status} | {_cell(check.actual)} | "
                f"{_cell(check.threshold)} | {message} |"
            )
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return json_path, md_path

    def require_pass(self) -> None:
        if not self.science_validated:
            failed = ", ".join(c.check_id for c in self.checks if c.status == "fail")
            raise ScientificQualityError(
                f"Run {self.run_id or self.run_type} failed scientific quality gates: {failed}"
            )


def load_quality_report(path: str | Path) -> QualityReport:
    """Reconstruct a :class:`QualityReport` from a written ``quality_report.json``.

    Inverse of :meth:`QualityReport.write`. Used by downstream consumers (e.g.
    the paper-data exporter) to verify an upstream run passed its gates without
    trusting a downstream self-reported status string.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"quality_report.json at {path} is not a JSON object")
    run_type = str(data.get("run_type") or "unknown")
    run_id = str(data.get("run_id") or "")
    checks: list[QualityCheck] = []
    for raw in data.get("checks") or []:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "fail")
        message = str(raw.get("message") or "")
        check_id = str(raw.get("check_id") or "unknown")
        if status not in {"pass", "warn", "fail"}:
            status = "fail"
        checks.append(
            QualityCheck(
                check_id=check_id,
                status=status,
                message=message,
                actual=raw.get("actual"),
                threshold=raw.get("threshold"),
            )
        )
    return QualityReport(
        run_type=run_type,
        run_id=run_id,
        checks=checks,
        science_validation_mode=str(data.get("science_validation_mode") or "quality_checks"),
        generated_at=str(data.get("generated_at") or ""),
    )


def serialize_manifest_scalar(value: Any) -> str:
    """Render a scalar as a flat run_manifest.yaml line value.

    The manifest is a simple flat YAML subset consumed by
    ``read_flat_run_manifest_field`` and must also parse under a standard YAML
    reader. Strings are emitted as YAML single-quoted scalars so that Windows
    path backslashes (``D:\\Tomato_Cal\\...``) remain literal — double-quoted
    YAML would treat ``\\T`` as an invalid escape and reject the file. Single
    quotes inside the value are doubled per the YAML rule, and the reader
    reverses that doubling so the value round-trips losslessly.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def _strip_manifest_scalar(value: str) -> str:
    """Strip the surrounding quote style emitted by ``serialize_manifest_scalar``.

    Single-quoted YAML scalars double internal single quotes (``''`` -> ``'``);
    double-quoted scalars are accepted for backward compatibility with older
    manifests but their content is returned verbatim (no escape interpretation,
    matching the historical reader behavior).
    """
    if value.startswith("'") and value.endswith("'") and len(value) >= 2:
        return value[1:-1].replace("''", "'")
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        return value[1:-1]
    return value


def read_flat_run_manifest_field(path: str | Path, key: str) -> str | None:
    """Read a single scalar value from a flat ``key: value`` run_manifest.yaml.

    The project writes run manifests as a simple flat YAML subset (see
    ``build_pest._write_run_manifest`` and ``finalize_calibration
    ._upsert_manifest_fields``): scalars are rendered as ``key: 'value'``,
    ``key: 123``, ``key: true``, or ``key: null``. This parser avoids a YAML
    dependency by handling only that subset and unquoting the value with
    ``_strip_manifest_scalar``. Older manifests that used double quotes are
    still accepted for backward compatibility.
    """
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    prefix = f"{key}:"
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if line.startswith(prefix):
            value = line[len(prefix):].strip()
            if value in {"null", "~", ""}:
                return None
            return _strip_manifest_scalar(value)
    return None


def assess_numeric_matrix(
    frame: pd.DataFrame,
    *,
    run_type: str,
    run_id: str = "",
    max_invalid_fraction: float = 0.0,
    min_varying_columns: int = 1,
    tolerance: float = 1e-12,
) -> QualityReport:
    """Assess forward-model output completeness and cross-run variation."""
    report = QualityReport(run_type=run_type, run_id=run_id)
    report.add("process_completed", not frame.empty, "Output matrix exists and contains rows", actual=len(frame), threshold=1)
    numeric = frame.apply(pd.to_numeric, errors="coerce").replace(-99.0, np.nan)
    total = int(numeric.size)
    invalid = int(numeric.isna().sum().sum())
    invalid_fraction = invalid / total if total else 1.0
    report.add(
        "output_finite",
        invalid_fraction <= max_invalid_fraction,
        "Invalid/failed model outputs remain below the configured limit",
        actual=invalid_fraction,
        threshold=max_invalid_fraction,
    )
    varying = int((numeric.nunique(dropna=True) > 1).sum())
    variances = numeric.var(axis=0, ddof=0, skipna=True)
    materially_varying = int((variances > tolerance).sum())
    report.add(
        "output_variation",
        materially_varying >= min_varying_columns,
        "At least one scientific output changes across parameter samples",
        actual=materially_varying,
        threshold=min_varying_columns,
    )
    report.add(
        "output_unique_values",
        varying >= min_varying_columns,
        "Output columns are not repeated constants",
        actual=varying,
        threshold=min_varying_columns,
    )
    return report


def assess_morris(
    frame: pd.DataFrame,
    *,
    run_id: str = "",
    score_column: str = "score",
    observation_column: str = "obs",
    tolerance: float = 1e-12,
) -> QualityReport:
    """Reject empty, non-finite, or all-zero Morris results."""
    report = QualityReport(run_type="morris", run_id=run_id)
    report.add("process_completed", not frame.empty, "Morris result table was produced", actual=len(frame), threshold=1)
    if score_column not in frame:
        report.add("morris_score_column", False, f"Missing Morris score column {score_column!r}")
        return report
    values = pd.to_numeric(frame[score_column], errors="coerce")
    finite = values[np.isfinite(values)]
    report.add(
        "morris_finite",
        len(finite) == len(values) and len(finite) > 0,
        "All Morris effects are finite",
        actual=len(finite),
        threshold=len(values),
    )
    nonzero = int((finite.abs() > tolerance).sum())
    report.add(
        "morris_non_degenerate",
        nonzero > 0,
        "At least one elementary-effect summary is materially non-zero",
        actual=nonzero,
        threshold=1,
    )
    if observation_column in frame:
        grouped = pd.DataFrame(
            {
                "observation": frame[observation_column].astype(str),
                "score": values,
            }
        ).groupby("observation", sort=True)["score"]
        degenerate_outputs = [
            str(name)
            for name, group in grouped
            if not bool((group[np.isfinite(group)].abs() > tolerance).any())
        ]
        report.add(
            "morris_output_non_degenerate",
            not degenerate_outputs,
            "Every declared response has at least one materially non-zero Morris effect",
            actual={
                "degenerate_count": len(degenerate_outputs),
                "degenerate_outputs": degenerate_outputs,
            },
            threshold={"degenerate_count": 0},
        )
    return report


def load_morris_summary(path: str | Path) -> pd.DataFrame:
    """Load a PESTPP-SEN .mio file into the quality-gate schema."""
    frame = pd.read_csv(path)
    columns = {str(column).strip().lower(): column for column in frame.columns}
    observation = (
        columns.get("observation_name")
        or columns.get("obsnme")
        or columns.get("obsname")
        or columns.get("observation")
    )
    parameter = (
        columns.get("parameter_name")
        or columns.get("parnme")
        or columns.get("parname")
        or columns.get("parameter")
    )
    score = (
        columns.get("mu*")
        or columns.get("mu_star")
        or columns.get("mustar")
        or columns.get("sen_mean_abs")
    )
    if observation is None or parameter is None or score is None:
        raise ValueError(f"Unexpected Morris summary columns: {list(frame.columns)}")
    return frame.rename(
        columns={observation: "obs", parameter: "par", score: "score"}
    )


def assess_morris_audit(
    audit: dict[str, Any],
    *,
    run_id: str = "",
    require_zero_model_failures: bool = True,
) -> QualityReport:
    """Require complete, trajectory-balanced Morris evidence before ranking."""
    summary = dict(audit.get("summary") or {})
    report = QualityReport(run_type="morris_run", run_id=run_id or str(summary.get("case", "")))
    planned = int(summary.get("planned_runs", 0) or 0)
    not_finalized = int(summary.get("not_finalized_runs", planned) or 0)
    runtime_failed = int(summary.get("runtime_failed_runs", 0) or 0)
    unknown_failed = int(summary.get("unknown_failed_runs", 0) or 0)
    model_failed = int(summary.get("model_failed_runs", 0) or 0)
    expected_trajectories = int(summary.get("expected_trajectories", 0) or 0)
    fully_valid = int(summary.get("fully_valid_trajectories", 0) or 0)
    minimum_effects = int(summary.get("minimum_valid_effects_per_parameter", 0) or 0)
    process_state = str(summary.get("process_state", ""))

    process_completed = (
        planned > 0
        and process_state == "completed"
        and not_finalized == 0
        and runtime_failed == 0
        and unknown_failed == 0
    )
    report.add(
        "process_completed",
        process_completed,
        "PEST++ manager completed and every planned run has a non-runtime terminal outcome",
        actual={"state": process_state, "not_finalized": not_finalized},
        threshold={"state": "completed", "not_finalized": 0},
    )
    report.add(
        "morris_no_runtime_failures",
        runtime_failed == 0 and unknown_failed == 0,
        "No interruption/runtime/unknown failures are mixed with model outcomes",
        actual=runtime_failed + unknown_failed,
        threshold=0,
    )
    report.add(
        "morris_no_model_failures",
        model_failed == 0 or not require_zero_model_failures,
        "Formal Morris rankings require a model-valid rectangular design domain",
        actual=model_failed,
        threshold=0,
        warning=not require_zero_model_failures and model_failed > 0,
    )
    report.add(
        "morris_complete_trajectories",
        expected_trajectories > 0 and fully_valid == expected_trajectories,
        "Every Morris trajectory contains only successful model evaluations",
        actual=fully_valid,
        threshold=expected_trajectories,
    )
    report.add(
        "morris_balanced_effect_coverage",
        expected_trajectories > 0 and minimum_effects == expected_trajectories,
        "Every parameter has the requested number of valid elementary effects",
        actual=minimum_effects,
        threshold=expected_trajectories,
    )
    report.add(
        "morris_final_summary_exists",
        bool(summary.get("mio_exists")),
        "PESTPP-SEN produced the final Morris summary (.mio)",
        actual=bool(summary.get("mio_exists")),
        threshold=True,
    )
    report.add(
        "morris_design_structure",
        not audit.get("design_warnings"),
        "Each trajectory step changes exactly one parameter",
        actual=len(audit.get("design_warnings") or []),
        threshold=0,
    )
    return report


def assess_sobol(
    frame: pd.DataFrame,
    *,
    run_id: str = "",
    columns: Iterable[str] = ("Si", "STi", "S1", "ST"),
    tolerance: float = 1e-12,
) -> QualityReport:
    """Reject empty or all-zero Sobol indices."""
    report = QualityReport(run_type="sobol", run_id=run_id)
    report.add("process_completed", not frame.empty, "Sobol result table was produced", actual=len(frame), threshold=1)
    present = [column for column in columns if column in frame]
    report.add("sobol_columns", bool(present), "At least one supported Sobol index column exists", actual=present)
    if not present:
        return report
    values = pd.concat([pd.to_numeric(frame[column], errors="coerce") for column in present], ignore_index=True)
    finite = values[np.isfinite(values)]
    report.add(
        "sobol_finite",
        len(finite) == len(values) and len(finite) > 0,
        "All Sobol indices are finite",
        actual=len(finite),
        threshold=len(values),
    )
    nonzero = int((finite.abs() > tolerance).sum())
    report.add("sobol_non_degenerate", nonzero > 0, "At least one Sobol index is materially non-zero", actual=nonzero, threshold=1)
    return report


def assess_ies(
    parameter_initial: pd.DataFrame,
    observation_ensemble: pd.DataFrame,
    *,
    parameter_final: pd.DataFrame | None = None,
    phi_values: pd.DataFrame | pd.Series | None = None,
    run_id: str = "",
    tolerance: float = 1e-12,
    max_invalid_fraction: float = 0.0,
    max_realization_loss_fraction: float = 0.10,
    min_realizations: int = 2,
) -> QualityReport:
    """Check ensemble variation, objective variation, and parameter updating."""
    report = QualityReport(run_type="ies", run_id=run_id)
    report.add(
        "process_completed",
        not parameter_initial.empty and not observation_ensemble.empty,
        "IES parameter and simulated-observation ensembles exist",
    )
    par_numeric = parameter_initial.apply(pd.to_numeric, errors="coerce")
    obs_numeric = observation_ensemble.apply(pd.to_numeric, errors="coerce").replace(-99.0, np.nan)
    report.add(
        "ies_ensemble_size",
        len(par_numeric) >= int(min_realizations),
        "Prior ensemble contains enough realizations to assess variation",
        actual=len(par_numeric),
        threshold=int(min_realizations),
    )
    unique_indices = par_numeric.index.is_unique and obs_numeric.index.is_unique
    report.add(
        "ies_unique_realizations",
        unique_indices,
        "Parameter and observation realization identifiers are unique",
    )
    par_invalid_fraction = float(par_numeric.isna().sum().sum()) / max(int(par_numeric.size), 1)
    obs_invalid_fraction = float(obs_numeric.isna().sum().sum()) / max(int(obs_numeric.size), 1)
    report.add(
        "ies_parameter_finite",
        par_invalid_fraction <= max_invalid_fraction,
        "Prior parameter ensemble contains finite numeric values",
        actual=par_invalid_fraction,
        threshold=max_invalid_fraction,
    )
    report.add(
        "ies_observation_finite",
        obs_invalid_fraction <= max_invalid_fraction,
        "Simulated-observation failures remain below the configured limit",
        actual=obs_invalid_fraction,
        threshold=max_invalid_fraction,
    )
    initial_ids = set(map(str, par_numeric.index))
    observation_ids = set(map(str, obs_numeric.index))
    retained_fraction = len(initial_ids & observation_ids) / max(len(initial_ids), 1)
    report.add(
        "ies_realization_alignment",
        retained_fraction >= 1.0 - max_realization_loss_fraction,
        "Simulated observations retain the required fraction of prior realizations",
        actual=retained_fraction,
        threshold=1.0 - max_realization_loss_fraction,
    )
    par_varying = int((par_numeric.var(axis=0, ddof=0) > tolerance).sum())
    obs_varying = int((obs_numeric.var(axis=0, ddof=0) > tolerance).sum())
    report.add("ies_prior_variation", par_varying > 0, "Adjustable prior parameters vary", actual=par_varying, threshold=1)
    report.add("ies_simulation_variation", obs_varying > 0, "Simulated observations vary across realizations", actual=obs_varying, threshold=1)

    if phi_values is None:
        report.add(
            "ies_phi_finite",
            False,
            "Phi values were not supplied",
            actual=0,
            threshold=1,
        )
        report.add("ies_phi_variation", False, "Phi values were not supplied")
    else:
        phi_all = pd.to_numeric(pd.Series(np.asarray(phi_values).ravel()), errors="coerce")
        phi = phi_all[np.isfinite(phi_all)]
        report.add(
            "ies_phi_finite",
            len(phi) == len(phi_all) and len(phi) > 0,
            "All supplied Phi values are finite",
            actual=len(phi),
            threshold=len(phi_all),
        )
        spread = float(phi.max() - phi.min()) if len(phi) else 0.0
        scale = max(float(phi.abs().mean()), 1.0) if len(phi) else 1.0
        relative_spread = spread / scale
        phi_relative_tolerance = 1e-8
        report.add(
            "ies_phi_variation",
            relative_spread > phi_relative_tolerance,
            "Phi differs materially across realizations or iterations",
            actual=relative_spread,
            threshold=phi_relative_tolerance,
        )

    if parameter_final is None:
        report.add("ies_parameter_update", False, "Final parameter ensemble was not supplied")
    else:
        initial = par_numeric.sort_index(axis=1)
        final = parameter_final.apply(pd.to_numeric, errors="coerce").reindex(columns=initial.columns)
        common = initial.index.intersection(final.index)
        final_retained_fraction = len(common) / max(len(initial), 1)
        report.add(
            "ies_final_realization_alignment",
            final_retained_fraction >= 1.0 - max_realization_loss_fraction,
            "Final parameters retain the required fraction of prior realizations",
            actual=final_retained_fraction,
            threshold=1.0 - max_realization_loss_fraction,
        )
        final_invalid_fraction = float(final.isna().sum().sum()) / max(int(final.size), 1)
        report.add(
            "ies_final_parameter_finite",
            final_invalid_fraction <= max_invalid_fraction,
            "Final parameter ensemble contains finite numeric values",
            actual=final_invalid_fraction,
            threshold=max_invalid_fraction,
        )
        if len(common):
            delta = (final.loc[common] - initial.loc[common]).abs().to_numpy()
            finite_delta = delta[np.isfinite(delta)]
            max_delta = float(finite_delta.max()) if finite_delta.size else 0.0
        else:
            max_delta = 0.0
        report.add("ies_parameter_update", max_delta > tolerance, "Parameter ensemble changes after assimilation", actual=max_delta, threshold=tolerance)
    return report


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value).replace("|", "\\|")
