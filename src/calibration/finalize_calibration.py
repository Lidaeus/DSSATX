"""Finalize a completed IES calibration with separate engineering/science gates.

The parallel runner may establish that an IES process completed, but that is
not evidence that the calibration is scientifically valid.  This entry point
is the only place that can promote a run to ``science_validated``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.common.quality import read_flat_run_manifest_field, serialize_manifest_scalar
from src.calibration.engineering_gate import engineering_status, profile_for_run
from src.calibration.stage_representative import resolve_final_iteration, write_stage_representative
from src.reporting.quality_gate import assess_ies_run


# During P2-MVP tooling development there are no machine-generated validation
# metrics, group-Phi audit artifacts, or deterministic rerun certificates that
# can authorize a scientific claim.  Keep this hard-off until a reviewed
# implementation replaces the guard; user-provided booleans alone are never
# sufficient evidence.
SCIENCE_PROMOTION_ENABLED = False


def _sha256(path: Path) -> str | None:
    """SHA-256 of a file, or None if it does not exist (optional artifacts)."""
    if not path.is_file():
        return None
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_artifact_manifest(run_dir: Path, case: str, representative: dict[str, str] | None) -> Path:
    """Write a minimal SHA-256 manifest for the core calibration artifacts.

    The run_manifest already binds inputs/bounds/policy/inheritance and the
    representative parameter file. This manifest closes the gap on the
    per-stage scientific artifacts that the run_manifest does not cover: the
    PST, the final parameter ensemble, the Phi table, the quality report, the
    member-status table, the finalize payload, and (when present) the
    representative deterministic-rerun outputs. Only the deterministic-rerun
    outputs under ``representative_deterministic_rerun/`` are hashed — the
    parallel ``_agents/`` temp trees are intentionally excluded so this stays a
    minimal, stable manifest rather than a full run archive.
    """
    run_dir = run_dir.resolve()
    quality_dir = run_dir / "ies_quality"
    rerun_dir = run_dir / "representative_deterministic_rerun"
    # Resolve against PST noptmax and the Phi table so stale files copied from
    # an older, longer run cannot be promoted as current evidence.
    final_iter = -1
    final_par = None
    final_obs = None
    if run_dir.is_dir():
        try:
            final_iter, final_par = resolve_final_iteration(run_dir, case)
        except FileNotFoundError:
            pass
    if final_iter >= 0:
        candidate = run_dir / f"{case}.{final_iter}.obs.csv"
        if candidate.is_file():
            final_obs = candidate
    rerun_outputs = []
    if rerun_dir.is_dir():
        for entry in sorted(rerun_dir.iterdir()):
            if entry.is_file() and entry.suffix == ".OUT":
                rerun_outputs.append(entry)
    candidates = [
        ("pst", run_dir / f"{case}.pst"),
        ("final_parameter_ensemble", final_par),
        ("final_observation_ensemble", final_obs),
        ("phi_actual", run_dir / f"{case}.phi.actual.csv"),
        ("quality_report", quality_dir / "ies_run_quality.json"),
        ("member_status", quality_dir / f"{case}.member_status.csv"),
        ("finalize_payload", run_dir / "calibration_finalize" / "calibration_finalize.json"),
        ("stage_representative_params", run_dir / "calibration_finalize" / "stage_representative_params.csv"),
    ]
    artifacts = []
    for role, path in candidates:
        if path is None:
            continue
        digest = _sha256(path)
        if digest is None:
            continue
        artifacts.append({"role": role, "path": path.relative_to(run_dir).as_posix(), "sha256": digest})
    for path in rerun_outputs:
        digest = _sha256(path)
        if digest:
            artifacts.append({
                "role": "representative_deterministic_rerun_output",
                "path": path.relative_to(run_dir).as_posix(),
                "sha256": digest,
            })
    manifest = {
        "schema_version": 1,
        "case": case,
        "run_dir": str(run_dir),
        "generated_by": "src.calibration.finalize_calibration._write_artifact_manifest",
        "scope": (
            "Minimal SHA-256 manifest for core per-stage calibration artifacts "
            "(PST, final ensemble, Phi, quality report, member status, finalize "
            "payload, representative params, representative deterministic-rerun "
            "outputs). Excludes _agents/ temp trees and manager logs."
        ),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }
    out_path = run_dir / "calibration_finalize" / "calibration_artifacts_manifest.json"
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def verify_calibration_artifact_manifest(
    run_dir: str | Path,
    case: str,
    *,
    required_rerun_outputs: set[str] | None = None,
) -> dict[str, Any]:
    """Verify finalized core artifacts before a downstream tool reads them.

    Artifact paths are resolved relative to ``run_dir`` instead of trusting
    the absolute descriptive path in the JSON, so copied run bundles remain
    verifiable. Missing, duplicate, escaping, or hash-mismatched entries fail.
    """
    run_dir = Path(run_dir).resolve()
    manifest_path = run_dir / "calibration_finalize" / "calibration_artifacts_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"calibration artifact manifest not found: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid calibration artifact manifest: {manifest_path}") from exc
    if str(payload.get("case") or "") != case:
        raise ValueError(
            f"artifact manifest case {payload.get('case')!r} does not match {case!r}"
        )
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or payload.get("artifact_count") != len(artifacts):
        raise ValueError("artifact manifest count does not match its artifact entries")
    required_roles = {
        "pst",
        "final_parameter_ensemble",
        "final_observation_ensemble",
        "phi_actual",
        "quality_report",
        "member_status",
        "finalize_payload",
        "stage_representative_params",
    }
    roles: set[str] = set()
    seen_paths: set[str] = set()
    rerun_names: set[str] = set()
    for entry in artifacts:
        if not isinstance(entry, dict):
            raise ValueError("artifact manifest entries must be objects")
        role = str(entry.get("role") or "").strip()
        relative = str(entry.get("path") or "").strip().replace("\\", "/")
        expected = str(entry.get("sha256") or "").strip().lower()
        if not role or not relative or len(expected) != 64:
            raise ValueError(f"invalid artifact manifest entry: {entry!r}")
        if relative in seen_paths:
            raise ValueError(f"duplicate artifact path in manifest: {relative}")
        seen_paths.add(relative)
        path = (run_dir / Path(relative)).resolve()
        try:
            path.relative_to(run_dir)
        except ValueError as exc:
            raise ValueError(f"artifact path escapes run directory: {relative}") from exc
        actual = _sha256(path)
        if actual is None:
            raise FileNotFoundError(f"manifest artifact is missing: {path}")
        if actual.lower() != expected:
            raise ValueError(
                f"artifact hash mismatch for {relative}: expected {expected}, got {actual}"
            )
        roles.add(role)
        if role == "representative_deterministic_rerun_output":
            rerun_names.add(Path(relative).name)
    missing_roles = sorted(required_roles - roles)
    if missing_roles:
        raise ValueError(
            "artifact manifest is missing required roles: " + ", ".join(missing_roles)
        )
    missing_rerun = sorted((required_rerun_outputs or set()) - rerun_names)
    if missing_rerun:
        raise ValueError(
            "artifact manifest is missing required deterministic rerun outputs: "
            + ", ".join(missing_rerun)
            + "; run finalize_calibration.py again after the representative rerun"
        )
    return payload


def _upsert_manifest_fields(path: Path, fields: dict[str, Any]) -> None:
    """Replace generated scalar fields without leaving stale duplicate keys.

    Values are serialized with ``serialize_manifest_scalar`` so that Windows
    paths (with backslashes) render as YAML single-quoted scalars and remain
    valid under both the project reader and a standard YAML parser.
    """
    existing = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    keys = set(fields)
    kept = [line for line in existing if not any(line.startswith(f"{key}:") for key in keys)]
    kept.extend(f"{key}: {serialize_manifest_scalar(value)}" for key, value in fields.items())
    path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")


def _science_evidence(run_dir: Path) -> tuple[bool, list[str]]:
    """Require an explicit, frozen science evidence manifest.

    The automatic IES audit intentionally cannot promote a run.  A later
    review step must write ``science_validation_manifest.json`` with all four
    prerequisites true and the split/design hashes bound to the run.
    """
    if not SCIENCE_PROMOTION_ENABLED:
        return False, ["science_promotion_disabled_until_machine_evidence"]
    manifest_path = run_dir / "run_manifest.yaml"
    approval_scope = (
        read_flat_run_manifest_field(manifest_path, "approval_scope")
        if manifest_path.is_file()
        else None
    )
    if str(approval_scope or "").strip().lower() == "tooling_development":
        return False, ["tooling_development_run"]
    path = run_dir / "science_validation_manifest.json"
    if not path.is_file():
        return False, ["science_validation_manifest_missing"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, ["science_validation_manifest_invalid"]
    required = ("group_phi_checked", "deterministic_rerun_checked", "validation_split_frozen", "source_hashes_bound")
    missing = [key for key in required if payload.get(key) is not True]
    return not missing, missing


def finalize_calibration(run_dir: str | Path, case: str) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    report = assess_ies_run(run_dir, case)
    quality_dir = run_dir / "ies_quality"
    quality_dir.mkdir(parents=True, exist_ok=True)
    report.write(quality_dir, stem="ies_run_quality")
    representative = write_stage_representative(run_dir, case)
    profile = profile_for_run(run_dir, case)
    engineering_status_value, engineering_failures = engineering_status(report, profile)
    _science_ok, science_failures = _science_evidence(run_dir)
    # During tooling development both engineering success and failure remain
    # non-scientific outcomes.  Keep one stable downstream state and expose
    # the engineering failures separately.
    science_status = "science_pending"
    payload = {
        "schema_version": 1,
        "case": case,
        "engineering_status": engineering_status_value,
        "engineering_failures": engineering_failures,
        "science_status": science_status,
        "science_failures": science_failures,
        "scientific_status": "validated" if science_status == "science_validated" else "not_assessed",
        "quality_report": str(run_dir / "ies_quality" / "ies_run_quality.json"),
        "member_status": str(run_dir / "ies_quality" / f"{case}.member_status.csv"),
        "engineering_profile": profile,
        "stage_representative": representative or {},
    }
    manifest_path = run_dir / "run_manifest.yaml"
    manifest_stage = read_flat_run_manifest_field(manifest_path, "design_stage") if manifest_path.is_file() else None
    manifest_design = read_flat_run_manifest_field(manifest_path, "design_table_id") if manifest_path.is_file() else None
    manifest_scope = read_flat_run_manifest_field(manifest_path, "approval_scope") if manifest_path.is_file() else None
    payload.update({
        "design_stage": manifest_stage,
        "design_table_id": manifest_design,
        "approval_scope": manifest_scope,
    })
    out_dir = run_dir / "calibration_finalize"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_manifest_path = out_dir / "calibration_artifacts_manifest.json"
    # Persist the manifest path before hashing the finalize payload. The
    # artifact manifest intentionally does not hash itself, avoiding a
    # circular dependency while keeping the payload provenance complete.
    payload["calibration_artifacts_manifest"] = str(artifact_manifest_path)
    (out_dir / "calibration_finalize.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if manifest_path.is_file() and representative:
        _upsert_manifest_fields(manifest_path, {
            "stage_representative_params": representative["path"],
            "stage_representative_params_sha256": representative["sha256"],
            "stage_representative_rule": representative["rule"],
            "stage_representative_source": representative["source"],
            "stage_representative_source_sha256": representative["source_sha256"],
        })
    status_path = run_dir / "run_status.json"
    status = {}
    if status_path.is_file():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            status = {}
    status.update({
        "engineering_status": engineering_status_value,
        "engineering_status_error": ", ".join(engineering_failures),
        "science_status": science_status,
        "science_status_error": ", ".join(science_failures),
        "scientific_status": payload["scientific_status"],
        "finalized_by": "src.calibration.finalize_calibration",
    })
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_artifact_manifest(run_dir, case, representative)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize an IES calibration with engineering/science gates")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    payload = finalize_calibration(args.run_dir, args.case)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["engineering_status"] == "engineering_validated" else 2


if __name__ == "__main__":
    raise SystemExit(main())
