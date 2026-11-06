#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, 'D:/Tomato_Cal')
from tools.calibration.eval_full_gen_13trt_n1_fix_200x6 import (
    init_batches, get_obs_lookup, run_dssat_single, extract_season_yields,
    calc_stats, SEASONS, EVAL_DIR, RUN_DIR, PREFIX
)
import pandas as pd
import numpy as np

init_batches()
obs_lookup = get_obs_lookup()
df_par = pd.read_csv(RUN_DIR / f"{PREFIX}.6.par.csv", index_col=0)
df_phi = pd.read_csv(RUN_DIR / f"{PREFIX}.phi.actual.csv")

it_row = df_phi[df_phi["iteration"] == 6].iloc[0]
meta_cols = {"iteration", "total_runs", "mean", "standard_deviation", "min", "max"}
real_cols = [c for c in df_phi.columns if c not in meta_cols]
phi_series = it_row[real_cols].dropna().astype(float).sort_values()

# Select top 16 candidates
candidate_reals = [str(r) for r in phi_series.index[:16] if str(r) in df_par.index]
print("Evaluating top candidates:", candidate_reals)

records = []
scratch_base = EVAL_DIR / "runs"
scratch_base.mkdir(parents=True, exist_ok=True)

for cand in candidate_reals:
    cname = f"iter6_real_{cand}"
    cdir = scratch_base / cname
    cdir.mkdir(parents=True, exist_ok=True)
    
    p_row = df_par.loc[cand]
    p_df = pd.DataFrame({"name": p_row.index, "value": p_row.values})
    p_csv = cdir / "params.csv"
    p_df.to_csv(p_csv, header=False, index=False)
    
    s_dfs = []
    for sname, (bpath, exp_dir) in SEASONS.items():
        s_out = cdir / sname
        run_dssat_single(p_csv, bpath, exp_dir, s_out)
        expt = "XXQL2501" if sname == "25SP" else ("XXQL2601" if sname == "26SP" else "XXQL2502")
        s_dfs.append(extract_season_yields(s_out, expt, obs_lookup))
        
    full_df = pd.concat(s_dfs, ignore_index=True)
    full_df.to_csv(cdir / "treatment_yield_35.csv", index=False)
    
    sp25 = full_df[full_df["season"] == "25SP"].set_index("treatment")
    sp26 = full_df[full_df["season"] == "26SP"].set_index("treatment")
    fa25 = full_df[full_df["season"] == "25FA"]
    twosp = full_df[full_df["season"].isin(["25SP", "26SP"])]
    
    st25 = calc_stats(sp25["obs_t_ha"], sp25["sim_t_ha"])
    st26 = calc_stats(sp26["obs_t_ha"], sp26["sim_t_ha"])
    st2sp = calc_stats(twosp["obs_t_ha"], twosp["sim_t_ha"])
    stfa = calc_stats(fa25["obs_t_ha"], fa25["sim_t_ha"])
    stgrand = calc_stats(full_df["obs_t_ha"], full_df["sim_t_ha"])
    
    # Inversion checks
    w3_n1_n3_25 = sp25.loc[4, "sim_t_ha"] - sp25.loc[2, "sim_t_ha"]
    w1_n1_n3_25 = sp25.loc[12, "sim_t_ha"] - sp25.loc[10, "sim_t_ha"]
    w3n1_err_25 = sp25.loc[4, "error_t_ha"]
    
    w3_n1_n3_26 = sp26.loc[7, "sim_t_ha"] - sp26.loc[1, "sim_t_ha"]
    w1_n1_n3_26 = sp26.loc[10, "sim_t_ha"] - sp26.loc[3, "sim_t_ha"]
    w3n1_err_26 = sp26.loc[7, "error_t_ha"]
    
    rec = {
        "Candidate": cname,
        "Real": cand,
        "Phi": phi_series[cand],
        "TwoSp_NRMSE%": st2sp["NRMSE%"],
        "TwoSp_NSE": st2sp["NSE"],
        "TwoSp_R2": st2sp["R2"],
        "25SP_NRMSE%": st25["NRMSE%"],
        "25SP_NSE": st25["NSE"],
        "26SP_NRMSE%": st26["NRMSE%"],
        "26SP_NSE": st26["NSE"],
        "25FA_NRMSE%": stfa["NRMSE%"],
        "Grand_NRMSE%": stgrand["NRMSE%"],
        "Grand_NSE": stgrand["NSE"],
        "25SP_W3(N1-N3)": w3_n1_n3_25,
        "26SP_W3(N1-N3)": w3_n1_n3_26,
        "25SP_W3N1_Err": w3n1_err_25,
        "26SP_W3N1_Err": w3n1_err_26,
        "prolff": p_row.get("prolff"),
        "rtno3": p_row.get("rtno3"),
        "fnpgn2": p_row.get("fnpgn2"),
        "kcan": p_row.get("kcan"),
        "dswbar": p_row.get("dswbar"),
        "lfmax": p_row.get("lfmax"),
    }
    records.append(rec)
    print(f"Done {cname}: TwoSp NRMSE={st2sp['NRMSE%']:.2f}%, NSE={st2sp['NSE']:.4f}, 25SP W3(N1-N3)={w3_n1_n3_25:+.2f}, 26SP W3(N1-N3)={w3_n1_n3_26:+.2f}")

df_res = pd.DataFrame(records)
out_csv = EVAL_DIR / "extended_16_candidates_summary.csv"
df_res.to_csv(out_csv, index=False)
print("\n" + "="*110)
print("EXTENDED 16 CANDIDATES RANKED BY TWOSPRING NRMSE:")
print("="*110)
show_cols = [
    "Candidate", "Phi", "TwoSp_NRMSE%", "TwoSp_NSE", "TwoSp_R2",
    "25SP_NRMSE%", "26SP_NRMSE%", "Grand_NRMSE%",
    "25SP_W3(N1-N3)", "26SP_W3(N1-N3)", "25SP_W3N1_Err", "26SP_W3N1_Err"
]
print(df_res.sort_values(by="TwoSp_NRMSE%")[show_cols].to_string(index=False))
