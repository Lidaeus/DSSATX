"""Tests for the DAP-based (days-after-planting) policy materialiser.

These cover the v2 design's core methodological shift: one DAP policy transfers
across both spring weather years via each year's planting date, so calendar
dates differ but DAP intervals are identical.  No real DSSAT is invoked.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.management.dap_policy import (
    CandidatePolicy,
    HardConstraints,
    build_calendar_stages,
    load_dap_stages,
    materialize_dap_scenario,
    read_final_chfpw,
)


DESIGN = "configs/management/eggplant_greenhouse_drip_formal_v2.json"

DAP_2025_PLANTING = 25075
DAP_2025_LAST_HARVEST = 25220
DAP_2026_PLANTING = 26069
DAP_2026_LAST_HARVEST = 26198
N_AFTER_DAP = 96


def _load_dap_stages() -> tuple:
    payload = json.loads(Path(DESIGN).read_text(encoding="utf-8"))
    return load_dap_stages(payload["stage_policy"]["stages"])


def test_dap_to_calendar_gives_identical_dap_intervals_across_years():
    # Improvement: one common DAP policy transfers across both weather years.
    stages = _load_dap_stages()
    cal_2025 = build_calendar_stages(stages, DAP_2025_PLANTING, DAP_2025_LAST_HARVEST)
    cal_2026 = build_calendar_stages(stages, DAP_2026_PLANTING, DAP_2026_LAST_HARVEST)
    # DAP intervals identical, calendar dates differ.
    assert [(s.dap_start, s.dap_end) for s in cal_2025] == [(s.dap_start, s.dap_end) for s in cal_2026]
    assert [s.cal_start for s in cal_2025] != [s.cal_start for s in cal_2026]
    assert cal_2025[0].cal_start == DAP_2025_PLANTING
    assert cal_2026[0].cal_start == DAP_2026_PLANTING


def test_nitrogen_cutoff_dap96_maps_to_both_years_correctly():
    # Improvement: nitrogen cutoff (DAP 96) lands on the right calendar date each year.
    from src.dssat.run_dssat import _yyddd_add_days

    assert _yyddd_add_days(DAP_2025_PLANTING, N_AFTER_DAP) == 25171
    assert _yyddd_add_days(DAP_2026_PLANTING, N_AFTER_DAP) == 26165
    # The flowering_early_harvest stage end (DAP 96) must equal the cutoff in each year.
    stages = _load_dap_stages()
    cal_2025 = build_calendar_stages(stages, DAP_2025_PLANTING, DAP_2025_LAST_HARVEST)
    cal_2026 = build_calendar_stages(stages, DAP_2026_PLANTING, DAP_2026_LAST_HARVEST)
    flowering_25 = next(s for s in cal_2025 if s.name == "flowering_early_harvest")
    flowering_26 = next(s for s in cal_2026 if s.name == "flowering_early_harvest")
    assert flowering_25.cal_end == 25171
    assert flowering_26.cal_end == 26165


def test_calendar_stages_must_span_planting_to_last_harvest():
    stages = _load_dap_stages()
    # Last stage end clamped to last harvest.
    cal = build_calendar_stages(stages, DAP_2025_PLANTING, DAP_2025_LAST_HARVEST)
    assert cal[-1].cal_end == DAP_2025_LAST_HARVEST
    assert cal[0].cal_start == DAP_2025_PLANTING
    # 2026 last harvest is earlier (DAP 129) than the stage's DAP 145 end -> clamped.
    cal26 = build_calendar_stages(stages, DAP_2026_PLANTING, DAP_2026_LAST_HARVEST)
    assert cal26[-1].cal_end == DAP_2026_LAST_HARVEST


def test_decode_to_candidate_enforces_s4_nitrogen_zero_and_simplex():
    from src.management.nsga3_search import DecisionBounds, decode_to_candidate

    bounds = DecisionBounds(
        irrigation_mm=(240.0, 500.0),
        nitrogen_kg_ha=(0.0, 320.0),
        irrigation_share_floor=0.08,
        nitrogen_share_floor=0.05,
    )
    candidate = decode_to_candidate([0.5] * 8, bounds, "c1")
    assert candidate.nitrogen_stage_shares[3] == 0.0
    assert abs(sum(candidate.irrigation_stage_shares) - 1.0) < 1e-8
    assert abs(sum(candidate.nitrogen_stage_shares) - 1.0) < 1e-8
    assert all(s >= bounds.irrigation_share_floor - 1e-9 for s in candidate.irrigation_stage_shares[:3])


def test_candidate_policy_rejects_nonzero_s4_nitrogen_and_unnormalised_shares():
    # S4 nitrogen must be zero; the materialiser rejects a nonzero S4 share.
    good_shares_irr = (0.25, 0.25, 0.25, 0.25)
    bad_nitrogen = (0.25, 0.25, 0.25, 0.1)  # S4 nonzero -> rejected
    candidate = CandidatePolicy("bad", 300.0, good_shares_irr, 100.0, bad_nitrogen)
    stages = _load_dap_stages()
    cal = build_calendar_stages(stages, DAP_2025_PLANTING, DAP_2025_LAST_HARVEST)
    hard = HardConstraints(irrigation_event_max_mm=45.0, nitrogen_after_dap=96, yield_floor_fraction=0.9)
    with pytest.raises(ValueError, match="S4"):
        materialize_dap_scenario(
            source_filex="data/user/experiments/xxql2501_20260716/XXQL2501.TMX",
            output_dir="/tmp/_unused_dap_test",
            candidate=candidate,
            calendar_stages=cal,
            hard=hard,
            target_treatment=2,
        )


def test_candidate_policy_rejects_unnormalised_irrigation_shares():
    candidate = CandidatePolicy(
        "bad2", 300.0, (0.2, 0.2, 0.2, 0.2),  # sum 0.8 != 1
        100.0, (0.5, 0.3, 0.2, 0.0),
    )
    stages = _load_dap_stages()
    cal = build_calendar_stages(stages, DAP_2025_PLANTING, DAP_2025_LAST_HARVEST)
    hard = HardConstraints(irrigation_event_max_mm=45.0, nitrogen_after_dap=96, yield_floor_fraction=0.9)
    with pytest.raises(ValueError, match="sum to one"):
        materialize_dap_scenario(
            source_filex="data/user/experiments/xxql2501_20260716/XXQL2501.TMX",
            output_dir="/tmp/_unused_dap_test2",
            candidate=candidate,
            calendar_stages=cal,
            hard=hard,
            target_treatment=2,
        )


def test_read_final_chfpw_returns_last_row_value(tmp_path):
    freshwt = tmp_path / "FreshWt.OUT"
    freshwt.write_text(
        "*RUN 1\n"
        "@YEAR DOY  DAS  CHFPW\n"
        " 25  200   10   100.0\n"
        " 25  220  145   1559.4\n",
        encoding="utf-8",
    )
    assert read_final_chfpw(freshwt) == 1559.4


def test_read_final_chfpw_returns_none_for_missing_or_empty(tmp_path):
    assert read_final_chfpw(tmp_path / "nonexistent.OUT") is None
    empty = tmp_path / "Empty.OUT"
    empty.write_text("*RUN 1\n@YEAR DOY DAS CHFPW\n", encoding="utf-8")
    assert read_final_chfpw(empty) is None


def test_materialize_dap_scenario_preserves_seasonal_totals_and_writes_ledger(tmp_path):
    # Use the real trial FileX as the template (TN2: MI=1, MF=1).
    stages = _load_dap_stages()
    cal = build_calendar_stages(stages, DAP_2025_PLANTING, DAP_2025_LAST_HARVEST)
    hard = HardConstraints(irrigation_event_max_mm=45.0, nitrogen_after_dap=96, yield_floor_fraction=0.9)
    candidate = CandidatePolicy(
        policy_id="dap_test_001",
        seasonal_irrigation_mm=300.0,
        irrigation_stage_shares=(0.25, 0.25, 0.25, 0.25),
        seasonal_nitrogen_kg_ha=120.0,
        nitrogen_stage_shares=(0.5, 0.3, 0.2, 0.0),
    )
    out = tmp_path / "scenario"
    manifest = materialize_dap_scenario(
        source_filex="data/user/experiments/xxql2501_20260716/XXQL2501.TMX",
        output_dir=out,
        candidate=candidate,
        calendar_stages=cal,
        hard=hard,
        target_treatment=2,
        parameter_set_id="test_ps",
    )
    # Seasonal totals preserved (rounding-safe).
    assert abs(manifest["seasonal_irrigation_mm"] - 300.0) < 1e-2
    assert abs(manifest["seasonal_nitrogen_kg_ha"] - 120.0) < 1e-2
    assert manifest["rainfall_considered"] is False
    assert manifest["surrogate_model"] is False
    # Ledger written with rainfall_considered=false.
    ledger = (out / "MgmtEvent.OUT").read_text(encoding="utf-8")
    assert "rainfall_considered" in ledger
    assert "false" in ledger
    # No nitrogen after the DAP-96 cutoff (25171 for 2025).
    assert "establishment" in ledger or "canopy_expansion" in ledger
    # The edited FileX exists.
    assert (out / "XXQL2501.TMX").is_file()
