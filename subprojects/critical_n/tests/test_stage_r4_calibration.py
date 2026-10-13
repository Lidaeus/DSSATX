"""Unit and integration tests for Stage R4 calibration and diagnostic comparison.

Verifies:
1. Parameter purification: exactly 61 active parameters, 5 ghost parameters strictly fixed.
2. Bottleneck release: SENPOR_LATE upper bound relaxed to 0.300, RWUMX to 0.006, RTNO3 to 0.003,
   FRSTMF to 0.950, FL-LF in [140.0, 220.0], exogenous invariants locked (CNC_A=4.85, CNC_B=0.38,
   CNC_W0=1.00, CNC_NC_INF=1.70%).
3. Objective catalog & rebalancing: 737 targets (689 base + 48 CNC r_tol), 17 families,
   76% terminal yield dominance, HPODW downweighted to 2.0%, SWAD to 1.5%, Pseudo-Huber loss.
4. Production isolation: C:\\DSSAT48\\DSCSM048.EXE untouched (hash verified).
5. r_tol zero-residual projection operator logic across N0-N3 physiological tolerance intervals.
"""

from __future__ import annotations

import math
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

from subprojects.critical_n.calibration.stage_r4_setup import (
    STAGE_R4_ACTIVE_PARAMETERS,
    STAGE_R4_GHOST_PARAMETERS,
    STAGE_R4_BOUND_ADJUSTMENTS,
    STAGE_R4_OBJECTIVE_POLICY,
    create_stage_r4_bounds,
    create_stage_r4_objective_catalog,
    loss_residual,
)
from subprojects.critical_n.core.objective_penalty import (
    PHYSIOLOGICAL_NNI_INTERVALS,
    tolerance_relaxation_operator,
    pseudo_huber_loss,
)
from subprojects.critical_n.scripts.build_and_verify_dssat import (
    PRODUCTION_EXE,
    PRODUCTION_HASH,
    check_production_safety,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CRITICAL_N_DIR = PROJECT_ROOT / "subprojects" / "critical_n"


def test_stage_r4_active_parameters_purified():
    """Verify exactly 61 active parameters and that 5 Fortran ghost parameters are purged."""
    base_bounds_file = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_26sp_all12_posterior_joint65_20261012.csv"
    assert base_bounds_file.is_file(), f"Missing base bounds file: {base_bounds_file}"

    b_df = create_stage_r4_bounds(base_bounds_file)
    active_params = b_df[b_df["status"] == "active"]["name"].tolist()

    # Must be exactly 61 active parameters
    assert len(active_params) == 61
    assert set(active_params) == set(STAGE_R4_ACTIVE_PARAMETERS)

    # 5 ghost parameters must all be status: fixed
    b_indexed = b_df.set_index("name")
    for gp in STAGE_R4_GHOST_PARAMETERS:
        assert gp in b_indexed.index, f"Ghost parameter {gp} missing from bounds table"
        assert b_indexed.loc[gp, "status"] == "fixed", f"Ghost parameter {gp} is not fixed!"


def test_stage_r4_bottleneck_bounds_released():
    """Verify physical bottlenecks released and exogenous invariants locked."""
    base_bounds_file = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_26sp_all12_posterior_joint65_20261012.csv"
    b_df = create_stage_r4_bounds(base_bounds_file).set_index("name")

    # SENPOR_LATE upper bound relaxed to 0.300 (in range 0.28~0.32)
    senpor = b_df.loc["SENPOR_LATE"]
    assert senpor["status"] == "active"
    assert senpor["upper"] >= 0.280
    assert math.isclose(senpor["upper"], 0.300, abs_tol=1e-4)

    # RWUMX lower bound relaxed to 0.006
    rwumx = b_df.loc["RWUMX"]
    assert rwumx["status"] == "active"
    assert rwumx["lower"] <= 0.006

    # RTNO3 lower bound relaxed to 0.003
    rtno3 = b_df.loc["RTNO3"]
    assert rtno3["status"] == "active"
    assert math.isclose(rtno3["lower"], 0.003, abs_tol=1e-4)

    # FRSTMF upper bound relaxed to 0.950
    frstmf = b_df.loc["FRSTMF"]
    assert frstmf["status"] == "active"
    assert math.isclose(frstmf["upper"], 0.950, abs_tol=1e-4)

    # FL-LF maintained in reasonable physiological range [140.0, 220.0]
    fl_lf = b_df.loc["FL-LF"]
    assert fl_lf["status"] == "active"
    assert fl_lf["lower"] >= 140.0
    assert fl_lf["upper"] <= 220.0

    # Invariants strictly locked
    invariants = {
        "CNC_A": 4.85,
        "CNC_B": 0.38,
        "CNC_W0": 1.00,
        "CNC_NC_INF": 1.70,
    }
    for inv_name, expected_val in invariants.items():
        assert inv_name in b_df.index
        assert b_df.loc[inv_name, "status"] == "fixed"
        assert math.isclose(float(b_df.loc[inv_name, "init"]), expected_val, rel_tol=1e-4)


def test_stage_r4_objective_catalog_and_policy():
    """Verify objective catalog has 737 targets, 17 families, 100.0 budget, and rebalanced weights."""
    base_obs_file = PROJECT_ROOT / "configs/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/calibration_observations.csv"
    tmt_file = PROJECT_ROOT / "configs/figures/treatment_metadata_xxql2601.csv"

    obs_df, pol_df = create_stage_r4_objective_catalog(base_obs_file, tmt_file)

    # 1. Target count
    assert len(obs_df) == 737  # 689 base direct targets + 48 CNC r_tol soft constraints
    assert len(pol_df) == 17

    # 2. Total phi budget
    assert math.isclose(pol_df["phi_budget"].sum(), 100.0, rel_tol=1e-5)

    pol_indexed = pol_df.set_index("family")

    # 3. Terminal yield dominance
    dry_b = pol_indexed.loc["FINAL_DRY_YIELD", "phi_budget"]
    fresh_b = pol_indexed.loc["FINAL_FRESH_YIELD", "phi_budget"]
    assert math.isclose(dry_b + fresh_b, 76.0, abs_tol=1e-4)

    # 4. De-weighted variables
    assert math.isclose(pol_indexed.loc["HARVEST_DRY_EVENT", "phi_budget"], 2.0, abs_tol=1e-4)
    assert math.isclose(pol_indexed.loc["STEM_DRY_MASS", "phi_budget"], 1.5, abs_tol=1e-4)

    # 5. CNC soft constraint
    assert "CNC_NNI_PENALTY" in pol_indexed.index
    assert math.isclose(pol_indexed.loc["CNC_NNI_PENALTY", "phi_budget"], 2.0, abs_tol=1e-4)
    assert pol_indexed.loc["CNC_NNI_PENALTY", "loss"] == "pseudo_huber"

    # 6. Verify 48 CNC targets
    cnc_targets = obs_df[obs_df["family"] == "CNC_NNI_PENALTY"]
    assert len(cnc_targets) == 48
    assert (cnc_targets["observed"] == 0.0).all()
    assert (cnc_targets["variable"] == "R_TOL").all()
    expected_w = math.sqrt(2.0 / 48)
    assert np.allclose(cnc_targets["final_weight"], expected_w, rtol=1e-5)


def test_stage_r4_r_tol_projection_operator():
    """Verify zero-residual one-sided relaxation operator r_tol properties."""
    # N3 luxury interval: [1.00, 1.30]
    lo_n3, hi_n3 = PHYSIOLOGICAL_NNI_INTERVALS["N3"]
    assert lo_n3 == 1.00 and hi_n3 == 1.30

    # Inside interval -> exactly 0.0
    assert tolerance_relaxation_operator(1.05, lo_n3, hi_n3) == 0.0
    assert tolerance_relaxation_operator(1.15, lo_n3, hi_n3) == 0.0
    assert tolerance_relaxation_operator(1.30, lo_n3, hi_n3) == 0.0

    # Below interval (deficit) -> negative deviation
    r_def = tolerance_relaxation_operator(0.90, lo_n3, hi_n3)
    assert math.isclose(r_def, -0.10, abs_tol=1e-6)

    # Above interval (excess luxury) -> positive deviation
    r_exc = tolerance_relaxation_operator(1.50, lo_n3, hi_n3)
    assert math.isclose(r_exc, 0.20, abs_tol=1e-6)

    # Pseudo-Huber loss on zero residual is exactly 0.0
    assert pseudo_huber_loss(0.0, delta=0.15) == 0.0
    # On non-zero residual is strictly positive and smooth
    assert pseudo_huber_loss(r_exc, delta=0.15) > 0.0


def test_stage_r4_production_environment_isolation():
    """Verify production DSSAT binary is 100% unmodified and isolated."""
    assert PRODUCTION_EXE.is_file(), "Production DSCSM048.EXE not found"
    check_production_safety()
    import hashlib
    current_hash = hashlib.sha256(PRODUCTION_EXE.read_bytes()).hexdigest()
    assert current_hash == PRODUCTION_HASH
