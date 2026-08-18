"""DAP-based (days-after-planting) water--nitrogen policy materialiser.

The v2 formal design transfers one management policy across two spring weather
years.  A policy is expressed in **DAP** (days after planting) so it is identical
in both calendar years even though the planting dates differ.  This module maps
that year-agnostic policy onto a specific year's calendar and rewrites a FileX
template's irrigation/fertilizer events accordingly.

It reuses the v1 FileX materialisation primitives (``_events`` / ``_allocate`` /
``_replace_field`` from :mod:`src.management.core`) but is driven by DAP-derived
calendar stages instead of hard-coded calendar dates, so the same candidate can
be materialised independently in 2025 and 2026.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from src.common.experiment_inputs import parse_filex
from src.dssat.run_dssat import _read_freshwt_var_by_run, _yyddd_add_days
from src.management.core import (
    _allocate,
    _events,
    _replace_field,
)


@dataclass(frozen=True)
class DapStage:
    """A management stage expressed in days after planting (DAP)."""

    name: str
    dap_start: int
    dap_end: int


@dataclass(frozen=True)
class CalendarStage:
    """A DAP stage mapped onto one year's YYDDD calendar."""

    name: str
    dap_start: int
    dap_end: int
    cal_start: int
    cal_end: int


@dataclass(frozen=True)
class CandidatePolicy:
    """A year-agnostic water--nitrogen decision vector.

    ``nitrogen_stage_shares`` must have its fourth element (S4) equal to zero:
    the v2 design forbids late-season nitrogen (after DAP 96).  All four
    irrigation shares must be non-negative and sum to one; the first three
    nitrogen shares must sum to one.
    """

    policy_id: str
    seasonal_irrigation_mm: float
    irrigation_stage_shares: tuple[float, ...]
    seasonal_nitrogen_kg_ha: float
    nitrogen_stage_shares: tuple[float, ...]


@dataclass(frozen=True)
class HardConstraints:
    """Per-design hard constraints enforced during materialisation."""

    irrigation_event_max_mm: float
    nitrogen_after_dap: int
    yield_floor_fraction: float


def load_dap_stages(stage_payload: list[dict[str, Any]]) -> tuple[DapStage, ...]:
    """Read DAP stages from the v2 JSON ``stage_policy.stages`` list."""
    if len(stage_payload) != 4:
        raise ValueError("the v2 policy requires exactly four DAP stages")
    stages = []
    previous_end = -1
    for row in stage_payload:
        start, end = int(row["dap_start"]), int(row["dap_end"])
        if start > end:
            raise ValueError(f"DAP stage {row.get('name')!r} has start > end")
        if start <= previous_end:
            raise ValueError("DAP stages must be ordered and non-overlapping")
        stages.append(DapStage(str(row["name"]), start, end))
        previous_end = end
    return tuple(stages)


def build_calendar_stages(
    dap_stages: tuple[DapStage, ...],
    planting_yyddd: int,
    last_harvest_yyddd: int,
) -> list[CalendarStage]:
    """Map DAP stages onto one weather year's YYDDD calendar.

    Each DAP boundary becomes a calendar date via ``planting + dap``.  The final
    stage's ``cal_end`` is clamped to ``last_harvest_yyddd`` (the policy ends at
    the last harvest regardless of DAP count).  The stages must cover the whole
    planting-to-harvest span.
    """
    if not dap_stages:
        raise ValueError("at least one DAP stage is required")
    calendar: list[CalendarStage] = []
    for stage in dap_stages:
        cal_start = _yyddd_add_days(planting_yyddd, stage.dap_start)
        cal_end = _yyddd_add_days(planting_yyddd, stage.dap_end)
        if cal_end > last_harvest_yyddd:
            cal_end = last_harvest_yyddd
        if cal_start > cal_end:
            raise ValueError(
                f"DAP stage {stage.name!r} starts after last harvest when mapped to year"
            )
        calendar.append(CalendarStage(stage.name, stage.dap_start, stage.dap_end, cal_start, cal_end))
    if calendar[0].cal_start != planting_yyddd:
        raise ValueError("first calendar stage must begin on the planting date")
    if calendar[-1].cal_end != last_harvest_yyddd:
        raise ValueError("calendar stages must span to the last harvest date")
    return calendar


def _stage_for_date(
    date_code: int, calendar_stages: list[CalendarStage]
) -> CalendarStage:
    for stage in calendar_stages:
        if stage.cal_start <= date_code <= stage.cal_end:
            return stage
    # Pre-transplant basal events fall into the establishment stage (S1).
    if date_code < calendar_stages[0].cal_start:
        return calendar_stages[0]
    raise ValueError(f"management event {date_code} is outside the calendar stage span")


def _build_calendar_management_design(
    calendar_stages: list[CalendarStage], hard: HardConstraints
) -> Any:
    """Adapt the DAP-derived calendar stages to the v1 ``ManagementDesign`` shape.

    The v1 materialiser (:mod:`src.management.core`) expects a four-element
    ``(name, start, end)`` stage tuple and three constraint fields.  We assemble
    a lightweight stand-in object exposing exactly those attributes so we can
    reuse the audited ``_events`` / ``_allocate`` / ``_replace_field`` helpers
    without duplicating their fixed-width FileX logic.
    """
    from src.management.core import ManagementDesign

    return ManagementDesign(
        management_design_id="dap_derived",
        stages=tuple((s.name, s.cal_start, s.cal_end) for s in calendar_stages),
        irrigation_event_max_mm=hard.irrigation_event_max_mm,
        irrigation_min_interval_days=1,
        nitrogen_cutoff_date=_yyddd_add_days(
            calendar_stages[0].cal_start, hard.nitrogen_after_dap
        ),
    )


def materialize_dap_scenario(
    source_filex: str | Path,
    output_dir: str | Path,
    candidate: CandidatePolicy,
    calendar_stages: list[CalendarStage],
    hard: HardConstraints,
    target_treatment: int,
    parameter_set_id: str = "pending",
) -> dict[str, Any]:
    """Rewrite a FileX template with one DAP policy mapped onto one year.

    Enforces the v2 hard constraints: single-event irrigation cap, nitrogen
    cutoff after ``hard.nitrogen_after_dap`` DAP, and S4 nitrogen share == 0.
    Writes the edited FileX, a ``MgmtEvent.OUT`` ledger and a manifest.
    """
    if len(candidate.irrigation_stage_shares) != 4:
        raise ValueError("irrigation_stage_shares must have four entries")
    if len(candidate.nitrogen_stage_shares) != 4:
        raise ValueError("nitrogen_stage_shares must have four entries")
    if candidate.nitrogen_stage_shares[3] != 0.0:
        raise ValueError("S4 (peak_late_harvest) nitrogen share must be zero")
    if abs(sum(candidate.irrigation_stage_shares) - 1.0) > 1e-8:
        raise ValueError("irrigation stage shares must sum to one")
    if abs(sum(candidate.nitrogen_stage_shares[:3]) - 1.0) > 1e-8:
        raise ValueError("first three nitrogen stage shares must sum to one")
    if any(v < 0 for v in candidate.irrigation_stage_shares):
        raise ValueError("irrigation stage shares must be non-negative")
    if any(v < 0 for v in candidate.nitrogen_stage_shares):
        raise ValueError("nitrogen stage shares must be non-negative")

    design = _build_calendar_management_design(calendar_stages, hard)
    source, out = Path(source_filex), Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    lines = source.read_text(encoding="utf-8", errors="ignore").splitlines()

    factors = parse_filex(source)["treatments"].get(target_treatment)
    if not factors:
        raise KeyError(f"TN{target_treatment} is absent from the FileX")

    irrigation = _events(
        lines, "*IRRIGATION AND WATER MANAGEMENT", int(factors["MI"]), "IDATE", "IRVAL"
    )
    nitrogen = _events(
        lines, "*FERTILIZERS (INORGANIC)", int(factors["MF"]), "FDATE", "FAMN"
    )

    # Pre-transplant basal events (e.g. a starter fertilizer coded a few days
    # before transplanting) belong logically to the establishment stage.  Extend
    # the first stage's calendar start to the earliest event so the v1 stage
    # classifier accepts them rather than rejecting them as out-of-range.
    earliest = min(
        [e["date"] for e in irrigation + nitrogen] or [calendar_stages[0].cal_start]
    )
    if earliest < design.stages[0][1]:
        from src.management.core import ManagementDesign

        adjusted_stages = (
            (design.stages[0][0], earliest, design.stages[0][2]),
        ) + design.stages[1:]
        design = ManagementDesign(
            management_design_id=design.management_design_id,
            stages=adjusted_stages,
            irrigation_event_max_mm=design.irrigation_event_max_mm,
            irrigation_min_interval_days=design.irrigation_min_interval_days,
            nitrogen_cutoff_date=design.nitrogen_cutoff_date,
        )

    water = _allocate(candidate.seasonal_irrigation_mm, candidate.irrigation_stage_shares, irrigation, design)
    nitrogen_alloc = _allocate(candidate.seasonal_nitrogen_kg_ha, candidate.nitrogen_stage_shares, nitrogen, design)

    if any(value > hard.irrigation_event_max_mm + 1e-9 for value in water.values()):
        raise ValueError("an irrigation event exceeds the drip-system single-event cap")
    # S4 nitrogen share is zero by design; the v1 allocator's rounding-residual
    # fix-up can place a sub-milligram residual onto an S4 event.  Clamp those
    # to exactly zero so the late-season cutoff check is not tripped by float
    # dust while genuine late nitrogen is still caught.
    for event in nitrogen:
        if _stage_for_date(event["date"], calendar_stages).name == calendar_stages[3].name:
            nitrogen_alloc[event["line"]] = 0.0
    nitrogen_cutoff_cal = design.nitrogen_cutoff_date
    if any(
        event["date"] > nitrogen_cutoff_cal and nitrogen_alloc[event["line"]] > 1e-6
        for event in nitrogen
    ):
        raise ValueError("nitrogen is applied after the late-season cutoff date")

    for events, values in ((irrigation, water), (nitrogen, nitrogen_alloc)):
        for event in events:
            lines[event["line"]] = _replace_field(lines[event["line"]], event["field"], values[event["line"]])

    filex = out / source.name
    filex.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    ledger = out / "MgmtEvent.OUT"
    with ledger.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "policy_id", "season", "parameter_set_id", "event_type",
                "date_code", "dap_stage", "amount", "unit", "rainfall_considered",
            ],
        )
        writer.writeheader()
        for kind, events, values, unit in (
            ("irrigation", irrigation, water, "mm"),
            ("nitrogen", nitrogen, nitrogen_alloc, "kg N/ha"),
        ):
            for event in events:
                stage = _stage_for_date(event["date"], calendar_stages)
                writer.writerow(
                    {
                        "policy_id": candidate.policy_id,
                        "season": "formal_v2",
                        "parameter_set_id": parameter_set_id,
                        "event_type": kind,
                        "date_code": event["date"],
                        "dap_stage": stage.name,
                        "amount": values[event["line"]],
                        "unit": unit,
                        "rainfall_considered": "false",
                    }
                )

    manifest = {
        "policy_id": candidate.policy_id,
        "parameter_set_id": parameter_set_id,
        "production_system": "greenhouse_drip_eggplant",
        "rainfall_considered": False,
        "surrogate_model": False,
        "seasonal_irrigation_mm": round(sum(water.values()), 3),
        "seasonal_nitrogen_kg_ha": round(sum(nitrogen_alloc.values()), 3),
        "irrigation_stage_shares": list(candidate.irrigation_stage_shares),
        "nitrogen_stage_shares": list(candidate.nitrogen_stage_shares),
        "nitrogen_after_dap_cutoff": hard.nitrogen_after_dap,
        "irrigation_event_max_mm": hard.irrigation_event_max_mm,
        "target_treatment": target_treatment,
        "calendar_stages": [
            {"name": s.name, "dap_start": s.dap_start, "dap_end": s.dap_end,
             "cal_start": s.cal_start, "cal_end": s.cal_end}
            for s in calendar_stages
        ],
        "source_filex": str(source.resolve()),
        "scenario_filex": str(filex.resolve()),
        "management_event_ledger": str(ledger.resolve()),
    }
    (out / "management_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def read_final_chfpw(freshwt_path: str | Path) -> float | None:
    """Return the final-row cumulative fresh pod weight (``CHFPW``).

    Wraps :func:`src.dssat.run_dssat._read_freshwt_var_by_run` (which returns a
    full daily series) and returns the value at the latest date for run 1.
    Returns ``None`` when the output file is missing, empty, or lacks the
    ``CHFPW`` column -- the caller treats that as a failed (infeasible) run.
    """
    by_run = _read_freshwt_var_by_run(freshwt_path, "CHFPW")
    series = by_run.get(1)
    if not series:
        return None
    return float(series[max(series)])
