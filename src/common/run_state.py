"""Canonical process-state semantics for long-running PEST++ jobs."""

from __future__ import annotations

from typing import Any


PROCESS_STATES = {
    "prepared",
    "launching",
    "running",
    "stopping",
    "completed",
    "aborted",
    "runtime_failed",
}

WINDOWS_CONTROL_C_EXIT = 0xC000013A


def normalize_exit_code(exit_code: int | None) -> int | None:
    """Return an unsigned 32-bit representation for Windows exit codes."""
    if exit_code is None:
        return None
    return int(exit_code) & 0xFFFFFFFF


def is_control_c_exit(exit_code: int | None) -> bool:
    return normalize_exit_code(exit_code) == WINDOWS_CONTROL_C_EXIT


def classify_manager_exit(
    exit_code: int | None,
    *,
    stop_requested: bool = False,
    keyboard_interrupt: bool = False,
) -> tuple[str, str]:
    """Classify manager termination without conflating aborts and failures."""
    normalized = normalize_exit_code(exit_code)
    if keyboard_interrupt or stop_requested or is_control_c_exit(normalized):
        return "aborted", "operator_or_external_interrupt"
    if normalized == 0:
        return "completed", "manager_exit_zero"
    return "runtime_failed", "manager_nonzero_exit"


def canonical_status(value: Any, *, exit_code: int | None = None) -> str:
    """Normalize legacy run_status.json values to the canonical vocabulary."""
    text = str(value or "").strip().lower()
    if text in PROCESS_STATES:
        return text
    if text.startswith("failed"):
        if is_control_c_exit(exit_code):
            return "aborted"
        return "runtime_failed"
    if text.startswith("complete"):
        return "completed"
    if text.startswith("run"):
        return "running"
    if text.startswith("stop"):
        return "stopping"
    return text or "prepared"
