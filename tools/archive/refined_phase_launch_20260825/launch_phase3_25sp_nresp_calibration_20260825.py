"""Phase 3: 25SP Nitrogen Stress & Response Parameter Calibration Launcher.

Setup:
- Best Environmental Base: Scheme 5 10-layer micro-grid soil ([2, 4, 15, 30, 40, 60, 80, 100, 140, 180] cm)
- Vigorous transplant initial conditions (PLWT = 9.442 g/plant, RTDEPI = 14.77 cm, PLDP = 8.0 cm)
- Cleaned outlier-free initial soil mineral N
- 4 Key Contrasting Treatments in 25SP: 
    * W3N0 (TRNO 5 - Zero Nitrogen, High Water)
    * W1N0 (TRNO 13 - Zero Nitrogen, Low Water)
    * W3N3 (TRNO 2 - High Nitrogen, High Water)
    * W1N3 (TRNO 10 - High Nitrogen, Low Water)
  (N0 treatments constitute exactly 50% of the dataset to maximize nitrogen response identifiability without dilution)
- Active Parameters: RTNO3, RTNH4, NREXP, NRMIN, NSTFAC, NMOBMX, NVSMOB, NRCVR, LNREF, NSLOPE, NSLA, SOIL_SLPF, organ protein fractions (PROLFI/G/F, PROSTI/G/F, PRORTI/G/F, PROSHI/G/F), XFINT, CMOBMX, SENRTE, SENDAY, soil bulk densities
- General phenology and temperature cardinals anchored at Phase 2 best posterior values.
- Configuration: 80 reals x 5 iters x 6 agents
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
import pandas as pd
import numpy as np
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CASE_NAME = "calib_25sp_nresp_phase3_20260825"
BOUNDS_ID = "eggplant_calib_25sp_nresp_phase3_20260825"
RUN_DIR = ROOT / "workspace/runs" / CASE_NAME
N_REALS = 80
NOPTMAX = 5
N_AGENTS = 6
SEED = 20260825

EXP_BUNDLE = ROOT / "data/user/experiments/xxql2501_best_env_10layer_20260825"
OFFICIAL_SPE = Path(r"C:\DSSAT48\Genotype\TMGRO048.SPE")
PHASE2_BEST_PARAMS = ROOT / "workspace/runs/calib_25sp_6treat_phase2_20260825/deterministic_best_base/best_params.csv"


def prepare_and_launch():
    print(f"\n====================================================================")
    print(f"   [Phase 3] 25SP Nitrogen Stress & Response Calibration")
    print(f"   Case: {CASE_NAME} | Bounds: {BOUNDS_ID}")
    print(f"   Treatments: 2 (W3N3), 5 (W3N0), 10 (W1N3), 13 (W1N0)")
    print(f"   Configuration: {N_REALS} reals x {NOPTMAX} iters x {N_AGENTS} agents")
    print(f"====================================================================\n")

    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Write Multi-Season Design JSON (Single Season with 4 contrasting treatments)
    design_path = ROOT / "configs/runs" / f"{CASE_NAME}.json"
    design_content = {
        "schema_version": 1,
        "design_id": CASE_NAME,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "Phase 3: 25SP Nitrogen Stress and Response Calibration with N0 Treatments",
        "bounds_id": BOUNDS_ID,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "diagnostic_single_season": True,
        "initial_condition_policy": "10-layer micro-grid soil with vigorous transplant and cleaned soil N",
        "nitrogen_response_objective": {"enabled": False},
        "water_response_objective": {"enabled": False},
        "harvest_dry_objective": {
            "enabled": True,
            "mode": "increment_plus_terminal",
            "variable": "CHPDT",
            "process_lambda_per_season": 200.0,
            "terminal_lambda_per_season": 300.0
        },
        "process_state_objective": {
            "enabled": True,
            "mode": "signed_difference_plus_terminal",
            "variables": ["LAID", "LWAD", "SWAD"]
        },
        "seasons": [
            {
                "season_id": "25SP",
                "experiment_code": "XXQL2501",
                "bundle_path": str(EXP_BUNDLE),
                "role": "calibration",
                "treatments": [2, 5, 10, 13]
            }
        ],
        "pest_ies": {
            "num_reals": N_REALS,
            "noptmax": NOPTMAX,
            "par_sigma_range": 4.0,
            "lambda_mults": [0.1, 1.0, 10.0],
            "subreg": True,
            "subreg_how": "par_sigma_range"
        }
    }
    with open(design_path, "w", encoding="utf-8") as f:
        json.dump(design_content, f, indent=2)

    # 2. Build PST via build_pest.py
    print(f"[1/4] Building PST via build_pest.py...")
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = str(OFFICIAL_SPE.resolve())
    policy_path = ROOT / "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv"

    cmd_build = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(design_path),
        "--input-dir", str(EXP_BUNDLE),
        "--bounds-id", BOUNDS_ID,
        "--bounds-crop", "eggplant",
        "--prefix", CASE_NAME,
        "--noptmax", str(NOPTMAX),
        "--ies-num-reals", str(N_REALS),
        "--random-seed", str(SEED),
        "--bad-phi-sigma", "1e300",
        "--batch", "DSSBatch.v48",
        "--harvest-var", "CHPDT",
        "--include-soil",
        "--out-dir", str(RUN_DIR),
        "--param-review-mode", "off",
        "--bounds-review-mode", "off",
        "--observation-policy-csv", str(policy_path),
        "--initial-ensemble-method", "sobol",
        "--no-include-n-uptake",
    ]
    subprocess.run(cmd_build, cwd=str(ROOT), env=env, check=True)

    # 3. Center-anchoring initial values
    print(f"\n[2/4] Center-anchoring parameter initial values to Phase 2 posterior base...")
    pst_file = RUN_DIR / f"{CASE_NAME}.pst"
    pst = pyemu.Pst(str(pst_file))
    
    if PHASE2_BEST_PARAMS.exists():
        df_base = pd.read_csv(PHASE2_BEST_PARAMS)
        base_dict = dict(zip(df_base["name"].str.lower(), df_base["value"]))
        n_anchored = 0
        for name in pst.parameter_data.index:
            key = str(name).lower()
            if key in base_dict:
                bval = float(base_dict[key])
                lb = float(pst.parameter_data.at[name, "parlbnd"])
                ub = float(pst.parameter_data.at[name, "parubnd"])
                safe_val = max(lb, min(ub, bval))
                pst.parameter_data.at[name, "parval1"] = safe_val
                n_anchored += 1
        print(f"  Successfully center-anchored {n_anchored} parameters!")

    pst.write(str(pst_file), version=2)

    # Update params CSV
    tpl_params_csv = RUN_DIR / f"{CASE_NAME}_params.csv"
    if "parnme" in pst.parameter_data.columns:
        params_df = pst.parameter_data[["parnme", "parval1", "parlbnd", "parubnd", "pargp"]].copy()
    else:
        params_df = pst.parameter_data.reset_index()[["index", "parval1", "parlbnd", "parubnd", "pargp"]].copy()
    params_df.columns = ["name", "value", "lower", "upper", "pargp"]
    params_df.to_csv(tpl_params_csv, index=False)

    n_adj = (pst.parameter_data["partrans"] == "none").sum()
    n_obs = len(pst.observation_data)
    nnz_obs = (pst.observation_data["weight"] > 0).sum()
    print(f"  PST verification: Total Params={len(pst.parameter_data)}, Active={n_adj}, Total Obs={n_obs}, Weighted Obs={nnz_obs}")

    # 4. Launch Parallel PEST++ IES
    print(f"\n[3/4] Launching {N_AGENTS}-Agent Parallel PEST++ IES...")
    cmd_parallel = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(RUN_DIR),
        "--case", CASE_NAME,
        "--mode", "ies",
        "--n-agents", str(N_AGENTS),
        "--wait"
    ]
    subprocess.run(cmd_parallel, cwd=str(ROOT), check=True)
    print(f"\n[4/4] Phase 3 Calibration Execution Finished!")

    # Auto-run analysis
    from tools.analysis.analyze_phase1_calibration_results import analyze_run
    analyze_run(CASE_NAME, RUN_DIR, design_path)


if __name__ == "__main__":
    prepare_and_launch()
