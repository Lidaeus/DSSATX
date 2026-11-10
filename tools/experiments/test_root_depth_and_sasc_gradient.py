#!/usr/bin/env python3
"""Controlled experiment to test:
1. Root depth truncation (SRGF at 100-140cm: 0.0 vs 0.01 vs 0.02 vs 0.05)
2. SASC_RATIO gradient (0.90, 0.92, 0.94, 0.96)
to investigate W1 water response deficit and W1N0 bias reduction.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dssat.run_dssat import prepare_run_directory

SCRATCH_DIR = PROJECT_ROOT / "scratch" / "root_sasc_exp"
if SCRATCH_DIR.exists():
    shutil.rmtree(SCRATCH_DIR)
SCRATCH_DIR.mkdir(parents=True)

BATCH_DIR = SCRATCH_DIR / "batches"
BATCH_DIR.mkdir()

# 25SP: 11 treatments
b25 = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch.v48"

# 26SP: 12 treatments
b26_lines = ["$BATCH(SEASON)", "! 2026 Spring all 12 treatments"]
for tn in range(1, 13):
    b26_lines.append(f"XXQL2601.TMX                                                                                    {tn:2d}      1      0      0      0")
b26 = BATCH_DIR / "DSSBatch_26SP_all.v48"
b26.write_text("\n".join(b26_lines) + "\n", encoding="utf-8")

# 25FA: 12 treatments
bfa_lines = ["$BATCH(SEASON)", "! 2025 Autumn all 12 treatments"]
for tn in range(1, 13):
    bfa_lines.append(f"XXQL2502.TMX                                                                                    {tn:2d}      1      0      0      0")
bfa = BATCH_DIR / "DSSBatch_25FA_all.v48"
bfa.write_text("\n".join(bfa_lines) + "\n", encoding="utf-8")

SEASONS = {
    "25SP": (b25, PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2501_corrected_20260923"),
    "26SP": (b26, PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2601_corrected_20260923"),
    "25FA": (bfa, PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_corrected_20260923"),
}

TMT_META = {
    # 25SP
    ("XXQL2501", 2): {"season": "25SP", "water": "W3", "nitro": "N3"},
    ("XXQL2501", 3): {"season": "25SP", "water": "W3", "nitro": "N2"},
    ("XXQL2501", 4): {"season": "25SP", "water": "W3", "nitro": "N1"},
    ("XXQL2501", 5): {"season": "25SP", "water": "W3", "nitro": "N0"},
    ("XXQL2501", 6): {"season": "25SP", "water": "W2", "nitro": "N3"},
    ("XXQL2501", 9): {"season": "25SP", "water": "W2", "nitro": "N0"},
    ("XXQL2501", 10): {"season": "25SP", "water": "W1", "nitro": "N3"},
    ("XXQL2501", 11): {"season": "25SP", "water": "W1", "nitro": "N2"},
    ("XXQL2501", 12): {"season": "25SP", "water": "W1", "nitro": "N1"},
    ("XXQL2501", 13): {"season": "25SP", "water": "W1", "nitro": "N0"},
    ("XXQL2501", 14): {"season": "25SP", "water": "CK", "nitro": "N2"},
    # 26SP
    ("XXQL2601", 1): {"season": "26SP", "water": "W3", "nitro": "N3"},
    ("XXQL2601", 2): {"season": "26SP", "water": "W2", "nitro": "N3"},
    ("XXQL2601", 3): {"season": "26SP", "water": "W1", "nitro": "N3"},
    ("XXQL2601", 4): {"season": "26SP", "water": "W3", "nitro": "N2"},
    ("XXQL2601", 5): {"season": "26SP", "water": "W2", "nitro": "N2"},
    ("XXQL2601", 6): {"season": "26SP", "water": "W1", "nitro": "N2"},
    ("XXQL2601", 7): {"season": "26SP", "water": "W3", "nitro": "N1"},
    ("XXQL2601", 8): {"season": "26SP", "water": "W2", "nitro": "N1"},
    ("XXQL2601", 9): {"season": "26SP", "water": "W3", "nitro": "N0"},
    ("XXQL2601", 10): {"season": "26SP", "water": "W1", "nitro": "N1"},
    ("XXQL2601", 11): {"season": "26SP", "water": "W2", "nitro": "N0"},
    ("XXQL2601", 12): {"season": "26SP", "water": "W1", "nitro": "N0"},
    # 25FA
    ("XXQL2502", 1): {"season": "25FA", "water": "W3", "nitro": "N3"},
    ("XXQL2502", 2): {"season": "25FA", "water": "W2", "nitro": "N3"},
    ("XXQL2502", 3): {"season": "25FA", "water": "W1", "nitro": "N3"},
    ("XXQL2502", 4): {"season": "25FA", "water": "W3", "nitro": "N2"},
    ("XXQL2502", 5): {"season": "25FA", "water": "W2", "nitro": "N2"},
    ("XXQL2502", 6): {"season": "25FA", "water": "W1", "nitro": "N2"},
    ("XXQL2502", 7): {"season": "25FA", "water": "W3", "nitro": "N1"},
    ("XXQL2502", 8): {"season": "25FA", "water": "W2", "nitro": "N1"},
    ("XXQL2502", 9): {"season": "25FA", "water": "W3", "nitro": "N0"},
    ("XXQL2502", 10): {"season": "25FA", "water": "W1", "nitro": "N1"},
    ("XXQL2502", 11): {"season": "25FA", "water": "W2", "nitro": "N0"},
    ("XXQL2502", 12): {"season": "25FA", "water": "W1", "nitro": "N0"},
}

REF_OBS_CSV = PROJECT_ROOT / "workspace" / "experiments" / "compare_real81_and_optionb" / "new_calib_35_treatments_compare.csv"
ref_obs_df = pd.read_csv(REF_OBS_CSV)
OBS_LOOKUP = {(row["EXCODE"], int(row["TN"])): float(row["OBS_t_ha"]) for _, row in ref_obs_df.iterrows()}

def calc_stats(obs, sim):
    mask = np.isfinite(obs) & np.isfinite(sim)
    o = obs[mask].to_numpy()
    s = sim[mask].to_numpy()
    if len(o) < 2: return {"RMSE": np.nan, "NRMSE%": np.nan, "NSE": np.nan, "R2": np.nan, "d": np.nan}
    rmse = np.sqrt(np.mean((s - o)**2))
    nrmse = rmse / np.mean(o) * 100.0
    denom = np.sum((o - np.mean(o))**2)
    nse = 1.0 - (np.sum((o - s)**2) / denom) if denom else np.nan
    denom_d = np.sum((np.abs(s - np.mean(o)) + np.abs(o - np.mean(o)))**2)
    d = 1.0 - (np.sum((o - s)**2) / denom_d) if denom_d else np.nan
    r = np.corrcoef(o, s)[0, 1] if np.std(o) > 1e-6 and np.std(s) > 1e-6 else np.nan
    r2 = r**2 if np.isfinite(r) else np.nan
    return {"RMSE": rmse, "NRMSE%": nrmse, "NSE": nse, "R2": r2, "d": d}

def run_season(param_csv: Path, batch_path: Path, input_dir: Path, out_dir: Path):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    batch_dest = prepare_run_directory(out_dir, ["--batch", str(batch_path), "--input-dir", str(input_dir)])
    cmd = [
        sys.executable, "-m", "src.dssat.run_dssat",
        "--param-csv", str(param_csv.resolve()),
        "--batch", batch_dest.name,
        "--harvest-var", "CHPDT",
        "--input-dir", str(input_dir.resolve()),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run(cmd, cwd=out_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    if p.returncode != 0:
        raise RuntimeError(f"DSSAT execution failed: {p.stderr}")

def extract_season_results(run_dir: Path, expt_prefix: str):
    ph_path = run_dir / "PestHarvest.OUT"
    sim_dict = {}
    with open(ph_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.strip().split()
            if "TN" in parts and "@CHFPWS@" in parts:
                tn = int(parts[parts.index("TN") + 1])
                val = float(parts[parts.index("@CHFPWS@") + 1])
                sim_dict[tn] = val / 1000.0  # t/ha
    rows = []
    for trno in sorted(sim_dict.keys()):
        meta = TMT_META.get((expt_prefix, trno), {})
        obs_val = OBS_LOOKUP.get((expt_prefix, trno), np.nan)
        sim_val = sim_dict.get(trno, np.nan)
        rows.append({
            "expt": expt_prefix,
            "treatment": trno,
            "season": meta.get("season", ""),
            "water": meta.get("water", ""),
            "nitro": meta.get("nitro", ""),
            "obs_t_ha": obs_val,
            "sim_t_ha": sim_val,
            "err": sim_val - obs_val,
        })
    return pd.DataFrame(rows)

# Load Real 24 base parameters
P24_CSV = PROJECT_ROOT / "workspace" / "runs" / "full_gen_13trt_n1_fix_200x6_20260924" / "eval_top_candidates" / "runs" / "iter6_real_24" / "params.csv"
p24_df = pd.read_csv(P24_CSV, header=None, names=["name", "value"])
base_dict = dict(zip(p24_df["name"], p24_df["value"]))

EXPERIMENTS = {
    # 1. Baseline
    "Base_Real24": {},
    # 2. Root truncation experiments (SASC=0.90)
    "Trunc100_SRGF0_SASC090": {"soil_srgf_09": 0.000},
    "Allow140_SRGF001_SASC090": {"soil_srgf_09": 0.010},
    "Allow140_SRGF002_SASC090": {"soil_srgf_09": 0.020},
    # 3. SASC Gradient with Truncate 100cm
    "Trunc100_SASC092": {"soil_srgf_09": 0.000, "sasc_ratio": 0.92},
    "Trunc100_SASC094": {"soil_srgf_09": 0.000, "sasc_ratio": 0.94},
    "Trunc100_SASC096": {"soil_srgf_09": 0.000, "sasc_ratio": 0.96},
    # 4. SASC Gradient with Allow 140cm (SRGF=0.02)
    "Allow140_002_SASC092": {"soil_srgf_09": 0.020, "sasc_ratio": 0.92},
    "Allow140_002_SASC094": {"soil_srgf_09": 0.020, "sasc_ratio": 0.94},
    "Allow140_002_SASC096": {"soil_srgf_09": 0.020, "sasc_ratio": 0.96},
}

summary_list = []
detailed_dfs = {}

for exp_name, overrides in EXPERIMENTS.items():
    cdict = base_dict.copy()
    cdict.update(overrides)
    p_csv = SCRATCH_DIR / f"{exp_name}_params.csv"
    pd.DataFrame(list(cdict.items()), columns=["name", "value"]).to_csv(p_csv, index=False)
    
    s_dfs = []
    for sname, (bpath, exp_dir) in SEASONS.items():
        out_dir = SCRATCH_DIR / exp_name / sname
        run_season(p_csv, bpath, exp_dir, out_dir)
        expt = "XXQL2501" if sname == "25SP" else ("XXQL2601" if sname == "26SP" else "XXQL2502")
        s_dfs.append(extract_season_results(out_dir, expt))
        
    df_all = pd.concat(s_dfs, ignore_index=True)
    detailed_dfs[exp_name] = df_all
    
    sp25 = df_all[df_all["season"] == "25SP"].set_index("treatment")
    sp26 = df_all[df_all["season"] == "26SP"].set_index("treatment")
    twosp = df_all[df_all["season"].isin(["25SP", "26SP"])]
    
    st25 = calc_stats(sp25["obs_t_ha"], sp25["sim_t_ha"])
    st26 = calc_stats(sp26["obs_t_ha"], sp26["sim_t_ha"])
    st2sp = calc_stats(twosp["obs_t_ha"], twosp["sim_t_ha"])
    stgrand = calc_stats(df_all["obs_t_ha"], df_all["sim_t_ha"])
    
    # 26SP W1N0 and Water gap checks
    # In 26SP: W1N0 is tr 12; W3N0 is tr 9; W2N0 is tr 11
    # W1N3 is tr 3; W3N3 is tr 1
    # W1 mean yield vs W3 mean yield in 26SP
    w1_26_mean = df_all[(df_all["season"] == "26SP") & (df_all["water"] == "W1")]["sim_t_ha"].mean()
    w3_26_mean = df_all[(df_all["season"] == "26SP") & (df_all["water"] == "W3")]["sim_t_ha"].mean()
    w1_w3_gap_26 = w1_26_mean - w3_26_mean
    
    # W1N0 error
    w1n0_err_26 = sp26.loc[12, "err"]
    w3n0_err_26 = sp26.loc[9, "err"]
    
    # 25SP W1N0 and W3(N1-N3)
    w1n0_err_25 = sp25.loc[13, "err"]
    w3_inv_25 = sp25.loc[4, "sim_t_ha"] - sp25.loc[2, "sim_t_ha"]
    
    summary_list.append({
        "Experiment": exp_name,
        "TwoSp_NRMSE%": st2sp["NRMSE%"],
        "TwoSp_NSE": st2sp["NSE"],
        "TwoSp_R2": st2sp["R2"],
        "25SP_NRMSE%": st25["NRMSE%"],
        "25SP_NSE": st25["NSE"],
        "25SP_R2": st25["R2"],
        "26SP_NRMSE%": st26["NRMSE%"],
        "26SP_NSE": st26["NSE"],
        "26SP_R2": st26["R2"],
        "26SP_W1N0_Err": w1n0_err_26,
        "26SP_W3N0_Err": w3n0_err_26,
        "26SP_W1-W3_Gap": w1_w3_gap_26,
        "25SP_W1N0_Err": w1n0_err_25,
        "25SP_W3(N1-N3)": w3_inv_25,
    })
    print(f"Done {exp_name:24s} | 26SP W1N0 Err={w1n0_err_26:+.2f} | 26SP W1-W3={w1_w3_gap_26:+.2f} | TwoSp NRMSE={st2sp['NRMSE%']:.2f}% | 26SP NSE={st26['NSE']:+.3f}")

sum_df = pd.DataFrame(summary_list)
res_csv = PROJECT_ROOT / "workspace" / "experiments" / "compare_real81_and_optionb" / "root_and_sasc_experiment_summary.csv"
sum_df.to_csv(res_csv, index=False)
print("\n" + "="*120)
print("EXPERIMENT SUMMARY: ROOT DEPTH TRUNCATION & SASC GRADIENT:")
print("="*120)
cols_show = ["Experiment", "TwoSp_NRMSE%", "TwoSp_NSE", "25SP_NRMSE%", "25SP_NSE", "26SP_NRMSE%", "26SP_NSE", "26SP_R2", "26SP_W1N0_Err", "26SP_W1-W3_Gap"]
print(sum_df[cols_show].to_string(index=False))
