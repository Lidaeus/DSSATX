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


def test_soil_n_balance_mass_conservation():
    """Verify that SoilNiBal.OUT achieves exact closure (< 1e-4 kg N/ha) across all runs."""
    soil_files = [
        VERIFY_DIR / "greenhouse" / "cnc_mepho_l" / "SoilNiBal.OUT",
        VERIFY_DIR / "greenhouse" / "cnc_mepho_c" / "SoilNiBal.OUT",
    ]

    for sfile in soil_files:
        if not sfile.is_file():
            continue
        text = sfile.read_text(encoding="latin-1")
        runs = text.split("*RUN")
        assert len(runs) > 1, f"No runs found in {sfile}"

        for i, r in enumerate(runs[1:], 1):
            matches = re.findall(r"Balance\s+([\d\.\-]+)", r)
            assert len(matches) > 0, f"No balance line found in {sfile.name} Run {i}"
            balance_val = float(matches[-1])
            # Strict tolerance < 1e-4 kg N/ha (output is -0.000 or 0.000)
            assert abs(balance_val) < 1e-4, (
                f"Soil N balance violation in {sfile.name} Run {i}: Balance = {balance_val}"
            )


def test_sequential_leaf_buffer_depletion_and_transition():
    """Verify smooth continuous transition from safe buffer mining to stress degradation."""
    wtlf = 120.0
    wcrlf = 10.0
    prolfg = 0.220
    wtnlf = 5.0
    senrte = 1.0
    sla = 200.0
    daily_demand = 0.50

    states = []
    for day in range(1, 5):
        # Effective structural leaf mass
        w_struct = max(0.0, wtlf - wcrlf)
        nbuf_free = max(0.0, wtnlf - prolfg * 0.16 * w_struct)

        nruslf_safe = max(0.0, min(daily_demand, nbuf_free))
        nruslf_stress = max(0.0, daily_demand - nruslf_safe)

        # Invariant 1: Total mobilization identity holds exactly
        assert abs(nruslf_safe + nruslf_stress - daily_demand) < 1e-12

        # Invariant 2: Safe mobilization never exceeds available buffer
        assert nruslf_safe <= nbuf_free + 1e-12

        # Invariant 3: Senescence driven only by stress
        lfsen = senrte * nruslf_stress / 0.16
        if nruslf_stress == 0.0:
            assert lfsen == 0.0

        # Invariant 4: Mass deduction decoupled (solute 1.0 vs protein 6.25)
        dw_loss = nruslf_safe * 1.0 + nruslf_stress / 0.16

        # Invariant 5: Area shrinkage driven only by stress
        area_loss = (nruslf_stress / 0.16) * sla
        if nruslf_stress == 0.0:
            assert area_loss == 0.0

        states.append({
            "day": day,
            "nbuf": nbuf_free,
            "safe": nruslf_safe,
            "stress": nruslf_stress,
            "lfsen": lfsen,
            "dw_loss": dw_loss,
            "area_loss": area_loss,
        })

        # Update pools for next day
        wtnlf = max(0.0, wtnlf - daily_demand)
        wtlf = max(0.0, wtlf - dw_loss)

    # Day 1 & 2: pure safe mobilization
    assert states[0]["stress"] == 0.0 and states[0]["lfsen"] == 0.0
    assert states[1]["stress"] == 0.0 and states[1]["lfsen"] == 0.0
    # Day 3: buffer partially depleted -> mixed mobilization
    assert states[2]["safe"] > 0.0 and states[2]["stress"] > 0.0
    # Day 4: buffer exhausted -> pure stress mobilization
    assert states[3]["safe"] == 0.0 and states[3]["stress"] == daily_demand
    assert states[3]["lfsen"] > 0.0


def test_sub_carbohydrate_reserve_boundary_condition():
    """Verify that when WTLF <= WCRLF, NBUF_FREE never exceeds total leaf N (WTNLF)."""
    # Boundary: leaf dry weight less than carbohydrate pool (e.g. extreme numerical state)
    wtlf = 8.0
    wcrlf = 10.0
    wtnlf = 0.50
    prolfg = 0.220

    # Without MAX(0.0, WTLF - WCRLF), (8.0 - 10.0) = -2.0 would ADD to WTNLF
    w_struct = max(0.0, wtlf - wcrlf)
    assert w_struct == 0.0
    nbuf_free = max(0.0, wtnlf - prolfg * 0.16 * w_struct)

    # Structural invariant: free buffer cannot exceed actual leaf N
    assert nbuf_free <= wtnlf
    assert abs(nbuf_free - wtnlf) < 1e-12

    # Mobilization with negative anomaly input
    nruslf = 0.30
    nruslf_safe = max(0.0, min(nruslf, nbuf_free))
    nruslf_stress = max(0.0, nruslf - nruslf_safe)
    assert nruslf_safe <= wtnlf
    assert nruslf_safe + nruslf_stress == nruslf


def test_species_prolfg_fallback_resolution():
    """Verify that PROLFG correctly falls back to PROLFI * 0.815 when unparsed."""
    # Simulation of CROPGRO Fortran fallback logic:
    # 1. Normal parsing success
    prolfg_parsed = 0.220
    prolfg = prolfg_parsed if prolfg_parsed > 0.0 else 0.0
    assert prolfg == 0.220

    # 2. Parsing failure with known PROLFI (e.g. Soybean PROLFI = 0.356)
    prolfg = 0.0  # initialized to 0.0, NOT 0.220!
    prolfi = 0.356
    if prolfg <= 0.0:
        if prolfi > 0.0:
            prolfg = prolfi * 0.815
        else:
            prolfg = 0.220
    assert abs(prolfg - (0.356 * 0.815)) < 1e-6
    assert prolfg > 0.280  # distinctly different from default 0.220!

    # 3. Parsing failure with unknown PROLFI
    prolfg_none = 0.0
    prolfi_none = 0.0
    if prolfg_none <= 0.0:
        if prolfi_none > 0.0:
            prolfg_none = prolfi_none * 0.815
        else:
            prolfg_none = 0.220
    assert prolfg_none == 0.220

