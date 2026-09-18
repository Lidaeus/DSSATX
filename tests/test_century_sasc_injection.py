"""Tests for CENTURY MESOM=P SASC injection and SOIL_SLNF bounds."""
import re
from pathlib import Path
import pytest

from src.common.param_registry import (
    PHYSICAL_BOUNDS,
    compute_default_bounds,
    validate_frozen_bounds,
)
from src.dssat.run_dssat import update_soil_analysis_sasc_in_filex


def test_soil_slnf_physical_upper_bound_is_one():
    """DSSAT Fortran IPSOIL_Inp.for:485-492 mandates SLNF <= 1.0."""
    assert "SOIL_SLNF" in PHYSICAL_BOUNDS
    lower, upper = PHYSICAL_BOUNDS["SOIL_SLNF"]
    assert lower == 0.0
    assert upper == 1.0

    # Default bound inference should not exceed 1.0
    lb, ub, status = compute_default_bounds("SOIL_SLNF", 1.0, "SOIL")
    assert ub <= 1.0


def test_sasc_ratio_physical_bounds():
    """SASC_RATIO represents stable organic carbon fraction in [0.0, 1.0]."""
    for key in ["SASC_RATIO", "SASC_FRAC", "SASC_25SP", "SASC_26SP"]:
        assert key in PHYSICAL_BOUNDS
        lower, upper = PHYSICAL_BOUNDS[key]
        assert lower == 0.0
        assert upper == 1.0

    lb, ub, status = compute_default_bounds("SASC_RATIO", 0.88, "IC")
    assert 0.50 <= lb < ub <= 0.99
    assert status == "active"


def test_sasc_injection_into_filex(tmp_path: Path):
    """Verify update_soil_analysis_sasc_in_filex injects SASC into FileX @A section."""
    sample_tmx = (
        "*EXP.DETAILS: TEST\n\n"
        "*SOIL ANALYSIS\n"
        "@A SADAT  SMHB  SMPX  SMKE  SANAME\n"
        " 1 25042 SA012 SA001   -99  1\n"
        "@A  SABL  SADM  SAOC  SANI SAPHW SAPHB  SAPX  SAKE  SASC\n"
        " 1    20  1.36  0.81 0.074  8.26   -99  76.2   1.8   -99\n"
        " 1    40  1.55  0.59 0.054  8.08   -99  37.7   0.5   -99\n"
        " 1    60  1.56  0.44 0.040  7.90   -99  30.2   0.3   -99\n"
        "\n*SIMULATION CONTROLS\n"
    )
    tmx_p = tmp_path / "XXQL2501.TMX"
    tmx_p.write_text(sample_tmx, encoding="utf-8")

    param_csv = tmp_path / "params.csv"
    param_csv.write_text("name,value\nSASC_RATIO,0.88\n", encoding="utf-8")

    update_soil_analysis_sasc_in_filex(param_csv_path=str(param_csv), filex_path=str(tmx_p))

    content = tmx_p.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Layer 1: SAOC=0.81 * 0.88 = 0.7128 -> 0.71
    # Layer 2: SAOC=0.59 * 0.88 = 0.5192 -> 0.52
    # Layer 3: SAOC=0.44 * 0.88 = 0.3872 -> 0.39
    assert " 1    20  1.36  0.81 0.074  8.26   -99  76.2   1.8  0.71" in lines
    assert " 1    40  1.55  0.59 0.054  8.08   -99  37.7   0.5  0.52" in lines
    assert " 1    60  1.56  0.44 0.040  7.90   -99  30.2   0.3  0.39" in lines
    # Verify line lengths match header length (56 chars)
    for line in lines:
        if line.startswith(" 1    "):
            assert len(line) == 56


def test_slnf_and_icns_physical_bounds():
    """Verify SLNF alias and ICNS mineral-N scaling boundaries."""
    assert "SLNF" in PHYSICAL_BOUNDS
    assert PHYSICAL_BOUNDS["SLNF"] == (0.0, 1.0)
    for k in ["ICNS", "ICNS_25SP", "ICNS_26SP", "ICNS_25FA"]:
        assert k in PHYSICAL_BOUNDS
        assert PHYSICAL_BOUNDS[k] == (0.01, 10.0)


def test_sasc_multi_digit_formatting(tmp_path: Path):
    """Verify high SAOC value (e.g. 15.0 * 0.88 = 13.20) maintains exact 56 char column alignment."""
    sample_tmx = (
        "*EXP.DETAILS: TEST\n\n"
        "*SOIL ANALYSIS\n"
        "@A  SABL  SADM  SAOC  SANI SAPHW SAPHB  SAPX  SAKE  SASC\n"
        " 1    20  1.36 15.00 0.074  8.26   -99  76.2   1.8   -99\n"
        "\n*SIMULATION CONTROLS\n"
    )
    tmx_p = tmp_path / "XXQL2501.TMX"
    tmx_p.write_text(sample_tmx, encoding="utf-8")
    param_csv = tmp_path / "params.csv"
    param_csv.write_text("name,value\nSASC_RATIO,0.88\n", encoding="utf-8")

    update_soil_analysis_sasc_in_filex(param_csv_path=str(param_csv), filex_path=str(tmx_p))
    line = [l for l in tmx_p.read_text(encoding="utf-8").splitlines() if l.startswith(" 1    20")][0]
    assert len(line) == 56
    assert line.endswith("13.20")
    # In Fortran (51X, F6.0): 51 chars skipped, cols 52-57 are ' 13.20'
    assert line[51:56] == "13.20"


def test_resolve_param_source_relative_path(tmp_path: Path):
    """Verify _resolve_param_source finds relative files in nested subdirectories."""
    from src.calibration.run_dssat import _resolve_param_source
    sub = tmp_path / "sub" / "runs"
    sub.mkdir(parents=True)
    p = sub / "cand_params.csv"
    p.write_text("name,value\n", encoding="utf-8")

    resolved = _resolve_param_source(["--param-csv", "sub/runs/cand_params.csv"], tmp_path)
    assert resolved == p.resolve()

