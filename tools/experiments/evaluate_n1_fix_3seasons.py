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

SCRATCH_DIR = PROJECT_ROOT / "scratch" / "n1_fix_3seasons"
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

def calc_nse(obs, sim):
    mask = np.isfinite(obs) & np.isfinite(sim)
    o = obs[mask].to_numpy()
    s = sim[mask].to_numpy()
    if len(o) < 2: return np.nan
    denom = np.sum((o - np.mean(o))**2)
    if denom == 0: return np.nan
    return 1.0 - (np.sum((o - s)**2) / denom)

def run_season(param_csv: Path, batch_path: Path, input_dir: Path, out_dir: Path):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    
    batch_dest = prepare_run_directory(out_dir, ["--batch", str(batch_path), "--input-dir", str(input_dir)])
    
    cmd = [
        sys.executable,
        "-m",
        "src.dssat.run_dssat",
        "--param-csv", str(param_csv.resolve()),
        "--batch", batch_dest.name,
        "--harvest-var", "CHPDT",
        "--input-dir", str(input_dir.resolve()),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run(cmd, cwd=out_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    if p.returncode != 0:
        raise RuntimeError(f"DSSAT execution failed in {out_dir}: {p.stderr}")

REF_OBS_CSV = PROJECT_ROOT / "workspace" / "experiments" / "compare_real81_and_optionb" / "new_calib_35_treatments_compare.csv"
ref_obs_df = pd.read_csv(REF_OBS_CSV)
OBS_LOOKUP = {(row["EXCODE"], int(row["TN"])): float(row["OBS_t_ha"]) for _, row in ref_obs_df.iterrows()}

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
        rows.append({
            "expt": expt_prefix,
            "treatment": trno,
            "season": meta.get("season", ""),
            "water": meta.get("water", ""),
            "nitro": meta.get("nitro", ""),
            "obs_t_ha": obs_val,
            "sim_t_ha": sim_dict.get(trno, np.nan),
        })
    return pd.DataFrame(rows)

# Base parameters: New_Real 80
BASE_CSV = PROJECT_ROOT / "workspace" / "runs" / "full_gen_13trt_corrected_sasc090_icns1_shift05_200x6_20260924" / "eval_top_candidates" / "cand_real_80" / "params.csv"
base_params = pd.read_csv(BASE_CSV, header=None, names=["param", "value"])
base_dict = dict(zip(base_params["param"], base_params["value"]))

CANDIDATES = {
    "Baseline_Real80": {},
    "Fix_PROLFF_0.20_FNPGN2_6.0": {"prolff": 0.20, "fnpgn2": 6.0},
    "Fix_PROLFF_0.22_FNPGN2_6.0": {"prolff": 0.22, "fnpgn2": 6.0},
    "Fix_PROLFF_0.22_FNPGN2_6.0_RTNO3_0.015": {"prolff": 0.22, "fnpgn2": 6.0, "rtno3": 0.015},
    "Fix_PROLFF_0.24_FNPGN2_6.0_RTNO3_0.012": {"prolff": 0.24, "fnpgn2": 6.0, "rtno3": 0.012},
}

summary_list = []

for cname, overrides in CANDIDATES.items():
    cdict = base_dict.copy()
    cdict.update(overrides)
    p_csv = SCRATCH_DIR / f"{cname}_params.csv"
    pd.DataFrame(list(cdict.items())).to_csv(p_csv, header=False, index=False)
    
    all_season_dfs = []
    for sname, (bpath, exp_dir) in SEASONS.items():
        out_dir = SCRATCH_DIR / cname / sname
        run_season(p_csv, bpath, exp_dir, out_dir)
        prefix = "XXQL2501" if sname == "25SP" else ("XXQL2601" if sname == "26SP" else "XXQL2502")
        df_season = extract_season_results(out_dir, prefix)
        all_season_dfs.append(df_season)
        
    df_all = pd.concat(all_season_dfs, ignore_index=True)
    df_all["err"] = df_all["sim_t_ha"] - df_all["obs_t_ha"]
    
    # Calculate metrics
    res_entry = {"Candidate": cname}
    
    # By season
    for sname in ["25SP", "26SP", "25FA"]:
        sub_s = df_all[df_all["season"] == sname]
        rmse = np.sqrt(np.mean(sub_s["err"]**2))
        nrmse = rmse / np.mean(sub_s["obs_t_ha"]) * 100.0
        nse = calc_nse(sub_s["obs_t_ha"], sub_s["sim_t_ha"])
        res_entry[f"{sname}_NRMSE%"] = nrmse
        res_entry[f"{sname}_NSE"] = nse
        
    # Calibration (25SP + 26SP)
    sub_cal = df_all[df_all["season"].isin(["25SP", "26SP"])]
    rmse_cal = np.sqrt(np.mean(sub_cal["err"]**2))
    res_entry["TwoSpring_NRMSE%"] = rmse_cal / np.mean(sub_cal["obs_t_ha"]) * 100.0
    res_entry["TwoSpring_NSE"] = calc_nse(sub_cal["obs_t_ha"], sub_cal["sim_t_ha"])
    
    # Grand 35
    rmse_grand = np.sqrt(np.mean(df_all["err"]**2))
    res_entry["Grand35_NRMSE%"] = rmse_grand / np.mean(df_all["obs_t_ha"]) * 100.0
    res_entry["Grand35_NSE"] = calc_nse(df_all["obs_t_ha"], df_all["sim_t_ha"])
    
    # Check 25SP N ladders
    # 25SP: W3N3=tr2, W3N1=tr4; W1N3=tr10, W1N1=tr12
    sp25 = df_all[df_all["season"] == "25SP"].set_index("treatment")
    res_entry["25SP_W3(N1-N3)"] = sp25.loc[4, "sim_t_ha"] - sp25.loc[2, "sim_t_ha"]
    res_entry["25SP_W1(N1-N3)"] = sp25.loc[12, "sim_t_ha"] - sp25.loc[10, "sim_t_ha"]
    res_entry["25SP_W3N1_Err"] = sp25.loc[4, "err"]
    
    # 26SP: W3N3=tr1, W3N1=tr7; W1N3=tr3, W1N1=tr10
    sp26 = df_all[df_all["season"] == "26SP"].set_index("treatment")
    res_entry["26SP_W3(N1-N3)"] = sp26.loc[7, "sim_t_ha"] - sp26.loc[1, "sim_t_ha"]
    res_entry["26SP_W1(N1-N3)"] = sp26.loc[10, "sim_t_ha"] - sp26.loc[3, "sim_t_ha"]
    res_entry["26SP_W3N1_Err"] = sp26.loc[7, "err"]
    
    summary_list.append(res_entry)
    print(f"Finished {cname} | TwoSpring NRMSE={res_entry['TwoSpring_NRMSE%']:.2f}% | Grand NRMSE={res_entry['Grand35_NRMSE%']:.2f}% | 25SP W3(N1-N3)={res_entry['25SP_W3(N1-N3)']:+.2f} | 26SP W3(N1-N3)={res_entry['26SP_W3(N1-N3)']:+.2f}")

df_sum = pd.DataFrame(summary_list)
print("\n" + "="*110)
print("COMPREHENSIVE 3-SEASON EVALUATION ACROSS N1 FIX CANDIDATES:")
print("="*110)
cols_show = ["Candidate", "Grand35_NRMSE%", "Grand35_NSE", "TwoSpring_NRMSE%", "TwoSpring_NSE", "25SP_NRMSE%", "26SP_NRMSE%", "25FA_NRMSE%", "25SP_W3(N1-N3)", "26SP_W3(N1-N3)", "25SP_W3N1_Err"]
print(df_sum[cols_show].to_string(index=False))
df_sum.to_csv(PROJECT_ROOT / "workspace" / "experiments" / "compare_real81_and_optionb" / "n1_fix_3seasons_summary.csv", index=False)
