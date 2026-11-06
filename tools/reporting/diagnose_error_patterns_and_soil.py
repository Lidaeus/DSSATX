#!/usr/bin/env python3
"""Comprehensive diagnostic script to investigate:
1. Which treatments consistently have large errors across recent calibration rounds (C23, C26, Real81, Real80, Real24, C27).
2. Soil initial conditions (SH2O, SNO3, SNH4, SAOC) of these outlier treatments compared to normal treatments.
3. Which treatments primarily degrade/drag down 26SP R^2 (Leave-One-Out and Combinatorial ablation analysis).
"""

import sys
import re
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("D:/Tomato_Cal")

# 1. Load calibration data
grand = pd.read_csv(PROJECT_ROOT / "workspace/experiments/compare_real81_and_optionb/grand_comparison_with_n1_fix.csv")
c23 = pd.read_csv(PROJECT_ROOT / "workspace/candidates/candidate_c23_real194_final_spring_precision/all_35_treatments_final_yield.csv")
c26 = pd.read_csv(PROJECT_ROOT / "workspace/candidates/candidate_c26_real19_final_uncertainty/all_35_treatments_final_yield.csv")
c27 = pd.read_csv(PROJECT_ROOT / "workspace/candidates/candidate_c27_real24_root140_sasc092/all_35_treatments_final_yield.csv")

df = grand[["SEASON", "EXCODE", "TN", "Trt_Label", "OBS_t_ha", "SIM_OrigReal81_NewSoil_t_ha", "SIM_New_Real80_t_ha", "SIM_FixN1_Real24_t_ha"]].copy()
df.rename(columns={
    "SIM_OrigReal81_NewSoil_t_ha": "Real81",
    "SIM_New_Real80_t_ha": "Real80",
    "SIM_FixN1_Real24_t_ha": "Real24"
}, inplace=True)

c23_map = {(r["season"], int(r.get("tn", r.get("treatment")))): float(r["sim_t_ha"]) for _, r in c23.iterrows()}
c26_map = {(r["season"], int(r.get("tn", r.get("treatment")))): float(r["sim_t_ha"]) for _, r in c26.iterrows()}
c27_map = {(r["season"], int(r.get("tn", r.get("treatment")))): float(r["sim_t_ha"]) for _, r in c27.iterrows()}

df["C23"] = [c23_map.get((r["SEASON"], r["TN"]), np.nan) for _, r in df.iterrows()]
df["C26"] = [c26_map.get((r["SEASON"], r["TN"]), np.nan) for _, r in df.iterrows()]
df["C27"] = [c27_map.get((r["SEASON"], r["TN"]), np.nan) for _, r in df.iterrows()]

models = ["C23", "C26", "Real81", "Real80", "Real24", "C27"]
for m in models:
    df[f"{m}_err"] = df[m] - df["OBS_t_ha"]
    df[f"{m}_abs_err"] = np.abs(df[f"{m}_err"])
    df[f"{m}_rel_pct"] = (df[f"{m}_err"] / df["OBS_t_ha"]) * 100.0

df["mean_abs_err"] = df[[f"{m}_abs_err" for m in models]].mean(axis=1)
df["mean_signed_err"] = df[[f"{m}_err" for m in models]].mean(axis=1)
df["mean_rel_pct"] = df[[f"{m}_rel_pct" for m in models]].mean(axis=1)

print("="*90)
print("PART 1: TREATMENTS CONSISTENTLY SHOWING LARGE ERRORS ACROSS RECENT CALIBRATION ROUNDS")
print("="*90)

for season in ["25SP", "26SP", "25FA"]:
    print(f"\n--- {season} Treatments Ranked by Mean Absolute Error ---")
    s_df = df[df["SEASON"] == season].sort_values("mean_abs_err", ascending=False)
    for _, r in s_df.iterrows():
        err_strs = [f"{m}={r[f'{m}_err']:+5.1f}" for m in models]
        print(f"{r['Trt_Label']:6s} (T{int(r['TN']):2d}): Obs={r['OBS_t_ha']:5.2f} | Mean|Err|={r['mean_abs_err']:5.2f} t/ha (Rel={r['mean_rel_pct']:+5.1f}%) | " + " ".join(err_strs))

# 2. Parse soil initial conditions from TMX files
def parse_tmx_soil(tmx_path: Path):
    with open(tmx_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    
    # Parse Soil Analysis (*SOIL ANALYSIS)
    sa_dict = {}
    sa_sec = content[content.find("*SOIL ANALYSIS"):content.find("*INITIAL CONDITIONS")]
    # blocks starting with @A SADAT ...
    sa_blocks = re.split(r"@A\s+SADAT.*?\n", sa_sec)[1:]
    for block in sa_blocks:
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        if not lines: continue
        hdr = lines[0].split()
        sa_id = int(hdr[0])
        # Find data lines after @A  SABL ...
        layer_rows = []
        data_started = False
        for l in lines[1:]:
            if "@A" in l and "SABL" in l:
                data_started = True
                continue
            if data_started:
                parts = l.split()
                if len(parts) >= 9:
                    sabl = float(parts[1])
                    sadm = float(parts[2])
                    saoc = float(parts[3])
                    sani = float(parts[4])
                    layer_rows.append({"depth": sabl, "bd": sadm, "oc": saoc, "ni": sani})
        sa_dict[sa_id] = pd.DataFrame(layer_rows)
        
    # Parse Initial Conditions (*INITIAL CONDITIONS)
    ic_dict = {}
    ic_sec = content[content.find("*INITIAL CONDITIONS"):content.find("*PLANTING DETAILS")]
    ic_blocks = re.split(r"@C\s+PCR.*?\n", ic_sec)[1:]
    for block in ic_blocks:
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        if not lines: continue
        hdr = lines[0].split()
        ic_id = int(hdr[0])
        layer_rows = []
        data_started = False
        for l in lines[1:]:
            if "@C" in l and "ICBL" in l:
                data_started = True
                continue
            if data_started:
                parts = l.split()
                if len(parts) >= 5:
                    icbl = float(parts[1])
                    sh2o = float(parts[2])
                    snh4 = float(parts[3])
                    sno3 = float(parts[4])
                    layer_rows.append({"depth": icbl, "sh2o": sh2o, "snh4": snh4, "sno3": sno3})
        ic_dict[ic_id] = pd.DataFrame(layer_rows)
        
    return sa_dict, ic_dict

print("\n" + "="*90)
print("PART 2: INITIAL SOIL WATER, MINERAL N, AND ORGANIC C PROFILES OF OUTLIER TREATMENTS")
print("="*90)

sa26, ic26 = parse_tmx_soil(PROJECT_ROOT / "data/user/experiments/xxql2601_corrected_20260923/XXQL2601.TMX")
sa25, ic25 = parse_tmx_soil(PROJECT_ROOT / "data/user/experiments/xxql2501_corrected_20260923/XXQL2501.TMX")

def summarize_profile(df_ic, df_sa):
    # Soil layer depths: e.g. 0-2, 2-4, 4-15, 15-30, 30-40, 40-60, 60-80, 80-100, 100-140, 140-180
    # Calculate profile water in mm (sh2o * thickness_cm * 10)
    # Calculate profile mineral N in kg N/ha (mg/kg * bd * thickness_cm * 0.1)
    # Merge on depth
    m = pd.merge(df_ic, df_sa, on="depth")
    prev_d = 0.0
    water_top40 = 0.0
    water_sub100 = 0.0
    water_total = 0.0
    
    n_top40 = 0.0
    n_sub100 = 0.0
    n_total = 0.0
    
    oc_top30 = []
    
    for _, r in m.iterrows():
        thick_cm = r["depth"] - prev_d
        w_mm = r["sh2o"] * thick_cm * 10.0
        n_kgha = (r["sno3"] + r["snh4"]) * r["bd"] * thick_cm * 0.1
        water_total += w_mm
        n_total += n_kgha
        
        if r["depth"] <= 40:
            water_top40 += w_mm
            n_top40 += n_kgha
        elif r["depth"] <= 100:
            water_sub100 += w_mm
            n_sub100 += n_kgha
            
        if r["depth"] <= 30:
            oc_top30.append(r["oc"])
            
        prev_d = r["depth"]
        
    return {
        "water_top40_mm": water_top40,
        "water_sub100_mm": water_sub100,
        "water_total_mm": water_total,
        "minN_top40_kgha": n_top40,
        "minN_sub100_kgha": n_sub100,
        "minN_total_kgha": n_total,
        "mean_top30_oc_pct": np.mean(oc_top30) if oc_top30 else np.nan,
    }

print("\n--- 26SP Soil Profile Summary by Treatment ---")
profile_26_rows = []
for tn in range(1, 13):
    trt_label = df[(df["SEASON"] == "26SP") & (df["TN"] == tn)]["Trt_Label"].values[0]
    mean_err = df[(df["SEASON"] == "26SP") & (df["TN"] == tn)]["mean_signed_err"].values[0]
    abs_err = df[(df["SEASON"] == "26SP") & (df["TN"] == tn)]["mean_abs_err"].values[0]
    p_info = summarize_profile(ic26[tn], sa26[tn])
    p_info.update({"TN": tn, "Label": trt_label, "MeanErr": mean_err, "MeanAbsErr": abs_err})
    profile_26_rows.append(p_info)

df_prof26 = pd.DataFrame(profile_26_rows)
print(df_prof26[["TN", "Label", "MeanErr", "water_top40_mm", "water_total_mm", "minN_top40_kgha", "minN_total_kgha", "mean_top30_oc_pct"]].to_string(index=False))

print("\n--- 25SP Soil Profile Summary by Treatment ---")
profile_25_rows = []
for tn in [2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14]:
    trt_label = df[(df["SEASON"] == "25SP") & (df["TN"] == tn)]["Trt_Label"].values[0]
    mean_err = df[(df["SEASON"] == "25SP") & (df["TN"] == tn)]["mean_signed_err"].values[0]
    abs_err = df[(df["SEASON"] == "25SP") & (df["TN"] == tn)]["mean_abs_err"].values[0]
    p_info = summarize_profile(ic25[tn], sa25[tn])
    p_info.update({"TN": tn, "Label": trt_label, "MeanErr": mean_err, "MeanAbsErr": abs_err})
    profile_25_rows.append(p_info)

df_prof25 = pd.DataFrame(profile_25_rows)
print(df_prof25[["TN", "Label", "MeanErr", "water_top40_mm", "water_total_mm", "minN_top40_kgha", "minN_total_kgha", "mean_top30_oc_pct"]].to_string(index=False))


# 3. R2 Leave-One-Out (LOO) Analysis for 26SP
print("\n" + "="*90)
print("PART 3: 26SP R^2 SENSITIVITY AND OUTLIER LEVERAGE ANALYSIS")
print("="*90)

sp26 = df[df["SEASON"] == "26SP"].copy()
o = sp26["OBS_t_ha"].to_numpy()

for model in ["C27", "Real24", "Real81", "C26"]:
    s = sp26[model].to_numpy()
    r_full = np.corrcoef(o, s)[0, 1]
    r2_full = r_full**2
    print(f"\nModel {model} Full 26SP (12 trts): R^2 = {r2_full:.4f} (r = {r_full:.4f})")
    
    loo_results = []
    for i in range(len(sp26)):
        mask = np.ones(len(sp26), dtype=bool)
        mask[i] = False
        o_sub = o[mask]
        s_sub = s[mask]
        r_sub = np.corrcoef(o_sub, s_sub)[0, 1]
        r2_sub = r_sub**2
        delta_r2 = r2_sub - r2_full
        tn = sp26.iloc[i]["TN"]
        label = sp26.iloc[i]["Trt_Label"]
        err = s[i] - o[i]
        loo_results.append({
            "TN": tn, "Label": label, "Obs": o[i], "Sim": s[i], "Err": err,
            "R2_without": r2_sub, "Delta_R2": delta_r2
        })
    df_loo = pd.DataFrame(loo_results).sort_values("Delta_R2", ascending=False)
    print("Leave-One-Out Impact on R^2 (sorted by positive contribution to R^2 when removed):")
    print(df_loo.to_string(index=False))

# Combinatorial analysis: Leave-2-Out and Leave-3-Out for C27
print("\n--- Combinatorial Ablation for C27 (Which combinations of 2 or 3 treatments suppress R^2?) ---")
from itertools import combinations

s_c27 = sp26["C27"].to_numpy()
comb2 = []
for c in combinations(range(12), 2):
    mask = np.ones(12, dtype=bool)
    mask[list(c)] = False
    r2 = (np.corrcoef(o[mask], s_c27[mask])[0, 1])**2
    names = "+".join([sp26.iloc[idx]["Trt_Label"] for idx in c])
    comb2.append({"Excluded": names, "R2": r2, "Gain": r2 - 0.447})

print("Top 5 Leave-2-Out Combinations for C27:")
print(pd.DataFrame(comb2).sort_values("R2", ascending=False).head(5).to_string(index=False))

comb3 = []
for c in combinations(range(12), 3):
    mask = np.ones(12, dtype=bool)
    mask[list(c)] = False
    r2 = (np.corrcoef(o[mask], s_c27[mask])[0, 1])**2
    names = "+".join([sp26.iloc[idx]["Trt_Label"] for idx in c])
    comb3.append({"Excluded": names, "R2": r2, "Gain": r2 - 0.447})

print("\nTop 5 Leave-3-Out Combinations for C27:")
print(pd.DataFrame(comb3).sort_values("R2", ascending=False).head(5).to_string(index=False))

