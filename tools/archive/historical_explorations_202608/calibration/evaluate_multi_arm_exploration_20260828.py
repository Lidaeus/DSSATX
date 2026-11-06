"""Evaluate and Compare All 4 Multi-Arm Exploration Results Across All 34 Treatments.

Evaluates:
- Arm A: v15 baseline on 0-4 / 4-60cm soil
- Arm B: Clean TMT/TMA + Measured Soil N on 0-4 / 4-60cm soil
- Arm C: Parameter Expanded (61 params) + Soil Fertility/Mineralization on 0-4 / 4-60cm soil
- Arm D: Full Synergy (Clean + Measured N + PLWT=7g + Expanded 61 params) on 0-4 / 4-60cm soil
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.analyze_results import (
    deterministic_harvest_compare,
    deterministic_process_compare,
)
from src.calibration.nitrogen_response import derive_filex_water_n_mapping

ARMS = {
    "Arm_A": {
        "label": "Arm A (v15 Baseline, 0-4/4-60cm Soil)",
        "run_dir": ROOT / "workspace/runs/e02_from_scratch_arm_a_v15_baseline_20260828",
        "case": "e02_arm_a",
        "bundles": {
            "25SP": ROOT / "data/user/experiments/xxql2501_from_scratch_0_4_60cm_20260827",
            "26SP": ROOT / "data/user/experiments/xxql2601_from_scratch_0_4_60cm_20260827",
            "25FA": ROOT / "data/user/experiments/xxfa_from_scratch_0_4_60cm_20260827",
        }
    },
    "Arm_B": {
        "label": "Arm B (Clean TMT/TMA + Measured Soil N, 0-4/4-60cm Soil)",
        "run_dir": ROOT / "workspace/runs/e02_from_scratch_arm_b_clean_measuredn_20260828",
        "case": "e02_arm_b",
        "bundles": {
            "25SP": ROOT / "data/user/experiments/xxql2501_clean_measuredn_0_4_60cm_20260828",
            "26SP": ROOT / "data/user/experiments/xxql2601_clean_measuredn_0_4_60cm_20260828",
            "25FA": ROOT / "data/user/experiments/xxfa_clean_measuredn_0_4_60cm_20260828",
        }
    },
    "Arm_C": {
        "label": "Arm C (Expanded 61 Params + Soil Fertility/Mineralization)",
        "run_dir": ROOT / "workspace/runs/e02_from_scratch_arm_c_param_expanded_20260828",
        "case": "e02_arm_c",
        "bundles": {
            "25SP": ROOT / "data/user/experiments/xxql2501_from_scratch_0_4_60cm_20260827",
            "26SP": ROOT / "data/user/experiments/xxql2601_from_scratch_0_4_60cm_20260827",
            "25FA": ROOT / "data/user/experiments/xxfa_from_scratch_0_4_60cm_20260827",
        }
    },
    "Arm_D": {
        "label": "Arm D (Full Synergy: Clean Data + Measured N + PLWT=7g + Expanded 61 Params)",
        "run_dir": ROOT / "workspace/runs/e02_from_scratch_arm_d_full_synergy_20260828",
        "case": "e02_arm_d",
        "bundles": {
            "25SP": ROOT / "data/user/experiments/xxql2501_full_synergy_0_4_60cm_20260828",
            "26SP": ROOT / "data/user/experiments/xxql2601_full_synergy_0_4_60cm_20260828",
            "25FA": ROOT / "data/user/experiments/xxfa_full_synergy_0_4_60cm_20260828",
        }
    }
}

SEASONS_INFO = [
    {"season_id": "25SP", "excode": "XXQL2501", "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]},
    {"season_id": "26SP", "excode": "XXQL2601", "treatments": list(range(1, 13))},
    {"season_id": "25FA", "excode": "XXQL2502", "treatments": list(range(1, 13))},
]


def metrics(obs: np.ndarray, sim: np.ndarray) -> dict[str, float | int]:
    valid = np.isfinite(obs) & np.isfinite(sim) & (obs != -99) & (sim != -99)
    y = obs[valid]
    p = sim[valid]
    if len(y) == 0:
        return {"n": 0, "rmse": np.nan, "rrmse_pct": np.nan, "nse": np.nan, "d_index": np.nan, "r2": np.nan, "bias": np.nan}
    e = p - y
    sst = float(np.sum((y - np.mean(y)) ** 2))
    dden = float(np.sum((np.abs(p - np.mean(y)) + np.abs(y - np.mean(y))) ** 2))
    rmse = float(np.sqrt(np.mean(e ** 2)))
    rrmse_pct = float(100.0 * rmse / np.mean(np.abs(y))) if np.mean(np.abs(y)) > 0 else np.nan
    nse = float(1.0 - np.sum(e ** 2) / sst) if sst > 0 else np.nan
    d_idx = float(1.0 - np.sum(e ** 2) / dden) if dden > 0 else np.nan
    r2 = float(np.corrcoef(y, p)[0, 1] ** 2) if len(y) > 1 and np.std(y) > 0 and np.std(p) > 0 else np.nan
    bias = float(np.mean(e))
    return {
        "n": int(len(y)),
        "rmse": rmse,
        "rrmse_pct": rrmse_pct,
        "nse": nse,
        "d_index": d_idx,
        "r2": r2,
        "bias": bias
    }


def extract_best_candidate(arm_key: str, arm_cfg: dict) -> Path:
    run_dir = arm_cfg["run_dir"]
    case = arm_cfg["case"]
    
    # 1. Read phi to find min phi realization
    phi_df = pd.read_csv(run_dir / f"{case}.phi.actual.csv")
    par_df = pd.read_csv(run_dir / f"{case}.5.par.csv")
    
    # Find min phi realization in iter 5
    # Read obs to get phi or pick min phi realization from par_df
    real_col = [c for c in par_df.columns if c in ["real_name", "realization"]][0]
    
    # Export base and best
    det_dir = ROOT / f"workspace/runs/{case}_deterministic_eval_20260828"
    if det_dir.exists():
        shutil.rmtree(det_dir)
    det_dir.mkdir(parents=True, exist_ok=True)
    
    # Export best member (member with lowest phi or base)
    # Check if 'base' in par_df
    best_row = par_df.iloc[0] # default
    if "base" in par_df[real_col].astype(str).str.lower().values:
        best_row = par_df[par_df[real_col].astype(str).str.lower() == "base"].iloc[0]
    
    param_cols = [c for c in par_df.columns if c not in ["real_name", "realization", "iteration"]]
    params_data = []
    for p in param_cols:
        params_data.append({"name": p.upper(), "value": float(best_row[p])})
    
    param_csv = det_dir / f"{case}_best_params.csv"
    pd.DataFrame(params_data).to_csv(param_csv, index=False)
    
    # Write deterministic multi-season design JSON
    design_data = {
        "schema_version": 1,
        "status": "deterministic_replay",
        "design_id": f"{case}_deterministic_replay",
        "stage": "EVAL",
        "purpose": f"Deterministic replay across 34 treatments for {arm_cfg['label']}",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "full",
        "observation_policy": "configs/runs/e02_from_scratch_objective_contract_20260826.csv",
        "group_policy": "configs/runs/e02_from_scratch_group_policy_20260826.csv",
        "initial_condition_policy": "0-4cm and 4-60cm two-layer soil scheme",
        "seasons": [
            {
                "season_id": s["season_id"],
                "experiment_code": s["excode"],
                "bundle_path": str(arm_cfg["bundles"][s["season_id"]].relative_to(ROOT)).replace("\\", "/"),
                "bundle_manifest_sha256": hashlib.sha256((arm_cfg["bundles"][s["season_id"]] / "input_manifest.json").read_bytes()).hexdigest(),
                "role": "calibration",
                "treatments": s["treatments"]
            }
            for s in SEASONS_INFO
        ]
    }
    design_file = det_dir / "eval_design.json"
    design_file.write_text(json.dumps(design_data, indent=2), encoding="utf-8")
    
    # Run multiseason deterministic replay
    print(f"Running deterministic replay for {arm_key} ({arm_cfg['label']})...")
    cmd = [
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_file),
        "--param-csv", str(param_csv),
        "--prefix", f"{case}_eval",
        "--harvest-var", "CHPDT"
    ]
    res = subprocess.run(cmd, cwd=det_dir, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error in {arm_key} replay:\n", res.stderr or res.stdout)
    else:
        print(f"Replay completed for {arm_key}")
        
    # Run deterministic comparisons for each season
    for s in SEASONS_INFO:
        sid = s["season_id"]
        sdir = det_dir / "_seasons" / sid
        filex = next(sdir.glob("*.TMX"))
        batch = sdir / "analysis_batch.v48"
        batch.write_text(
            "\n".join(f"{filex.resolve()} {int(tn)} 1 0 0 0" for tn in s["treatments"]) + "\n",
            encoding="utf-8"
        )
        deterministic_process_compare(sid, str(batch), var_names=["L#SD", "LAID", "LWAD", "SWAD", "CHTD"], run_dir=str(sdir))
        deterministic_harvest_compare(sid, str(batch), run_dir=str(sdir))
        
    return det_dir


def evaluate_all():
    all_metrics_records = []
    
    for arm_key, arm_cfg in ARMS.items():
        det_dir = extract_best_candidate(arm_key, arm_cfg)
        
        # Calculate metrics for each season and variable
        for s in SEASONS_INFO:
            sid = s["season_id"]
            sdir = det_dir / "_seasons" / sid
            
            # Process compare
            proc_file = sdir / f"{sid}_deterministic_process_compare.csv"
            if proc_file.exists():
                p_df = pd.read_csv(proc_file)
                for var in ["LAID", "LWAD", "SWAD", "CHTD"]:
                    if f"OBS_{var}" in p_df.columns and f"SIM_{var}" in p_df.columns:
                        m = metrics(p_df[f"OBS_{var}"].to_numpy(float), p_df[f"SIM_{var}"].to_numpy(float))
                        all_metrics_records.append({
                            "Arm": arm_key,
                            "Arm_Label": arm_cfg["label"],
                            "Season": sid,
                            "Variable": var,
                            **m
                        })
                        
            # Harvest compare
            harv_file = sdir / f"{sid}_deterministic_harvest_compare.csv"
            if harv_file.exists():
                h_df = pd.read_csv(harv_file)
                for var in ["DRY_CUM", "FRESH_CUM", "DRY_INC", "FRESH_INC"]:
                    if f"OBS_{var}" in h_df.columns and f"SIM_{var}" in h_df.columns:
                        m = metrics(h_df[f"OBS_{var}"].to_numpy(float), h_df[f"SIM_{var}"].to_numpy(float))
                        all_metrics_records.append({
                            "Arm": arm_key,
                            "Arm_Label": arm_cfg["label"],
                            "Season": sid,
                            "Variable": var,
                            **m
                        })
                        
    out_df = pd.DataFrame(all_metrics_records)
    out_csv = ROOT / "workspace/reports/multi_arm_exploration_34treatments_metrics_20260828.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_csv, index=False)
    print(f"\nAll metrics exported to {out_csv}")
    return out_df


if __name__ == "__main__":
    df = evaluate_all()
