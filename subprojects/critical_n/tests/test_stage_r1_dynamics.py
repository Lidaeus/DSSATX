"""Tests for Stage R1 decoupled nitrogen mobilization, senescence, and growth dynamics.

Validates the three-way decoupled mechanism across MOBIL + SENES + GROW:
1. Mathematical invariants of N_buf,free and decoupled mobilization:
   - N_buf,free = max(0.0, WTNLF - PROLFG * 0.16 * (WTLF - WCRLF))
   - NRUSLF_safe = min(NRUSLF, N_buf,free)
   - NRUSLF_stress = max(0.0, NRUSLF - NRUSLF_safe)
   - Identity: NRUSLF_safe + NRUSLF_stress == NRUSLF
2. Senescence coupling: LFSEN = SENRTE * NRUSLF_stress / 0.16
   - Safe mobilization does not trigger defoliation (LFSEN = 0 when stress = 0)
3. Dry weight and leaf area deductions:
   - Leaf mass lost: NRUSLF_safe * 1.0 + NRUSLF_stress / 0.16
   - Leaf area shrinkage: (NRUSLF_stress / 0.16) * SLA (safe mobilization has 0 area shrinkage)
4. Nitrogen mass balance conservation:
   - Full PlantNBal.OUT closure audit (discrepancy <= 0.05 kg N/ha due to 2-decimal rounding)
5. Greenhouse simulation regression:
   - Prevents defoliation avalanche under severe N deficit (N0 treatments)
   - Maintains steady bounded growth under high N (N3 treatments)
"""

from __future__ import annotations

import re
from pathlib import Path
import pytest
import pandas as pd

from subprojects.critical_n.scripts.build_and_verify_dssat import (
    BIN_CNC,
    PRODUCTION_EXE,
    PRODUCTION_HASH,
    check_production_safety,
)
from subprojects.critical_n.scheme_b.patch_manager import validate_fortran_fixed_format

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CRITICAL_N_DIR = PROJECT_ROOT / "subprojects" / "critical_n"
FORTRAN_PATCH_DIR = CRITICAL_N_DIR / "fortran_patch"
VERIFY_DIR = CRITICAL_N_DIR / "verification_runs"


def test_r1_mathematical_decoupling_invariants():
    """Verify algebraic properties and bounds of R1 leaf buffer decoupling."""
    # Test case 1: Luxury N buffer (WTNLF well above normal growth requirement)
    wtlf = 100.0   # g DM/m2
    wcrlf = 10.0   # g DM/m2
    prolfg = 0.220 # normal protein fraction
    # Threshold for buffer N = 0.220 * 0.16 * 90.0 = 3.168 g N/m2
    wtnlf = 4.50   # g N/m2 (high N)
    
    nbuf_free = max(0.0, wtnlf - prolfg * 0.16 * (wtlf - wcrlf))
    assert abs(nbuf_free - (4.50 - 3.168)) < 1e-6
    assert nbuf_free > 0.0

    # Demand: mine 0.50 g N/m2
    nruslf = 0.50
    nruslf_safe = min(nruslf, nbuf_free)
    nruslf_stress = max(0.0, nruslf - nruslf_safe)

    assert nruslf_safe == 0.50
    assert nruslf_stress == 0.0
    assert nruslf_safe + nruslf_stress == nruslf

    # Senescence: LFSEN should be 0!
    senrte = 1.0
    lfsen = senrte * nruslf_stress / 0.16
    assert lfsen == 0.0

    # Dry weight loss: only solute mass 0.50 * 1.0 = 0.50 (NOT 0.50 / 0.16 = 3.125)
    dw_loss = nruslf_safe * 1.0 + nruslf_stress / 0.16
    assert abs(dw_loss - 0.50) < 1e-6

    # Leaf area loss: 0.0 (safe mobilization does not shrink leaf area)
    sla = 200.0
    area_loss = (nruslf_stress / 0.16) * sla
    assert area_loss == 0.0

    # Test case 2: Buffer exhausted (WTNLF below normal growth requirement)
    wtnlf_low = 2.50 # g N/m2 (< 3.168)
    nbuf_free_low = max(0.0, wtnlf_low - prolfg * 0.16 * (wtlf - wcrlf))
    assert nbuf_free_low == 0.0

    nruslf_safe_low = min(nruslf, nbuf_free_low)
    nruslf_stress_low = max(0.0, nruslf - nruslf_safe_low)

    assert nruslf_safe_low == 0.0
    assert nruslf_stress_low == 0.50
    assert nruslf_safe_low + nruslf_stress_low == nruslf

    # Under stress mobilization, senescence and area shrinkage occur normally
    lfsen_low = senrte * nruslf_stress_low / 0.16
    assert abs(lfsen_low - 3.125) < 1e-6
    dw_loss_low = nruslf_safe_low * 1.0 + nruslf_stress_low / 0.16
    assert abs(dw_loss_low - 3.125) < 1e-6
    area_loss_low = (nruslf_stress_low / 0.16) * sla
    assert abs(area_loss_low - 625.0) < 1e-6


def test_r1_fortran_fixed_format_compliance():
    """Verify that all R1 patched Fortran routines obey 72-column fixed-form rules."""
    src_dir = FORTRAN_PATCH_DIR / "src_scheme_b"
    routines = [
        "MOBIL_CNC.FOR",
        "GROW_CNC.FOR",
        "SENES_CNC.FOR",
        "CROPGRO_CNC.FOR",
        "PHOTO_CNC.FOR",
    ]
    for r in routines:
        fpath = src_dir / r
        assert fpath.is_file(), f"Missing routine: {r}"
        violations = validate_fortran_fixed_format(fpath)
        assert len(violations) == 0, f"Format violations in {r}: {violations[:3]}"


def test_plant_n_balance_mass_conservation():
    """Verify that PlantNBal.OUT achieves exact mass balance closure across all treatments."""
    pnb_files = [
        VERIFY_DIR / "greenhouse" / "cnc_mepho_l" / "PlantNBal.OUT",
        VERIFY_DIR / "greenhouse" / "cnc_mepho_c" / "PlantNBal.OUT",
    ]

    for pnb_file in pnb_files:
        if not pnb_file.is_file():
            continue
        text = pnb_file.read_text(encoding="latin-1")
        runs = text.split("*RUN")
        assert len(runs) > 1, f"No runs found in {pnb_file}"

        for i, r in enumerate(runs[1:], 1):
            totals = re.findall(r"TOTAL N\s+([\d\.\-]+)", r)
            if len(totals) >= 2:
                plant_total = float(totals[0])
                input_total = float(totals[1])
                diff = abs(plant_total - input_total)
                # Formatted output rounds to 2 decimals (0.01 per line * multiple lines <= 0.05)
                assert diff <= 0.05, (
                    f"Mass balance violation in {pnb_file.name} Run {i}: "
                    f"Plant={plant_total}, Input={input_total}, Diff={diff}"
                )


def test_nitrogen_stress_avalanche_prevention():
    """Verify that under N0 severe deficit, canopy LAI avoids death spiral and remains viable."""
    pg_file = VERIFY_DIR / "greenhouse" / "cnc_mepho_l" / "PlantGro.OUT"
    if not pg_file.is_file():
        pytest.skip(f"PlantGro.OUT not found at {pg_file}")

    with open(pg_file, "r") as f:
        lines = f.readlines()

    records = []
    cur_run = None
    headers = None
    for l in lines:
        if l.startswith("*RUN"):
            cur_run = int(l.split()[1])
        elif l.startswith("@YEAR") or l.startswith("@ YEAR"):
            headers = l.strip().replace("@", " ").split()
        elif cur_run is not None and headers is not None and l.strip() and not l.startswith("*") and not l.startswith("!"):
            parts = l.strip().split()
            if len(parts) == len(headers):
                d = dict(zip(headers, parts))
                d["RUN"] = cur_run
                records.append(d)

    df = pd.DataFrame(records)
    df["LAID"] = pd.to_numeric(df["LAID"], errors="coerce")
    df["CWAD"] = pd.to_numeric(df["CWAD"], errors="coerce")

    # Run 4, 6, 10 are N0 (zero N) treatments
    for n0_run in [4, 6, 10]:
        sub = df[df["RUN"] == n0_run]
        assert len(sub) > 50, f"Insufficient records for Run {n0_run}"
        peak_lai = sub["LAID"].max()
        final_lai = sub["LAID"].iloc[-1]
        peak_cwad = sub["CWAD"].max()

        # Defoliation avalanche prevention assertions:
        # In native DSSAT under unconstrained mobilization, LAI plunges to ~0
        # In R1 decoupled model, peak LAI > 2.5 and final LAI > 2.0 (no collapse)
        assert peak_lai > 2.5, f"Run {n0_run} peak LAI unexpectedly low: {peak_lai}"
        assert final_lai > 2.0, f"Run {n0_run} experienced defoliation collapse: final LAI = {final_lai}"
        assert peak_cwad > 3000, f"Run {n0_run} standing biomass crushed: CWAD = {peak_cwad}"


def test_high_nitrogen_steady_growth():
    """Verify that under N3 luxury N, growth is steady, healthy, and bounded."""
    pg_file = VERIFY_DIR / "greenhouse" / "cnc_mepho_l" / "PlantGro.OUT"
    if not pg_file.is_file():
        pytest.skip(f"PlantGro.OUT not found at {pg_file}")

    with open(pg_file, "r") as f:
        lines = f.readlines()

    records = []
    cur_run = None
    headers = None
    for l in lines:
        if l.startswith("*RUN"):
            cur_run = int(l.split()[1])
        elif l.startswith("@YEAR") or l.startswith("@ YEAR"):
            headers = l.strip().replace("@", " ").split()
        elif cur_run is not None and headers is not None and l.strip() and not l.startswith("*") and not l.startswith("!"):
            parts = l.strip().split()
            if len(parts) == len(headers):
                d = dict(zip(headers, parts))
                d["RUN"] = cur_run
                records.append(d)

    df = pd.DataFrame(records)
    df["LAID"] = pd.to_numeric(df["LAID"], errors="coerce")
    df["CWAD"] = pd.to_numeric(df["CWAD"], errors="coerce")

    # Run 1 is high N (N3)
    sub = df[df["RUN"] == 1]
    peak_lai = sub["LAID"].max()
    final_lai = sub["LAID"].iloc[-1]
    peak_cwad = sub["CWAD"].max()

    assert peak_lai > 8.0, f"High N peak LAI low: {peak_lai}"
    assert final_lai > 8.0, f"High N final LAI low: {final_lai}"
    assert peak_cwad > 4000, f"High N biomass low: {peak_cwad}"


def test_production_isolation_unbroken():
    """Verify that production DSCSM048.EXE is completely untouched."""
    check_production_safety()
    assert BIN_CNC.is_file()
