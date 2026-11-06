#!/usr/bin/env python3
"""Quantitative verification of the systematic yield underestimation fix:
Testing balanced high-capacity source-sink parameters:
  - LFMAX = 2.35 (Boost leaf photosynthetic capacity)
  - SFDUR = 48.0 (Extend fruit cohort expansion duration)
  - XFRT = 0.95 (Increase daily assimilate partition to fruit)
  - FNPGN1 = 0.85, FNPGN2 = 3.85 (Relieve photosynthesis over-suppression in N2/N3)
  - PROLFF = 0.185, PROSTF = 0.100, NVSMOB = 0.400 (Maintain nitrogen remobilization floor)
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
BASE_DIR = PROJECT_ROOT / "workspace/runs/e02_formal_v45_nitrogen_synergy_two_seasons_20260830/best_member_18_two_season_deterministic_20260830"
PARAM_CSV = BASE_DIR / "best_member_18_params.csv"
OUT_DIR = PROJECT_ROOT / "workspace/reports/yield_verification_experiment_20260830"
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


def main():
    scen_dir = OUT_DIR / "balanced_high_yield_test"
    if scen_dir.exists():
        shutil.rmtree(scen_dir)
    scen_dir.mkdir(parents=True, exist_ok=True)
    
    df_p = pd.read_csv(PARAM_CSV)
    p_dict = {str(r["name"]).lower(): float(r["value"]) for _, r in df_p.iterrows()}
    
    # Apply calibrated physiological improvements
    p_dict["lfmax"] = 2.350
    p_dict["sfdur"] = 48.000
    p_dict["xfrt"] = 0.950
    p_dict["fnpgn1"] = 0.850
    p_dict["fnpgn2"] = 3.850
    p_dict["prolff"] = 0.185
    p_dict["prostf"] = 0.100
    p_dict["nvsmob"] = 0.400
    p_dict["kcan"] = 0.480
    
    p_df = pd.DataFrame([{"name": k, "value": v} for k, v in p_dict.items()])
    p_csv = scen_dir / "params.csv"
    p_df.to_csv(p_csv, index=False)
    
    design = {
        "schema_version": 1,
        "design_id": "balanced_high_yield_test",
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
    subprocess.run(cmd, cwd=str(scen_dir), env=ENV, capture_output=True, text=True)
    
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
    r2_26_f, nse_26_f, d_26_f, rrmse_26_f = calc_stats(h26["OBS_FRESH_CUM"].to_numpy(float), h26["SIM_FRESH_CUM"].to_numpy(float))
    
    print("\n========================== 25SP TREATMENT YIELD COMPARISON ==========================")
    for tn in sorted(h25_term.index):
        obs_f = h25_term.loc[tn, "OBS_FRESH_CUM"]
        sim_f = h25_term.loc[tn, "SIM_FRESH_CUM"]
        pbias = 100.0 * (sim_f - obs_f) / obs_f
        print(f"  TN {tn:2d}: OBS = {obs_f:7.1f} kg/ha | SIM = {sim_f:7.1f} kg/ha | PBIAS = {pbias:+6.2f}%")
        
    print("\n========================== 26SP TREATMENT YIELD COMPARISON ==========================")
    for tn in sorted(h26_term.index):
        obs_f = h26_term.loc[tn, "OBS_FRESH_CUM"]
        sim_f = h26_term.loc[tn, "SIM_FRESH_CUM"]
        pbias = 100.0 * (sim_f - obs_f) / obs_f
        print(f"  TN {tn:2d}: OBS = {obs_f:7.1f} kg/ha | SIM = {sim_f:7.1f} kg/ha | PBIAS = {pbias:+6.2f}%")
        
    print(f"\n25SP Fresh Yield NSE = {nse_25_f:.4f}, R2 = {r2_25_f:.4f}")
    print(f"26SP Fresh Yield NSE = {nse_26_f:.4f}, R2 = {r2_26_f:.4f}")


if __name__ == "__main__":
    main()
