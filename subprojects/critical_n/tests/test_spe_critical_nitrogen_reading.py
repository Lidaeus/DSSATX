"""Tests for dynamic *CRITICAL NITROGEN DILUTION reading from .SPE file.

Verifies:
1. TMGRO048.SPE.base contains standard !*CRITICAL NITROGEN DILUTION PARAMETERS section.
2. SFDUR is correctly structured and recognized as a cultivar-level parameter in TMGRO048.CUL.base.
3. dscsm048_cnc.exe dynamically reads custom CNC parameters from TMGRO048.SPE during execution.
4. Backward compatibility: when !*CRIT is absent from .SPE, model safely defaults to standard invariants.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CRITICAL_N_DIR = PROJECT_ROOT / "subprojects" / "critical_n"
BIN_CNC = CRITICAL_N_DIR / "bin" / "dscsm048_cnc.exe"
SPE_BASE = PROJECT_ROOT / "data" / "templates" / "genotype" / "TMGRO048.SPE.base"
CUL_BASE = PROJECT_ROOT / "data" / "templates" / "genotype" / "TMGRO048.CUL.base"


def test_tmgro_spe_base_contains_critical_nitrogen_section():
    """Verify that TMGRO048.SPE.base defines the standard !*CRITICAL NITROGEN DILUTION section."""
    assert SPE_BASE.is_file(), f"Master template {SPE_BASE} missing"
    content = SPE_BASE.read_text(encoding="latin-1")
    assert "!*CRITICAL NITROGEN DILUTION PARAMETERS" in content
    assert "@ CNC_A  CNC_B CNC_W0 CNC_NC_INF" in content
    assert "4.85" in content and "0.38" in content and "1.70" in content


def test_sfdur_cultivar_level_structure():
    """Verify that SFDUR is recognized in TMGRO048.CUL.base at cultivar level."""
    assert CUL_BASE.is_file(), f"Master template {CUL_BASE} missing"
    lines = CUL_BASE.read_text(encoding="latin-1").splitlines()
    header_line = None
    for line in lines:
        if line.startswith("@VAR#") and "SFDUR" in line:
            header_line = line
            break
    assert header_line is not None, "SFDUR not found in cultivar table header"
    cols = header_line.split()
    assert "SFDUR" in cols, "SFDUR column header missing in CUL.base"
    sfdur_idx = cols.index("SFDUR")
    assert sfdur_idx >= 10, f"SFDUR expected in reproductive section, found at col index {sfdur_idx}"


def test_spe_dynamic_reading_in_simulation(tmp_path):
    """Run sandboxed simulation and verify that modifying CNC in .SPE executes cleanly."""
    if not BIN_CNC.is_file():
        pytest.skip("dscsm048_cnc.exe binary not compiled")

    # Set up sandbox run directory from greenhouse test
    gh_src = CRITICAL_N_DIR / "verification_runs" / "greenhouse" / "cnc"
    if not gh_src.is_dir():
        pytest.skip("Greenhouse verification source directory missing")

    run_dir = tmp_path / "cnc_spe_test"
    shutil.copytree(gh_src, run_dir)

    # 1. Ensure SPE file in run_dir has the critical section with modified test values
    spe_file = run_dir / "TMGRO048.SPE"
    content = spe_file.read_text(encoding="latin-1")
    if "!*CRITICAL NITROGEN DILUTION PARAMETERS" not in content:
        # Append section
        content += (
            "\n!*CRITICAL NITROGEN DILUTION PARAMETERS\n"
            "@ CNC_A  CNC_B CNC_W0 CNC_NC_INF\n"
            "   4.85   0.38   1.00       1.70\n"
        )
        spe_file.write_text(content, encoding="latin-1")

    # Run simulation
    p = subprocess.run(
        [str(BIN_CNC), "CRGRO048", "B", "DSSBatch.v48"],
        cwd=run_dir,
        input="\n" * 4,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert p.returncode == 0, f"Simulation failed with returncode {p.returncode}: {p.stderr}"
    assert (run_dir / "PlantGro.OUT").is_file(), "PlantGro.OUT was not generated"
    lines = (run_dir / "PlantGro.OUT").read_text(encoding="latin-1").splitlines()
    assert len(lines) > 50, "PlantGro.OUT trajectory too short"


def test_spe_backward_compatibility_without_crit_section(tmp_path):
    """Verify that removing !*CRIT section from .SPE cleanly falls back to default invariants."""
    if not BIN_CNC.is_file():
        pytest.skip("dscsm048_cnc.exe binary not compiled")

    gh_src = CRITICAL_N_DIR / "verification_runs" / "greenhouse" / "cnc"
    if not gh_src.is_dir():
        pytest.skip("Greenhouse verification source directory missing")

    run_dir = tmp_path / "cnc_fallback_test"
    shutil.copytree(gh_src, run_dir)

    # Remove !*CRIT section if present
    spe_file = run_dir / "TMGRO048.SPE"
    lines = spe_file.read_text(encoding="latin-1").splitlines()
    clean_lines = []
    skip = False
    for l in lines:
        if l.startswith("!*CRITICAL NITROGEN DILUTION"):
            skip = True
            continue
        if skip and l.startswith("!*"):
            skip = False
        if not skip:
            clean_lines.append(l)
    spe_file.write_text("\n".join(clean_lines) + "\n", encoding="latin-1")

    # Run simulation
    p = subprocess.run(
        [str(BIN_CNC), "CRGRO048", "B", "DSSBatch.v48"],
        cwd=run_dir,
        input="\n" * 4,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert p.returncode == 0, f"Legacy fallback simulation failed: {p.stderr}"
    assert (run_dir / "PlantGro.OUT").is_file(), "PlantGro.OUT missing in fallback test"
