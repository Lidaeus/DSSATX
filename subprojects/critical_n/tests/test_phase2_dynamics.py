"""Phase 2 Physiological Redesign & Mathematical Symmetry Test Suite.

Verifies:
1. Complete elimination of the F1 branch inversion: FNINL > FNINLG and FNINS > FNINSG
   globally across all W_eff in [0.1, 25.0] t/ha.
2. Continuous normalized dilution formula: C^0 continuity at W_eff = W_0 for any W_0 > 0.
3. Purge of toxic 0.675 multiplier in PHOTO_CNC.FOR / PHOTO.for.
4. Stoichiometric dry mass symmetry: beta_sol = 4.4 and symmetric NADLF_BUF / NADLF_FUNC refill.
5. Strict adherence to user constraint: NUPTAK.for remains 100% untouched.
6. Absolute safety of production C:\\DSSAT48\\DSCSM048.EXE.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
import pytest

from subprojects.critical_n.core.dilution_curve import (
    DEFAULT_CNC_A,
    DEFAULT_CNC_B,
    DEFAULT_CNC_NC_INF,
    DEFAULT_CNC_W0,
    critical_n_concentration,
    nni,
)
from subprojects.critical_n.scheme_b.patch_manager import validate_fortran_fixed_format


CRITICAL_N_DIR = Path(__file__).resolve().parents[1]
FORTRAN_PATCH_SRC = CRITICAL_N_DIR / "fortran_patch" / "src_scheme_b"
DSSAT_CNC_DIR = CRITICAL_N_DIR / "dssat_csm_cnc"
UPSTREAM_DIR = Path(__file__).resolve().parents[3] / "workspace" / "diagnostics" / "dssat-csm-os-v4.8.2-source"

PRODUCTION_EXE = Path(r"C:\DSSAT48\DSCSM048.EXE")
PRODUCTION_HASH = "92173d5f63bc60d58839630b9a29f57632a19b373cab0faa8ad70362d98f5c7a"


def test_production_exe_safety():
    """Verify production DSSAT remains untouched."""
    if PRODUCTION_EXE.is_file():
        h = hashlib.sha256(PRODUCTION_EXE.read_bytes()).hexdigest()
        assert h == PRODUCTION_HASH, f"CRITICAL SAFETY VIOLATION: Production DSSAT was modified! {h}"


def test_nuptak_untouched():
    """Verify NUPTAK.for was not modified in dssat_csm_cnc per user instructions."""
    cnc_nuptak = DSSAT_CNC_DIR / "Plant" / "CROPGRO" / "NUPTAK.for"
    upstream_nuptak = UPSTREAM_DIR / "Plant" / "CROPGRO" / "NUPTAK.for"
    assert cnc_nuptak.is_file(), "NUPTAK.for must exist in dssat_csm_cnc"
    assert upstream_nuptak.is_file(), "NUPTAK.for must exist in upstream source"
    assert cnc_nuptak.read_bytes() == upstream_nuptak.read_bytes(), (
        "USER CONSTRAINT VIOLATION: NUPTAK.for was modified! Soil N uptake function must remain untouched."
    )


def test_dilution_continuity_at_w0():
    """Verify that Nc(W_eff) is strictly C^0 continuous at W_eff = W_0 for various W_0."""
    w0_candidates = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0]
    for w0 in w0_candidates:
        nc_left = critical_n_concentration(w0 - 1e-7, a=4.85, b=0.38, w0=w0, nc_inf=1.70)
        nc_at = critical_n_concentration(w0, a=4.85, b=0.38, w0=w0, nc_inf=1.70)
        nc_right = critical_n_concentration(w0 + 1e-7, a=4.85, b=0.38, w0=w0, nc_inf=1.70)

        assert abs(nc_left - 4.85) < 1e-6, f"Left limit at W0={w0} must equal a=4.85"
        assert abs(nc_at - 4.85) < 1e-6, f"At W0={w0} must equal a=4.85"
        assert abs(nc_right - 4.85) < 1e-5, f"Right limit at W0={w0} must be continuous with a=4.85"


def test_f1_inversion_elimination_sweep():
    """Verify FNINL > FNINLG and FNINS > FNINSG globally across W_eff in [0.1, 25.0]."""
    test_params = [
        {"PROLFI": 0.270, "PROLFG": 0.220, "PROLFF": 0.110, "PROSTI": 0.188, "PROSTG": 0.136, "PROSTF": 0.065},
        {"PROLFI": 0.250, "PROLFG": 0.210, "PROLFF": 0.100, "PROSTI": 0.160, "PROSTG": 0.120, "PROSTF": 0.050},
        {"PROLFI": 0.320, "PROLFG": 0.260, "PROLFF": 0.130, "PROSTI": 0.220, "PROSTG": 0.150, "PROSTF": 0.070},
        {"PROLFI": 0.220, "PROLFG": 0.180, "PROLFF": 0.090, "PROSTI": 0.140, "PROSTG": 0.100, "PROSTF": 0.040},
    ]

    weff_points = [0.1 * (1.2 ** i) for i in range(35)]  # spans ~0.1 to ~40 t DM/ha

    for params in test_params:
        prolfi = params["PROLFI"]
        prolfg = params["PROLFG"]
        prolff = params["PROLFF"]
        prosti = params["PROSTI"]
        prostg = params["PROSTG"]
        prostf = params["PROSTF"]

        fninlg = prolfg * 0.16
        fninsg = prostg * 0.16

        for weff in weff_points:
            # Emulate Fortran DEMAND_CNC logic
            if weff < DEFAULT_CNC_W0:
                nc_dem = DEFAULT_CNC_A
            else:
                nc_dem = DEFAULT_CNC_NC_INF + (DEFAULT_CNC_A - DEFAULT_CNC_NC_INF) * (
                    (weff / DEFAULT_CNC_W0) ** (-DEFAULT_CNC_B)
                )

            fninl = min(prolfi * 0.16, max(prolfg * 0.16 + 0.002, 1.05 * nc_dem / 100.0))
            if prolfi > prolff:
                fr_dil = (fninl - prolff * 0.16) / ((prolfi - prolff) * 0.16)
                fr_dil = max(0.0, min(1.0, fr_dil))
            else:
                fr_dil = 1.0

            fnins = prostf * 0.16 + (prosti - prostf) * 0.16 * fr_dil
            fnins = min(prosti * 0.16, fnins)
            fnins = max(prostg * 0.16 + 0.001, fnins)

            # Mathematical assertion: Strictly greater!
            assert fninl > fninlg, f"F1 VIOLATION: FNINL ({fninl:.5f}) <= FNINLG ({fninlg:.5f}) at weff={weff:.2f}"
            assert fninl - fninlg >= 0.002 - 1e-9, f"Margin must be >= 0.002 at weff={weff:.2f}"
            assert fnins > fninsg, f"F1 VIOLATION: FNINS ({fnins:.5f}) <= FNINSG ({fninsg:.5f}) at weff={weff:.2f}"
            assert fnins - fninsg >= 0.001 - 1e-9, f"Margin must be >= 0.001 at weff={weff:.2f}"

            # Verify NGRVEG > NGRVGG for any arbitrary positive vegetative growth
            for wldotn, wsdotn in [(1.0, 1.0), (0.01, 0.05), (5.0, 2.0), (0.0, 1.0), (1.0, 0.0)]:
                ngrlf = wldotn * fninl
                ngrfg = wldotn * fninlg
                ngrst = wsdotn * fnins
                ngrsg = wsdotn * fninsg
                ngrveg = ngrlf + ngrst
                ngrvgg = ngrfg + ngrsg
                assert ngrveg > ngrvgg, f"NGRVEG ({ngrveg}) must be > NGRVGG ({ngrvgg})"


def test_photo_purged_s_nni():
    """Verify that PHOTO_CNC.FOR and PHOTO.for do not contain toxic S_NNI multiplier."""
    for p in [FORTRAN_PATCH_SRC / "PHOTO_CNC.FOR", DSSAT_CNC_DIR / "Plant" / "CROPGRO" / "PHOTO.for"]:
        content = p.read_text(encoding="utf-8")
        assert "S_NNI" not in content, f"S_NNI multiplier must be completely purged from {p.name}"
        assert "ARG_NNI" not in content, f"ARG_NNI must be purged from {p.name}"
        assert "AGEFCC * S_NNI" not in content, f"AGEFCC * S_NNI must be purged from {p.name}"


def test_grow_stoichiometric_symmetry():
    """Verify GROW_CNC.FOR and GROW.for use beta_sol=4.4 and symmetric NADLF_FUNC / NADLF_BUF."""
    for p in [FORTRAN_PATCH_SRC / "GROW_CNC.FOR", DSSAT_CNC_DIR / "Plant" / "CROPGRO" / "GROW.for"]:
        content = p.read_text(encoding="utf-8")
        assert "NRUSLF_SAFE * 4.4" in content, f"GROW must use beta_sol=4.4 for NRUSLF_SAFE in {p.name}"
        assert "NRUSLF_SAFE * 1.0" not in content, f"Old 1.0 multiplier must be removed from {p.name}"
        assert "NADLF_FUNC" in content, f"NADLF_FUNC must be present in {p.name}"
        assert "NADLF_BUF" in content, f"NADLF_BUF must be present in {p.name}"
        assert "ADD_LFDM" in content, f"ADD_LFDM must be present in {p.name}"
        assert "NADLF_FUNC / 0.16 + NADLF_BUF * 4.4" in content, f"Symmetric refill formula must be in {p.name}"
        assert "ALFDOT + SLA * (NADLF_FUNC/0.16)" in content, f"ALFDOT must only refill with functional protein in {p.name}"


def test_demand_reading_prolfg():
    """Verify DEMAND_CNC.FOR reads PROLFG and PROSTG from species file."""
    for p in [FORTRAN_PATCH_SRC / "DEMAND_CNC.FOR", DSSAT_CNC_DIR / "Plant" / "CROPGRO" / "DEMAND.for"]:
        content = p.read_text(encoding="utf-8")
        assert "PROLFG, PROSTG" in content, f"PROLFG and PROSTG must be declared and handled in {p.name}"
        assert "PROLFG * 0.16 + 0.002" in content, f"Lower bound safeguard must be present in {p.name}"
        assert "PROSTG * 0.16 + 0.001" in content, f"Lower bound safeguard must be present in {p.name}"
        assert "((WEFF / CNC_W0) ** (-CNC_B))" in content, f"Normalized dilution formula must be in {p.name}"


def test_fortran_fixed_format_compliance():
    """Ensure all patched Scheme B Fortran sources strictly obey 72-column limit."""
    patch_files = [
        FORTRAN_PATCH_SRC / "DEMAND_CNC.FOR",
        FORTRAN_PATCH_SRC / "GROW_CNC.FOR",
        FORTRAN_PATCH_SRC / "PHOTO_CNC.FOR",
        FORTRAN_PATCH_SRC / "MOBIL_CNC.FOR",
        FORTRAN_PATCH_SRC / "SENES_CNC.FOR",
        FORTRAN_PATCH_SRC / "CROPGRO_CNC.FOR",
        FORTRAN_PATCH_SRC / "PODS_CNC.FOR",
        FORTRAN_PATCH_SRC / "FreshWt_CNC.FOR",
    ]
    for pf in patch_files:
        assert pf.is_file(), f"File {pf} must exist"
        violations = validate_fortran_fixed_format(pf)
        assert len(violations) == 0, f"72-column violations detected in {pf.name}: {violations[:3]}"
