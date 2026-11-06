"""Tests for DSSAT compiler toolchain, binary integrity, CTest test suite, and sandbox simulation execution."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import pytest

from subprojects.critical_n.scripts.build_and_verify_dssat import (
    find_toolchain,
    check_production_safety,
    run_ctest_suite,
    run_official_benchmark,
    run_greenhouse_experiment,
    PRODUCTION_EXE,
    PRODUCTION_HASH,
    BIN_VANILLA,
    BIN_CNC,
    BUILD_BASELINE_DIR,
    BUILD_CUSTOM_DIR,
    DSSAT_CSM_CNC_DIR,
)
from subprojects.critical_n.scheme_b.patch_manager import validate_fortran_fixed_format


def test_toolchain_detection():
    """Verify all required compiler and build tools are detected."""
    tools = find_toolchain()
    assert "gfortran" in tools
    assert "gcc" in tools
    assert "cmake" in tools
    assert "ninja" in tools
    assert "ctest" in tools

    for tool_name, tool_path in tools.items():
        assert Path(tool_path).is_file(), f"Tool {tool_name} path does not exist: {tool_path}"


def test_production_dssat_unmodified_contract():
    """Verify production DSSAT binary is untouched and matches known SHA-256."""
    assert PRODUCTION_EXE.is_file(), "Production DSCSM048.EXE not found"
    check_production_safety()
    current_hash = hashlib.sha256(PRODUCTION_EXE.read_bytes()).hexdigest()
    assert current_hash == PRODUCTION_HASH


def test_compiled_binaries_exist_and_isolated():
    """Verify that both vanilla and CNC binaries exist within subprojects/critical_n/bin/."""
    assert BIN_VANILLA.is_file(), f"Missing vanilla binary: {BIN_VANILLA}"
    assert BIN_CNC.is_file(), f"Missing Scheme B binary: {BIN_CNC}"

    # Verify both are located inside subprojects/critical_n/bin/
    assert "subprojects" in str(BIN_VANILLA)
    assert "subprojects" in str(BIN_CNC)

    # Size should be reasonable for release build (~10-20MB)
    assert 5 * 1024 * 1024 < BIN_VANILLA.stat().st_size < 30 * 1024 * 1024
    assert 5 * 1024 * 1024 < BIN_CNC.stat().st_size < 30 * 1024 * 1024


def test_patched_fortran_sources_fixed_format_compliance():
    """Verify all Scheme B patched routines in dssat_csm_cnc strictly obey 72 columns."""
    if not DSSAT_CSM_CNC_DIR.is_dir():
        pytest.skip("Custom source tree not yet generated")

    cropgro_dir = DSSAT_CSM_CNC_DIR / "Plant" / "CROPGRO"
    for fname in ["PHOTO.for", "SENES.for", "CROPGRO.for"]:
        fpath = cropgro_dir / fname
        assert fpath.is_file(), f"Patched source missing: {fpath}"
        violations = validate_fortran_fixed_format(fpath)
        assert len(violations) == 0, f"Format violations in {fname}: {violations[:3]}"


def test_custom_dssat_runs_help():
    """Verify that the custom binary can be invoked and outputs DSSAT version info."""
    assert BIN_CNC.is_file()
    # Running without arguments returns DSSAT usage help
    p = subprocess.run([str(BIN_CNC)], capture_output=True, text=True)
    # DSSAT exits with STOP 99 when no arguments given
    assert "dscsm048 <model> runmode <argA> <argB>" in p.stdout


def test_ctest_suite_execution():
    """Verify native CTest test runner executes and passes all registered test cases."""
    if not (BUILD_BASELINE_DIR / "CTestTestfile.cmake").is_file():
        pytest.skip("CTestTestfile.cmake not yet generated in baseline build directory")

    tools = find_toolchain()

    # 1. Baseline CTest
    res_v = run_ctest_suite(BUILD_BASELINE_DIR, tools)
    assert res_v["passed"], f"Baseline CTest failed:\n{res_v['stdout']}\n{res_v['stderr']}"

    # 2. Custom Scheme B CTest
    if (BUILD_CUSTOM_DIR / "CTestTestfile.cmake").is_file():
        res_c = run_ctest_suite(BUILD_CUSTOM_DIR, tools)
        assert res_c["passed"], f"Scheme B CTest failed:\n{res_c['stdout']}\n{res_c['stderr']}"


def test_compiled_vanilla_and_cnc_tomato_benchmark_execution(tmp_path):
    """Verify both compiled binaries can execute official Tomato benchmark end-to-end."""
    if not BIN_VANILLA.is_file() or not BIN_CNC.is_file():
        pytest.skip("Compiled binaries not present")

    # Run vanilla
    v_work = tmp_path / "tomato_vanilla"
    res_v = run_official_benchmark(BIN_VANILLA, "Tomato.v48", v_work, crop_model="CRGRO048")
    assert res_v["returncode"] == 0, f"Vanilla Tomato benchmark failed: {res_v['stderr']}"
    assert res_v["has_summary"] is True
    assert res_v["summary_lines"] > 0

    # Run CNC
    c_work = tmp_path / "tomato_cnc"
    res_c = run_official_benchmark(BIN_CNC, "Tomato.v48", c_work, crop_model="CRGRO048")
    assert res_c["returncode"] == 0, f"CNC Tomato benchmark failed: {res_c['stderr']}"
    assert res_c["has_summary"] is True
    assert res_c["summary_lines"] > 0


def test_greenhouse_simulation_mepho_l_backward_compatibility(tmp_path):
    """Verify Scheme B binary under standard MEPHO='L' produces full output without regression."""
    if not BIN_CNC.is_file():
        pytest.skip("Scheme B binary not present")

    work_dir = tmp_path / "gh_mepho_l"
    res = run_greenhouse_experiment(BIN_CNC, work_dir, mepho="L")
    assert res["returncode"] == 0, f"Greenhouse simulation MEPHO=L failed: {res['stderr']}"
    assert res["has_plantgro"] is True
    assert res["plantgro_lines"] > 1000
    assert res["has_freshwt"] is True


def test_greenhouse_simulation_scheme_b_active_coupling(tmp_path):
    """Verify Scheme B binary under MEPHO='C' engages continuous NNI acclimation with numerical stability."""
    if not BIN_VANILLA.is_file() or not BIN_CNC.is_file():
        pytest.skip("Binaries not present")

    v_work = tmp_path / "gh_v_c"
    c_work = tmp_path / "gh_c_c"

    res_v = run_greenhouse_experiment(BIN_VANILLA, v_work, mepho="C")
    res_c = run_greenhouse_experiment(BIN_CNC, c_work, mepho="C")

    assert res_v["returncode"] == 0, f"Vanilla MEPHO=C failed: {res_v['stderr']}"
    assert res_c["returncode"] == 0, f"CNC MEPHO=C failed: {res_c['stderr']}"

    assert res_c["has_plantgro"] is True
    assert res_c["plantgro_lines"] > 1000

    # Read PlantGro files and check for active Scheme B differentiation
    v_lines = (v_work / "PlantGro.OUT").read_text().splitlines()
    c_lines = (c_work / "PlantGro.OUT").read_text().splitlines()
    diffs = [i for i, (l1, l2) in enumerate(zip(v_lines, c_lines)) if l1 != l2 and not l1.startswith("*DSSAT")]
    # Active coupling must produce distinct physiological trajectories
    assert len(diffs) > 100, f"Expected active Scheme B trajectory divergence, got {len(diffs)} diffs"
