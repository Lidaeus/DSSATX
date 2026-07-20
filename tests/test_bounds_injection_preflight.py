"""T3 tests for the bounds-injection read-back verifier.

These tests exercise the verifier on a small synthetic bounds CSV (so they run
fast) and assert the outcome categories the preflight distinguishes.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sa.preflight_bounds_injection_20260720 import (
    verify_one_injection,
    run_preflight,
    _load_active_parameters,
    _values_match,
    _get_precision_tolerance,
    ReadbackResult,
)


def _write_synthetic_bounds(tmp_path: Path, rows: list[dict]) -> Path:
    """Write a minimal bounds CSV with the columns the preflight reads."""
    fields = ["name", "init", "lower", "upper", "status", "pargp", "location",
              "file", "cultivar", "ecotype", "mode"]
    out = tmp_path / "bounds.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    return out


def test_get_precision_tolerance():
    assert _get_precision_tolerance("0.3") == 0.05
    assert _get_precision_tolerance(".15") == 0.005
    assert _get_precision_tolerance("250") == 0.5
    assert _get_precision_tolerance("12.") == 0.5
    assert _get_precision_tolerance("") == 1e-6


def test_values_match_resolution(monkeypatch):
    # Mock template token retrieval to return "0.3" (1 dp, tolerance 0.05)
    monkeypatch.setattr(
        "tools.sa.preflight_bounds_injection_20260720._get_template_token",
        lambda pname, loc: "0.3"
    )
    # Requested 0.35, readback 0.3 -> diff 0.05 -> True
    assert _values_match(0.35, 0.3, "TEST", "ECO")
    # Requested 0.36, readback 0.3 -> diff 0.06 -> False
    assert not _values_match(0.36, 0.3, "TEST", "ECO")
    assert not _values_match(0.35, None, "TEST", "ECO")


def test_cul_parameter_injects_and_reads_back_exactly(tmp_path, monkeypatch):
    """LFMAX (CUL) at init should round-trip exactly — its field is wide enough."""
    from src.dssat import run_dssat as rd
    geno = PROJECT_ROOT / "data" / "templates" / "genotype"
    work = tmp_path / "lfmax_init"
    work.mkdir()
    monkeypatch.chdir(work)
    rd.CUL_FILE = "TMGRO048.CUL"
    rd.CUL_BASE_FILE = "TMGRO048.CUL.base"
    row = {
        "name": "LFMAX", "init": "1.27", "lower": "1.27", "upper": "1.36",
        "status": "active", "location": "CUL", "file": "TMGRO048.CUL.base",
    }
    result = verify_one_injection(row, "init", work)
    assert result.matched, f"LFMAX init should round-trip: requested={result.requested} readback={result.readback}"
    assert result.readback == pytest.approx(1.27)


def test_spe_temperature_parameter_round_trips(tmp_path, monkeypatch):
    """TB1 (SPE temperature stage 1) at upper should round-trip."""
    from src.dssat import run_dssat as rd
    work = tmp_path / "tb1_upper"
    work.mkdir()
    monkeypatch.chdir(work)
    rd.SPE_FILE = "TMGRO048.SPE"
    row = {
        "name": "TB1", "init": "9.2", "lower": "8.0", "upper": "12.0",
        "status": "active", "location": "SPE", "file": "TMGRO048.SPE.base",
    }
    result = verify_one_injection(row, "upper", work)
    assert result.matched, f"TB1 upper should round-trip: requested={result.requested} readback={result.readback}"
    assert result.readback == pytest.approx(12.0)


def integration_full_preflight_report_categories():
    """The full preflight on the real 55-param proposal. Excluded from normal pytest."""
    report = run_preflight()
    assert report.total_active == 55
    assert report.total_injections == 165  # 55 × 3 levels

    assert report.structural_violations == [], "No structural violations expected"

    param_names_with_errors = {
        r.parameter for r in report.readback_results if not r.matched
    }
    assert "PM06" not in param_names_with_errors, (
        "PM06 should round-trip exactly after the ECO field widening"
    )
    xfint_errors = [r for r in report.readback_results
                    if r.parameter == "XFINT" and not r.matched]
    assert not xfint_errors, (
        f"XFINT should pass after lower-bound correction to 0.12; got {xfint_errors}"
    )

    exact = sum(1 for r in report.readback_results if r.matched)
    assert exact == 165, f"All 165 injections should match within field resolution; got {exact}"


def test_load_active_parameters_filters_to_cul_eco_spe():
    bounds = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_proposals" / "eggplant" / "eggplant_formal_multiseason_candidate_v1_20260719.csv"
    active = _load_active_parameters(bounds)
    locations = {r["location"] for r in active}
    assert locations == {"CUL", "ECO", "SPE"}, f"Active params must be CUL/ECO/SPE only; got {locations}"
    assert len(active) == 55
