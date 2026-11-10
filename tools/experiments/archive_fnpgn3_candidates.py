import json
import shutil
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("D:/Tomato_Cal")
CAND_DIR = PROJECT_ROOT / "workspace/candidates"
SCREEN_DIR = PROJECT_ROOT / "scratch/screen_fnpgn3_real_sh2o"
SOURCE_RUN = "full_gen_13trt_fnpgn3_real_sh2o_150x6_20260922"

candidates = [
    {
        "id": "C20",
        "real": 126,
        "folder": "candidate_c20_real126_fnpgn3_depression",
        "title": "High-N Yield Depression & 3-Season Champion (FNPGN3=5.08, Grand NRMSE=12.16%, 25FA NRMSE=7.49%)",
        "desc": "First candidate in project history to successfully reproduce high-N yield depression (W1N3 - W1N2 = -0.30 t/ha in 25SP, -0.04 t/ha in 26SP) via photosynthetic leaf-N threshold response (FNPGN3=5.08, FNPGN4=6.31, LNREF=4.86, satisfying FNPGN2 <= LNREF <= FNPGN3). Calibrated under restored true unscaled 25SP initial soil water. Outstanding 3-season balance: 25FA blind NRMSE=7.49%, 26SP NRMSE=10.41%, 25SP NRMSE=11.62%, Grand 35-treatment NRMSE=12.16%, d-index=0.9841, NSE=0.9414. Low-N canopy fully retained (25SP W1N0 LAI=3.45, LN%=2.88%). Max 26SP yield 73.38 t/ha passes yield ceiling."
    },
    {
        "id": "C21",
        "real": 21,
        "folder": "candidate_c21_real21_fnpgn3_depression",
        "title": "Spring High-Precision & High-N Depression Candidate (25SP NRMSE=7.90%, FNPGN3=5.28, Grand NRMSE=12.72%)",
        "desc": "Ultra-high spring precision candidate: 25SP NRMSE=7.90% (all W1 errors < 2.0%), Grand NRMSE=12.72%, d-index=0.9841. Successfully reproduces high-N yield depression (25SP W1N3 - W1N2 = -0.11 t/ha, 26SP W1N3 - W1N2 = -0.01 t/ha) with FNPGN3=5.28, FNPGN4=6.70. Healthy canopy retention (25SP W1N0 LAI=3.44, LN%=3.03%). Strong 25SP W1 N response: Delta Y = +12.31 t/ha (106.2% of observed)."
    },
    {
        "id": "C22",
        "real": 85,
        "folder": "candidate_c22_real85_fnpgn3_depression",
        "title": "Grand Minimum NRMSE & Robust Depression Candidate (Grand NRMSE=11.89%, d-index=0.9860, FNPGN3=5.48)",
        "desc": "Achieves lowest grand 35-treatment NRMSE (11.89%, RMSE=5.99 t/ha) and highest d-index (0.9860) in the fnpgn3 series. Strong high-N yield depression in 26SP (W1N3 - W1N2 = -0.96 t/ha, W2N3 - W2N2 = -0.07 t/ha) and 25SP (W1N3 - W1N2 = -0.08 t/ha). 25SP NRMSE=8.80%, 26SP NRMSE=12.11%. Canopy retention confirmed (25SP W1N0 LAI=3.63, LN%=2.81%)."
    }
]

def calc_stats(obs, sim):
    obs = np.array(obs, dtype=float)
    sim = np.array(sim, dtype=float)
    err = sim - obs
    rmse = np.sqrt(np.mean(err**2))
    nrmse = 100.0 * rmse / np.mean(obs)
    sst = np.sum((obs - np.mean(obs))**2)
    den = np.sum((np.abs(sim - np.mean(obs)) + np.abs(obs - np.mean(obs)))**2)
    d = 1.0 - (np.sum(err**2) / den) if den > 0 else np.nan
    r = np.corrcoef(obs, sim)[0, 1] if len(obs) > 1 else np.nan
    r2 = r**2 if not np.isnan(r) else np.nan
    nse = 1.0 - (np.sum(err**2) / sst) if sst > 0 else np.nan
    return rmse, nrmse, d, r2, nse

matrix_rows = []

for c in candidates:
    target_dir = CAND_DIR / c["folder"]
    target_dir.mkdir(parents=True, exist_ok=True)
    
    src_case_dir = SCREEN_DIR / f"iter6_real{c['real']}"
    src_yield_file = src_case_dir / f"iter6_real{c['real']}_35trt_yield.csv"
    src_param_file = src_case_dir / "params.csv"
    
    shutil.copy2(src_param_file, target_dir / "params.csv")
    
    # Process clean yield file
    df_y = pd.read_csv(src_yield_file)
    df_clean = pd.DataFrame({
        "season": df_y["season"],
        "tn": df_y["tn"],
        "obs_cum_yield_kg_ha": df_y["obs_cum_yield_kg_ha"],
        "sim_cum_yield_kg_ha": (df_y["sim_t_ha"] * 1000.0).round(1),
        "bias_kg_ha": ((df_y["sim_t_ha"] * 1000.0) - df_y["obs_cum_yield_kg_ha"]).round(1),
        "bias_pct": (((df_y["sim_t_ha"] * 1000.0) - df_y["obs_cum_yield_kg_ha"]) / df_y["obs_cum_yield_kg_ha"] * 100.0).round(2),
        "sim_t_ha": df_y["sim_t_ha"].round(4),
        "obs_t_ha": (df_y["obs_cum_yield_kg_ha"] / 1000.0).round(4)
    })
    df_clean.to_csv(target_dir / "all_35_treatments_final_yield.csv", index=False)
    
    # Compute metrics
    sp25 = df_clean[df_clean["season"] == "25SP"]
    sp26 = df_clean[df_clean["season"] == "26SP"]
    fa25 = df_clean[df_clean["season"] == "25FA"]
    spring = df_clean[df_clean["season"].isin(["25SP", "26SP"])]
    
    rmse25, nrmse25, d25, r225, nse25 = calc_stats(sp25["obs_t_ha"], sp25["sim_t_ha"])
    rmse26, nrmse26, d26, r226, nse26 = calc_stats(sp26["obs_t_ha"], sp26["sim_t_ha"])
    rmsesp, nrmsesp, dsp, r2sp, nsesp = calc_stats(spring["obs_t_ha"], spring["sim_t_ha"])
    rmsefa, nrmsefa, dfa, r2fa, nsefa = calc_stats(fa25["obs_t_ha"], fa25["sim_t_ha"])
    rmsetot, nrmsetot, dtot, r2tot, nsetot = calc_stats(df_clean["obs_t_ha"], df_clean["sim_t_ha"])
    
    y25_dict = dict(zip(sp25["tn"], sp25["sim_cum_yield_kg_ha"]))
    y26_dict = dict(zip(sp26["tn"], sp26["sim_cum_yield_kg_ha"]))
    
    max_26y = float(sp26["sim_t_ha"].max())
    delta_26w2 = y26_dict.get(2, 0) - y26_dict.get(11, 0)
    delta_26w1 = y26_dict.get(3, 0) - y26_dict.get(12, 0)
    delta_25w1 = y25_dict.get(10, 0) - y25_dict.get(13, 0)
    w1_ratio = (delta_25w1 / 11590.0) * 100.0
    
    n3_n2_25_w1 = y25_dict.get(10, 0) - y25_dict.get(11, 0)
    n3_n2_26_w1 = y26_dict.get(3, 0) - y26_dict.get(6, 0)
    
    # Read key params
    p_df = pd.read_csv(target_dir / "params.csv").set_index("name")
    
    manifest = {
        "candidate_id": c["folder"],
        "run_id": SOURCE_RUN,
        "iteration": 6,
        "realization": c["real"],
        "tb1": round(float(p_df.loc["tb1", "value"]), 3),
        "senrte": round(float(p_df.loc["senrte", "value"]), 3),
        "nmobmx": round(float(p_df.loc["nmobmx", "value"]), 3),
        "fnpgn1": round(float(p_df.loc["fnpgn1", "value"]), 3),
        "fnpgn2": round(float(p_df.loc["fnpgn2", "value"]), 3),
        "fnpgn3": round(float(p_df.loc["fnpgn3", "value"]), 3),
        "fnpgn4": round(float(p_df.loc["fnpgn4", "value"]), 3),
        "lnref": round(float(p_df.loc["lnref", "value"]), 3),
        "icns_25sp": 0.75,
        "soil_slu1": 1.70,
        "grand_35_nrmse": f"{nrmsetot:.2f}%",
        "spring_23_nrmse": f"{nrmsesp:.2f}%",
        "season_25sp_nrmse": f"{nrmse25:.2f}%",
        "season_26sp_nrmse": f"{nrmse26:.2f}%",
        "season_25fa_nrmse": f"{nrmsefa:.2f}%",
        "grand_r2": round(r2tot, 3),
        "grand_d_index": round(dtot, 4),
        "grand_nse": round(nsetot, 4),
        "high_n_depression_25sp_w1_kg_ha": round(n3_n2_25_w1, 1),
        "high_n_depression_26sp_w1_kg_ha": round(n3_n2_26_w1, 1),
        "w1_n_gap_25sp_kg_ha": round(delta_25w1, 1),
        "w1_n_gap_26sp_kg_ha": round(delta_26w1, 1),
        "max_26sp_yield_t_ha": round(max_26y, 2),
        "title": c["title"],
        "description": c["desc"]
    }
    
    with open(target_dir / "candidate_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        
    import yaml
    with open(target_dir / "candidate_manifest.yaml", "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, allow_unicode=True, sort_keys=False)
        
    print(f"Archived {c['id']} in {target_dir}")
    
    matrix_rows.append({
        "candidate": f"{c['id']}_real{c['real']}",
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
        "W1_N_ratio_pct": w1_ratio
    })

# Update benchmark matrix
bm_path = CAND_DIR / "all_candidates_3season_benchmark_matrix.csv"
if bm_path.is_file():
    df_bm = pd.read_csv(bm_path)
    df_bm = df_bm[~df_bm["candidate"].isin([r["candidate"] for r in matrix_rows])]
    df_new = pd.concat([df_bm, pd.DataFrame(matrix_rows)], ignore_index=True)
    df_new.to_csv(bm_path, index=False)
    print(f"Updated benchmark matrix with {len(matrix_rows)} new rows.")
