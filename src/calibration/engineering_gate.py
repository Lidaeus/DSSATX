"""Shared engineering acceptance profiles for persisted IES runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyemu


FORMAL_IES_CHECKS = frozenset({
    "process_completed",
    "ies_ensemble_size",
    "ies_unique_realizations",
    "ies_parameter_finite",
    "ies_observation_finite",
    "ies_realization_alignment",
    "ies_prior_variation",
    "ies_simulation_variation",
    "ies_phi_finite",
    "ies_phi_variation",
    "ies_final_realization_alignment",
    "ies_final_parameter_finite",
    "ies_parameter_update",
    "ies_iteration_progress",
    "ies_member_status_table",
})

PRIOR_ONLY_IES_CHECKS = FORMAL_IES_CHECKS - {
    "ies_parameter_update",
    "ies_iteration_progress",
}


def profile_for_run(run_dir: str | Path, prefix: str) -> str:
    """Return ``prior_only`` only for an explicit NOPTMAX<=0 PST."""
    pst = Path(run_dir) / f"{prefix}.pst"
    if pst.is_file():
        try:
            return "prior_only" if int(pyemu.Pst(str(pst)).control_data.noptmax) <= 0 else "formal_ies"
        except Exception:
            pass
    return "formal_ies"


def engineering_failures(report: Any, profile: str = "formal_ies") -> list[str]:
    required = PRIOR_ONLY_IES_CHECKS if profile == "prior_only" else FORMAL_IES_CHECKS
    checks = {check.check_id: check for check in report.checks}
    # A report that silently omits a required check is incomplete, not valid.
    return [
        check_id
        for check_id in sorted(required)
        if check_id not in checks or checks[check_id].status == "fail"
    ]


def engineering_status(report: Any, profile: str = "formal_ies") -> tuple[str, list[str]]:
    failed = engineering_failures(report, profile)
    return ("engineering_validated" if not failed else "engineering_failed", failed)
