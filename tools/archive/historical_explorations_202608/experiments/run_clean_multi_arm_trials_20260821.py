"""Run Clean Multi-Arm Exploratory Trials with Pure Measured Initial Nitrogen (no legacy IC overwrite).

Arms:
- Arm A: High Leaf Nitrogen & Photosynthetic Capacity (Measured LNREF 4.2-5.6%)
- Arm B: Greenhouse Background Mineralization & 13-Layer Soil (SOIL_SLNF 1.8-2.6)
- Arm C: Enhanced Early Root Foraging & Deep Expansion (RTEXF 0.25-0.45, RWDTH 0.6-1.0, RTNO3/NH4, NRCVR)
- Arm D: Full Synergistic Optimization (A + B + C + Mild Senescence)
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
from tools.calibration.prepare_v20_senescence_slnf_official_20260820 import apply_phi_budget_weights

N_REALS = 50
NOPTMAX = 3
SEED = 20260821
BASE_FROZEN = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v21_13layer_synergy_20260820.csv"


def build_and_run_arm(arm_id: str, arm_name: str, bound_mods: dict[str, dict[str, float | str]]) -> dict:
    case_name = f"e02_clean_arm_{arm_id.lower()}_{arm_name}_50x3_20260821"
    run_dir = ROOT / "workspace/runs" / case_name
    bounds_id = f"eggplant_e02_clean_arm_{arm_id.lower()}_20260821"
    
    if run_dir.exists():
        shutil.rmtree(run_dir)
        
    print(f"\n=======================================================")
    print(f"   Building Clean {arm_id}: {arm_name}")
    print(f"   Run Dir: {run_dir}")
    print(f"=======================================================")
    
    # 1. Prepare bounds proposal
    frame = pd.read_csv(BASE_FROZEN, encoding="utf-8-sig")
    existing = set(frame["name"].str.lower())
    for pname, adj in bound_mods.items():
        if pname in existing:
            idx = frame[frame["name"].str.lower() == pname].index[0]
            for k, v in adj.items():
                if k in frame.columns:
                    frame.at[idx, k] = v
        else:
            new_row = {c: "" for c in frame.columns}
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
        
    subprocess.run([
        sys.executable, str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(proposal_csv), "--crop", "eggplant",
        "--bounds-id", bounds_id, "--notes", f"Clean {arm_id} ({arm_name}) with pure measured IC"
    ], cwd=ROOT, check=True)
    
    # 2. Design JSON
    design_path = ROOT / "configs/runs" / f"{case_name}.json"
    design_content = {
        "schema_version": 1,
        "design_id": case_name,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": f"Clean {arm_id} ({arm_name}) Exploration with Pure Measured IC",
        "bounds_id": bounds_id,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Pure measured FileX IC values with no legacy override",
        "nitrogen_response_objective": {"enabled": False},
        "water_response_objective": {"enabled": False},
        "harvest_dry_objective": {
            "enabled": True, "mode": "increment_plus_terminal", "variable": "CHPDT",
            "process_lambda_per_season": 200.0, "terminal_lambda_per_season": 300.0
        },
        "process_state_objective": {
            "enabled": True, "mode": "signed_difference_plus_terminal", "variables": ["LAID", "LWAD", "SWAD"]
        },
        "seasons": [
            {
                "season_id": "25SP", "experiment_code": "XXQL2501",
                "bundle_path": str(ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v4_13layer_20260820"),
                "role": "calibration", "treatments": [2, 5, 10, 13]
            },
            {
                "season_id": "26SP", "experiment_code": "XXQL2601",
                "bundle_path": str(ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v4_13layer_20260820"),
                "role": "calibration", "treatments": [2, 11, 3, 12]
            }
        ]
    }
    design_path.write_text(json.dumps(design_content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    
    # 3. Build Task using build_fixed_soil_joint_v3
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    cmd_build = [
        sys.executable, str(ROOT / "tools/calibration/build_fixed_soil_joint_v3_20260813.py"),
        "--variant", "official",
        "--case", case_name,
        "--design", str(design_path),
        "--bounds-id", bounds_id,
        "--noptmax", str(NOPTMAX),
        "--ies-num-reals", str(N_REALS),
        "--random-seed", str(SEED),
    ]
    subprocess.run(cmd_build, cwd=ROOT, env=env, check=True)
    
    # 4. Sync PST, Apply Phi Budget, Generate Sobol
    pst_path = run_dir / f"{case_name}.pst"
    audit_path = run_dir / f"{case_name}.weights.audit.csv"
    registry_path = run_dir / f"{case_name}_observation_registry.csv"
    pst = pyemu.Pst(str(pst_path))
    frozen = pd.read_csv(frozen_csv, encoding="utf-8-sig").set_index("name")
    
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
    
    # 5. Run Parallel IES
    print(f"Launching parallel IES for Clean {arm_id} ({N_REALS} reals x {NOPTMAX} iters)...")
    cmd_run = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir),
        "--case", case_name,
        "--mode", "ies",
        "--n-agents", "6",
        "--wait"
    ]
    subprocess.run(cmd_run, cwd=ROOT, check=True)
    
    # 6. Extract Best Phi
    phi_csv = run_dir / f"{case_name}.phi.actual.csv"
    best_phi = np.nan
    best_mem = None
    if phi_csv.exists():
        phi_df = pd.read_csv(phi_csv)
        last_row = phi_df.iloc[-1]
        members = [c for c in phi_df.columns if c not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]]
        min_p = float("inf")
        for m in members:
            val = float(last_row[m])
            if val < min_p:
                min_p = val
                best_mem = m
        best_phi = min_p
        print(f"Clean {arm_id} Completed: Best Member #{best_mem} with Phi = {best_phi:.2f}")
        
    return {
        "arm_id": arm_id, "name": arm_name, "case_name": case_name,
        "best_member": best_mem, "best_phi": best_phi, "run_dir": str(run_dir)
    }


def main():
    arms_config = [
        (
            "A", "High_LNREF_Measured",
            {
                "lnref": {"init": 4.80, "lower": 4.20, "upper": 5.60, "status": "active"},
                "lfmax": {"init": 1.45, "lower": 1.10, "upper": 1.90, "status": "active"},
                "slavr": {"init": 160.0, "lower": 130.0, "upper": 200.0, "status": "active"},
            }
        ),
        (
            "B", "High_SLNF_13Layer",
            {
                "soil_slnf": {"init": 2.20, "lower": 1.80, "upper": 2.80, "status": "active"},
                "lnref": {"init": 4.80, "lower": 4.20, "upper": 5.60, "status": "active"},
            }
        ),
        (
            "C", "Enhanced_Early_Root_Foraging",
            {
                "rtexf": {"init": 0.30, "lower": 0.22, "upper": 0.45, "status": "active"},
                "rwdth": {"init": 0.80, "lower": 0.60, "upper": 1.20, "status": "active"},
                "rtno3": {"init": 0.045, "lower": 0.030, "upper": 0.050, "status": "active"},
                "rtnh4": {"init": 0.045, "lower": 0.030, "upper": 0.050, "status": "active"},
                "nrcvr": {"init": 0.30, "lower": 0.20, "upper": 0.45, "status": "active"},
            }
        ),
        (
            "D", "Full_Synergy_Enhanced_Roots",
            {
                "lnref": {"init": 4.80, "lower": 4.20, "upper": 5.60, "status": "active"},
                "soil_slnf": {"init": 2.20, "lower": 1.80, "upper": 2.80, "status": "active"},
                "rtexf": {"init": 0.30, "lower": 0.22, "upper": 0.45, "status": "active"},
                "rwdth": {"init": 0.80, "lower": 0.60, "upper": 1.20, "status": "active"},
                "rtno3": {"init": 0.045, "lower": 0.030, "upper": 0.050, "status": "active"},
                "rtnh4": {"init": 0.045, "lower": 0.030, "upper": 0.050, "status": "active"},
                "nrcvr": {"init": 0.30, "lower": 0.20, "upper": 0.45, "status": "active"},
                "xfint": {"init": 0.18, "lower": 0.10, "upper": 0.30, "status": "active"},
                "nmobmx": {"init": 0.14, "lower": 0.08, "upper": 0.20, "status": "active"},
                "senrte": {"init": 0.80, "lower": 0.30, "upper": 2.50, "status": "active"},
                "nvsmob": {"init": 0.22, "lower": 0.20, "upper": 0.25, "status": "active"},
            }
        ),
    ]
    
    results = []
    for arm_id, arm_name, mods in arms_config:
        case_name = f"e02_clean_arm_{arm_id.lower()}_{arm_name}_50x3_20260821"
        run_dir = ROOT / "workspace/runs" / case_name
        phi_csv = run_dir / f"{case_name}.phi.actual.csv"
        if phi_csv.exists() and len(pd.read_csv(phi_csv)) >= 4:
            print(f"Skipping already completed {arm_id} ({case_name})")
            phi_df = pd.read_csv(phi_csv)
            last_row = phi_df.iloc[-1]
            members = [c for c in phi_df.columns if c not in ["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]]
            best_mem = None
            min_p = float("inf")
            for m in members:
                val = float(last_row[m])
                if val < min_p:
                    min_p = val
                    best_mem = m
            results.append({
                "arm_id": arm_id, "name": arm_name, "case_name": case_name,
                "best_member": best_mem, "best_phi": min_p, "run_dir": str(run_dir)
            })
            continue
        res = build_and_run_arm(arm_id, arm_name, mods)
        results.append(res)
        
    summary_df = pd.DataFrame(results)
    out_summary = ROOT / "workspace/experiments/clean_multi_arm_trials_summary_20260821.csv"
    out_summary.parent.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(out_summary, index=False)
    print("\n=======================================================")
    print("   Clean Multi-Arm Trials Summary (Pure Measured IC)")
    print("=======================================================")
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
