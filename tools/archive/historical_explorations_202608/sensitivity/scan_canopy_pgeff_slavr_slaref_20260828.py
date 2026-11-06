"""Deterministic Grid Scan of Canopy Parameters (PGEFF, SLAVR, SLAREF, LFMAX)
to verify physiological SLA (200-280 cm2/g) and positive LAI response after SPE injection bug fix.
"""
from __future__ import annotations

import csv
import itertools
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.analyze_results import deterministic_process_compare

SCAN_DIR = ROOT / "workspace/reports/canopy_grid_scan_20260828"
SCAN_DIR.mkdir(parents=True, exist_ok=True)

# Grid values
PGEFF_VALS = [0.03, 0.054, 0.08, 0.13]
SLAVR_VALS = [180.0, 240.0, 300.0]
SLAREF_VALS = [300.0, 450.0, 600.0]

def run_canopy_grid():
    results = []
    
    # Base member 38 params as template
    base_params_file = ROOT / "workspace/runs/e02_v15_boundary_fix_official_200x6_20260819/deterministic_candidates/best_phi_member38_two_season_20260819/best_member_38_params.csv"
    base_df = pd.read_csv(base_params_file)
    base_dict = {str(r['name']).strip().upper(): float(r['value']) for _, r in base_df.iterrows()}
    
    total_combos = len(PGEFF_VALS) * len(SLAVR_VALS) * len(SLAREF_VALS)
    print(f"Running deterministic canopy grid scan ({total_combos} combinations)...")
    
    combo_id = 0
    for pgeff, slavr, slaref in itertools.product(PGEFF_VALS, SLAVR_VALS, SLAREF_VALS):
        combo_id += 1
        work_dir = SCAN_DIR / f"combo_{combo_id:02d}"
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        
        # Prepare param CSV
        p_dict = dict(base_dict)
        p_dict["PGEFF"] = pgeff
        p_dict["SLAVR"] = slavr
        p_dict["SLAREF"] = slaref
        p_dict["LFMAX"] = 1.90
        p_dict["KC_SLOPE"] = 0.015
        
        param_csv = work_dir / "params.csv"
        pd.DataFrame([{"name": k, "value": v} for k, v in p_dict.items()]).to_csv(param_csv, index=False)
        
        # Prepare mini design for 25SP & 26SP
        design_data = {
            "schema_version": 1,
            "status": "scan",
            "design_id": f"scan_combo_{combo_id}",
            "stage": "SCAN",
            "purpose": "Canopy parameter sensitivity scan",
            "cultivar_identity": "TM0008",
            "shared_parameter_scope": "full",
            "observation_policy": "configs/runs/e02_from_scratch_objective_contract_20260826.csv",
            "group_policy": "configs/runs/e02_from_scratch_group_policy_20260826.csv",
            "initial_condition_policy": "0-4cm and 4-60cm two-layer soil scheme",
            "seasons": [
                {
                    "season_id": "25SP",
                    "experiment_code": "XXQL2501",
                    "bundle_path": "data/user/experiments/xxql2501_from_scratch_0_4_60cm_20260827",
                    "bundle_manifest_sha256": "5cc7d9cd8c04ede8d362d70796fdb97719d3cc795592df0e5bc6254f35386f1c",
                    "role": "calibration",
                    "treatments": [2, 5, 10, 13]
                },
                {
                    "season_id": "26SP",
                    "experiment_code": "XXQL2601",
                    "bundle_path": "data/user/experiments/xxql2601_from_scratch_0_4_60cm_20260827",
                    "bundle_manifest_sha256": "0797c4ef972dec19a9617dc3fdfa821322149a2b70e30275831fb58005b0e860",
                    "role": "calibration",
                    "treatments": [1, 3, 9, 12]
                }
            ]
        }
        import json
        design_file = work_dir / "design.json"
        design_file.write_text(json.dumps(design_data, indent=2), encoding="utf-8")
        
        # Run multiseason
        cmd = [
            sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
            "--design", str(design_file),
            "--param-csv", str(param_csv),
            "--prefix", f"combo_{combo_id}",
            "--harvest-var", "CHPDT"
        ]
        res = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Combo {combo_id} failed:", res.stderr[:200])
            continue
            
        # Analyze SLA and LAI in 25SP and 26SP
        for sid, tns in [("25SP", [2, 5, 10, 13]), ("26SP", [1, 3, 9, 12])]:
            sdir = work_dir / "_seasons" / sid
            filex = next(sdir.glob("*.TMX"))
            batch = sdir / "analysis_batch.v48"
            batch.write_text("\n".join(f"{filex.resolve()} {tn} 1 0 0 0" for tn in tns) + "\n", encoding="utf-8")
            deterministic_process_compare(sid, str(batch), var_names=["LAID", "LWAD", "SWAD"], run_dir=str(sdir))
            
            proc_file = sdir / f"{sid}_deterministic_process_compare.csv"
            if proc_file.exists():
                df_p = pd.read_csv(proc_file)
                # Compute metrics
                obs_l = df_p["OBS_LAID"].to_numpy(float)
                sim_l = df_p["SIM_LAID"].to_numpy(float)
                obs_w = df_p["OBS_LWAD"].to_numpy(float)
                sim_w = df_p["SIM_LWAD"].to_numpy(float)
                
                valid = (obs_l > 0) & (sim_l > 0) & (obs_w > 0) & (sim_w > 0)
                # LAI [m2 m-2] / LWAD [kg ha-1] -> SLA [cm2 g-1]: ×100000.
                sim_sla_med = np.median((sim_l[valid] * 100000.0) / sim_w[valid]) if np.any(valid) else np.nan
                obs_sla_med = np.median((obs_l[valid] * 100000.0) / obs_w[valid]) if np.any(valid) else np.nan

                obs_l_valid = obs_l[valid]
                sim_l_valid = sim_l[valid]
                e = sim_l_valid - obs_l_valid
                sst = np.sum((obs_l_valid - np.mean(obs_l_valid))**2)
                nse = 1.0 - np.sum(e**2)/sst if sst > 0 else np.nan
                bias = np.mean(e)
                rmse = np.sqrt(np.mean(e**2))
                
                results.append({
                    "combo_id": combo_id,
                    "PGEFF": pgeff,
                    "SLAVR": slavr,
                    "SLAREF": slaref,
                    "season": sid,
                    "sim_sla_median": sim_sla_med,
                    "obs_sla_median": obs_sla_med,
                    "lai_nse": nse,
                    "lai_bias": bias,
                    "lai_rmse": rmse
                })
                
    res_df = pd.DataFrame(results)
    out_csv = SCAN_DIR / "canopy_grid_scan_summary.csv"
    res_df.to_csv(out_csv, index=False)
    print(f"Grid scan complete! Results saved to: {out_csv}")
    return res_df

if __name__ == "__main__":
    df = run_canopy_grid()
    print(df.to_string())
