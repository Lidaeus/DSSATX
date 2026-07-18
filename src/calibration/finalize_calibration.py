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
from src.reporting.quality_gate import assess_ies_run


ENGINEERING_CHECKS = {
    "process_completed",
    "ies_ensemble_size",
    "ies_unique_realizations",
    "ies_parameter_finite",
    "ies_observation_finite",
    "ies_realization_alignment",
    "ies_final_realization_alignment",
    "ies_final_parameter_finite",
    "ies_iteration_progress",
    "ies_member_status_table",
}


def _engineering_status(report: Any) -> tuple[str, list[str]]:
    failed = [c.check_id for c in report.checks if c.check_id in ENGINEERING_CHECKS and c.status == "fail"]
    return ("engineering_validated" if not failed else "engineering_failed", failed)


def _science_evidence(run_dir: Path) -> tuple[bool, list[str]]:
    """Require an explicit, frozen science evidence manifest.

    The automatic IES audit intentionally cannot promote a run.  A later
    review step must write ``science_validation_manifest.json`` with all four
    prerequisites true and the split/design hashes bound to the run.
    """
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
    engineering_status, engineering_failures = _engineering_status(report)
    science_ok, science_failures = _science_evidence(run_dir)
    science_status = "science_validated" if engineering_status == "engineering_validated" and science_ok else "science_pending"
    if engineering_status != "engineering_validated":
        science_status = "science_blocked"
    payload = {
        "schema_version": 1,
        "case": case,
        "engineering_status": engineering_status,
        "engineering_failures": engineering_failures,
        "science_status": science_status,
        "science_failures": science_failures,
        "scientific_status": "validated" if science_status == "science_validated" else "not_assessed",
        "quality_report": str(run_dir / "ies_quality" / "ies_run_quality.json"),
        "member_status": str(run_dir / "ies_quality" / f"{case}.member_status.csv"),
    }
    out_dir = run_dir / "calibration_finalize"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "calibration_finalize.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    status_path = run_dir / "run_status.json"
    status = {}
    if status_path.is_file():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            status = {}
    status.update({
        "engineering_status": engineering_status,
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
