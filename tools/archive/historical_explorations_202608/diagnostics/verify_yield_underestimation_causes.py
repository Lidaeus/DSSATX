#!/usr/bin/env python3
"""Diagnostic script to identify and verify the exact physiological root causes
for the systematic fresh and dry fruit yield underestimation in 25SP and 26SP.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PYTHON = sys.executable
RUN_ID = "e02_formal_v45_nitrogen_synergy_two_seasons_20260830"
BASE_DIR = PROJECT_ROOT / "workspace/runs" / RUN_ID / "best_member_18_two_season_deterministic_20260830"
PARAM_CSV = BASE_DIR / "best_member_18_params.csv"
OUT_DIR = PROJECT_ROOT / "workspace/reports/yield_underestimation_diagnosis_20260830"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ENV = os.environ.copy()
ENV["PYTHONPATH"] = str(PROJECT_ROOT)

from src.reporting.analyze_results import deterministic_harvest_compare, deterministic_process_compare


def calc_stats(obs, sim):
    ok = np.isfinite(obs) & np.isfinite(sim) & (obs != -99) & (sim != -99)
    o, s = obs[ok], sim[ok]
    sst = np.sum((o - o.mean()) ** 2)
    nse = float(1.0 - np.sum((s - o) ** 2) / sst) if sst > 0 else np.nan
    rrmse = float(100.0 * np.sqrt(np.mean((s - o) ** 2)) / np.mean(np.abs(o))) if len(o) > 0 else np.nan
    r2 = float(np.corrcoef(o, s)[0, 1] ** 2) if len(o) > 1 else np.nan
    d_idx = float(1.0 - np.sum((s - o)**2) / np.sum((np.abs(s - o.mean()) + np.abs(o - o.mean()))**2)) if sst > 0 else np.nan
    return r2, nse, d_idx, rrmse


def run_experiment(exp_id: str, desc: str, mods: dict[str, float]) -> dict:
    scen_dir = OUT_DIR / exp_id
    if scen_dir.exists():
        shutil.rmtree(scen_dir)
    scen_dir.mkdir(parents=True, exist_ok=True)
    
    df_p = pd.read_csv(PARAM_CSV)
    p_dict = {str(r["name"]).lower(): float(r["value"]) for _, r in df_p.iterrows()}
    for k, v in mods.items():
        p_dict[k.lower()] = float(v)
        
    p_df = pd.DataFrame([{"name": k, "value": v} for k, v in p_dict.items()])
    p_csv = scen_dir / "params.csv"
    p_df.to_csv(p_csv, index=False)
    
    design = {
        "schema_version": 1,
        "design_id": exp_id,
        "cultivar_identity": "TM0008",
        "observation_policy": "configs/runs/e02_from_scratch_objective_contract_20260826.csv",
        "group_policy": "configs/runs/e02_group_policy_v41_nresp_10x_yield_3x.csv",
        "seasons": [
            {
                "season_id": "25SP", "experiment_code": "XXQL2501",
                "bundle_path": "data/user/experiments/xxql2501_user_ic_scheme4_20260830",
                "role": "calibration", "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]
            },
            {
                "season_id": "26SP", "experiment_code": "XXQL2601",
                "bundle_path": "data/user/experiments/xxql2601_formal_scheme4_soil_20260830",
                "role": "calibration", "treatments": list(range(1, 13))
            }
        ],
        "diagnostic_only": {"25SP": [], "26SP": []}
    }
    d_file = scen_dir / "design.json"
    d_file.write_text(json.dumps(design, indent=2), encoding="utf-8")
    
    cmd = [
        PYTHON, str(PROJECT_ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(d_file),
        "--param-csv", str(p_csv),
        "--prefix", "sim",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    res = subprocess.run(cmd, cwd=str(scen_dir), env=ENV, capture_output=True, text=True)
    if res.returncode != 0 and not (scen_dir / "_seasons/25SP/PlantGro.OUT").exists():
        print(f"Error in {exp_id}:\n", res.stderr)
        return None
        
    full_tmts = {
        "25SP": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
        "26SP": list(range(1, 13)),
    }
    
    for sid, tmts in full_tmts.items():
        s_dir = scen_dir / "_seasons" / sid
        filex = next(s_dir.glob("*.TMX"))
        batch = s_dir / "analysis_batch.v48"
        batch.write_text("\n".join(f"{filex.resolve()} {int(tn)} 1 0 0 0" for tn in tmts) + "\n", encoding="utf-8")
        deterministic_harvest_compare(sid, str(batch), run_dir=str(s_dir))
        deterministic_process_compare(sid, str(batch), var_names=["LAID", "LWAD", "SWAD"], run_dir=str(s_dir))
        
    h25 = pd.read_csv(scen_dir / "_seasons/25SP/25SP_deterministic_harvest_compare.csv")
    h26 = pd.read_csv(scen_dir / "_seasons/26SP/26SP_deterministic_harvest_compare.csv")
    
    h25_term = h25[h25["HNO"] == h25["HNO"].max()].set_index("TN")
    h26_term = h26[h26["HNO"] == h26["HNO"].max()].set_index("TN")
    
    r2_25_f, nse_25_f, d_25_f, rrmse_25_f = calc_stats(h25["OBS_FRESH_CUM"].to_numpy(float), h25["SIM_FRESH_CUM"].to_numpy(float))
    r2_25_d, nse_25_d, d_25_d, rrmse_25_d = calc_stats(h25["OBS_DRY_CUM"].to_numpy(float), h25["SIM_DRY_CUM"].to_numpy(float))
    r2_26_f, nse_26_f, d_26_f, rrmse_26_f = calc_stats(h26["OBS_FRESH_CUM"].to_numpy(float), h26["SIM_FRESH_CUM"].to_numpy(float))
    r2_26_d, nse_26_d, d_26_d, rrmse_26_d = calc_stats(h26["OBS_DRY_CUM"].to_numpy(float), h26["SIM_DRY_CUM"].to_numpy(float))
    
    # 25SP Contrasts & Yields
    w3_25_n2n0 = h25_term.loc[3, "SIM_FRESH_CUM"] - h25_term.loc[5, "SIM_FRESH_CUM"]
    w3_25_n3n0 = h25_term.loc[2, "SIM_FRESH_CUM"] - h25_term.loc[5, "SIM_FRESH_CUM"]
    w1_25_n2n0 = h25_term.loc[11, "SIM_FRESH_CUM"] - h25_term.loc[13, "SIM_FRESH_CUM"]
    
    # 26SP Contrasts & Yields
    w2_26_n2n0 = h26_term.loc[5, "SIM_FRESH_CUM"] - h26_term.loc[11, "SIM_FRESH_CUM"]
    w1_26_n2n0 = h26_term.loc[6, "SIM_FRESH_CUM"] - h26_term.loc[12, "SIM_FRESH_CUM"]
    
    # Mean PBIAS
    pbias_25_f = 100.0 * np.mean((h25_term["SIM_FRESH_CUM"] - h25_term["OBS_FRESH_CUM"]) / h25_term["OBS_FRESH_CUM"])
    pbias_26_f = 100.0 * np.mean((h26_term["SIM_FRESH_CUM"] - h26_term["OBS_FRESH_CUM"]) / h26_term["OBS_FRESH_CUM"])
    
    return {
        "exp_id": exp_id,
        "description": desc,
        "25SP_Mean_PBIAS_%": round(pbias_25_f, 2),
        "26SP_Mean_PBIAS_%": round(pbias_26_f, 2),
        "25SP_W3N2_Fresh": round(float(h25_term.loc[3, "SIM_FRESH_CUM"]), 1),
        "25SP_W3N0_Fresh": round(float(h25_term.loc[5, "SIM_FRESH_CUM"]), 1),
        "25SP_W3_N2N0_diff": round(w3_25_n2n0, 1),
        "26SP_W2N2_Fresh": round(float(h26_term.loc[5, "SIM_FRESH_CUM"]), 1),
        "26SP_W2N0_Fresh": round(float(h26_term.loc[11, "SIM_FRESH_CUM"]), 1),
        "26SP_W2_N2N0_diff": round(w2_26_n2n0, 1),
        "25SP_Fresh_NSE": round(nse_25_f, 4),
        "26SP_Fresh_NSE": round(nse_26_f, 4),
        "25SP_Fresh_R2": round(r2_25_f, 4),
        "26SP_Fresh_R2": round(r2_26_f, 4),
    }


def main():
    print("==================== HYPOTHESIS TESTING: YIELD UNDERESTIMATION CAUSES ====================")
    
    experiments = [
        # Baseline
        ("H0_Baseline_v45", "v45 Best Member #18", {}),
        
        # Test 1: Relieve FNPGN Photosynthetic Nitrogen Penalty (Unlock standard photosynthesis)
        ("H1_Relieve_FNPGN", "FNPGN1=0.60, FNPGN2=3.40 (Standard Cropgro leaf N curve)", {
            "FNPGN1": 0.600, "FNPGN2": 3.400
        }),
        
        # Test 2: Increase SFDUR (Extend fruit cohort filling duration from 35 to 48-55d)
        ("H2_Extend_SFDUR", "SFDUR=50.0 (Uncap fruit filling duration per cohort)", {
            "SFDUR": 50.000
        }),
        
        # Test 3: Increase LFMAX (Boost maximum leaf photosynthetic capacity from 1.95 to 2.35)
        ("H3_Boost_LFMAX", "LFMAX=2.35 (Boost leaf photosynthetic rate)", {
            "LFMAX": 2.350
        }),
        
        # Test 4: Increase XFRT (Maximize daily carbon partitioning to fruit from 0.875 to 0.980)
        ("H4_Max_XFRT", "XFRT=0.980 (Maximize assimilate partition to fruit)", {
            "XFRT": 0.980
        }),
        
        # Test 5: Relieve late-season senescence (SENRTE=1.5, SENDAY=0.02)
        ("H5_Relieve_Senesc", "SENRTE=1.50, SENDAY=0.020 (Preserve late green canopy)", {
            "SENRTE": 1.500, "SENDAY": 0.020
        }),
        
        # Test 6: Synergy of Source & Sink (LFMAX=2.35 + SFDUR=50 + XFRT=0.98)
        ("H6_Source_Sink_Synergy", "LFMAX=2.35, SFDUR=50, XFRT=0.98 (Full source-sink power)", {
            "LFMAX": 2.350, "SFDUR": 50.000, "XFRT": 0.980
        }),
        
        # Test 7: Source-Sink Synergy + Balanced FNPGN (FNPGN1=0.85, FNPGN2=3.80, PROLFF=0.18, PROSTF=0.10)
        ("H7_Perfect_Yield_Balance", "LFMAX=2.35, SFDUR=50, XFRT=0.98 + FNPGN1=0.85, FNPGN2=3.80, PROLFF=0.18, PROSTF=0.10", {
            "LFMAX": 2.350, "SFDUR": 50.000, "XFRT": 0.980,
            "FNPGN1": 0.850, "FNPGN2": 3.800,
            "PROLFF": 0.180, "PROSTF": 0.100, "NVSMOB": 0.400
        }),
    ]
    
    results = []
    for eid, desc, mods in experiments:
        print(f"  Testing [{eid}]: {desc}...")
        r = run_experiment(eid, desc, mods)
        if r:
            results.append(r)
            
    df = pd.DataFrame(results)
    out_csv = OUT_DIR / "yield_underestimation_diagnosis_results.csv"
    df.to_csv(out_csv, index=False)
    
    print("\n========================== YIELD UNDERESTIMATION DIAGNOSIS SCORECARD ==========================")
    cols_show = [
        "exp_id", "25SP_Mean_PBIAS_%", "26SP_Mean_PBIAS_%",
        "25SP_W3N2_Fresh", "25SP_W3N0_Fresh", "25SP_W3_N2N0_diff",
        "26SP_W2N2_Fresh", "26SP_W2N0_Fresh", "26SP_W2_N2N0_diff",
        "25SP_Fresh_NSE", "26SP_Fresh_NSE"
    ]
    print(df[cols_show].to_string(index=False))
    print(f"\n[OK] Results saved to {out_csv}")


if __name__ == "__main__":
    main()
