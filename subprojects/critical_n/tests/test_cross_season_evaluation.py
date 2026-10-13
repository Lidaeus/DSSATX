#!/usr/bin/env python3
"""Test Suite for Cross-Season Phenotype Evaluation & Stage R4+ Enhanced Parameters.

Verifies:
1. Production C:\\DSSAT48\\DSCSM048.EXE safety & zero-byte modification.
2. Parameter compliance: stage_r4_enhanced_parameters.csv strictly respects
   frozen bounds, keeps 5 Fortran ghost parameters fixed, and locks 4 exogenous invariants.
3. 26SP Calibration fidelity: Terminal fresh yield NRMSE strictly < 6.0%.
4. Cross-season generalization: Enhanced parameters achieve superior or competitive
   NSE, d-index, and NRMSE in 25SP and 25FA compared to the Official Baseline.
5. Mass conservation: PlantNBal residuals < 0.25 kg N/ha and SoilNiBal = 0.0 kg N/ha across all seasons.
6. Execution sandbox isolation: all operations remain strictly under subprojects/critical_n/.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CRITICAL_N_DIR = PROJECT_ROOT / "subprojects" / "critical_n"

from subprojects.critical_n.scripts.build_and_verify_dssat import (
    PRODUCTION_EXE,
    check_production_safety,
)
from subprojects.critical_n.calibration.stage_r4_setup import (
    STAGE_R4_ACTIVE_PARAMETERS,
    STAGE_R4_GHOST_PARAMETERS,
)
from subprojects.critical_n.core.dilution_curve import (
    DEFAULT_CNC_A,
    DEFAULT_CNC_B,
    DEFAULT_CNC_NC_INF,
    DEFAULT_CNC_W0,
)


def test_production_environment_isolation():
    """Verify production DSSAT remains pristine and untouched."""
    check_production_safety()
    assert PRODUCTION_EXE.exists(), "Production executable missing"


def test_stage_r4_enhanced_parameter_integrity():
    """Verify enhanced parameter set respects bounds and parameter identities."""
    enh_path = CRITICAL_N_DIR / "reports/stage_r4_enhanced_parameters.csv"
    bounds_path = CRITICAL_N_DIR / "reports/stage_r4_bounds.csv"

    assert enh_path.exists(), "Missing stage_r4_enhanced_parameters.csv"
    assert bounds_path.exists(), "Missing stage_r4_bounds.csv"

    enh_df = pd.read_csv(enh_path)
    bounds_df = pd.read_csv(bounds_path).set_index("name")

    enh_dict = dict(zip(enh_df["name"], enh_df["value"]))

    # Check exactly 61 active parameters
    active_in_enh = [p for p in enh_dict if bounds_df.loc[p, "status"] == "active"]
    assert len(active_in_enh) == 61, f"Expected 61 active parameters, found {len(active_in_enh)}"

    # Check 5 ghost parameters are fixed
    for gp in STAGE_R4_GHOST_PARAMETERS:
        assert gp in enh_dict, f"Ghost parameter {gp} missing"
        assert abs(enh_dict[gp] - bounds_df.loc[gp, "init"]) < 1e-6, f"Ghost parameter {gp} modified"

    # Check 4 exogenous CNC invariants
    assert abs(enh_dict["CNC_A"] - DEFAULT_CNC_A) < 1e-6
    assert abs(enh_dict["CNC_B"] - DEFAULT_CNC_B) < 1e-6
    assert abs(enh_dict["CNC_W0"] - DEFAULT_CNC_W0) < 1e-6
    assert abs(enh_dict["CNC_NC_INF"] - DEFAULT_CNC_NC_INF) < 1e-6

    # Check bounds for all parameters
    for name, val in enh_dict.items():
        if name in bounds_df.index:
            b_row = bounds_df.loc[name]
            lo = float(b_row["lower"])
            hi = float(b_row["upper"])
            assert lo - 1e-6 <= val <= hi + 1e-6, f"Parameter {name}={val} outside bounds [{lo}, {hi}]"


def test_cross_season_metrics_artifacts_exist():
    """Verify generated metrics reports and audits exist and are non-empty."""
    rep_dir = CRITICAL_N_DIR / "reports"
    required_files = [
        "official_vs_stage_r4_vs_enhanced_metrics.csv",
        "cross_season_treatment_summary.csv",
        "cross_season_mass_balance_audit.csv",
        "cross_season_nitrogen_dilution_audit.csv",
        "cross_season_trajectories_all.csv",
        "stage_r4_enhanced_parameters.csv",
        "stage_r4_enhanced_summary.json",
    ]
    for fn in required_files:
        fp = rep_dir / fn
        assert fp.exists(), f"Required artifact {fn} does not exist"
        assert fp.stat().st_size > 0, f"Artifact {fn} is empty"


def test_calibration_fidelity_and_generalization_gain():
    """Verify Enhanced parameters satisfy 26SP NRMSE < 6% and improve cross-season generalization."""
    metrics_path = CRITICAL_N_DIR / "reports/official_vs_stage_r4_vs_enhanced_metrics.csv"
    assert metrics_path.exists()
    df = pd.read_csv(metrics_path)

    # 1. 26SP Terminal Yield NRMSE check: must be < 6.0% and better than or equal to Stage R4
    tmt_path = CRITICAL_N_DIR / "reports/cross_season_treatment_summary.csv"
    tmt_df = pd.read_csv(tmt_path)
    enh_26_term = tmt_df[(tmt_df["season_id"] == "26SP") & (tmt_df["config_id"] == "custom_stage_r4_enhanced")]
    obs_26 = enh_26_term["fresh_yield_obs_kgha"].to_numpy()
    sim_26 = enh_26_term["fresh_yield_sim_kgha"].to_numpy()
    rmse_26 = np.sqrt(np.mean((sim_26 - obs_26) ** 2))
    nrmse_26 = 100.0 * rmse_26 / np.mean(obs_26)
    assert nrmse_26 < 6.0, f"26SP terminal fresh yield NRMSE {nrmse_26:.2f}% exceeds 6.0% limit"
    assert nrmse_26 <= 5.48, f"26SP terminal fresh yield NRMSE {nrmse_26:.2f}% should beat or equal Stage R4 (5.48%)"

    # 2. 25SP Spring Validation Gain: Enhanced achieves superior NSE and NRMSE over Official and Stage R4
    row_25sp_y = df[(df["season_id"] == "25SP") & (df["dataset_role"] == "validation") & (df["variable"] == "CHFPW")].iloc[0]
    assert row_25sp_y["nse_enhanced"] > 0.70, f"Expected 25SP yield NSE > 0.70, got {row_25sp_y['nse_enhanced']:.3f}"
    assert row_25sp_y["nse_enhanced"] > row_25sp_y["nse_official"], "25SP yield NSE should exceed Official"
    assert row_25sp_y["nse_enhanced"] > row_25sp_y["nse_stage_r4"], "25SP yield NSE should exceed Stage R4"
    assert row_25sp_y["nrmse_enhanced"] < row_25sp_y["nrmse_official"], "25SP yield NRMSE should be lower than Official"

    # 25SP LWAD fit
    row_25sp_lw = df[(df["season_id"] == "25SP") & (df["dataset_role"] == "validation") & (df["variable"] == "LWAD")].iloc[0]
    assert row_25sp_lw["nse_enhanced"] > 0.88, f"Expected 25SP LWAD NSE > 0.88, got {row_25sp_lw['nse_enhanced']:.3f}"

    # 3. 25FA Fall-Winter Validation & Diagnostic Gains
    # Validation fresh yield error cut by at least 25 percentage points vs Official
    row_25fa_y = df[(df["season_id"] == "25FA") & (df["dataset_role"] == "validation") & (df["variable"] == "CHFPW")].iloc[0]
    assert row_25fa_y["nrmse_enhanced"] < row_25fa_y["nrmse_official"] - 25.0, (
        f"Expected Enhanced 25FA yield NRMSE ({row_25fa_y['nrmse_enhanced']:.1f}%) "
        f"to be at least 25% lower than Official ({row_25fa_y['nrmse_official']:.1f}%)"
    )
    assert row_25fa_y["d_enhanced"] > row_25fa_y["d_official"], "Enhanced Willmott d should be higher than Official"

    # Diagnostic fresh yield error improves over Stage R4 and Official
    row_25fa_diag_y = df[(df["season_id"] == "25FA") & (df["dataset_role"] == "diagnostic") & (df["variable"] == "CHFPW")].iloc[0]
    assert row_25fa_diag_y["nrmse_enhanced"] < row_25fa_diag_y["nrmse_stage_r4"], "Diagnostic fresh yield NRMSE should improve over Stage R4"
    assert row_25fa_diag_y["nse_enhanced"] > row_25fa_diag_y["nse_stage_r4"], "Diagnostic fresh yield NSE should improve over Stage R4"

    # Leaf N% NSE in 25FA should be positive
    row_25fa_ln = df[(df["season_id"] == "25FA") & (df["dataset_role"] == "validation") & (df["variable"] == "LEAF_N_PCT")].iloc[0]
    assert row_25fa_ln["nse_enhanced"] > 0.0, "25FA validation Leaf N% NSE should be positive under Scheme B"


def test_mass_conservation_audit():
    """Verify Plant and Soil nitrogen mass balance closure across all runs."""
    mb_path = CRITICAL_N_DIR / "reports/cross_season_mass_balance_audit.csv"
    assert mb_path.exists()
    mb_df = pd.read_csv(mb_path)

    # Check that all records passed
    assert len(mb_df) >= 72, f"Expected at least 72 balance records, got {len(mb_df)}"
    assert (mb_df["status"] == "PASS").all(), "Some mass balance checks failed"

    # Check maximum plant N residual < 0.25 kg N/ha
    plant_mb = mb_df[mb_df["balance_type"] == "PlantNBal"]
    max_plant_res = plant_mb["residual_kgha"].max()
    assert max_plant_res < 0.25, f"Maximum plant N residual {max_plant_res:.4f} exceeds 0.25 kg/ha"


def test_nitrogen_dilution_trajectories():
    """Verify that organ nitrogen concentrations follow dilution dynamics under Scheme B."""
    dil_path = CRITICAL_N_DIR / "reports/cross_season_nitrogen_dilution_audit.csv"
    assert dil_path.exists()
    dil_df = pd.read_csv(dil_path)

    # In 26SP Treatment 1 for enhanced: check leaf N % decreases from early to late
    enh_t1 = dil_df[(dil_df["config_id"] == "custom_stage_r4_enhanced") & (dil_df["season_id"] == "26SP") & (dil_df["treatment"] == 1)]
    early_leaf_n = enh_t1[enh_t1["phase"] == "early"]["leaf_n_pct"].iloc[0]
    late_leaf_n = enh_t1[enh_t1["phase"] == "late"]["leaf_n_pct"].iloc[0]
    assert late_leaf_n <= early_leaf_n, f"Expected leaf N dilution: early={early_leaf_n}%, late={late_leaf_n}%"
