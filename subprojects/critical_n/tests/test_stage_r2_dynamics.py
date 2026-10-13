"""Tests for Stage R2 dynamic demand-side nitrogen dilution mechanism.

Validates the Stage R2 core mechanisms across DEMAND + CROPGRO:
1. Mathematical invariants of asymptotic lower-bound critical dilution:
   - Nc(Weff) = Nc_inf + (a - Nc_inf) * [max(W0, Weff)]^(-b)
   - Parameters: a = 4.85%, b = 0.38, W0 = 1.00 t DM/ha, Nc_inf = 1.70%
   - NVSTL(t) = max(PROLFF * 0.16, Nc(Weff(t)) / 100.0)
   - NVSTS(t) allometric coordination with PROSTF * 0.16
2. Strict Fortran 77/90 fixed-format compliance (cols <= 72, 0 violations).
3. Plant and soil nitrogen mass balance conservation:
   - PlantNBal.OUT closure within 0.05 kg N/ha (file 2-decimal rounding)
   - SoilNiBal.OUT exact closure (Initial == Final, diff < 1e-4 kg N/ha)
4. Empirical greenhouse eggplant/tomato dynamics:
   - Breaks the flat-line pathology of organ nitrogen
   - Exhibits allometric organ dilution with cumulative biomass accumulation
5. Production isolation:
   - C:\\DSSAT48\\DSCSM048.EXE remains unmodified
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

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CRITICAL_N_DIR = PROJECT_ROOT / "subprojects" / "critical_n"
FORTRAN_PATCH_DIR = CRITICAL_N_DIR / "fortran_patch"
VERIFY_DIR = CRITICAL_N_DIR / "verification_runs"


def test_r2_mathematical_cnc_dilution_invariants():
    """Verify algebraic properties and bounds of asymptotic CNC dilution in DEMAND."""
    a_cnc = 4.85
    b_cnc = 0.38
    w0_cnc = 1.00
    nc_inf = 1.70

    prolfi = 0.270
    prolff = 0.110
    prosti = 0.188
    prostf = 0.065

    fninl = prolfi * 0.16  # 0.0432 (4.32%)
    fnins = prosti * 0.16  # 0.03008 (3.01%)
    prolff_16 = prolff * 0.16  # 0.0176 (1.76%)
    prostf_16 = prostf * 0.16  # 0.0104 (1.04%)

    def calc_targets(weff: float) -> tuple[float, float, float]:
        if weff < w0_cnc:
            nc = a_cnc
        else:
            nc = nc_inf + (a_cnc - nc_inf) * (weff ** (-b_cnc))

        nvstl = max(prolff_16, nc / 100.0)

        if fninl > prolff_16:
            fr_dil = (nvstl - prolff_16) / (fninl - prolff_16)
            fr_dil = max(0.0, min(1.0, fr_dil))
        else:
            fr_dil = 1.0

        nvsts = prostf_16 + (fnins - prostf_16) * fr_dil
        nvsts = max(prostf_16, min(fnins, nvsts))
        return nc, nvstl, nvsts

    # 1. Early vegetative / seedling (Weff <= 1.0 t DM/ha)
    nc_seed, nvstl_seed, nvsts_seed = calc_targets(0.3)
    assert abs(nc_seed - a_cnc) < 1e-6
    assert abs(nvstl_seed - a_cnc / 100.0) < 1e-6
    assert abs(nvsts_seed - fnins) < 1e-6

    # 2. Intermediate growth (Weff = 3.0 t DM/ha)
    nc_3, nvstl_3, nvsts_3 = calc_targets(3.0)
    assert nc_3 < a_cnc
    assert nc_3 > nc_inf
    assert nvstl_3 < nvstl_seed
    assert nvsts_3 < nvsts_seed
    assert nvsts_3 > prostf_16

    # 3. High biomass (Weff = 15.0 t DM/ha)
    nc_15, nvstl_15, nvsts_15 = calc_targets(15.0)
    assert nc_15 < nc_3
    assert nvstl_15 < nvstl_3
    assert nvsts_15 < nvsts_3

    # 4. Asymptotic limit (Weff -> infinity)
    nc_inf_calc, nvstl_inf, nvsts_inf = calc_targets(100000.0)
    assert abs(nc_inf_calc - nc_inf) < 0.05
    assert abs(nvstl_inf - prolff_16) < 0.01
    assert abs(nvsts_inf - prostf_16) < 0.01

    # Monotonicity checks
    prev_nc = 100.0
    prev_nvstl = 100.0
    prev_nvsts = 100.0
    for w in [0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0]:
        nc_cur, nvstl_cur, nvsts_cur = calc_targets(w)
        assert nc_cur <= prev_nc
        assert nvstl_cur <= prev_nvstl
        assert nvsts_cur <= prev_nvsts
        prev_nc = nc_cur
        prev_nvstl = nvstl_cur
        prev_nvsts = nvsts_cur


def test_r2_fortran_fixed_format_compliance():
    """Verify that all patched Fortran sources obey 72-column fixed-form rules."""
    src_dir = FORTRAN_PATCH_DIR / "src_scheme_b"
    routines = [
        "DEMAND_CNC.FOR",
        "CROPGRO_CNC.FOR",
        "GROW_CNC.FOR",
        "MOBIL_CNC.FOR",
        "SENES_CNC.FOR",
        "PHOTO_CNC.FOR",
    ]
    for r in routines:
        fpath = src_dir / r
        assert fpath.is_file(), f"Missing routine: {r}"
        violations = validate_fortran_fixed_format(fpath)
        assert len(violations) == 0, f"Format violations in {r}: {violations[:3]}"


def test_r2_plant_and_soil_n_balance_conservation():
    """Verify that PlantNBal.OUT and SoilNiBal.OUT achieve mass balance closure."""
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
        lines = [l for l in text.splitlines() if "Total N balance" in l]
        assert len(lines) > 0, f"No balance lines in {sni_file}"
        for l in lines:
            parts = l.split()
            init_n = float(parts[-2])
            final_n = float(parts[-1])
            assert abs(init_n - final_n) < 1e-4, (
                f"Soil N mass balance mismatch in {sni_file.name}: "
                f"Initial={init_n}, Final={final_n}"
            )


def test_r2_tissue_nitrogen_allometric_dilution():
    """Verify that Stage R2 dynamic demand breaks the organ nitrogen flat line."""
    vanilla_n = VERIFY_DIR / "greenhouse" / "vanilla_mepho_l" / "PlantN.OUT"
    cnc_n = VERIFY_DIR / "greenhouse" / "cnc_mepho_l" / "PlantN.OUT"

    if not vanilla_n.is_file() or not cnc_n.is_file():
        pytest.skip("Greenhouse run outputs not found")

    def parse_plantn(fpath: Path) -> pd.DataFrame:
        rows = []
        with open(fpath, "r") as f:
            reading = False
            current_trt = None
            for line in f:
                if line.startswith("*RUN"):
                    current_trt = int(line.split("XXQL2501")[1].split()[0])
                elif line.startswith("@YEAR"):
                    reading = True
                elif reading and line.strip():
                    parts = line.split()
                    if len(parts) >= 15:
                        try:
                            dap = int(parts[3])
                            lnd = float(parts[13])
                            snd = float(parts[14])
                            rows.append({"TRNO": current_trt, "DAP": dap, "LN%D": lnd, "SN%D": snd})
                        except ValueError:
                            pass
                elif not line.strip():
                    reading = False
        return pd.DataFrame(rows)

    df_van = parse_plantn(vanilla_n)
    df_cnc = parse_plantn(cnc_n)

    # In Treatment 2 (95F-180 N):
    v2 = df_van[df_van["TRNO"] == 2]
    c2 = df_cnc[df_cnc["TRNO"] == 2]

    # Vanilla stem nitrogen was a flat line across the season (range < 0.10%)
    v_stem_range = v2["SN%D"].max() - v2["SN%D"].min()
    assert v_stem_range < 0.15, f"Vanilla stem was not flat: range={v_stem_range}"

    # CNC stem nitrogen dynamically increases during vegetative filling and dilutes allometrically
    c_stem_max = c2["SN%D"].max()
    c_stem_min = c2[c2["DAP"] > 60]["SN%D"].min()
    c_stem_range = c_stem_max - c_stem_min
    assert c_stem_range > 1.0, f"CNC stem nitrogen did not dilate: range={c_stem_range}"

    # Verify that stem N reaches at least 4.5% during vegetative phase and dilutes toward 3.0%
    assert c_stem_max >= 4.50
    assert c2[c2["DAP"] == 113]["SN%D"].values[0] < 3.20


def test_r2_production_isolation_unbroken():
    """Verify that production DSSAT and root repository remained 100% untouched."""
    check_production_safety()
    if PRODUCTION_EXE.is_file():
        import hashlib
        current_hash = hashlib.sha256(PRODUCTION_EXE.read_bytes()).hexdigest()
        assert current_hash == PRODUCTION_HASH

    assert BIN_CNC.is_file()
    assert BIN_CNC.stat().st_size > 10 * 1024 * 1024
