#!/usr/bin/env python3
"""Multi-arm small-scale forward exploration script targeting nitrogen response inversion repair.
Explores 5 mechanism arms:
  Arm 1: Nitrogen remobilization & organ minimum protein (PROLFF, PROSTF, NVSMOB, NMOBMX)
  Arm 2: Leaf nitrogen photosynthesis sensitivity (FNPGN1, FNPGN2)
  Arm 3: Nitrogen stress accelerated senescence & leaf abscission (SENRTE, SENDAY)
  Arm 4: Nitrogen stress vegetative/reproductive growth regulation (NREXP, NSTFAC)
  Arm 5: Full synergy integrated schemes (Cross-mechanism multi-parameter sets)
Runs deterministically on all 22 treatments in 25SP & 26SP using official DSSAT kernel.
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
OUT_DIR = PROJECT_ROOT / "workspace/reports/multiarm_nitrogen_exploration_20260830"
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


def run_single_arm(arm_id: str, desc: str, mods: dict[str, float]) -> dict:
    scen_dir = OUT_DIR / arm_id
    if scen_dir.exists():
        shutil.rmtree(scen_dir)
    scen_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Base parameters + mods
    df_p = pd.read_csv(BASE_PARAM_CSV)
    p_dict = {str(r["name"]).lower(): float(r["value"]) for _, r in df_p.iterrows()}
    for k, v in mods.items():
        p_dict[k.lower()] = float(v)
        
    p_df = pd.DataFrame([{"name": k, "value": v} for k, v in p_dict.items()])
    p_csv = scen_dir / "params.csv"
    p_df.to_csv(p_csv, index=False)
    
    # 2. Design JSON
    design = {
        "schema_version": 1,
        "design_id": arm_id,
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
        print(f"Error in {arm_id}:\n", res.stderr)
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
        "arm_id": arm_id,
        "description": desc,
        "PROLFF": mods.get("PROLFF", p_dict.get("prolff", 0.129)),
        "PROSTF": mods.get("PROSTF", p_dict.get("prostf", 0.046)),
        "NVSMOB": mods.get("NVSMOB", p_dict.get("nvsmob", 0.784)),
        "NMOBMX": mods.get("NMOBMX", p_dict.get("nmobmx", 0.237)),
        "FNPGN1": mods.get("FNPGN1", p_dict.get("fnpgn1", 0.479)),
        "FNPGN2": mods.get("FNPGN2", p_dict.get("fnpgn2", 4.017)),
        "SENRTE": mods.get("SENRTE", p_dict.get("senrte", 2.221)),
        "SENDAY": mods.get("SENDAY", p_dict.get("senday", 0.025)),
        "NREXP": mods.get("NREXP", p_dict.get("nrexp", 0.445)),
        "NSTFAC": mods.get("NSTFAC", p_dict.get("nstfac", 0.166)),
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
    print("==================== EVALUATING 5 MECHANISM ARMS ACROSS 25 SCENARIOS ====================")
    
    scenarios = [
        # Baseline
        ("Arm0_Baseline", "Calibrated Member #33", {}),
        
        # Arm 1: Nitrogen Remobilization (PROLFF, PROSTF, NVSMOB, NMOBMX)
        ("Arm1_Remob_1", "PROLFF=0.20, PROSTF=0.10, NVSMOB=0.38, NMOBMX=0.10", {
            "PROLFF": 0.200, "PROSTF": 0.100, "NVSMOB": 0.380, "NMOBMX": 0.100
        }),
        ("Arm1_Remob_2", "PROLFF=0.22, PROSTF=0.12, NVSMOB=0.32, NMOBMX=0.08", {
            "PROLFF": 0.220, "PROSTF": 0.120, "NVSMOB": 0.320, "NMOBMX": 0.080
        }),
        
        # Arm 2: Photosynthesis-Nitrogen Response (FNPGN1, FNPGN2)
        ("Arm2_PhotoN_1", "FNPGN1=1.20, FNPGN2=4.20", {
            "FNPGN1": 1.200, "FNPGN2": 4.200
        }),
        ("Arm2_PhotoN_2", "FNPGN1=1.50, FNPGN2=4.50", {
            "FNPGN1": 1.500, "FNPGN2": 4.500
        }),
        ("Arm2_PhotoN_3", "FNPGN1=1.80, FNPGN2=4.50", {
            "FNPGN1": 1.800, "FNPGN2": 4.500
        }),
        ("Arm2_PhotoN_Remob", "PROLFF=0.20, PROSTF=0.10, NVSMOB=0.38, NMOBMX=0.10 + FNPGN1=1.50, FNPGN2=4.20", {
            "PROLFF": 0.200, "PROSTF": 0.100, "NVSMOB": 0.380, "NMOBMX": 0.100,
            "FNPGN1": 1.500, "FNPGN2": 4.200
        }),
        
        # Arm 3: Nitrogen-Stress Senescence & Abscission (SENRTE, SENDAY)
        ("Arm3_Senesc_1", "SENRTE=3.50, SENDAY=0.040", {
            "SENRTE": 3.500, "SENDAY": 0.040
        }),
        ("Arm3_Senesc_2", "SENRTE=4.50, SENDAY=0.060", {
            "SENRTE": 4.500, "SENDAY": 0.060
        }),
        ("Arm3_Senesc_3", "SENRTE=5.50, SENDAY=0.080", {
            "SENRTE": 5.500, "SENDAY": 0.080
        }),
        ("Arm3_Senesc_Remob", "PROLFF=0.20, PROSTF=0.10, NVSMOB=0.38, NMOBMX=0.10 + SENRTE=4.50, SENDAY=0.060", {
            "PROLFF": 0.200, "PROSTF": 0.100, "NVSMOB": 0.380, "NMOBMX": 0.100,
            "SENRTE": 4.500, "SENDAY": 0.060
        }),
        
        # Arm 4: N Stress Growth Regulation & Partitioning (NREXP, NSTFAC)
        ("Arm4_Partition_1", "NREXP=0.700, NSTFAC=0.350", {
            "NREXP": 0.700, "NSTFAC": 0.350
        }),
        ("Arm4_Partition_2", "NREXP=0.900, NSTFAC=0.500", {
            "NREXP": 0.900, "NSTFAC": 0.500
        }),
        ("Arm4_Partition_Remob", "PROLFF=0.20, PROSTF=0.10, NVSMOB=0.38, NMOBMX=0.10 + NREXP=0.850, NSTFAC=0.450", {
            "PROLFF": 0.200, "PROSTF": 0.100, "NVSMOB": 0.380, "NMOBMX": 0.100,
            "NREXP": 0.850, "NSTFAC": 0.450
        }),
        
        # Arm 5: Full Synergy Integrated Schemes (Combinations of all 4 mechanisms)
        ("Arm5_Synergy_A_Balanced", "PROLFF=0.18, PROSTF=0.09, NVSMOB=0.42, NMOBMX=0.12, FNPGN1=1.20, FNPGN2=4.20, SENRTE=3.5, SENDAY=0.04, NREXP=0.75, NSTFAC=0.35", {
            "PROLFF": 0.180, "PROSTF": 0.090, "NVSMOB": 0.420, "NMOBMX": 0.120,
            "FNPGN1": 1.200, "FNPGN2": 4.200, "SENRTE": 3.500, "SENDAY": 0.040,
            "NREXP": 0.750, "NSTFAC": 0.350
        }),
        ("Arm5_Synergy_B_Targeted", "PROLFF=0.20, PROSTF=0.10, NVSMOB=0.38, NMOBMX=0.10, FNPGN1=1.50, FNPGN2=4.30, SENRTE=4.5, SENDAY=0.05, NREXP=0.85, NSTFAC=0.45", {
            "PROLFF": 0.200, "PROSTF": 0.100, "NVSMOB": 0.380, "NMOBMX": 0.100,
            "FNPGN1": 1.500, "FNPGN2": 4.300, "SENRTE": 4.500, "SENDAY": 0.050,
            "NREXP": 0.850, "NSTFAC": 0.450
        }),
        ("Arm5_Synergy_C_Strong", "PROLFF=0.22, PROSTF=0.12, NVSMOB=0.32, NMOBMX=0.08, FNPGN1=1.60, FNPGN2=4.50, SENRTE=5.0, SENDAY=0.06, NREXP=0.95, NSTFAC=0.55", {
            "PROLFF": 0.220, "PROSTF": 0.120, "NVSMOB": 0.320, "NMOBMX": 0.080,
            "FNPGN1": 1.600, "FNPGN2": 4.500, "SENRTE": 5.000, "SENDAY": 0.060,
            "NREXP": 0.950, "NSTFAC": 0.550
        }),
        ("Arm5_Synergy_D_MaxN0_Penalty", "PROLFF=0.24, PROSTF=0.14, NVSMOB=0.28, NMOBMX=0.06, FNPGN1=1.80, FNPGN2=4.60, SENRTE=5.5, SENDAY=0.08, NREXP=1.00, NSTFAC=0.60", {
            "PROLFF": 0.240, "PROSTF": 0.140, "NVSMOB": 0.280, "NMOBMX": 0.060,
            "FNPGN1": 1.800, "FNPGN2": 4.600, "SENRTE": 5.500, "SENDAY": 0.080,
            "NREXP": 1.000, "NSTFAC": 0.600
        }),
    ]
    
    results = []
    for sid, desc, mods in scenarios:
        print(f"  Running [{sid}]: {desc}...")
        r = run_single_arm(sid, desc, mods)
        if r:
            results.append(r)
            
    df_res = pd.DataFrame(results)
    out_csv = OUT_DIR / "multiarm_nitrogen_exploration_results.csv"
    df_res.to_csv(out_csv, index=False)
    
    print("\n========================== MULTI-ARM EXPLORATION SUMMARY SCORECARD ==========================")
    cols_show = [
        "arm_id", "25SP_W3_N2N0_diff", "25SP_W3_N3N0_diff", "25SP_W1_N2N0_diff",
        "26SP_W2_N2N0_diff", "26SP_W1_N2N0_diff", "25SP_Fresh_NSE", "26SP_Fresh_NSE",
        "25SP_TN5_W3N0_Yield", "25SP_TN3_W3N2_Yield"
    ]
    print(df_res[cols_show].to_string(index=False))
    print(f"\n[OK] Complete report saved to {out_csv}")


if __name__ == "__main__":
    main()
