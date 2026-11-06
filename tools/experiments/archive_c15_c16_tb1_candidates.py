#!/usr/bin/env python3
"""Archive candidates C15 (new_iter6_real72) and C16 (new_iter6_real90).
Also update workspace/candidates/all_candidates_3season_benchmark_matrix.csv.
"""
import json
import shutil
from pathlib import Path
import pandas as pd
import numpy as np

import sys
PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SCRATCH_DIR = PROJECT_ROOT / "scratch/eval_new_tb1_150x6"
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

treatment_labels_25fa = {
    1: ("W3N3", "W3", "N3"),
    2: ("W2N3", "W2", "N3"),
    3: ("W1N3", "W1", "N3"),
    4: ("W1N2", "W1", "N2"),
    5: ("W2N2", "W2", "N2"),
    6: ("W3N2", "W3", "N2"),
    7: ("W1N1", "W1", "N1"),
    8: ("W2N1", "W2", "N1"),
    9: ("W1N0", "W1", "N0"),
    10: ("W3N1", "W3", "N1"),
    11: ("W2N0", "W2", "N0"),
    12: ("W3N0", "W3", "N0"),
}

candidates_info = [
    {
        "id": "C15",
        "tag": "new_iter6_real72",
        "real": "72",
        "dir_name": "candidate_c15_real72_grand_champion",
        "title": "All-Time Historic Grand Champion (35-Treatment Grand NRMSE 8.06%, Spring NRMSE 6.60%, 25FA Blind NRMSE 18.38%)",
        "desc": "All-time project accuracy record across all 35 treatments: Grand 35-treatment NRMSE=8.06%, Grand d-index=0.9936, Grand NSE=0.9036. Spring Pooled 23-treatment NRMSE=6.60% (25SP=5.43%, 26SP=7.64%), Autumn 25FA Blind NRMSE=18.38% with zero cold runaway. 26SP high-N yield strictly capped at 70.19 t/ha (well under 75 t/ha ceiling). 26SP W2 N-response Delta Y=+6,014 kg/ha, 25SP W1 drought N-response Delta Y=+4,798 kg/ha. TB1=9.21 C.",
        "phi": 965.742,
    },
    {
        "id": "C16",
        "tag": "new_iter6_real90",
        "real": "90",
        "dir_name": "candidate_c16_real90_strong_nresp",
        "title": "Strongest Water-Nitrogen Gradient Champion (25W1 Delta Y=+10,151 kg/ha [87.6%], Grand NRMSE 9.15%, 25FA Blind NRMSE 16.32%)",
        "desc": "Exceptional physiological nitrogen response champion: 25SP W1 drought nitrogen response Delta Y=+10,151 kg/ha (reproducing 87.6% of measured +11,590 kg/ha gradient). Grand 35-treatment NRMSE=9.15%, Grand d-index=0.9914, Grand NSE=0.9479. Spring Pooled 23-treatment NRMSE=7.85% (25SP=5.64%, 26SP=9.66%), Autumn 25FA Blind NRMSE=16.32%. 26SP peak yield perfectly controlled at 63.55 t/ha. TB1=8.95 C.",
        "phi": 1074.88,
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

def calc_nse(obs, sim):
    mask = np.isfinite(obs) & np.isfinite(sim)
    o = obs[mask].to_numpy()
    s = sim[mask].to_numpy()
    if len(o) < 2: return np.nan
    denom = np.sum((o - np.mean(o))**2)
    if denom == 0: return np.nan
    return 1.0 - (np.sum((o - s)**2) / denom)

def main():
    from tools.eval_full_gen98 import evaluate_run
    
    matrix_rows = []
    
    for cinfo in candidates_info:
        cid = cinfo["id"]
        tag = cinfo["tag"]
        dir_name = cinfo["dir_name"]
        target_dir = CAND_DIR / dir_name
        target_dir.mkdir(parents=True, exist_ok=True)
        
        cand_run_dir = SCRATCH_DIR / f"run_{tag}"
        param_src = SCRATCH_DIR / f"{tag}_params.csv"
        shutil.copy(param_src, target_dir / "params.csv")
        
        # Build all_harvest_events_dynamics and final yield
        batches = {
            "25SP": PROJECT_ROOT / "data/templates/batch/DSSBatch.v48",
            "26SP": SCRATCH_DIR / "batches/DSSBatch_26SP_all.v48",
            "25FA": SCRATCH_DIR / "batches/DSSBatch_25FA_all.v48",
        }
        
        all_h_list = []
        final_yield_records = []
        metrics_detail_records = []
        
        for season in ["25SP", "26SP", "25FA"]:
            s_dir = cand_run_dir / season
            bpath = batches[season]
            res = evaluate_run(bpath, s_dir)
            df_h, _ = res
            df_h["SEASON"] = season
            all_h_list.append(df_h)
            
            last_rows = df_h.sort_values("DATE").groupby(["EXCODE", "TN"]).last().reset_index()
            for _, r in last_rows.iterrows():
                tn = int(r["TN"])
                obs = float(r["OBS_FRESH_CUM"])
                sim = float(r["SIM_FRESH_CUM"])
                diff = sim - obs
                pct = (diff / obs) * 100.0 if obs != 0 else 0
                
                final_yield_records.append({
                    "season": season,
                    "tn": tn,
                    "obs_cum_yield_kg_ha": obs,
                    "sim_cum_yield_kg_ha": sim,
                    "bias_kg_ha": diff,
                    "bias_pct": pct
                })
                
                if season == "25SP":
                    lbl, w, n = treatment_labels_25.get(tn, (f"TN{tn}", "UNK", "UNK"))
                elif season == "26SP":
                    lbl, w, n = treatment_labels_26.get(tn, (f"TN{tn}", "UNK", "UNK"))
                else:
                    lbl, w, n = treatment_labels_25fa.get(tn, (f"TN{tn}", "UNK", "UNK"))
                    
                metrics_detail_records.append({
                    "season": season,
                    "tn": tn,
                    "label": lbl,
                    "water": w,
                    "nitro": n,
                    "obs": obs,
                    "sim": sim,
                    "diff": diff,
                    "rel_err": pct
                })
                
        df_all_h = pd.concat(all_h_list, ignore_index=True)
        df_all_h.to_csv(target_dir / "all_harvest_events_dynamics.csv", index=False)
        
        df_final_y = pd.DataFrame(final_yield_records)
        df_final_y.to_csv(target_dir / "all_35_treatments_final_yield.csv", index=False)
        
        df_detail = pd.DataFrame(metrics_detail_records)
        df_detail.to_csv(target_dir / "metrics_three_seasons.csv", index=False)
        
        # Metrics
        y25 = df_final_y[df_final_y["season"] == "25SP"]
        y26 = df_final_y[df_final_y["season"] == "26SP"]
        yfa = df_final_y[df_final_y["season"] == "25FA"]
        yspring = df_final_y[df_final_y["season"].isin(["25SP", "26SP"])]
        
        rmse25, nrmse25, d25, r225 = calc_metrics(y25["obs_cum_yield_kg_ha"], y25["sim_cum_yield_kg_ha"])
        rmse26, nrmse26, d26, r226 = calc_metrics(y26["obs_cum_yield_kg_ha"], y26["sim_cum_yield_kg_ha"])
        rmsesp, nrmsesp, dsp, r2sp = calc_metrics(yspring["obs_cum_yield_kg_ha"], yspring["sim_cum_yield_kg_ha"])
        rmsefa, nrmsefa, dfa, r2fa = calc_metrics(yfa["obs_cum_yield_kg_ha"], yfa["sim_cum_yield_kg_ha"])
        rmsetot, nrmsetot, dtot, r2tot = calc_metrics(df_final_y["obs_cum_yield_kg_ha"], df_final_y["sim_cum_yield_kg_ha"])
        
        nse25 = calc_nse(df_all_h[df_all_h["SEASON"] == "25SP"]["OBS_FRESH_CUM"], df_all_h[df_all_h["SEASON"] == "25SP"]["SIM_FRESH_CUM"])
        nse26 = calc_nse(df_all_h[df_all_h["SEASON"] == "26SP"]["OBS_FRESH_CUM"], df_all_h[df_all_h["SEASON"] == "26SP"]["SIM_FRESH_CUM"])
        nsefa = calc_nse(df_all_h[df_all_h["SEASON"] == "25FA"]["OBS_FRESH_CUM"], df_all_h[df_all_h["SEASON"] == "25FA"]["SIM_FRESH_CUM"])
        nsesp = calc_nse(df_all_h[df_all_h["SEASON"].isin(["25SP", "26SP"])]["OBS_FRESH_CUM"], df_all_h[df_all_h["SEASON"].isin(["25SP", "26SP"])]["SIM_FRESH_CUM"])
        nsetot = calc_nse(df_all_h["OBS_FRESH_CUM"], df_all_h["SIM_FRESH_CUM"])
        
        y26_dict = dict(zip(y26["tn"], y26["sim_cum_yield_kg_ha"]))
        y25_dict = dict(zip(y25["tn"], y25["sim_cum_yield_kg_ha"]))
        
        max_26y = y26["sim_cum_yield_kg_ha"].max() / 1000.0
        delta_26w2 = y26_dict.get(2, 0) - y26_dict.get(11, 0)
        delta_26w1 = y26_dict.get(3, 0) - y26_dict.get(12, 0)
        delta_25w1 = y25_dict.get(10, 0) - y25_dict.get(13, 0)
        w1_ratio = (delta_25w1 / 11590.0) * 100.0
        
        # Manifest
        manifest = {
            "candidate_id": cid,
            "folder_name": dir_name,
            "source_run": "full_gen_13trt_tb1_80_95_150x6_20260920",
            "realization": f"iter6_real{cinfo['real']}",
            "real_name": f"real_{cinfo['real']}",
            "creation_date": "2026-09-20",
            "status": "archived_candidate",
            "title": cinfo["title"],
            "description": cinfo["desc"],
            "phi": cinfo["phi"],
            "key_metrics": {
                "25SP_NRMSE_pct": round(nrmse25, 2),
                "25SP_RMSE_kg_ha": round(rmse25, 1),
                "25SP_d_index": round(d25, 4),
                "25SP_R2": round(r225, 4),
                "25SP_dyn_NSE": round(nse25, 4),
                "26SP_NRMSE_pct": round(nrmse26, 2),
                "26SP_RMSE_kg_ha": round(rmse26, 1),
                "26SP_d_index": round(d26, 4),
                "26SP_R2": round(r226, 4),
                "26SP_dyn_NSE": round(nse26, 4),
                "Spring_Pooled_23trt_NRMSE_pct": round(nrmsesp, 2),
                "Spring_Pooled_23trt_RMSE_kg_ha": round(rmsesp, 1),
                "Spring_Pooled_23trt_d_index": round(dsp, 4),
                "Spring_Pooled_23trt_R2": round(r2sp, 4),
                "Spring_dyn_NSE": round(nsesp, 4),
                "25FA_Blind_12trt_NRMSE_pct": round(nrmsefa, 2),
                "25FA_Blind_12trt_RMSE_kg_ha": round(rmsefa, 1),
                "25FA_Blind_12trt_d_index": round(dfa, 4),
                "25FA_Blind_12trt_R2": round(r2fa, 4),
                "25FA_dyn_NSE": round(nsefa, 4),
                "Grand_Pooled_35trt_NRMSE_pct": round(nrmsetot, 2),
                "Grand_Pooled_35trt_RMSE_kg_ha": round(rmsetot, 1),
                "Grand_Pooled_35trt_d_index": round(dtot, 4),
                "Grand_Pooled_35trt_R2": round(r2tot, 4),
                "Grand_dyn_NSE": round(nsetot, 4),
                "Delta_Y_W2_26SP_kg_ha": round(delta_26w2, 1),
                "Delta_Y_W1_26SP_kg_ha": round(delta_26w1, 1),
                "Delta_Y_W1_25SP_kg_ha": round(delta_25w1, 1),
                "W1_N_Response_Ratio_pct": round(w1_ratio, 2),
                "Max_26SP_Yield_t_ha": round(float(max_26y), 2),
                "Ceiling_Passed": bool(max_26y <= 75.0)
            }
        }
        
        with open(target_dir / "candidate_manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            
        print(f"Successfully archived {cid} ({dir_name})")
        print(f"  Grand NRMSE: {nrmsetot:.2f}%, Spring NRMSE: {nrmsesp:.2f}%, 25FA Blind: {nrmsefa:.2f}%")
        print(f"  Delta Y 25W1: +{delta_25w1:.1f} kg/ha ({w1_ratio:.1f}%), Max 26SP: {max_26y:.2f} t/ha")
        
        matrix_rows.append({
            "candidate": f"{cid}_real{cinfo['real']}",
            "Spring_NRMSE_pct": nrmsesp,
            "Spring_d": dsp,
            "Spring_R2": r2sp,
            "Spring_NSE": nsesp,
            "25SP_NRMSE_pct": nrmse25,
            "25SP_d": d25,
            "25SP_NSE": nse25,
            "26SP_NRMSE_pct": nrmse26,
            "26SP_d": d26,
            "26SP_NSE": nse26,
            "25FA_NRMSE_pct": nrmsefa,
            "25FA_d": dfa,
            "25FA_NSE": nsefa,
            "Grand_NRMSE_pct": nrmsetot,
            "Grand_d": dtot,
            "Grand_NSE": nsetot,
            "Max_26SP_Y_t_ha": max_26y,
            "Ceiling_Passed": max_26y <= 75.0,
            "Delta_Y_26W2_kg": delta_26w2,
            "Delta_Y_26W1_kg": delta_26w1,
            "Delta_Y_25W1_kg": delta_25w1,
            "W1_N_ratio_pct": w1_ratio,
        })
        
    # Update benchmark matrix
    bm_path = CAND_DIR / "all_candidates_3season_benchmark_matrix.csv"
    if bm_path.is_file():
        df_bm = pd.read_csv(bm_path)
        # Remove old rows for C15, C16 if exist
        df_bm = df_bm[~df_bm["candidate"].isin([r["candidate"] for r in matrix_rows])]
        df_new = pd.concat([pd.DataFrame(matrix_rows), df_bm], ignore_index=True)
        df_new.to_csv(bm_path, index=False)
        print(f"\nUpdated {bm_path} with {len(matrix_rows)} new candidates.")

if __name__ == "__main__":
    main()
