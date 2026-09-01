"""Set up Multi-Arm Parallel Exploration Experiments (Arms A, B, C, D) for v32."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.param_registry import assert_valid_frozen_bounds

BOUNDS_DIR = ROOT / "data/parameter_registry/bounds_frozen/eggplant"
CONFIG_DIR = ROOT / "configs/runs"

# 1. Base template from v31
v31_df = pd.read_csv(BOUNDS_DIR / "eggplant_e02_v31_balanced_bounds_20260829.csv")


def setup_arm_a():
    """Arm A: Baseline Rebalanced Control."""
    df = v31_df.copy()
    bounds_path = BOUNDS_DIR / "eggplant_e02_v32_arm_a_baseline_bounds.csv"
    df.to_csv(bounds_path, index=False)
    assert_valid_frozen_bounds(str(bounds_path))

    policy_content = """group,phi_budget,note
PHENO,0.10,PDAT only in first design; ADAT/MDAT diagnostic
CANOPY,0.50,Measured multi-date LAI state constraint
CANOPY_INCREMENT,0.35,Implementation alias for LAI increment
CANOPY_TERMINAL,0.20,Implementation alias for exact-date terminal LAI
BIOMASS,0.35,Raw LWAD/SWAD states diagnostic only
BIOMASS_INCREMENT,0.35,Leaf/stem dry-mass increments
BIOMASS_TERMINAL,0.20,Terminal leaf/stem dry-mass states
PLANT_N,0.40,SNAM plus LNAM
HARVEST_FRESH,2.00,Fresh cumulative harvest target
HARVEST_DRY_INCREMENT,2.00,Event dry-harvest increments
HARVEST_DRY_TOTAL,3.50,Terminal cumulative dry harvest
HARVEST_DRY_TREND,0.10,Diagnostic-only safety budget
N_RESPONSE,0.05,Response NSE
W_RESPONSE,0.05,Response NSE
CUMULATIVE_HARVEST,1.80,Cumulative yield target
INCREMENTAL_HARVEST,1.20,Incremental harvest target
SOIL_WATER,0.05,Audited soil-water
"""
    (CONFIG_DIR / "e02_from_scratch_group_policy_v32_arma.csv").write_text(policy_content, encoding="utf-8")


def setup_arm_b():
    """Arm B: Sink Duration & Remobilization Breakthrough."""
    df = v31_df.copy()
    overrides = {
        "sfdur": (50.0, 40.0, 68.0, "active"),
        "wtfsd": (0.50, 0.40, 0.65, "active"),
        "xfrmax": (0.25, 0.12, 0.40, "active"),
        "porpt": (0.32, 0.22, 0.45, "active"),
        "cmobmx": (0.10, 0.02, 0.25, "active"),
        "nmobmx": (0.10, 0.05, 0.25, "active"),
        "parmax": (45.0, 38.0, 55.0, "active"),
        "trifl": (0.78, 0.72, 0.85, "active"),
        "slavr": (240.0, 185.0, 310.0, "active"),
        "slaref": (290.0, 225.0, 370.0, "active"),
    }
    for p_name, (init_v, lo_v, hi_v, stat) in overrides.items():
        idx = df[df["name"].str.lower() == p_name.lower()].index
        if not idx.empty:
            df.loc[idx, "init"] = init_v
            df.loc[idx, "lower"] = lo_v
            df.loc[idx, "upper"] = hi_v
            df.loc[idx, "status"] = stat

    bounds_path = BOUNDS_DIR / "eggplant_e02_v32_arm_b_sink_filling_bounds.csv"
    df.to_csv(bounds_path, index=False)
    assert_valid_frozen_bounds(str(bounds_path))

    policy_content = """group,phi_budget,note
PHENO,0.10,PDAT only in first design; ADAT/MDAT diagnostic
CANOPY,0.40,Measured multi-date LAI state constraint
CANOPY_INCREMENT,0.25,Implementation alias for LAI increment
CANOPY_TERMINAL,0.15,Implementation alias for exact-date terminal LAI
BIOMASS,0.25,Raw LWAD/SWAD states diagnostic only
BIOMASS_INCREMENT,0.25,Leaf/stem dry-mass increments relaxed for sink expansion
BIOMASS_TERMINAL,0.15,Terminal leaf/stem dry-mass states relaxed for remobilization
PLANT_N,0.30,SNAM plus LNAM
HARVEST_FRESH,2.50,Fresh cumulative harvest target
HARVEST_DRY_INCREMENT,3.00,Event dry-harvest increments strongly boosted
HARVEST_DRY_TOTAL,5.00,Terminal cumulative dry harvest maximum budget
HARVEST_DRY_TREND,0.10,Diagnostic-only safety budget
N_RESPONSE,0.05,Response NSE
W_RESPONSE,0.05,Response NSE
CUMULATIVE_HARVEST,2.50,Cumulative yield target
INCREMENTAL_HARVEST,2.00,Incremental harvest target
SOIL_WATER,0.05,Audited soil-water
"""
    (CONFIG_DIR / "e02_from_scratch_group_policy_v32_armb.csv").write_text(policy_content, encoding="utf-8")


def setup_arm_c():
    """Arm C: Nitrogen Stress Mitigation & Uptake Dynamics."""
    df = v31_df.copy()
    overrides = {
        "nstfac": (0.85, 0.70, 0.95, "active"),
        "nmobmx": (0.12, 0.05, 0.25, "active"),
        "nrmin": (0.60, 0.35, 0.85, "active"),
        "nrexp": (0.65, 0.20, 1.20, "active"),
        "rtno3": (0.038, 0.025, 0.050, "active"),
        "rwumx": (0.045, 0.035, 0.053, "active"),
        "soil_slpf": (0.92, 0.88, 0.96, "active"),
        "sfdur": (48.0, 40.0, 60.0, "active"),
        "cmobmx": (0.08, 0.02, 0.20, "active"),
    }
    for p_name, (init_v, lo_v, hi_v, stat) in overrides.items():
        idx = df[df["name"].str.lower() == p_name.lower()].index
        if not idx.empty:
            df.loc[idx, "init"] = init_v
            df.loc[idx, "lower"] = lo_v
            df.loc[idx, "upper"] = hi_v
            df.loc[idx, "status"] = stat

    bounds_path = BOUNDS_DIR / "eggplant_e02_v32_arm_c_nitrogen_resilience_bounds.csv"
    df.to_csv(bounds_path, index=False)
    assert_valid_frozen_bounds(str(bounds_path))

    policy_content = """group,phi_budget,note
PHENO,0.10,PDAT only in first design; ADAT/MDAT diagnostic
CANOPY,0.45,Measured multi-date LAI state constraint
CANOPY_INCREMENT,0.30,Implementation alias for LAI increment
CANOPY_TERMINAL,0.20,Implementation alias for exact-date terminal LAI
BIOMASS,0.30,Raw LWAD/SWAD states diagnostic only
BIOMASS_INCREMENT,0.30,Leaf/stem dry-mass increments
BIOMASS_TERMINAL,0.20,Terminal leaf/stem dry-mass states
PLANT_N,0.60,SNAM plus LNAM boosted for nitrogen dynamics
HARVEST_FRESH,2.00,Fresh cumulative harvest target
HARVEST_DRY_INCREMENT,2.20,Event dry-harvest increments
HARVEST_DRY_TOTAL,4.00,Terminal cumulative dry harvest
HARVEST_DRY_TREND,0.10,Diagnostic-only safety budget
N_RESPONSE,0.40,Explicit penalty on N-treatment yield differential error
W_RESPONSE,0.05,Response NSE
CUMULATIVE_HARVEST,2.00,Cumulative yield target
INCREMENTAL_HARVEST,1.50,Incremental harvest target
SOIL_WATER,0.05,Audited soil-water
"""
    (CONFIG_DIR / "e02_from_scratch_group_policy_v32_armc.csv").write_text(policy_content, encoding="utf-8")


def setup_arm_d():
    """Arm D: 25-Parameter Condensed Integrated Arm."""
    df = v31_df.copy()
    # Active 25 core parameters
    core_25 = {
        "pgeff": (0.052, 0.045, 0.058),
        "parmax": (45.0, 38.0, 55.0),
        "sfdur": (50.0, 40.0, 65.0),
        "wtfsd": (0.50, 0.40, 0.65),
        "xfrmax": (0.25, 0.12, 0.38),
        "porpt": (0.32, 0.22, 0.42),
        "cmobmx": (0.08, 0.02, 0.22),
        "nmobmx": (0.10, 0.04, 0.22),
        "nstfac": (0.85, 0.75, 0.95),
        "nrmin": (0.60, 0.40, 0.85),
        "trifl": (0.78, 0.72, 0.85),
        "lfmax": (1.70, 1.40, 2.10),
        "lngsh": (25.0, 18.0, 35.0),
        "slavr": (240.0, 190.0, 310.0),
        "slaref": (290.0, 230.0, 360.0),
        "sizlf": (85.0, 60.0, 120.0),
        "fl-sd": (12.0, 10.0, 16.0),
        "sd-pm": (38.0, 30.0, 50.0),
        "pm06": (0.50, 0.20, 0.80),
        "pm09": (0.50, 0.20, 0.80),
        "soil_slpf": (0.92, 0.89, 0.96),
        "rtno3": (0.035, 0.020, 0.048),
        "rwumx": (0.045, 0.035, 0.053),
        "dswbar": (15.0, 8.0, 22.0),
        "kc_slope": (0.020, 0.010, 0.035),
    }

    # Set all other parameters to fixed
    for idx, row in df.iterrows():
        pname = row["name"].lower()
        if pname in core_25:
            init_v, lo_v, hi_v = core_25[pname]
            df.loc[idx, "init"] = init_v
            df.loc[idx, "lower"] = lo_v
            df.loc[idx, "upper"] = hi_v
            df.loc[idx, "status"] = "active"
        else:
            df.loc[idx, "status"] = "fixed"
            df.loc[idx, "lower"] = df.loc[idx, "init"]
            df.loc[idx, "upper"] = df.loc[idx, "init"]

    bounds_path = BOUNDS_DIR / "eggplant_e02_v32_arm_d_condensed_integrated_bounds.csv"
    df.to_csv(bounds_path, index=False)
    assert_valid_frozen_bounds(str(bounds_path))

    policy_content = """group,phi_budget,note
PHENO,0.10,PDAT only in first design; ADAT/MDAT diagnostic
CANOPY,0.45,Measured multi-date LAI state constraint
CANOPY_INCREMENT,0.30,Implementation alias for LAI increment
CANOPY_TERMINAL,0.15,Implementation alias for exact-date terminal LAI
BIOMASS,0.30,Raw LWAD/SWAD states diagnostic only
BIOMASS_INCREMENT,0.25,Leaf/stem dry-mass increments
BIOMASS_TERMINAL,0.15,Terminal leaf/stem dry-mass states relaxed for remobilization
PLANT_N,0.30,SNAM plus LNAM
HARVEST_FRESH,2.20,Fresh cumulative harvest target
HARVEST_DRY_INCREMENT,2.50,Event dry-harvest increments
HARVEST_DRY_TOTAL,4.50,Terminal cumulative dry harvest strongly boosted
HARVEST_DRY_TREND,0.10,Diagnostic-only safety budget
N_RESPONSE,0.10,Response NSE
W_RESPONSE,0.05,Response NSE
CUMULATIVE_HARVEST,2.20,Cumulative yield target
INCREMENTAL_HARVEST,1.80,Incremental harvest target
SOIL_WATER,0.05,Audited soil-water
"""
    (CONFIG_DIR / "e02_from_scratch_group_policy_v32_armd.csv").write_text(policy_content, encoding="utf-8")


def setup_run_configs():
    """Create run JSON configs for all 4 arms (60 realizations x 4 iterations)."""
    arms = [
        ("arma", "eggplant_e02_v32_arm_a_baseline_bounds", "e02_from_scratch_group_policy_v32_arma"),
        ("armb", "eggplant_e02_v32_arm_b_sink_filling_bounds", "e02_from_scratch_group_policy_v32_armb"),
        ("armc", "eggplant_e02_v32_arm_c_nitrogen_resilience_bounds", "e02_from_scratch_group_policy_v32_armc"),
        ("armd", "eggplant_e02_v32_arm_d_condensed_integrated_bounds", "e02_from_scratch_group_policy_v32_armd"),
    ]

    for arm_id, bounds_id, group_policy in arms:
        cfg = {
            "schema_version": 1,
            "design_id": f"e02_multiarm_v32_{arm_id}_60x4_20260829",
            "run_id": f"e02_multiarm_v32_{arm_id}_60x4_20260829",
            "case": f"e02_multiarm_v32_{arm_id}_20260829",
            "crop": "eggplant",
            "cultivar": "TM0008",
            "cultivar_identity": "TM0008",
            "mode": "eggplant_stage2",
            "bounds_id": bounds_id,
            "bounds_crop": "eggplant",
            "observation_policy": "configs/runs/e02_from_scratch_objective_contract_v31.csv",
            "group_policy": f"configs/runs/{group_policy}.csv",
            "noptmax": 4,
            "ies_num_reals": 60,
            "ies_par_csv": None,
            "pestpp_mode": "ies",
            "n_agents": 6,
            "harvest_var": "CHPDT",
            "dssat_model": "CRGRO048",
            "custom_dssat_executable": "C:/DSSAT48/DSCSM048.EXE",
            "custom_spe": "data/templates/genotype/TMGRO048.SPE.base",
            "seasons": [
                {
                    "season_id": "25SP",
                    "experiment_code": "XXQL2501",
                    "bundle_path": "data/user/experiments/xxql2501_formal_armab_rrmse_20260828",
                    "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
                    "role": "calibration"
                },
                {
                    "season_id": "26SP",
                    "experiment_code": "XXQL2601",
                    "bundle_path": "data/user/experiments/xxql2601_formal_armab_rrmse_26spncal_20260828",
                    "treatments": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
                    "role": "calibration"
                }
            ]
        }
        json_path = CONFIG_DIR / f"e02_multiarm_v32_{arm_id}_60x4_20260829.json"
        json_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"Created config: {json_path.name}")


if __name__ == "__main__":
    setup_arm_a()
    setup_arm_b()
    setup_arm_c()
    setup_arm_d()
    setup_run_configs()
    print("Multi-Arm v32 bounds, policies, and configs initialized successfully!")
