"""Preflight gates for starting a formal P1 sensitivity analysis."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.common.param_registry import validate_frozen_bounds
from src.common.quality import QualityReport
from src.common.project import sha256_file


def _read_flat_metadata(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if not path.is_file():
        return metadata
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"\'')
    return metadata


def assess_p1_bounds(
    bounds_csv: str | Path,
    *,
    metadata_path: str | Path | None = None,
    max_active_parameters: int = 60,
    require_approval: bool = True,
) -> QualityReport:
    """Assess whether a bounds file is technically and procedurally P1-ready."""
    bounds = Path(bounds_csv).resolve()
    report = QualityReport(run_type="p1_bounds_readiness", run_id=bounds.stem)
    report.add(
        "process_completed",
        bounds.is_file(),
        "Bounds file exists and can be assessed",
        actual=str(bounds),
    )
    if not bounds.is_file():
        return report

    issues = validate_frozen_bounds(str(bounds))
    errors = [issue for issue in issues if issue.severity == "error"]
    report.add(
        "p1_bounds_valid",
        not errors,
        "Bounds pass the shared immutable-input validator",
        actual=len(errors),
        threshold=0,
    )
    try:
        frame = pd.read_csv(bounds)
    except Exception as exc:
        report.add("p1_bounds_readable", False, f"Cannot parse bounds CSV: {exc}")
        return report
    required = {"name", "status", "location", "cultivar", "ecotype", "mode"}
    if not required.issubset(frame.columns):
        report.add(
            "p1_bounds_columns",
            False,
            "P1 readiness columns are present",
            actual=sorted(set(frame.columns)),
            threshold=sorted(required),
        )
        return report

    status = frame["status"].astype(str).str.strip().str.lower()
    location = frame["location"].astype(str).str.strip().str.upper()
    active = frame[status == "active"]
    nuisance_active = frame[(status == "active") & location.isin({"SOIL", "IC", "INIT"})]
    report.add(
        "p1_active_parameter_count",
        0 < len(active) <= int(max_active_parameters),
        "Active parameter count is non-zero and within the reviewed P1 screening budget",
        actual=len(active),
        threshold=f"1..{int(max_active_parameters)}",
    )
    report.add(
        "p1_nuisance_parameters_fixed",
        nuisance_active.empty,
        "SOIL and initial-condition parameters remain fixed unless separately approved",
        actual=len(nuisance_active),
        threshold=0,
    )

    contexts = frame[["cultivar", "ecotype", "mode"]].fillna("").astype(str).drop_duplicates()
    report.add(
        "p1_single_model_context",
        len(contexts) == 1,
        "One cultivar/ecotype/mode context is used in a P1 bounds file",
        actual=len(contexts),
        threshold=1,
    )

    metadata_file = Path(metadata_path).resolve() if metadata_path else bounds.with_suffix(".yaml")
    metadata = _read_flat_metadata(metadata_file)
    expected_hash = metadata.get("bounds_sha256") or metadata.get("proposal_sha256")
    actual_hash = sha256_file(bounds)
    report.add(
        "p1_bounds_hash_matches",
        bool(expected_hash) and expected_hash.lower() == actual_hash.lower(),
        "Bounds content matches the hash recorded in its review metadata",
        actual=actual_hash,
        threshold=expected_hash or "recorded hash required",
    )
    review_status = metadata.get("review_status", "missing").strip().lower()
    approved = review_status == "approved"
    report.add(
        "p1_bounds_approved",
        approved or not require_approval,
        "Formal P1 requires explicit approved metadata; proposals remain non-executable",
        actual=review_status,
        threshold="approved" if require_approval else "approval deferred for technical audit",
    )
    return report


__all__ = ["assess_p1_bounds"]
