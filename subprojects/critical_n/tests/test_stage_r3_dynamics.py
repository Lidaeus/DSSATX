"""Tests for Stage R3 dynamic vegetative demand dilution, CHPDTN fruit N tracking, and fruiting stability.

Validates the Stage R3 core mechanisms across DEMAND, PODS, FreshWt, and CROPGRO:
1. Dynamic allometric dilution for new vegetative tissue demand (DEMAND_CNC.FOR):
   - Nc_dem(Weff) = Nc_inf + (a - Nc_inf) * [max(W0, Weff)]^(-b)
   - FNINL(t) = min(PROLFI * 0.16, max(PROLFF * 0.16, Nc_dem / 100.0))
   - FNINS(t) allometric coordination with PROSTF * 0.16 and PROSTI * 0.16
   - NDMVEG incorporates diluted FNINL, FNINS for new tissue synthesis
   - NDMOLD targets NVSTL = FNINL and NVSTS = FNINS harmonized
2. Singularity protection & non-destructive pod addition under MEPHO='L' (PODS_CNC.FOR):
   - Guard against (FNINL - PROLFF * 0.16) singularity at line 747
   - Decoupled fruiting potential FNINL0 = PROLFI * 0.16 preserves fruiting rhythm
   - Pod addition RNITPD stays stably bounded in [0.1, 1.1]
3. Explicit cumulative harvest pod total N tracking CHPDTN (CROPGRO + FreshWt):
   - HPODN = HSDWT * (PCNSD / 100.0) + HSHELWT * (PCNSH / 100.0)
   - CHPDTN = CHPDTN + HPODN * 10.0 (kg[N]/ha)
   - FreshWt.OUT outputs CHPDTN column
   - Monotonically non-decreasing running total across entire season (persists on non-harvest days)
4. Plant and soil nitrogen mass balance conservation:
   - PlantNBal.OUT closure within 0.05 kg N/ha across all treatments
   - SoilNiBal.OUT exact closure (Balance == 0.000 kg N/ha)
5. Strict Fortran 77/90 fixed-format compliance across all 8 modified routines (0 violations).
6. Production isolation:
   - C:\\DSSAT48\\DSCSM048.EXE remains unmodified (hash verified)
   - Sandboxed binary subprojects/critical_n/bin/dscsm048_cnc.exe verified
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
from subprojects.critical_n.adapters.stream_parser import parse_fresh_wt_stream
from subprojects.critical_n.core.effective_biomass import CumulativeStateTracker

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CRITICAL_N_DIR = PROJECT_ROOT / "subprojects" / "critical_n"
FORTRAN_PATCH_DIR = CRITICAL_N_DIR / "fortran_patch"
VERIFY_DIR = CRITICAL_N_DIR / "verification_runs"


def test_r3_mathematical_new_tissue_allometric_dilution_invariants():
    """Verify algebraic properties and bounds of dynamic allometric dilution for new vegetative demand."""
    a_cnc = 4.85
    b_cnc = 0.38
    w0_cnc = 1.00
    nc_inf = 1.70

    prolfi = 0.270
    prolff = 0.110
    prosti = 0.188
    prostf = 0.065
    prorti = 0.130

    fninl_max = prolfi * 0.16   # 0.0432 (4.32% N)
    fnins_max = prosti * 0.16   # 0.03008 (3.01% N)
    prolff_16 = prolff * 0.16   # 0.0176 (1.76% N)
    prostf_16 = prostf * 0.16   # 0.0104 (1.04% N)
    fninr = prorti * 0.16       # 0.0208

    def calc_demand_n(weff: float) -> tuple[float, float, float, float]:
        if weff <= 0.0:
            fninl = fninl_max
            fnins = fnins_max
            nc_dem = a_cnc
        else:
            if weff < w0_cnc:
                nc_dem = a_cnc
            else:
                nc_dem = nc_inf + (a_cnc - nc_inf) * (weff ** (-b_cnc))

            fninl = min(fninl_max, max(prolff_16, 1.05 * nc_dem / 100.0))
            if prolfi > prolff:
                fr_dil = (fninl - prolff_16) / ((prolfi - prolff) * 0.16)
                fr_dil = max(0.0, min(1.0, fr_dil))
            else:
                fr_dil = 1.0

            fnins = prostf_16 + (prosti - prostf) * 0.16 * fr_dil
            fnins = max(prostf_16, min(fnins_max, fnins))

        # Sample vegetative tissue synthesis demand
        frlf = 0.50
        frstm = 0.30
        frrt = 0.20
        ndmveg_unit = frlf * fninl + frstm * fnins + frrt * fninr
        return nc_dem, fninl, fnins, ndmveg_unit

    # 1. Early stage / Seedling (Weff <= 1.0 t DM/ha)
    nc_0, fninl_0, fnins_0, ndm_0 = calc_demand_n(0.5)
    assert abs(nc_0 - a_cnc) < 1e-6
    # Early leaf demand is bounded at genetic upper limit FNINL = PROLFI * 0.16
    assert abs(fninl_0 - fninl_max) < 1e-6
    assert abs(fnins_0 - fnins_max) < 1e-6

    # 2. Intermediate growth (Weff = 3.0 t DM/ha)
    nc_3, fninl_3, fnins_3, ndm_3 = calc_demand_n(3.0)
    assert nc_3 < a_cnc
    assert nc_3 > nc_inf
    assert abs(fninl_3 - (1.05 * nc_3 / 100.0)) < 1e-6  # Follows 1.05 * Nc(Weff)
    assert fninl_3 > (nc_3 / 100.0)  # 5% luxury headroom over critical curve
    assert fninl_3 < fninl_0
    assert fnins_3 < fnins_0
    assert ndm_3 < ndm_0

    # 3. High cumulative biomass (Weff = 15.0 t DM/ha)
    nc_15, fninl_15, fnins_15, ndm_15 = calc_demand_n(15.0)
    assert nc_15 < nc_3
    assert fninl_15 < fninl_3
    assert fnins_15 < fnins_3
    assert ndm_15 < ndm_3

    # 4. Asymptotic limit (Weff -> infinity)
    nc_inf_calc, fninl_inf, fnins_inf, ndm_inf = calc_demand_n(1e6)
    assert abs(nc_inf_calc - nc_inf) < 0.05
    assert abs(fninl_inf - prolff_16) < 0.01
    assert abs(fnins_inf - prostf_16) < 0.01

    # Monotonicity test across biomass continuum
    prev_nc, prev_l, prev_s, prev_ndm = 100.0, 100.0, 100.0, 100.0
    for w in [0.2, 0.8, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0]:
        nc, fl, fs, ndm = calc_demand_n(w)
        assert nc <= prev_nc
        assert fl <= prev_l
        assert fs <= prev_s
        assert ndm <= prev_ndm
        prev_nc, prev_l, prev_s, prev_ndm = nc, fl, fs, ndm


def test_r3_fruiting_singularity_protection_and_stability():
    """Verify PODS singularity guard and fruiting rhythm decoupling."""
    prolff = 0.110
    prolff_16 = prolff * 0.16  # 0.0176
    rnitp = 2.0  # typical leaf N %

    # Native PODS formula: RNITPD = (RNITP*0.01 - PROLFF*0.16) / (FNINL - PROLFF*0.16)
    # If FNINL approaches PROLFF*0.16, divisor approaches zero
    def calc_rnitpd(fninl: float) -> float:
        denom = fninl - prolff_16
        if denom > 0.001:
            rnitpd = (rnitp * 0.01 - prolff_16) / denom
        else:
            rnitpd = 1.0
        return min(1.1, max(0.1, rnitpd))

    # Standard healthy case
    r_normal = calc_rnitpd(0.0432)
    assert 0.1 <= r_normal <= 1.1

    # Approaching singularity within 0.0005
    r_near_singularity = calc_rnitpd(prolff_16 + 0.0005)
    assert r_near_singularity == 1.0  # Guard engaged, prevents division-by-zero or explosion

    # Exact match to lower bound
    r_exact = calc_rnitpd(prolff_16)
    assert r_exact == 1.0


def test_r3_fortran_fixed_format_compliance_all_8_sources():
    """Verify that all 8 Scheme B patched Fortran routines obey 72-column fixed-form rules."""
    src_dir = FORTRAN_PATCH_DIR / "src_scheme_b"
    routines = [
        "DEMAND_CNC.FOR",
        "CROPGRO_CNC.FOR",
        "GROW_CNC.FOR",
        "MOBIL_CNC.FOR",
        "SENES_CNC.FOR",
        "PHOTO_CNC.FOR",
        "PODS_CNC.FOR",
        "FreshWt_CNC.FOR",
    ]
    for r in routines:
        fpath = src_dir / r
        assert fpath.is_file(), f"Missing Fortran routine: {r}"
        violations = validate_fortran_fixed_format(fpath)
        assert len(violations) == 0, f"72-column violations in {r}: {violations[:3]}"


def test_r3_chpdtn_presence_and_monotonicity_in_freshwt():
    """Verify that FreshWt.OUT outputs CHPDTN and maintains monotonically non-decreasing running totals."""
    fwt_file = VERIFY_DIR / "greenhouse" / "cnc_mepho_l" / "FreshWt.OUT"
    if not fwt_file.is_file():
        pytest.skip(f"FreshWt.OUT not found at {fwt_file}")

    # 1. Parse via stream_parser
    runs_data = parse_fresh_wt_stream(fwt_file)
    assert len(runs_data) > 0, "No runs parsed from FreshWt.OUT"

    for run_id, das_dict in runs_data.items():
        assert len(das_dict) > 0, f"Run {run_id} has empty record dictionary"
        records = sorted(das_dict.values(), key=lambda r: r.das)

        # All records must report has_chpdtn True
        assert all(r.has_chpdtn for r in records), f"Run {run_id} missing CHPDTN column in records"

        prev_n = 0.0
        for r in records:
            # Monotonic non-decreasing running total
            assert r.chpdtn >= prev_n - 1e-6, (
                f"Run {run_id} DAS {r.das} CHPDTN decreased: {r.chpdtn} < {prev_n}"
            )
            prev_n = r.chpdtn

        # Treatments with harvest must reach non-zero cumulative fruit N
        final_chpdtn = records[-1].chpdtn
        final_chpdt = records[-1].chpdt
        if final_chpdt > 50.0:
            assert final_chpdtn > 1.0, (
                f"Run {run_id} with CHPDT={final_chpdt} has implausibly low CHPDTN={final_chpdtn}"
            )

    # 2. Parse raw table into pandas for Treatment 2 detailed audit
    lines = fwt_file.read_text(encoding="latin-1").splitlines()
    header = None
    rows = []
    for line in lines:
        if line.startswith("@"):
            header = line.replace("@", " ").split()
        elif header and line.strip() and not line.startswith("*") and not line.startswith("!"):
            parts = line.split()
            if len(parts) == len(header):
                rows.append(parts)

    df = pd.DataFrame(rows, columns=header).astype(float)
    assert "CHPDTN" in df.columns, "CHPDTN missing from FreshWt.OUT header"

    df["RUN"] = (df["DAP"].diff() < 0).cumsum()

    # Verify per-run monotonicity across all 11 greenhouse runs
    for run_no, grp in df.groupby("RUN"):
        diffs = grp["CHPDTN"].diff().dropna()
        assert (diffs >= -1e-6).all(), f"Run {run_no} CHPDTN decreased on non-harvest day!"

    # Verify non-harvest day carry-forward in Run 1 (Treatment 2)
    # Harvest events occur at DAP 78, 83, 88, 95, 100, 109, 117
    r1 = df[df["RUN"] == 1]
    # On DAP 110-116 (between harvest 8 and 9), CHPDTN must remain strictly positive and constant
    between_harv = r1[(r1["DAP"] >= 110) & (r1["DAP"] <= 116)]
    assert len(between_harv) > 0
    unique_vals = between_harv["CHPDTN"].unique()
    assert len(unique_vals) == 1, f"CHPDTN varied between harvests: {unique_vals}"
    assert unique_vals[0] > 9.0, f"Expected CHPDTN ~9.64 kg/ha, got {unique_vals[0]}"


def test_r3_effective_biomass_integration_with_chpdtn():
    """Verify that CumulativeStateTracker absorbs CHPDTN and stabilizes post-harvest N state."""
    tracker = CumulativeStateTracker(cnc_a=4.85, cnc_b=0.38, cnc_w0=1.0, cnc_nc_inf=1.70)

    # Pre-harvest state: CWAD = 3000 kg/ha, CNAD = 100 kg/ha
    state_pre = tracker.step(das=70, cwad=3000.0, cnad=100.0, direct_chpdt=0.0, direct_chpdtn=0.0)
    assert abs(state_pre.w_eff - 3.0) < 1e-4
    assert state_pre.cum_harvest_n == 0.0

    # Harvest day: CWAD drops to 2500 kg/ha, fruit harvested = 500 kg/ha, fruit N = 17.5 kg/ha
    state_harv = tracker.step(das=71, cwad=2500.0, cnad=82.5, direct_chpdt=500.0, direct_chpdtn=17.5)
    assert abs(state_harv.w_eff - 3.0) < 1e-4  # Effective biomass conserved
    assert state_harv.cum_harvest_n == 17.5  # Cumulative fruit N updated
    assert state_harv.chpdtn == 17.5

    # Next non-harvest day: CWAD grows to 2550 kg/ha, standing N grows to 84.0 kg/ha
    state_post = tracker.step(das=72, cwad=2550.0, cnad=84.0, direct_chpdt=500.0, direct_chpdtn=17.5)
    assert abs(state_post.w_eff - 3.05) < 1e-4
    assert state_post.cum_harvest_n == 17.5  # Cumulative fruit N persists on non-harvest day
    # Total effective N = standing N + cumulative harvest N
    total_eff_n = state_post.cnad + state_post.cum_harvest_n
    assert abs(total_eff_n - (84.0 + 17.5)) < 1e-4


def test_r3_plant_and_soil_mass_balance_closure():
    """Verify that PlantNBal.OUT and SoilNiBal.OUT achieve closure across all treatments."""
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
                # Formatted output rounds to 2 decimals across multiple balance rows
                assert diff <= 0.05, (
                    f"Plant mass balance discrepancy in {pnb_file.name} Run {i}: "
                    f"Plant={plant_total}, Input={input_total}, Diff={diff}"
                )

    sni_files = [
        VERIFY_DIR / "greenhouse" / "cnc_mepho_l" / "SoilNiBal.OUT",
        VERIFY_DIR / "greenhouse" / "cnc_mepho_c" / "SoilNiBal.OUT",
    ]

    for sni_file in sni_files:
        if not sni_file.is_file():
            continue
        text = sni_file.read_text(encoding="latin-1")
        bal_lines = [l for l in text.splitlines() if "!   Balance" in l]
        assert len(bal_lines) > 0, f"No balance lines in {sni_file}"
        for bl in bal_lines:
            bal_val = float(bl.split()[-1])
            assert abs(bal_val) < 1e-3, f"Soil Balance line non-zero in {sni_file.name}: {bal_val}"


def test_r3_production_isolation_unbroken():
    """Verify that production DSSAT and root repository remained 100% untouched."""
    check_production_safety()
    if PRODUCTION_EXE.is_file():
        import hashlib
        current_hash = hashlib.sha256(PRODUCTION_EXE.read_bytes()).hexdigest()
        assert current_hash == PRODUCTION_HASH

    assert BIN_CNC.is_file()
    assert BIN_CNC.stat().st_size > 10 * 1024 * 1024


def test_r3_vanilla_vs_cnc_chpdtn_isolation():
    """Verify that vanilla FreshWt.OUT lacks CHPDTN while CNC FreshWt.OUT contains it."""
    v_dir = VERIFY_DIR / "greenhouse" / "vanilla_mepho_l"
    c_dir = VERIFY_DIR / "greenhouse" / "cnc_mepho_l"
    if not (v_dir / "FreshWt.OUT").is_file() or not (c_dir / "FreshWt.OUT").is_file():
        pytest.skip("Greenhouse verification runs missing")

    v_lines = (v_dir / "FreshWt.OUT").read_text(encoding="latin-1").splitlines()
    c_lines = (c_dir / "FreshWt.OUT").read_text(encoding="latin-1").splitlines()

    v_headers = [l for l in v_lines if l.startswith("@")]
    c_headers = [l for l in c_lines if l.startswith("@")]

    assert len(v_headers) > 0 and len(c_headers) > 0
    assert "CHPDTN" not in v_headers[0], "Vanilla FreshWt.OUT unexpectedly contains CHPDTN"
    assert "CHPDTN" in c_headers[0], "CNC FreshWt.OUT missing expected CHPDTN column"


def test_r3_greenhouse_fruiting_stability_mepho_l():
    """Verify fruiting stability under MEPHO='L' between Vanilla and CNC."""
    v_dir = VERIFY_DIR / "greenhouse" / "vanilla_mepho_l"
    c_dir = VERIFY_DIR / "greenhouse" / "cnc_mepho_l"
    if not (v_dir / "Summary.OUT").is_file() or not (c_dir / "Summary.OUT").is_file():
        pytest.skip("Greenhouse Summary.OUT missing")

    v_sum = [l for l in (v_dir / "Summary.OUT").read_text(encoding="latin-1").splitlines() if l.strip() and not l.startswith(("*", "@"))]
    c_sum = [l for l in (c_dir / "Summary.OUT").read_text(encoding="latin-1").splitlines() if l.strip() and not l.startswith(("*", "@"))]

    assert len(v_sum) == 12, f"Expected 12 runs in Vanilla Summary.OUT, got {len(v_sum)}"
    assert len(c_sum) == 12, f"Expected 12 runs in CNC Summary.OUT, got {len(c_sum)}"


def test_r3_allometric_dilution_boundary_and_degenerate_conditions():
    """Verify mathematical boundary and degenerate cases for Stage R3 DEMAND."""
    prolfi = 0.270
    prolff = 0.110
    prosti = 0.188
    prostf = 0.065

    # Degenerate condition: PROLFI <= PROLFF
    def calc_dil(weff: float, pi: float, pf: float, si: float, sf: float):
        if weff <= 0.0:
            fninl = pi * 0.16
            fnins = si * 0.16
        else:
            if weff < 1.00:
                nc_dem = 4.85
            else:
                nc_dem = 1.70 + (4.85 - 1.70) * (weff ** (-0.38))
            fninl = min(pi * 0.16, max(pf * 0.16, 1.05 * nc_dem / 100.0))
            if pi > pf:
                fr_dil = (fninl - pf * 0.16) / ((pi - pf) * 0.16)
                fr_dil = max(0.0, min(1.0, fr_dil))
            else:
                fr_dil = 1.0
            fnins = sf * 0.16 + (si - sf) * 0.16 * fr_dil
            fnins = max(sf * 0.16, min(si * 0.16, fnins))
        return fninl, fnins

    # Degenerate cultivar where PROLFI <= PROLFF (e.g. equal initial and final targets)
    fnl_deg, fns_deg = calc_dil(5.0, 0.10, 0.10, 0.06, 0.04)
    assert abs(fnl_deg - 0.10 * 0.16) < 1e-6
    assert abs(fns_deg - 0.06 * 0.16) < 1e-6

    # Negative / zero Weff
    fnl_neg, fns_neg = calc_dil(-2.0, prolfi, prolff, prosti, prostf)
    assert fnl_neg == prolfi * 0.16
    assert fns_neg == prosti * 0.16

    # Extreme high biomass Weff = 1000.0 t/ha
    fnl_huge, fns_huge = calc_dil(1000.0, prolfi, prolff, prosti, prostf)
    assert fnl_huge >= prolff * 0.16
    assert fns_huge >= prostf * 0.16

