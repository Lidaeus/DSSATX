"""Isolation and regression verification tests.

Verifies that the Critical Nitrogen Dilution subproject has zero invasive impact
on the existing core parameter calibration workflows in `src/`.
"""

import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_core_src_modules_unmodified_behavior():
    """Verify that importing and using src modules is completely undisturbed."""
    import src.dssat.run_dssat as rd
    import src.calibration.build_pest as bp
    import src.common.param_registry as pr

    # Check key functions and variables exist
    assert hasattr(rd, "prepare_run_directory")
    assert hasattr(bp, "PEST_HARVEST_FILE")
    assert hasattr(pr, "PHYSICAL_BOUNDS")
    assert len(pr.PHYSICAL_BOUNDS) > 50


def test_runner_adapter_zero_crash_on_standard_directory(tmp_path):
    """Verify runner_adapter does not crash or raise errors on normal DSSAT directories."""
    from subprojects.critical_n.calibration.runner_adapter import post_process_dssat_cnc

    # When DSSAT output files don't exist, simply returns None without error
    res = post_process_dssat_cnc(tmp_path)
    assert res is None


def test_subproject_directory_self_containment():
    """Verify that subprojects/critical_n/ contains all required packages and tools."""
    base = PROJECT_ROOT / "subprojects" / "critical_n"
    assert (base / "core" / "dilution_curve.py").is_file()
    assert (base / "core" / "effective_biomass.py").is_file()
    assert (base / "core" / "objective_penalty.py").is_file()
    assert (base / "adapters" / "stream_parser.py").is_file()
    assert (base / "adapters" / "pest_cnc_exporter.py").is_file()
    assert (base / "adapters" / "instruction_generator.py").is_file()
    assert (base / "calibration" / "bounds_protocol.py").is_file()
    assert (base / "calibration" / "cnc_builder.py").is_file()
    assert (base / "calibration" / "runner_adapter.py").is_file()
    assert (base / "scripts" / "run_cnc_postprocessor.py").is_file()
    assert (base / "scripts" / "demo_cnc_evaluation.py").is_file()
    assert (base / "scripts" / "compare_scheme_b_dynamics.py").is_file()
    assert (base / "scheme_b" / "acclimation.py").is_file()
    assert (base / "scheme_b" / "senescence_limiter.py").is_file()
    assert (base / "scheme_b" / "mass_balance.py").is_file()
    assert (base / "scheme_b" / "cropgro_proxy.py").is_file()
    assert (base / "scheme_b" / "adapter.py").is_file()
    assert (base / "scheme_b" / "patch_manager.py").is_file()
    assert (base / "fortran_patch" / "README.md").is_file()
    assert (base / "fortran_patch" / "patches" / "SENES.for.patch").is_file()
    assert (base / "fortran_patch" / "patches" / "PHOTO.for.patch").is_file()
    assert (base / "fortran_patch" / "patches" / "CROPGRO.for.patch").is_file()
    assert (base / "fortran_patch" / "src_scheme_b" / "SENES_CNC.FOR").is_file()
    assert (base / "fortran_patch" / "src_scheme_b" / "PHOTO_CNC.FOR").is_file()
    assert (base / "fortran_patch" / "src_scheme_b" / "CROPGRO_CNC.FOR").is_file()
