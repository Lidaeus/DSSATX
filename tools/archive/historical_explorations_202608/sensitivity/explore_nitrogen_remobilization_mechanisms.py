#!/usr/bin/env python3
"""Evaluate nitrogen remobilization and tissue minimum protein parameters:
- PROLFF in [0.160, 0.220]
- PROSTF in [0.080, 0.120]
- NVSMOB in [0.350, 0.500]
- NMOBMX in [0.080, 0.150]
on calibrated Member #33 parameters across all 22 treatments in 25SP & 26SP.
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
BASE_RUN_DIR = PROJECT_ROOT / "workspace/runs/e02_small_v44_n2n0_both_seasons_20260830/best_member_33_two_season_deterministic_20260830"
BASE_PARAM_CSV = BASE_RUN_DIR / "best_member_33_params.csv"
OUT_DIR = PROJECT_ROOT / "workspace/reports/n_remobilization_tuning_20260830"
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


def run_scenario(scenario_id: str, param_mods: dict[str, float]) -> dict:
    scen_dir = OUT_DIR / scenario_id
    if scen_dir.exists():
        shutil.rmtree(scen_dir)
    scen_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Base parameters
    df_p = pd.read_csv(BASE_PARAM_CSV)
    p_dict = {str(r["name"]).lower(): float(r["value"]) for _, r in df_p.iterrows()}
    for k, v in param_mods.items():
        p_dict[k.lower()] = float(v)
        
    p_df = pd.DataFrame([{"name": k, "value": v} for k, v in p_dict.items()])
    p_csv = scen_dir / "params.csv"
    p_df.to_csv(p_csv, index=False)
    
    # 2. Design JSON
    design = {
        "schema_version": 1,
        "design_id": scenario_id,
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
    
    # 3. Run multiseason
    cmd = [
        PYTHON, str(PROJECT_ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(d_file),
        "--param-csv", str(p_csv),
        "--prefix", "sim",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    res = subprocess.run(cmd, cwd=str(scen_dir), env=ENV, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error in {scenario_id}:\n", res.stderr)
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
    
    # 25SP Contrasts
    w3_25_n2n0 = h25_term.loc[3, "SIM_FRESH_CUM"] - h25_term.loc[5, "SIM_FRESH_CUM"]
    w3_25_n3n0 = h25_term.loc[2, "SIM_FRESH_CUM"] - h25_term.loc[5, "SIM_FRESH_CUM"]
    w1_25_n2n0 = h25_term.loc[11, "SIM_FRESH_CUM"] - h25_term.loc[13, "SIM_FRESH_CUM"]
    w1_25_n3n0 = h25_term.loc[10, "SIM_FRESH_CUM"] - h25_term.loc[13, "SIM_FRESH_CUM"]
    
    # 26SP Contrasts
    w2_26_n2n0 = h26_term.loc[5, "SIM_FRESH_CUM"] - h26_term.loc[11, "SIM_FRESH_CUM"]
    w2_26_n3n0 = h26_term.loc[2, "SIM_FRESH_CUM"] - h26_term.loc[11, "SIM_FRESH_CUM"]
    w1_26_n2n0 = h26_term.loc[6, "SIM_FRESH_CUM"] - h26_term.loc[12, "SIM_FRESH_CUM"]
    w1_26_n3n0 = h26_term.loc[3, "SIM_FRESH_CUM"] - h26_term.loc[12, "SIM_FRESH_CUM"]
    
    return {
        "scenario_id": scenario_id,
        "PROLFF": param_mods.get("PROLFF", p_dict.get("prolff", 0.110)),
        "PROSTF": param_mods.get("PROSTF", p_dict.get("prostf", 0.065)),
        "NVSMOB": param_mods.get("NVSMOB", p_dict.get("nvsmob", 0.714)),
        "NMOBMX": param_mods.get("NMOBMX", p_dict.get("nmobmx", 0.237)),
        "25SP_W3_N2N0_diff": round(w3_25_n2n0, 1),
        "25SP_W3_N3N0_diff": round(w3_25_n3n0, 1),
        "25SP_W1_N2N0_diff": round(w1_25_n2n0, 1),
        "25SP_W1_N3N0_diff": round(w1_25_n3n0, 1),
        "26SP_W2_N2N0_diff": round(w2_26_n2n0, 1),
        "26SP_W1_N2N0_diff": round(w1_26_n2n0, 1),
        "25SP_Fresh_NSE": round(nse_25_f, 4),
        "25SP_Fresh_R2": round(r2_25_f, 4),
        "25SP_Dry_NSE": round(nse_25_d, 4),
        "26SP_Fresh_NSE": round(nse_26_f, 4),
        "26SP_Fresh_R2": round(r2_26_f, 4),
        "26SP_Dry_NSE": round(nse_26_d, 4),
        "25SP_TN5_W3N0_Yield": round(float(h25_term.loc[5, "SIM_FRESH_CUM"]), 1),
        "25SP_TN3_W3N2_Yield": round(float(h25_term.loc[3, "SIM_FRESH_CUM"]), 1),
        "25SP_TN2_W3N3_Yield": round(float(h25_term.loc[2, "SIM_FRESH_CUM"]), 1),
    }


def main():
    print("==================== EVALUATING NITROGEN REMOBILIZATION TUNING SCENARIOS ====================")
    scenarios = [
        ("Base_Member33", {}),
        ("S1_PROLFF_0.160", {"PROLFF": 0.160}),
        ("S2_PROLFF_0.180", {"PROLFF": 0.180}),
        ("S3_PROLFF_0.200", {"PROLFF": 0.200}),
        ("S4_PROLFF_0.220", {"PROLFF": 0.220}),
        ("S5_PROSTF_0.090", {"PROSTF": 0.090}),
        ("S6_PROSTF_0.120", {"PROSTF": 0.120}),
        ("S7_NVSMOB_0.450", {"NVSMOB": 0.450}),
        ("S8_NVSMOB_0.350", {"NVSMOB": 0.350}),
        ("S9_NMOBMX_0.120", {"NMOBMX": 0.120}),
        ("S10_NMOBMX_0.080", {"NMOBMX": 0.080}),
        ("Combo_Mod_A", {"PROLFF": 0.160, "PROSTF": 0.080, "NVSMOB": 0.500, "NMOBMX": 0.150}),
        ("Combo_Mod_B", {"PROLFF": 0.180, "PROSTF": 0.090, "NVSMOB": 0.420, "NMOBMX": 0.120}),
        ("Combo_Mod_C", {"PROLFF": 0.200, "PROSTF": 0.100, "NVSMOB": 0.380, "NMOBMX": 0.100}),
        ("Combo_Mod_D", {"PROLFF": 0.220, "PROSTF": 0.120, "NVSMOB": 0.350, "NMOBMX": 0.080}),
        ("Combo_Mod_E_Strict", {"PROLFF": 0.240, "PROSTF": 0.140, "NVSMOB": 0.300, "NMOBMX": 0.060}),
    ]
    
    results = []
    for sid, mods in scenarios:
        print(f"  Running {sid}...")
        r = run_scenario(sid, mods)
        if r:
            results.append(r)
            
    df_res = pd.DataFrame(results)
    out_csv = OUT_DIR / "nitrogen_remobilization_comparison.csv"
    df_res.to_csv(out_csv, index=False)
    
    print("\n========================== NITROGEN REMOBILIZATION EXPLORATION SCORECARD ==========================")
    cols_show = [
        "scenario_id", "PROLFF", "PROSTF", "NVSMOB", "NMOBMX",
        "25SP_W3_N2N0_diff", "25SP_W1_N2N0_diff", "26SP_W2_N2N0_diff", "26SP_W1_N2N0_diff",
        "25SP_Fresh_NSE", "26SP_Fresh_NSE", "25SP_TN5_W3N0_Yield", "25SP_TN3_W3N2_Yield"
    ]
    print(df_res[cols_show].to_string(index=False))
    print(f"\n[OK] Results saved to {out_csv}")


if __name__ == "__main__":
    main()
