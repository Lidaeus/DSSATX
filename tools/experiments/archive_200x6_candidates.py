#!/usr/bin/env python3
"""Archive candidates C09 (real_164), C10 (real_125), C11 (real_140).
"""
import json
import shutil
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("D:/Tomato_Cal")
RUN_DIR = PROJECT_ROOT / "workspace/runs/full_gen_sasc094_sldr024_200x6_20260919"
EVAL_DIR = RUN_DIR / "three_seasons_eval"
CAND_DIR = PROJECT_ROOT / "workspace/candidates"

treatment_labels_25 = {
    2: ("W3N3", "W3", "N3"),
    3: ("W3N2", "W3", "N2"),
    4: ("W3N1", "W3", "N1"),
    5: ("W3N0", "W3", "N0"),
    6: ("W2N3", "W2", "N3"),
    9: ("W2N0", "W2", "N0"),
    10: ("W1N3", "W1", "N3"),
    11: ("W1N2", "W1", "N2"),
    12: ("W1N1", "W1", "N1"),
    13: ("W1N0", "W1", "N0"),
    14: ("CKN2", "CK", "N2"),
}

treatment_labels_26 = {
    1: ("W3N3", "W3", "N3"),
    2: ("W2N3", "W2", "N3"),
    3: ("W1N3", "W1", "N3"),
    4: ("W3N2", "W3", "N2"),
    5: ("W2N2", "W2", "N2"),
    6: ("W1N2", "W1", "N2"),
    7: ("W3N1", "W3", "N1"),
    8: ("W2N1", "W2", "N1"),
    9: ("W3N0", "W3", "N0"),
    10: ("W1N1", "W1", "N1"),
    11: ("W2N0", "W2", "N0"),
    12: ("W1N0", "W1", "N0"),
}

candidates_info = [
    {
        "id": "C09",
        "real": "164",
        "dir_name": "candidate_c09_real164",
        "title": "Unconstrained 200x6 Champion: Double-Season Balanced Precision (Pooled NRMSE 9.66%)",
        "desc": "Achieved unconstrained global optimization under SASC=0.94, SLDR=0.24, SLLL(0-4cm)=[0.18, 0.20]. Grand Pooled spring NRMSE=9.66% (25SP NRMSE=8.12%, 26SP NRMSE=11.06%, Dynamics NSE=0.899). W1 N-response gradient +5.09 t/ha (43.94%), W3N0 LAI=1.61, 26SP high-N yield strictly capped at 73.5 t/ha."
    },
    {
        "id": "C10",
        "real": "125",
        "dir_name": "candidate_c10_real125",
        "title": "Unconstrained 200x6 Global Minimum Phi (696.19) Maximum N-Response",
        "desc": "Global optimization minimum Phi=696.19 across 200x6 IES. 25SP W1 nitrogen response gradient +7.28 t/ha (62.85% of measured gradient), 25SP NRMSE=12.72%, 26SP NRMSE=15.29%, Pooled NRMSE=14.03%."
    },
    {
        "id": "C11",
        "real": "140",
        "dir_name": "candidate_c11_real140",
        "title": "Unconstrained 200x6 Ultra-High Precision on 25SP (NRMSE 5.60%, d=0.780)",
        "desc": "Historic 25SP precision record: NRMSE=5.60%, d=0.7803, Dynamics NSE=0.8973. W1 N-response gradient +6.01 t/ha (51.86%), W3N0 LAI=1.62."
    }
]

def calc_metrics(obs, sim):
    mask = np.isfinite(obs) & np.isfinite(sim)
    o = obs[mask].to_numpy()
    s = sim[mask].to_numpy()
    if len(o) == 0: return np.nan, np.nan, np.nan, np.nan
    rmse = np.sqrt(np.mean((s - o)**2))
    nrmse = (rmse / np.mean(o)) * 100.0 if np.mean(o) != 0 else np.nan
    denom = np.sum((np.abs(s - np.mean(o)) + np.abs(o - np.mean(o)))**2)
    d = 1.0 - (np.sum((o - s)**2) / denom) if denom != 0 else np.nan
    cov = np.cov(o, s)[0, 1] if len(o) > 1 else 0
    std_o = np.std(o, ddof=1) if len(o) > 1 else 0
    std_s = np.std(s, ddof=1) if len(s) > 1 else 0
    r2 = (cov / (std_o * std_s))**2 if (std_o * std_s) != 0 else np.nan
    return rmse, nrmse, d, r2

def main():
    for cinfo in candidates_info:
        cid = cinfo["id"]
        real = cinfo["real"]
        target_dir = CAND_DIR / cinfo["dir_name"]
        target_dir.mkdir(parents=True, exist_ok=True)
        
        src_real_dir = EVAL_DIR / f"cand_real_{real}"
        shutil.copy(src_real_dir / "params.csv", target_dir / "params.csv")
        shutil.copy(src_real_dir / "all_35_treatments_final_yield.csv", target_dir / "all_35_treatments_final_yield.csv")
        shutil.copy(src_real_dir / "all_harvest_events_dynamics.csv", target_dir / "all_harvest_events_dynamics.csv")
        
        df_y = pd.read_csv(target_dir / "all_35_treatments_final_yield.csv")
        records = []
        for _, r in df_y.iterrows():
            season = r["SEASON"]
            tn = int(r["TN"])
            obs = float(r["OBS_FRESH_CUM"])
            sim = float(r["SIM_FRESH_CUM"])
            diff = sim - obs
            rel_err = (diff / obs) * 100.0 if obs != 0 else 0
            
            if season == "25SP":
                label, water, nitro = treatment_labels_25.get(tn, (f"TN{tn}", "UNK", "UNK"))
            else:
                label, water, nitro = treatment_labels_26.get(tn, (f"TN{tn}", "UNK", "UNK"))
                
            records.append({
                "season": season,
                "tn": tn,
                "label": label,
                "water": water,
                "nitro": nitro,
                "obs": obs,
                "sim": sim,
                "diff": diff,
                "rel_err": rel_err
            })
        df_metrics_detail = pd.DataFrame(records)
        df_metrics_detail.to_csv(target_dir / "metrics_three_seasons.csv", index=False)
        
        y25 = df_y[df_y["SEASON"] == "25SP"]
        rmse25, nrmse25, d25, r225 = calc_metrics(y25["OBS_FRESH_CUM"], y25["SIM_FRESH_CUM"])
        
        y26 = df_y[df_y["SEASON"] == "26SP"]
        rmse26, nrmse26, d26, r226 = calc_metrics(y26["OBS_FRESH_CUM"], y26["SIM_FRESH_CUM"])
        
        rmsetot, nrmsetot, dtot, r2tot = calc_metrics(df_y["OBS_FRESH_CUM"], df_y["SIM_FRESH_CUM"])
        
        df_dyn = pd.read_csv(target_dir / "all_harvest_events_dynamics.csv")
        mask_tot = np.isfinite(df_dyn["OBS_FRESH_CUM"]) & np.isfinite(df_dyn["SIM_FRESH_CUM"])
        nse_dyn = 1.0 - (np.sum((df_dyn.loc[mask_tot, "OBS_FRESH_CUM"] - df_dyn.loc[mask_tot, "SIM_FRESH_CUM"])**2) / np.sum((df_dyn.loc[mask_tot, "OBS_FRESH_CUM"] - np.mean(df_dyn.loc[mask_tot, "OBS_FRESH_CUM"]))**2))
        
        y25_dict = dict(zip(y25["TN"], y25["SIM_FRESH_CUM"]))
        delta_w1 = y25_dict.get(10, 0) - y25_dict.get(13, 0)
        w1_ratio = (delta_w1 / 11590.0) * 100.0
        
        manifest = {
            "candidate_id": cid,
            "source_run": "full_gen_sasc094_sldr024_200x6_20260919",
            "realization": f"iter6_real{real}",
            "creation_date": "2026-09-19",
            "status": "archived_candidate",
            "title": cinfo["title"],
            "description": cinfo["desc"],
            "key_metrics": {
                "25SP_NRMSE_pct": round(nrmse25, 2),
                "25SP_RMSE_kg_ha": round(rmse25, 1),
                "25SP_R2": round(r225, 4),
                "25SP_d_index": round(d25, 4),
                "26SP_NRMSE_pct": round(nrmse26, 2),
                "26SP_RMSE_kg_ha": round(rmse26, 1),
                "26SP_R2": round(r226, 4),
                "26SP_d_index": round(d26, 4),
                "Spring_Pooled_23trt_NRMSE_pct": round(nrmsetot, 2),
                "Spring_Pooled_23trt_d_index": round(dtot, 4),
                "Spring_Pooled_23trt_R2": round(r2tot, 4),
                "cumulative_harvest_NSE_all": round(nse_dyn, 4),
                "25SP_W1_gradient_ratio_pct": round(w1_ratio, 2),
                "Delta_Y_W1_25SP_kg_ha": round(delta_w1, 1),
                "26SP_W2N3_yield_kg_ha": round(dict(zip(y26["TN"], y26["SIM_FRESH_CUM"])).get(2, 0), 1),
                "26SP_W1N3_yield_kg_ha": round(dict(zip(y26["TN"], y26["SIM_FRESH_CUM"])).get(3, 0), 1)
            }
        }
        with open(target_dir / "candidate_manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            
        print(f"Successfully archived {cid} ({cinfo['dir_name']})!")

if __name__ == "__main__":
    main()
