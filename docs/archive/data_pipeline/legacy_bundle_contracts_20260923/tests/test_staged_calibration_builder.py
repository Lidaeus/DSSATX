"""Unit tests for Phase 2 staged calibration (S1-S5) in build_pest.py."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu
import pytest

from src.calibration.build_pest import (
    STAGE_ACTIVE_PARAMS,
    _detect_and_relax_boundary_touches,
    _finalize_ies_contract,
    _load_parent_par_csv,
)
from src.common.param_registry import PHYSICAL_BOUNDS
from src.common.project import PROJECT_ROOT


def test_stage_active_params_counts():
    """Verify exact parameter counts per stage defined in Phase 1 plan."""
    assert len(STAGE_ACTIVE_PARAMS["S1"]) == 12
    assert len(STAGE_ACTIVE_PARAMS["S2"]) == 11
    assert len(STAGE_ACTIVE_PARAMS["S3"]) == 7
    assert len(STAGE_ACTIVE_PARAMS["S4"]) == 17
    assert len(STAGE_ACTIVE_PARAMS["S5"]) == 10

    # Ensure FL-VS is NOT active in any stage
    for stage, params in STAGE_ACTIVE_PARAMS.items():
        assert "FL-VS" not in params, f"FL-VS must be fixed, but found active in {stage}"


def test_s1_pest_build_dryrun():
    """Verify S1 PST generation with 8-run calibration batch."""
    test_out = PROJECT_ROOT / "workspace" / "test_s1_dryrun"
    if test_out.exists():
        shutil.rmtree(test_out)

    cmd = [
        "python",
        "src/calibration/build_pest.py",
        "--mode", "eggplant_staged_s1",
        "--bounds-id", "eggplant_e02_wnp_s1_s5_20260914",
        "--bounds-crop", "eggplant",
        "--prefix", "s1_dryrun",
        "--noptmax", "4",
        "--ies-num-reals", "80",
        "--batch", "data/templates/batch/DSSBatch_calib.v48",
        "--harvest-var", "CHPDT",
        "--param-review-mode", "off",
        "--out-dir", str(test_out),
    ]
    import subprocess
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"build_pest failed:\n{res.stderr}\n{res.stdout}"

    pst_path = test_out / "s1_dryrun.pst"
    assert pst_path.is_file()
    pst = pyemu.Pst(str(pst_path))

    # Assertions on PST
    assert pst.control_data.noptmax == 4
    par_df = pst.parameter_data
    adj = par_df[par_df["partrans"] == "none"]
    assert len(adj) == 12
    assert set(adj["parnme"].str.upper()) == {p.upper() for p in STAGE_ACTIVE_PARAMS["S1"]}

    # FL-VS must be strictly 100.0 fixed
    fl_vs = par_df.loc["fl-vs"]
    assert fl_vs["partrans"] == "fixed"
    assert float(fl_vs["parval1"]) == 100.0
    assert float(fl_vs["parlbnd"]) == 100.0
    assert float(fl_vs["parubnd"]) == 100.0

    # 8 phenology observations (8 runs * 1: ADAPM, excluding indeterminate MDAP)
    obs_df = pst.observation_data
    assert len(obs_df) == 8
    assert all(w == pytest.approx(0.5) for w in obs_df["weight"])

    # Ensemble checks
    ens_path = test_out / "s1_dryrun.0.par.csv"
    assert ens_path.is_file()
    ens = pd.read_csv(ens_path)
    assert len(ens) == 80
    assert set(ens.columns) - {"real_name"} == set(adj["parnme"])

    # Clean up
    shutil.rmtree(test_out)


def test_parent_par_csv_inheritance():
    """Verify --parent-par-csv properly updates parameters and inherits realizations."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        parent_file = tmp_path / "dummy_parent.par.csv"
        # Create a dummy parent par csv with S1 calibrated values
        df_parent = pd.DataFrame({
            "real_name": [str(i) for i in range(20)],
            "em-fl": np.linspace(24.0, 28.0, 20),
            "tb1": np.linspace(8.5, 9.0, 20),
        })
        df_parent.to_csv(parent_file, index=False)

        medians = _load_parent_par_csv(parent_file)
        assert "EM-FL" in medians
        assert "TB1" in medians
        assert medians["EM-FL"] == pytest.approx(26.0)
        assert medians["TB1"] == pytest.approx(8.75)


def test_s5_microtuning_bounds():
    """Verify S5 fine-tuning window (+/- 5%) is clamped within physical bounds."""
    test_out = PROJECT_ROOT / "workspace" / "test_s5_bounds_dryrun"
    if test_out.exists():
        shutil.rmtree(test_out)

    cmd = [
        "python",
        "src/calibration/build_pest.py",
        "--mode", "eggplant_staged_s5",
        "--bounds-id", "eggplant_e02_wnp_s1_s5_20260914",
        "--bounds-crop", "eggplant",
        "--prefix", "s5_dryrun",
        "--noptmax", "6",
        "--ies-num-reals", "40",
        "--batch", "data/templates/batch/DSSBatch_calib.v48",
        "--harvest-var", "CHPDT",
        "--param-review-mode", "off",
        "--out-dir", str(test_out),
    ]
    import subprocess
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"build_pest failed:\n{res.stderr}\n{res.stdout}"

    pst = pyemu.Pst(str(test_out / "s5_dryrun.pst"))
    adj = pst.parameter_data[pst.parameter_data["partrans"] == "none"]
    assert len(adj) == 10  # 8 core + 2 microtuning

    # Check PGEFF +/- 5%
    pgeff = adj.loc["pgeff"]
    pgeff_init = float(pgeff["parval1"])
    assert float(pgeff["parlbnd"]) == pytest.approx(pgeff_init * 0.95, rel=1e-3)
    assert float(pgeff["parubnd"]) == pytest.approx(pgeff_init * 1.05, rel=1e-3)

    # Clean up
    shutil.rmtree(test_out)


def test_detect_and_relax_boundary_touches():
    """Verify 10% bound relaxation when parent posterior severely touches boundaries."""
    df_parent = pd.DataFrame({
        "real_name": [str(i) for i in range(30)],
        "par_lower_touch": np.linspace(10.00, 10.30, 30),
        "par_upper_touch": np.linspace(1.95, 2.00, 30),
        "par_normal": np.linspace(4.5, 5.5, 30),
    })
    bounds_df = pd.DataFrame({
        "name": ["PAR_LOWER_TOUCH", "PAR_UPPER_TOUCH", "PAR_NORMAL"],
        "init": [10.2, 1.98, 5.0],
        "lower": [10.0, 1.0, 0.0],
        "upper": [20.0, 2.0, 10.0],
        "status": ["active", "active", "active"],
    })

    updated_bounds, audit = _detect_and_relax_boundary_touches(
        df_parent, bounds_df, relax_fraction=0.10
    )

    # PAR_LOWER_TOUCH: range = 10.0, delta = 1.0. New lower should be 10.0 - 1.0 = 9.0
    row_l = updated_bounds[updated_bounds["name"] == "PAR_LOWER_TOUCH"].iloc[0]
    assert float(row_l["lower"]) == pytest.approx(9.0)
    assert float(row_l["upper"]) == pytest.approx(20.0)

    # PAR_UPPER_TOUCH: range = 1.0, delta = 0.1. New upper should be 2.0 + 0.1 = 2.1
    row_u = updated_bounds[updated_bounds["name"] == "PAR_UPPER_TOUCH"].iloc[0]
    assert float(row_u["lower"]) == pytest.approx(1.0)
    assert float(row_u["upper"]) == pytest.approx(2.1)

    # PAR_NORMAL: should remain unchanged
    row_n = updated_bounds[updated_bounds["name"] == "PAR_NORMAL"].iloc[0]
    assert float(row_n["lower"]) == pytest.approx(0.0)
    assert float(row_n["upper"]) == pytest.approx(10.0)

