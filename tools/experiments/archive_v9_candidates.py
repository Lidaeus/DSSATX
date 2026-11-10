#!/usr/bin/env python3
"""Archive V9 candidates C06 (real_44), C07 (real_51), and C08 (real_68).
"""
import json
import shutil
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("D:/Tomato_Cal")
RUN_DIR = PROJECT_ROOT / "workspace/runs/full_gen_slll4cm_s0922_0945_150x5_20260919"
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

treatment_labels_26_25fa = {
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
        "id": "C06",
        "real": "44",
        "dir_name": "candidate_c06_real44",
        "title": "Global Minimum Phi (1627.0) Ultra-Precise Multi-Season Model",
        "desc": "Global optimization minimum Phi=1627.0 across 150x5 IES. Superb accuracy on both spring seasons: 25SP NRMSE=7.35% (d=0.658, NSE=0.923), 26SP NRMSE=9.34% (d=0.577, NSE=0.871). W1 nitrogen response +4.24 t/ha (36.58% of measured gradient), W3N0 end LAI=1.77, 26SP high-N yield strictly capped at 70.5 t/ha."
    },
    {
        "id": "C07",
        "real": "51",
        "dir_name": "candidate_c07_real51",
        "title": "Qualified Gate-Pass Champion (High W1 N-Response 29.6%, Yield Cap 63.7t)",
        "desc": "Qualified candidate passing all rigorous gates simultaneously. Phi=2315.6, 25SP W1 N response ratio=29.64% (+3.44 t/ha), 25SP W3N0 end LAI=1.26, 26SP high-N yield strictly capped at 63.7 t/ha (W2N3) and 61.3 t/ha (W1N3), 26SP NRMSE=8.94%."
    },
    {
        "id": "C08",
        "real": "68",
        "dir_name": "candidate_c08_real68",
        "title": "Balanced Robust Multi-Season Champion (26SP NRMSE 7.11%, High 25FA Stability)",
        "desc": "High-robustness multi-season candidate passing all gates. 26SP NRMSE=7.11% (d=0.637, NSE=0.946), 25FA independent NRMSE=55.69% (lowest across all candidates), Grand Pooled 35-treatment NRMSE=20.77% (d=0.960, R2=0.909), W1 response=22.29%, 26SP W2N3=67.7 t/ha."
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
        
        # Build detailed metrics_three_seasons.csv
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
                label, water, nitro = treatment_labels_26_25fa.get(tn, (f"TN{tn}", "UNK", "UNK"))
                
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
        
        # Compute season and pooled metrics
        y25 = df_y[df_y["SEASON"] == "25SP"]
        rmse25, nrmse25, d25, r225 = calc_metrics(y25["OBS_FRESH_CUM"], y25["SIM_FRESH_CUM"])
        
        y26 = df_y[df_y["SEASON"] == "26SP"]
        rmse26, nrmse26, d26, r226 = calc_metrics(y26["OBS_FRESH_CUM"], y26["SIM_FRESH_CUM"])
        
        yfa = df_y[df_y["SEASON"] == "25FA"]
        rmsefa, nrmsefa, dfa, r2fa = calc_metrics(yfa["OBS_FRESH_CUM"], yfa["SIM_FRESH_CUM"])
        
        rmsetot, nrmsetot, dtot, r2tot = calc_metrics(df_y["OBS_FRESH_CUM"], df_y["SIM_FRESH_CUM"])
        
        # Dynamics NSE
        df_dyn = pd.read_csv(target_dir / "all_harvest_events_dynamics.csv")
        mask_tot = np.isfinite(df_dyn["OBS_FRESH_CUM"]) & np.isfinite(df_dyn["SIM_FRESH_CUM"])
        nse_dyn = 1.0 - (np.sum((df_dyn.loc[mask_tot, "OBS_FRESH_CUM"] - df_dyn.loc[mask_tot, "SIM_FRESH_CUM"])**2) / np.sum((df_dyn.loc[mask_tot, "OBS_FRESH_CUM"] - np.mean(df_dyn.loc[mask_tot, "OBS_FRESH_CUM"]))**2))
        
        # W1 gradient
        y25_dict = dict(zip(y25["TN"], y25["SIM_FRESH_CUM"]))
        delta_w1 = y25_dict.get(10, 0) - y25_dict.get(13, 0)
        w1_ratio = (delta_w1 / 11590.0) * 100.0
        
        manifest = {
            "candidate_id": cid,
            "source_run": "full_gen_slll4cm_s0922_0945_150x5_20260919",
            "realization": f"iter5_real{real}",
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
                "25FA_NRMSE_pct": round(nrmsefa, 2),
                "Pooled_35trt_NRMSE_pct": round(nrmsetot, 2),
                "Pooled_35trt_d_index": round(dtot, 4),
                "Pooled_35trt_R2": round(r2tot, 4),
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
