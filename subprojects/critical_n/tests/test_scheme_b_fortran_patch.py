"""Tests for Scheme B Fortran patch compliance, sandbox application, and isolation."""

from __future__ import annotations

from pathlib import Path
import pytest

from subprojects.critical_n.scheme_b.patch_manager import (
    validate_fortran_fixed_format,
    apply_patch_in_sandbox,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FORTRAN_PATCH_DIR = PROJECT_ROOT / "subprojects" / "critical_n" / "fortran_patch"
ORIG_SRC_DIR = PROJECT_ROOT / "workspace" / "diagnostics" / "dssat-csm-os-v4.8.2-source" / "Plant" / "CROPGRO"


def test_fortran_fixed_format_column_72_compliance():
    """Verify all patched Fortran sources strictly obey the 72-column fixed-form limit."""
    src_dir = FORTRAN_PATCH_DIR / "src_scheme_b"
    assert src_dir.is_dir()

    for fname in [
        "PHOTO_CNC.FOR",
        "SENES_CNC.FOR",
        "CROPGRO_CNC.FOR",
        "MOBIL_CNC.FOR",
        "GROW_CNC.FOR",
        "DEMAND_CNC.FOR",
    ]:
        fpath = src_dir / fname
        assert fpath.is_file(), f"Missing patched Fortran source: {fname}"
        violations = validate_fortran_fixed_format(fpath)
        assert len(violations) == 0, (
            f"Fortran format violations in {fname}: {violations[:3]}"
        )


def test_fortran_patches_exist_and_non_empty():
    """Verify that unified diff patches exist and have content."""
    patch_dir = FORTRAN_PATCH_DIR / "patches"
    assert patch_dir.is_dir()

    for pname in [
        "PHOTO.for.patch",
        "SENES.for.patch",
        "CROPGRO.for.patch",
        "MOBIL.for.patch",
        "GROW.for.patch",
        "DEMAND.for.patch",
    ]:
        ppath = patch_dir / pname
        assert ppath.is_file()
        content = ppath.read_text(encoding="utf-8")
        assert len(content.strip()) > 50
        assert "@@" in content


def test_sandbox_patch_application_isolated(tmp_path):
    """Verify that patches apply cleanly in an isolated sandbox without touching originals."""
    if not ORIG_SRC_DIR.is_dir():
        pytest.skip(f"Original source directory not found: {ORIG_SRC_DIR}")

    patch_dir = FORTRAN_PATCH_DIR / "patches"

    # Test SENES patch in sandbox
    orig_senes = ORIG_SRC_DIR / "SENES.for"
    patch_senes = patch_dir / "SENES.for.patch"
    patched_file = apply_patch_in_sandbox(orig_senes, patch_senes, sandbox_dir=tmp_path)

    assert patched_file.is_file()
    patched_content = patched_file.read_text(encoding="latin-1")
    assert "WLDOTN" in patched_content
    assert "0.90 * MAX(0.0, WLDOTN)" in patched_content

    # Verify original file was completely untouched
    orig_content = orig_senes.read_text(encoding="latin-1")
    assert "0.90 * MAX(0.0, WLDOTN)" not in orig_content

    # Test PHOTO patch in sandbox
    orig_photo = ORIG_SRC_DIR / "PHOTO.for"
    patch_photo = patch_dir / "PHOTO.for.patch"
    patched_photo_file = apply_patch_in_sandbox(orig_photo, patch_photo, sandbox_dir=tmp_path)

    assert patched_photo_file.is_file()
    patched_photo_content = patched_photo_file.read_text(encoding="latin-1")
    assert "NNI_IN" in patched_photo_content
    assert "S_NNI" in patched_photo_content

    # Test CROPGRO patch in sandbox
    orig_cropgro = ORIG_SRC_DIR / "CROPGRO.for"
    patch_cropgro = patch_dir / "CROPGRO.for.patch"
    patched_cropgro_file = apply_patch_in_sandbox(orig_cropgro, patch_cropgro, sandbox_dir=tmp_path)

    assert patched_cropgro_file.is_file()
    patched_cropgro_content = patched_cropgro_file.read_text(encoding="latin-1")
    assert "NNI_CUR" in patched_cropgro_content
    assert "WEFF_C" in patched_cropgro_content
    assert "WLDOTN" in patched_cropgro_content

    # Test MOBIL patch in sandbox
    orig_mobil = ORIG_SRC_DIR / "MOBIL.for"
    patch_mobil = patch_dir / "MOBIL.for.patch"
    patched_mobil_file = apply_patch_in_sandbox(orig_mobil, patch_mobil, sandbox_dir=tmp_path)
    assert patched_mobil_file.is_file()
    patched_mobil_content = patched_mobil_file.read_text(encoding="latin-1")
    assert "NRUSLF_SAFE" in patched_mobil_content
    assert "NRUSLF_STR" in patched_mobil_content

    # Test GROW patch in sandbox
    orig_grow = ORIG_SRC_DIR / "GROW.for"
    patch_grow = patch_dir / "GROW.for.patch"
    patched_grow_file = apply_patch_in_sandbox(orig_grow, patch_grow, sandbox_dir=tmp_path)
    assert patched_grow_file.is_file()
    patched_grow_content = patched_grow_file.read_text(encoding="latin-1")
    assert "NRUSLF_SAFE * 1.0" in patched_grow_content
    assert "NRUSLF_STR/0.16" in patched_grow_content

    # Test DEMAND patch in sandbox
    orig_demand = ORIG_SRC_DIR / "DEMAND.for"
    patch_demand = patch_dir / "DEMAND.for.patch"
    patched_demand_file = apply_patch_in_sandbox(orig_demand, patch_demand, sandbox_dir=tmp_path)
    assert patched_demand_file.is_file()
    patched_demand_content = patched_demand_file.read_text(encoding="latin-1")
    assert "WEFF" in patched_demand_content
    assert "NC_DEM" in patched_demand_content
    assert "4.85" in patched_demand_content

    # Verify original files were completely untouched
    orig_cg_content = orig_cropgro.read_text(encoding="latin-1")
    assert "NNI_CUR" not in orig_cg_content
    orig_dem_content = orig_demand.read_text(encoding="latin-1")
    assert "NC_DEM" not in orig_dem_content


def test_sandbox_patched_sources_match_scheme_b_source_files(tmp_path):
    """Verify that applying patches to base sources exactly reproduces src_scheme_b files."""
    if not ORIG_SRC_DIR.is_dir():
        pytest.skip(f"Original source directory not found: {ORIG_SRC_DIR}")

    patch_dir = FORTRAN_PATCH_DIR / "patches"
    src_dir = FORTRAN_PATCH_DIR / "src_scheme_b"

    pairs = [
        ("PHOTO.for", "PHOTO.for.patch", "PHOTO_CNC.FOR"),
        ("SENES.for", "SENES.for.patch", "SENES_CNC.FOR"),
        ("CROPGRO.for", "CROPGRO.for.patch", "CROPGRO_CNC.FOR"),
        ("MOBIL.for", "MOBIL.for.patch", "MOBIL_CNC.FOR"),
        ("GROW.for", "GROW.for.patch", "GROW_CNC.FOR"),
        ("DEMAND.for", "DEMAND.for.patch", "DEMAND_CNC.FOR"),
    ]

    for orig_name, patch_name, cnc_name in pairs:
        orig_file = ORIG_SRC_DIR / orig_name
        patch_file = patch_dir / patch_name
        cnc_file = src_dir / cnc_name

        patched_file = apply_patch_in_sandbox(orig_file, patch_file, sandbox_dir=tmp_path)
        patched_lines = patched_file.read_text(encoding="latin-1").splitlines()
        cnc_lines = cnc_file.read_text(encoding="latin-1").splitlines()

        assert len(patched_lines) == len(cnc_lines), (
            f"Line count mismatch for {orig_name}: {len(patched_lines)} vs {len(cnc_lines)}"
        )
        assert patched_lines == cnc_lines, f"Content mismatch between patch output and {cnc_name}"

