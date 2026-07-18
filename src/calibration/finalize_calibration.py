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

from src.common.quality import read_flat_run_manifest_field
from src.calibration.engineering_gate import engineering_status, profile_for_run
from src.calibration.stage_representative import write_stage_representative
from src.reporting.quality_gate import assess_ies_run


# During P2-MVP tooling development there are no machine-generated validation
# metrics, group-Phi audit artifacts, or deterministic rerun certificates that
# can authorize a scientific claim.  Keep this hard-off until a reviewed
# implementation replaces the guard; user-provided booleans alone are never
# sufficient evidence.
SCIENCE_PROMOTION_ENABLED = False


def _upsert_manifest_fields(path: Path, fields: dict[str, str]) -> None:
    """Replace generated scalar fields without leaving stale duplicate keys."""
    existing = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    keys = set(fields)
    kept = [line for line in existing if not any(line.startswith(f"{key}:") for key in keys)]
    kept.extend(f'{key}: "{value}"' for key, value in fields.items())
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
