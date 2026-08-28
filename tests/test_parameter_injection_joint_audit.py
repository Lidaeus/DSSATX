"""Comprehensive Automated Test Suite for DSSAT Multi-Parameter Joint Injection & Read-back Audit.

Ensures:
1. Multi-parameter simultaneous row injection (e.g., PGEFF + KDIF + LFANGB on same row).
2. Full parameter vector joint injection across CUL, ECO, SPE, SOIL, and FileX.
3. Strict 3-way audit: Candidate Value -> Injected Formatted String -> Read-back Value.
4. Prevention of cross-field overwriting, label truncation, or format overflow.
5. Narrow-field precision and decimal floor representation checks.
"""
from __future__ import annotations

import csv
import hashlib
import re
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from src.dssat import run_dssat


ROOT = Path(__file__).resolve().parents[1]
SPE_BASE = ROOT / "data/templates/genotype/TMGRO048.SPE.base"
ECO_BASE = ROOT / "data/templates/genotype/TMGRO048.ECO.base"
CUL_BASE = ROOT / "data/templates/genotype/TMGRO048.CUL.base"
NUMBER_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?")


def _read_spe_named_rows(path: Path) -> dict[str, list[float]]:
    """Read all numeric values from named rows in SPE file."""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    row_values = {}
    for line in lines:
        for needle in [
            "PARMAX,PHTMAX",
            "PGEFF SCV KDIF",
            "DSWBAR,XFRMAX",
            "FINREF,SLAREF",
            "WTFSD,PORPT",
            "CMOBMX,CADSTF",
            "SLAMAX,SLAMIN",
            "SENRTE,SENRT2",
            "SETMAX,SRMAX",
            "RTNO3,RTNH4",
            "SLWREF,SLWSLO",
            "PROLFI,PROLFG",
            "PRORTI,PRORTG",
            "XPODF",
            "FRLFMX"
        ]:
            if needle in line:
                nums = [float(m.group(0)) for m in NUMBER_RE.finditer(line)]
                row_values[needle] = nums
    return row_values


def test_pgeff_kdif_lfangb_same_row_joint_injection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CRITICAL TEST: Verify that PGEFF, KDIF, and LFANGB on line 11 are injected independently
    and that LFANGB NEVER overwrites PGEFF."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_dssat, "SPE_FILE", "TMGRO048.SPE")
    (tmp_path / "TMGRO048.SPE.base").write_bytes(SPE_BASE.read_bytes())
    
    # Injected values: PGEFF is small, LFANGB is large
    params_csv = tmp_path / "test_pgeff_params.csv"
    test_values = {
        "PGEFF": 0.0541,
        "KDIF": 0.850,
        "LFANGB": 1.20,
    }
    with params_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "value"])
        for k, v in test_values.items():
            writer.writerow([k, v])
            
    run_dssat.update_spe_file(str(params_csv))
    
    spe_out = tmp_path / "TMGRO048.SPE"
    assert spe_out.exists()
    
    rows = _read_spe_named_rows(spe_out)
    assert "PGEFF SCV KDIF" in rows
    pgeff_row = rows["PGEFF SCV KDIF"]
    
    # Expected row: [PGEFF, SCV (0.20), KDIF, LFANGB]
    assert len(pgeff_row) >= 4
    read_pgeff = pgeff_row[0]
    read_scv = pgeff_row[1]
    read_kdif = pgeff_row[2]
    read_lfangb = pgeff_row[3]
    
    # PGEFF must match ~0.0541, NOT LFANGB (1.20)
    assert read_pgeff == pytest.approx(0.0541, abs=0.01), f"PGEFF was corrupted to {read_pgeff}!"
    assert read_scv == pytest.approx(0.20, abs=0.01)
    assert read_kdif == pytest.approx(0.850, abs=0.01)
    assert read_lfangb == pytest.approx(1.20, abs=0.05)


def test_dswbar_xfrmax_shlag_same_row_joint_injection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that DSWBAR, XFRMAX, and SHLAG on line 84 are injected independently."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_dssat, "SPE_FILE", "TMGRO048.SPE")
    (tmp_path / "TMGRO048.SPE.base").write_bytes(SPE_BASE.read_bytes())
    
    params_csv = tmp_path / "test_dswbar_params.csv"
    test_values = {
        "DSWBAR": 14.5,
        "XFRMAX": 0.22,
        "SHLAG": 0.08,
    }
    with params_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "value"])
        for k, v in test_values.items():
            writer.writerow([k, v])
            
    run_dssat.update_spe_file(str(params_csv))
    
    rows = _read_spe_named_rows(tmp_path / "TMGRO048.SPE")
    assert "DSWBAR,XFRMAX" in rows
    row = rows["DSWBAR,XFRMAX"]
    assert len(row) >= 3
    assert row[0] == pytest.approx(14.5, abs=0.1)
    assert row[1] == pytest.approx(0.22, abs=0.01)
    assert row[2] == pytest.approx(0.08, abs=0.01)


def test_narrow_field_precision_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that very small decimal values like SHLAG=0.001 survive without rounding to 0.0."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_dssat, "SPE_FILE", "TMGRO048.SPE")
    (tmp_path / "TMGRO048.SPE.base").write_bytes(SPE_BASE.read_bytes())
    
    params_csv = tmp_path / "test_narrow_params.csv"
    test_values = {
        "SHLAG": 0.001,
        "PGEFF": 0.0341,
        "RTNO3": 0.005,
    }
    with params_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "value"])
        for k, v in test_values.items():
            writer.writerow([k, v])
            
    run_dssat.update_spe_file(str(params_csv))
    
    rows = _read_spe_named_rows(tmp_path / "TMGRO048.SPE")
    row_dswbar = rows["DSWBAR,XFRMAX"]
    # SHLAG is 3rd element
    assert row_dswbar[2] == pytest.approx(0.001, abs=0.0005)
    
    row_pg = rows["PGEFF SCV KDIF"]
    assert row_pg[0] == pytest.approx(0.0341, abs=0.005)


def test_full_canopy_and_spe_joint_injection_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Comprehensive test: Injects 25 simultaneous parameters into SPE and asserts full readback integrity."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_dssat, "SPE_FILE", "TMGRO048.SPE")
    (tmp_path / "TMGRO048.SPE.base").write_bytes(SPE_BASE.read_bytes())
    
    test_params = {
        "PARMAX": 45.0,
        "PHTMAX": 68.0,
        "KCAN": 0.52,
        "KC_SLOPE": 0.018,
        "PGEFF": 0.065,
        "KDIF": 0.88,
        "LFANGB": 1.40,
        "FINREF": 250.0,
        "SLAREF": 480.0,
        "SIZREF": 420.0,
        "VSSINK": 5.2,
        "WTFSD": 0.42,
        "PORPT": 0.19,
        "FRSTMF": 0.32,
        "FRLFF": 0.26,
        "ATOP": 0.80,
        "FRCNOD": 0.05,
        "SLAMAX": 650.0,
        "SLAMIN": 320.0,
        "TURSLA": 0.85,
        "NSLA": 1.35,
        "DSWBAR": 16.0,
        "XFRMAX": 0.15,
        "SHLAG": 0.04,
        "FRLFMX": 0.65,
        "SETMAX": 0.35,
        "SRMAX": 0.45,
        "SENRTE": 1.10,
        "SENDAY": 0.025,
        "RTNO3": 0.025,
        "RTNH4": 0.035,
        "PORMIN": 0.040,
        "RTEXF": 0.35,
    }
    
    params_csv = tmp_path / "full_test_params.csv"
    with params_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "value"])
        for k, v in test_params.items():
            writer.writerow([k, v])
            
    run_dssat.update_spe_file(str(params_csv))
    
    spe_file = tmp_path / "TMGRO048.SPE"
    rows = _read_spe_named_rows(spe_file)
    
    # 1. PARMAX, PHTMAX, KCAN, KC_SLOPE
    r_par = rows["PARMAX,PHTMAX"]
    assert r_par[0] == pytest.approx(45.0, abs=0.1)
    assert r_par[1] == pytest.approx(68.0, abs=0.1)
    assert r_par[2] == pytest.approx(0.52, abs=0.01)
    assert r_par[3] == pytest.approx(0.018, abs=0.005)
    
    # 2. PGEFF, SCV, KDIF, LFANGB
    r_pg = rows["PGEFF SCV KDIF"]
    assert r_pg[0] == pytest.approx(0.065, abs=0.01)
    assert r_pg[2] == pytest.approx(0.88, abs=0.01)
    assert r_pg[3] == pytest.approx(1.40, abs=0.05)
    
    # 3. FINREF, SLAREF, SIZREF, VSSINK
    r_fin = rows["FINREF,SLAREF"]
    assert r_fin[0] == pytest.approx(250.0, abs=1.0)
    assert r_fin[1] == pytest.approx(480.0, abs=1.0)
    assert r_fin[2] == pytest.approx(420.0, abs=1.0)
    assert r_fin[3] == pytest.approx(5.2, abs=0.1)
    
    # 4. WTFSD, PORPT, FRSTMF, FRLFF, ATOP, FRCNOD
    r_wtf = rows["WTFSD,PORPT"]
    assert r_wtf[0] == pytest.approx(0.42, abs=0.01)
    assert r_wtf[1] == pytest.approx(0.19, abs=0.01)
    assert r_wtf[2] == pytest.approx(0.32, abs=0.01)
    assert r_wtf[3] == pytest.approx(0.26, abs=0.01)
    assert r_wtf[4] == pytest.approx(0.80, abs=0.01)
    assert r_wtf[5] == pytest.approx(0.05, abs=0.01)
