"""Run 4-arm exploratory calibration trials for senescence, LNREF, 13-layer soil, and root foraging.

Arms:
- Arm A: Measured High Leaf N (LNREF in [4.20, 5.60]%, XFINT in [0.10, 0.30])
- Arm B: 13-Layer Soil + High Background Mineralization (SOIL_SLNF in [1.60, 2.40], NRCVR in [0.15, 0.40])
- Arm C: Deep Root Growth & Foraging (RTEXF in [0.18, 0.35], deep SRGF active, RTNO3/RTNH4 in [0.03, 0.05])
- Arm D: Full-Factor Synergy (13-layer soil + LNREF [4.2-5.6]% + SLNF [1.6-2.4] + RTEXF [0.18-0.35] + NRCVR [0.15-0.40] + XFINT [0.10-0.30] + Senescence bounds)

Scale per arm: 50 reals x 3 iterations, 6 parallel agents.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.build_pest import _write_observation_noise_ensemble
from src.calibration.initial_ensemble import generate_lhs_ensemble, write_ensemble_csv

BASE_FROZEN = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v20_senescence_slnf_20260820.csv"
N_REALS = 50
NOPTMAX = 3
SEED = 20260820

ARM_SPECS = {
    "arm_a_measured_lnref": {
        "title": "Arm A: Measured High Leaf N (LNREF 4.2-5.6%)",
        "bundle_25sp": "xxql2501_repfilter_measuredmoisture_v3_measuredn_20260820",
        "bundle_26sp": "xxql2601_repfilter_measuredmoisture_v3_measuredn_20260820",
        "adjustments": {
            "lnref": {"init": 4.800, "lower": 4.200, "upper": 5.600, "status": "active"},
            "xfint": {"init": 0.180, "lower": 0.100, "upper": 0.300, "status": "active"},
        }
    },
    "arm_b_13layer_slnf": {
        "title": "Arm B: 13-Layer Soil + High Background Mineralization (SLNF 1.6-2.4)",
        "bundle_25sp": "xxql2501_repfilter_measuredmoisture_v4_13layer_20260820",
        "bundle_26sp": "xxql2601_repfilter_measuredmoisture_v4_13layer_20260820",
        "adjustments": {
            "soil_slnf": {"init": 1.900, "lower": 1.600, "upper": 2.400, "status": "active"},
            "nrcvr": {"init": 0.250, "lower": 0.150, "upper": 0.400, "status": "active"},
        }
    },
    "arm_c_deep_root_foraging": {
        "title": "Arm C: Deep Root Growth & Foraging (RTEXF 0.18-0.35 + Deep SRGF)",
        "bundle_25sp": "xxql2501_repfilter_measuredmoisture_v4_13layer_20260820",
        "bundle_26sp": "xxql2601_repfilter_measuredmoisture_v4_13layer_20260820",
        "adjustments": {
            "rtexf": {"init": 0.250, "lower": 0.180, "upper": 0.350, "status": "active"},
            "nrcvr": {"init": 0.250, "lower": 0.150, "upper": 0.400, "status": "active"},
            "rtno3": {"init": 0.045, "lower": 0.030, "upper": 0.050, "status": "active"},
            "rtnh4": {"init": 0.045, "lower": 0.030, "upper": 0.050, "status": "active"},
            "xfint": {"init": 0.180, "lower": 0.100, "upper": 0.300, "status": "active"},
        }
    },
    "arm_d_full_synergy": {
        "title": "Arm D: Full-Factor Synergy (13-Layer + LNREF 4.8% + SLNF 1.9 + RTEXF 0.25 + Root Foraging)",
        "bundle_25sp": "xxql2501_repfilter_measuredmoisture_v4_13layer_20260820",
        "bundle_26sp": "xxql2601_repfilter_measuredmoisture_v4_13layer_20260820",
        "adjustments": {
            "lnref": {"init": 4.800, "lower": 4.200, "upper": 5.600, "status": "active"},
            "soil_slnf": {"init": 1.900, "lower": 1.600, "upper": 2.400, "status": "active"},
            "rtexf": {"init": 0.250, "lower": 0.180, "upper": 0.350, "status": "active"},
            "nrcvr": {"init": 0.250, "lower": 0.150, "upper": 0.400, "status": "active"},
            "rtno3": {"init": 0.045, "lower": 0.030, "upper": 0.050, "status": "active"},
            "rtnh4": {"init": 0.045, "lower": 0.030, "upper": 0.050, "status": "active"},
            "xfint": {"init": 0.180, "lower": 0.100, "upper": 0.300, "status": "active"},
            "nmobmx": {"init": 0.140, "lower": 0.080, "upper": 0.200, "status": "active"},
            "senrte": {"init": 0.800, "lower": 0.300, "upper": 2.500, "status": "active"},
            "nvsmob": {"init": 0.220, "lower": 0.200, "upper": 0.250, "status": "active"},
        }
    }
}


def prepare_arm_task(arm_id: str, spec: dict) -> Path:
    case_name = f"e02_{arm_id}_50x3_20260820"
    bounds_id = f"eggplant_e02_{arm_id}_20260820"
    run_dir = ROOT / "workspace/runs" / case_name
    
    if run_dir.exists():
        shutil.rmtree(run_dir)
    
    # 1. Prepare Frozen Bounds
    frame = pd.read_csv(BASE_FROZEN, encoding="utf-8-sig")
    existing_names = set(frame["name"].str.lower())
    
    for pname, adj in spec["adjustments"].items():
        if pname in existing_names:
            idx = frame[frame["name"].str.lower() == pname].index[0]
            for k, v in adj.items():
                if k in frame.columns:
                    frame.at[idx, k] = v
        else:
            new_row = {col: "" for col in frame.columns}
            new_row["name"] = pname
            new_row.update(adj)
            frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)
            
    proposal_csv = ROOT / "data/parameter_registry/bounds_proposals" / f"{bounds_id}.csv"
    frozen_csv = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{bounds_id}.csv"
    proposal_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(proposal_csv, index=False, encoding="utf-8-sig")
    
    if frozen_csv.exists():
        os.remove(frozen_csv)
    meta_path = frozen_csv.parent / f"{bounds_id}.yaml"
    if meta_path.exists():
        os.remove(meta_path)
        
    cmd_freeze = [
        sys.executable, str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(proposal_csv), "--crop", "eggplant",
        "--bounds-id", bounds_id,
        "--notes", f"Exploratory trial: {spec['title']}"
    ]
    subprocess.run(cmd_freeze, cwd=ROOT, check=True)
    
    # 2. Prepare Design JSON
    design_path = ROOT / "configs/runs" / f"{case_name}.json"
    design_content = {
        "schema_version": 1,
        "design_id": case_name,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": f"Exploratory trial: {spec['title']}",
        "bounds_id": bounds_id,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Fixed corrected FileX with 5cm topdressing depth",
        "nitrogen_response_objective": {"enabled": False},
        "water_response_objective": {"enabled": False},
        "harvest_dry_objective": {
            "enabled": True, "mode": "increment_plus_terminal",
            "variable": "CHPDT", "process_lambda_per_season": 200.0, "terminal_lambda_per_season": 300.0
        },
        "process_state_objective": {
            "enabled": True, "mode": "signed_difference_plus_terminal", "variables": ["LAID", "LWAD", "SWAD"]
        },
        "seasonal_parameterization": None,
        "seasons": [
            {
                "season_id": "25SP", "experiment_code": "XXQL2501",
                "bundle_path": str(ROOT / f"data/user/experiments/{spec['bundle_25sp']}"),
                "role": "calibration", "treatments": [2, 5, 10, 13]
            },
            {
                "season_id": "26SP", "experiment_code": "XXQL2601",
                "bundle_path": str(ROOT / f"data/user/experiments/{spec['bundle_26sp']}"),
                "role": "calibration", "treatments": [2, 11, 3, 12]
            }
        ],
        "formal_contract": {
            "phi_budget": {
                "dry_proc": 200.0, "dry_term": 300.0, "laid": 150.0, "lwad": 150.0, "swad": 150.0, "soil_water": 50.0
            },
            "n_reals": N_REALS, "noptmax": NOPTMAX
        }
    }
    design_path.write_text(json.dumps(design_content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    
    # 3. Build PST using build_fixed_soil_joint_v3
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    cmd_build = [
        sys.executable, str(ROOT / "tools/calibration/build_fixed_soil_joint_v3_20260813.py"),
        "--variant", "official", "--case", case_name, "--design", str(design_path),
        "--bounds-id", bounds_id, "--noptmax", str(NOPTMAX),
        "--ies-num-reals", str(N_REALS), "--random-seed", str(SEED),
    ]
    subprocess.run(cmd_build, cwd=ROOT, env=env, check=True)
    
    # 4. Apply Weights & Initial Ensemble
    pst_path = run_dir / f"{case_name}.pst"
    audit_path = run_dir / f"{case_name}.weights.audit.csv"
    registry_path = run_dir / f"{case_name}_observation_registry.csv"
    pst = pyemu.Pst(str(pst_path))
    frozen = pd.read_csv(frozen_csv, encoding="utf-8-sig")
    frozen["name"] = frozen["name"].astype(str).str.lower()
    frozen = frozen.set_index("name")
    
    for name in pst.parameter_data.index:
        if name in frozen.index:
            status = str(frozen.at[name, "status"]).lower()
            if status == "fixed":
                pst.parameter_data.at[name, "partrans"] = "fixed"
                pst.parameter_data.at[name, "parval1"] = float(frozen.at[name, "init"])
                pst.parameter_data.at[name, "parlbnd"] = float(frozen.at[name, "lower"])
                pst.parameter_data.at[name, "parubnd"] = float(frozen.at[name, "upper"])
            else:
                value = float(frozen.at[name, "init"])
                lower = float(frozen.at[name, "lower"])
                upper = float(frozen.at[name, "upper"])
                pst.parameter_data.at[name, "partrans"] = "none"
                pst.parameter_data.at[name, "parlbnd"] = lower
                pst.parameter_data.at[name, "parubnd"] = upper
                pst.parameter_data.at[name, "parval1"] = min(max(value, lower), upper)
                
    # Reweight Phi budget
    from tools.calibration.prepare_v20_senescence_slnf_official_20260820 import apply_phi_budget_weights
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    apply_phi_budget_weights(pst, registry, audit, run_dir=run_dir)
    
    pst.control_data.noptmax = NOPTMAX
    pst.pestpp_options.update({
        "ies_num_reals": N_REALS,
        "rand_seed": SEED,
        "ies_parameter_ensemble": f"{case_name}.0.par.csv",
        "ies_observation_ensemble": f"{case_name}.observation_ensemble.csv",
        "ies_include_base": "false",
    })
    pst.write(str(pst_path))
    registry.reset_index(drop=True).to_csv(registry_path, index=False, encoding="utf-8-sig")
    audit.reset_index(drop=True).to_csv(audit_path, index=False, encoding="utf-8-sig")
    
    par = pst.parameter_data
    ensemble_bounds = pd.DataFrame({
        "name": par.index,
        "init": par.parval1,
        "lower": par.parlbnd,
        "upper": par.parubnd,
        "status": np.where(par.partrans.astype(str).str.lower().eq("fixed"), "fixed", "active"),
    })
    ensemble = generate_lhs_ensemble(N_REALS, ensemble_bounds, SEED, method="sobol")
    write_ensemble_csv(ensemble, run_dir / f"{case_name}.0.par.csv")
    _write_observation_noise_ensemble(pst_path, audit_path, run_dir, case_name, N_REALS, SEED)
    
    print(f"Task prepared for {arm_id} in {run_dir}")
    return run_dir


def run_all_arms() -> dict[str, dict]:
    results = {}
    for arm_id, spec in ARM_SPECS.items():
        print(f"\n=======================================================")
        print(f"  PREPARING & RUNNING: {spec['title']}")
        print(f"=======================================================")
        run_dir = prepare_arm_task(arm_id, spec)
        case_name = f"e02_{arm_id}_50x3_20260820"
        
        cmd_run = [
            sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
            "--run-dir", str(run_dir),
            "--case", case_name,
            "--mode", "ies",
            "--n-agents", "6",
            "--wait"
        ]
        res = subprocess.run(cmd_run, cwd=ROOT, text=True)
        if res.returncode != 0:
            print(f"Run failed for {arm_id}")
            continue
            
        # Parse Phi progress
        phi_file = run_dir / f"{case_name}.phi.actual.csv"
        if phi_file.exists():
            df_phi = pd.read_csv(phi_file)
            last = df_phi.iloc[-1]
            members = [c for c in df_phi.columns if c not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]]
            best_mem = None
            min_phi = float("inf")
            for m in members:
                val = float(last[m])
                if val < min_phi:
                    min_phi = val
                    best_mem = m
            results[arm_id] = {
                "title": spec["title"],
                "init_phi_mean": float(df_phi.iloc[0]["mean"]),
                "final_phi_mean": float(df_phi.iloc[-1]["mean"]),
                "best_member": best_mem,
                "best_phi": min_phi,
                "run_dir": str(run_dir)
            }
            print(f">>> {arm_id} SUCCESS: Best Member #{best_mem} with Phi = {min_phi:.2f}")
            
    summary_path = ROOT / "workspace/experiments/multi_arm_senescence_summary_20260820.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return results


if __name__ == "__main__":
    run_all_arms()
