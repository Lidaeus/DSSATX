#!/usr/bin/env python3
"""Post-calibration evaluation script for full_gen_13trt_n1_fix_200x6_20260924 across all 35 treatments:
1. Parse PEST-IES phi output and rank final ensemble candidates
2. Extract top candidates and run full 3-season deterministic simulations (35 treatments)
3. Calculate comprehensive statistics (RMSE, NRMSE, NSE, d-index, R2) for 25SP, 26SP, TwoSpring, 25FA, Grand 35
4. Evaluate W3(N1-N3) and W1(N1-N3) yield response ladders to confirm N1 over-prediction is resolved
5. Generate comparison tables and summary metrics
"""

import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dssat.run_dssat import prepare_run_directory

RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / "full_gen_13trt_n1_fix_200x6_20260924"
PREFIX = "full_gen_13trt_n1_fix_200x6_20260924"

EVAL_DIR = RUN_DIR / "eval_top_candidates"
BATCH_DIR = EVAL_DIR / "batches"

SEASONS = {
    "25SP": (
        PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch.v48",
        PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2501_corrected_20260923"
    ),
    "26SP": (
        None,  # Generated dynamically below
        PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2601_corrected_20260923"
    ),
    "25FA": (
        None,  # Generated dynamically below
        PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_corrected_20260923"
    ),
}

TMT_META = {
    # 25SP (11 trts)
    ("XXQL2501", 2): {"season": "25SP", "water": "W3", "nitro": "N3", "label": "W3N3"},
    ("XXQL2501", 3): {"season": "25SP", "water": "W3", "nitro": "N2", "label": "W3N2"},
    ("XXQL2501", 4): {"season": "25SP", "water": "W3", "nitro": "N1", "label": "W3N1"},
    ("XXQL2501", 5): {"season": "25SP", "water": "W3", "nitro": "N0", "label": "W3N0"},
    ("XXQL2501", 6): {"season": "25SP", "water": "W2", "nitro": "N3", "label": "W2N3"},
    ("XXQL2501", 9): {"season": "25SP", "water": "W2", "nitro": "N0", "label": "W2N0"},
    ("XXQL2501", 10): {"season": "25SP", "water": "W1", "nitro": "N3", "label": "W1N3"},
    ("XXQL2501", 11): {"season": "25SP", "water": "W1", "nitro": "N2", "label": "W1N2"},
    ("XXQL2501", 12): {"season": "25SP", "water": "W1", "nitro": "N1", "label": "W1N1"},
    ("XXQL2501", 13): {"season": "25SP", "water": "W1", "nitro": "N0", "label": "W1N0"},
    ("XXQL2501", 14): {"season": "25SP", "water": "CK", "nitro": "N2", "label": "CKN2"},
    # 26SP (12 trts)
    ("XXQL2601", 1): {"season": "26SP", "water": "W3", "nitro": "N3", "label": "W3N3"},
    ("XXQL2601", 2): {"season": "26SP", "water": "W2", "nitro": "N3", "label": "W2N3"},
    ("XXQL2601", 3): {"season": "26SP", "water": "W1", "nitro": "N3", "label": "W1N3"},
    ("XXQL2601", 4): {"season": "26SP", "water": "W3", "nitro": "N2", "label": "W3N2"},
    ("XXQL2601", 5): {"season": "26SP", "water": "W2", "nitro": "N2", "label": "W2N2"},
    ("XXQL2601", 6): {"season": "26SP", "water": "W1", "nitro": "N2", "label": "W1N2"},
    ("XXQL2601", 7): {"season": "26SP", "water": "W3", "nitro": "N1", "label": "W3N1"},
    ("XXQL2601", 8): {"season": "26SP", "water": "W2", "nitro": "N1", "label": "W2N1"},
    ("XXQL2601", 9): {"season": "26SP", "water": "W3", "nitro": "N0", "label": "W3N0"},
    ("XXQL2601", 10): {"season": "26SP", "water": "W1", "nitro": "N1", "label": "W1N1"},
    ("XXQL2601", 11): {"season": "26SP", "water": "W2", "nitro": "N0", "label": "W2N0"},
    ("XXQL2601", 12): {"season": "26SP", "water": "W1", "nitro": "N0", "label": "W1N0"},
    # 25FA (12 trts)
    ("XXQL2502", 1): {"season": "25FA", "water": "W3", "nitro": "N3", "label": "W3N3"},
    ("XXQL2502", 2): {"season": "25FA", "water": "W2", "nitro": "N3", "label": "W2N3"},
    ("XXQL2502", 3): {"season": "25FA", "water": "W1", "nitro": "N3", "label": "W1N3"},
    ("XXQL2502", 4): {"season": "25FA", "water": "W3", "nitro": "N2", "label": "W3N2"},
    ("XXQL2502", 5): {"season": "25FA", "water": "W2", "nitro": "N2", "label": "W2N2"},
    ("XXQL2502", 6): {"season": "25FA", "water": "W1", "nitro": "N2", "label": "W1N2"},
    ("XXQL2502", 7): {"season": "25FA", "water": "W3", "nitro": "N1", "label": "W3N1"},
    ("XXQL2502", 8): {"season": "25FA", "water": "W2", "nitro": "N1", "label": "W2N1"},
    ("XXQL2502", 9): {"season": "25FA", "water": "W3", "nitro": "N0", "label": "W3N0"},
    ("XXQL2502", 10): {"season": "25FA", "water": "W1", "nitro": "N1", "label": "W1N1"},
    ("XXQL2502", 11): {"season": "25FA", "water": "W2", "nitro": "N0", "label": "W2N0"},
    ("XXQL2502", 12): {"season": "25FA", "water": "W1", "nitro": "N0", "label": "W1N0"},
}

REF_OBS_CSV = PROJECT_ROOT / "workspace" / "experiments" / "compare_real81_and_optionb" / "new_calib_35_treatments_compare.csv"

def init_batches():
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    # 26SP
    b26_lines = ["$BATCH(SEASON)", "! 2026 Spring all 12 treatments"]
    for tn in range(1, 13):
        b26_lines.append(f"XXQL2601.TMX                                                                                    {tn:2d}      1      0      0      0")
    b26_path = BATCH_DIR / "DSSBatch_26SP_all.v48"
    b26_path.write_text("\n".join(b26_lines) + "\n", encoding="utf-8")
    
    # 25FA
    bfa_lines = ["$BATCH(SEASON)", "! 2025 Autumn all 12 treatments"]
    for tn in range(1, 13):
        bfa_lines.append(f"XXQL2502.TMX                                                                                    {tn:2d}      1      0      0      0")
    bfa_path = BATCH_DIR / "DSSBatch_25FA_all.v48"
    bfa_path.write_text("\n".join(bfa_lines) + "\n", encoding="utf-8")
    
    SEASONS["26SP"] = (b26_path, SEASONS["26SP"][1])
    SEASONS["25FA"] = (bfa_path, SEASONS["25FA"][1])

def get_obs_lookup():
    ref_df = pd.read_csv(REF_OBS_CSV)
    return {(row["EXCODE"], int(row["TN"])): float(row["OBS_t_ha"]) for _, row in ref_df.iterrows()}

def calc_stats(obs, sim):
    mask = np.isfinite(obs) & np.isfinite(sim)
    o = obs[mask].to_numpy()
    s = sim[mask].to_numpy()
    if len(o) < 2:
        return {"RMSE": np.nan, "NRMSE%": np.nan, "NSE": np.nan, "d_index": np.nan, "R2": np.nan}
    
    rmse = np.sqrt(np.mean((s - o)**2))
    nrmse = rmse / np.mean(o) * 100.0
    
    denom_nse = np.sum((o - np.mean(o))**2)
    nse = 1.0 - (np.sum((o - s)**2) / denom_nse) if denom_nse != 0 else np.nan
    
    denom_d = np.sum((np.abs(s - np.mean(o)) + np.abs(o - np.mean(o)))**2)
    d = 1.0 - (np.sum((o - s)**2) / denom_d) if denom_d != 0 else np.nan
    
    if np.std(o) > 1e-8 and np.std(s) > 1e-8:
        r = np.corrcoef(o, s)[0, 1]
        r2 = r**2
    else:
        r2 = np.nan
        
    return {"RMSE": rmse, "NRMSE%": nrmse, "NSE": nse, "d_index": d, "R2": r2}

def run_dssat_single(param_csv: Path, batch_path: Path, input_dir: Path, out_dir: Path):
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

def extract_season_yields(run_dir: Path, expt_prefix: str, obs_lookup: dict):
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
        obs_val = obs_lookup.get((expt_prefix, trno), np.nan)
        sim_val = sim_dict.get(trno, np.nan)
        rows.append({
            "expt": expt_prefix,
            "treatment": trno,
            "label": meta.get("label", f"T{trno}"),
            "season": meta.get("season", ""),
            "water": meta.get("water", ""),
            "nitro": meta.get("nitro", ""),
            "obs_t_ha": obs_val,
            "sim_t_ha": sim_val,
            "error_t_ha": sim_val - obs_val,
            "error_pct": (sim_val - obs_val) / obs_val * 100.0 if obs_val else np.nan
        })
    return pd.DataFrame(rows)

def find_latest_iteration(run_dir: Path, prefix: str):
    par_files = sorted(run_dir.glob(f"{prefix}.*.par.csv"))
    if not par_files:
        raise FileNotFoundError(f"No par.csv files found in {run_dir}")
    iters = []
    for p in par_files:
        parts = p.name.split(".")
        if len(parts) >= 3 and parts[1].isdigit():
            iters.append(int(parts[1]))
    if not iters:
        raise ValueError(f"Cannot parse iteration numbers from {par_files}")
    return max(iters)

def evaluate_all():
    init_batches()
    obs_lookup = get_obs_lookup()
    
    # 1. Identify latest iteration
    last_iter = find_latest_iteration(RUN_DIR, PREFIX)
    print(f"Latest calibration iteration found: Iteration {last_iter}")
    
    par_file = RUN_DIR / f"{PREFIX}.{last_iter}.par.csv"
    phi_file = RUN_DIR / f"{PREFIX}.phi.actual.csv"
    
    df_par = pd.read_csv(par_file, index_col=0)
    print(f"Loaded {len(df_par)} realizations from {par_file.name}")
    
    # Check phi
    ranked_reals = []
    if phi_file.exists():
        df_phi = pd.read_csv(phi_file)
        if "iteration" in df_phi.columns and last_iter in df_phi["iteration"].values:
            it_row = df_phi[df_phi["iteration"] == last_iter].iloc[0]
            meta_cols = {"iteration", "total_runs", "mean", "standard_deviation", "min", "max"}
            real_cols = [c for c in df_phi.columns if c not in meta_cols]
            phi_series = it_row[real_cols].dropna().astype(float)
            ranked_series = phi_series.sort_values()
            ranked_reals = list(ranked_series.index)
            print(f"Ranked {len(ranked_reals)} realizations by total phi from iteration {last_iter}")
            print(f"Top 8 phi values:\n{ranked_series.head(8)}")
    
    if not ranked_reals:
        ranked_reals = list(df_par.index)
        
    # Select top candidates (up to 6)
    top_candidates = []
    for r in ranked_reals:
        r_str = str(r)
        if r_str in df_par.index:
            top_candidates.append(r_str)
        elif isinstance(r, (int, np.integer)) and r in df_par.index:
            top_candidates.append(r)
        if len(top_candidates) >= 6:
            break
            
    print(f"Selected candidates for full 35-treatment evaluation: {top_candidates}")
    
    summary_records = []
    all_cand_details = {}
    
    scratch_base = EVAL_DIR / "runs"
    scratch_base.mkdir(parents=True, exist_ok=True)
    
    for cand in top_candidates:
        cand_name = f"iter{last_iter}_real_{cand}"
        cand_dir = scratch_base / cand_name
        cand_dir.mkdir(parents=True, exist_ok=True)
        
        # Save params.csv
        p_row = df_par.loc[cand]
        p_df = pd.DataFrame({"name": p_row.index, "value": p_row.values})
        param_csv = cand_dir / "params.csv"
        p_df.to_csv(param_csv, header=False, index=False)
        
        # Run 3 seasons
        season_dfs = []
        for sname, (bpath, exp_dir) in SEASONS.items():
            s_out = cand_dir / sname
            run_dssat_single(param_csv, bpath, exp_dir, s_out)
            expt = "XXQL2501" if sname == "25SP" else ("XXQL2601" if sname == "26SP" else "XXQL2502")
            df_s = extract_season_yields(s_out, expt, obs_lookup)
            season_dfs.append(df_s)
            
        full_df = pd.concat(season_dfs, ignore_index=True)
        all_cand_details[cand_name] = full_df
        full_df.to_csv(cand_dir / "treatment_yield_35.csv", index=False)
        
        # Calculate stats
        sp25_df = full_df[full_df["season"] == "25SP"]
        sp26_df = full_df[full_df["season"] == "26SP"]
        fa25_df = full_df[full_df["season"] == "25FA"]
        two_sp_df = full_df[full_df["season"].isin(["25SP", "26SP"])]
        
        st_25 = calc_stats(sp25_df["obs_t_ha"], sp25_df["sim_t_ha"])
        st_26 = calc_stats(sp26_df["obs_t_ha"], sp26_df["sim_t_ha"])
        st_2sp = calc_stats(two_sp_df["obs_t_ha"], two_sp_df["sim_t_ha"])
        st_fa = calc_stats(fa25_df["obs_t_ha"], fa25_df["sim_t_ha"])
        st_grand = calc_stats(full_df["obs_t_ha"], full_df["sim_t_ha"])
        
        # 25SP: W3N3=tr2, W3N1=tr4; W1N3=tr10, W1N1=tr12
        sp25_by_t = sp25_df.set_index("treatment")
        w3_n1_n3_25 = sp25_by_t.loc[4, "sim_t_ha"] - sp25_by_t.loc[2, "sim_t_ha"]
        w1_n1_n3_25 = sp25_by_t.loc[12, "sim_t_ha"] - sp25_by_t.loc[10, "sim_t_ha"]
        w3n1_err_25 = sp25_by_t.loc[4, "error_t_ha"]
        
        # 26SP: W3N3=tr1, W3N1=tr7; W1N3=tr3, W1N1=tr10
        sp26_by_t = sp26_df.set_index("treatment")
        w3_n1_n3_26 = sp26_by_t.loc[7, "sim_t_ha"] - sp26_by_t.loc[1, "sim_t_ha"]
        w1_n1_n3_26 = sp26_by_t.loc[10, "sim_t_ha"] - sp26_by_t.loc[3, "sim_t_ha"]
        w3n1_err_26 = sp26_by_t.loc[7, "error_t_ha"]
        
        # Key physiological parameters
        prolff_val = p_row.get("prolff", np.nan)
        prolfg_val = p_row.get("prolfg", np.nan)
        prolfi_val = p_row.get("prolfi", np.nan)
        fnpgn2_val = p_row.get("fnpgn2", np.nan)
        lnref_val = p_row.get("lnref", np.nan)
        rtno3_val = p_row.get("rtno3", np.nan)
        
        summary_records.append({
            "Candidate": cand_name,
            "Realization": cand,
            "PROLFF": prolff_val,
            "PROLFG": prolfg_val,
            "PROLFI": prolfi_val,
            "FNPGN2": fnpgn2_val,
            "LNREF": lnref_val,
            "RTNO3": rtno3_val,
            "25SP_NRMSE%": st_25["NRMSE%"],
            "25SP_NSE": st_25["NSE"],
            "25SP_R2": st_25["R2"],
            "26SP_NRMSE%": st_26["NRMSE%"],
            "26SP_NSE": st_26["NSE"],
            "26SP_R2": st_26["R2"],
            "TwoSpring_NRMSE%": st_2sp["NRMSE%"],
            "TwoSpring_NSE": st_2sp["NSE"],
            "TwoSpring_R2": st_2sp["R2"],
            "25FA_NRMSE%": st_fa["NRMSE%"],
            "25FA_NSE": st_fa["NSE"],
            "Grand35_NRMSE%": st_grand["NRMSE%"],
            "Grand35_NSE": st_grand["NSE"],
            "Grand35_R2": st_grand["R2"],
            "25SP_W3(N1-N3)": w3_n1_n3_25,
            "25SP_W1(N1-N3)": w1_n1_n3_25,
            "25SP_W3N1_Err": w3n1_err_25,
            "26SP_W3(N1-N3)": w3_n1_n3_26,
            "26SP_W1(N1-N3)": w1_n1_n3_26,
            "26SP_W3N1_Err": w3n1_err_26,
        })
        print(f"Finished {cand_name} | TwoSpring NRMSE={st_2sp['NRMSE%']:.2f}%, NSE={st_2sp['NSE']:.4f} | Grand NRMSE={st_grand['NRMSE%']:.2f}% | 25SP W3(N1-N3)={w3_n1_n3_25:+.2f} | 26SP W3(N1-N3)={w3_n1_n3_26:+.2f}")

    sum_df = pd.DataFrame(summary_records)
    sum_csv = EVAL_DIR / "candidates_evaluation_summary.csv"
    sum_df.to_csv(sum_csv, index=False)
    
    print("\n" + "="*120)
    print("EVALUATION SUMMARY OF TOP CANDIDATES ACROSS ALL 35 TREATMENTS:")
    print("="*120)
    cols_display = [
        "Candidate", "TwoSpring_NRMSE%", "TwoSpring_NSE", "TwoSpring_R2",
        "25SP_NRMSE%", "26SP_NRMSE%", "Grand35_NRMSE%", "Grand35_NSE",
        "25SP_W3(N1-N3)", "26SP_W3(N1-N3)", "25SP_W3N1_Err", "26SP_W3N1_Err"
    ]
    print(sum_df[cols_display].to_string(index=False))
    print(f"\nSaved detailed summary to: {sum_csv}")
    
    best_cand = sum_df.sort_values(by="TwoSpring_NRMSE%").iloc[0]["Candidate"]
    best_details = all_cand_details[best_cand]
    best_export_csv = EVAL_DIR / f"{best_cand}_all_35_treatments_yield.csv"
    best_details.to_csv(best_export_csv, index=False)
    print(f"Best Candidate ({best_cand}) full 35-treatment details saved to:\n  {best_export_csv}")

if __name__ == "__main__":
    evaluate_all()
