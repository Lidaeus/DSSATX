#!/usr/bin/env python3
"""Evaluate iter4_real118 and iter5_real113 with the updated 100cm SRGF bundle.

Simulates:
1. 25SP (11 treatments: 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14)
2. 26SP (12 treatments: 1..12)
3. 25FA (12 treatments: 1..12)

Extracts and reports:
- Per-treatment fitting metrics (Obs, Sim, Error, Bias%, NRMSE%)
- Summary performance by batch (Calibration 8 runs, Validation 15 runs, 25FA 12 runs, Pooled)
- Water-Nitrogen response gradients (26SP W2, 26SP W1, 25SP W3, 25SP W1)
- Comparison of SRGF 100cm vs previous SRGF 80cm
"""

import os
import sys
import shutil
import subprocess
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.run_dssat import prepare_run_directory
from tools.eval_full_gen98 import evaluate_run, calc_metrics
from src.reporting.analyze_results import _read_plantgro_vars_by_run, _read_evaluate_out

EVAL_DIR = PROJECT_ROOT / "workspace" / "runs" / "eval_srgf100_20260917"
CALIB_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_calib.v48"
VALID_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_valid.v48"
BATCH_25FA = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_v20260917_refresh" / "DSSBatch.v48"
BUNDLE_25FA = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_v20260917_refresh"

PARAM_DIR = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_98pct_v8_refreshed_20260917"
PARAMS_R118 = PARAM_DIR / "candidate_iter4_real118_params.csv"
PARAMS_R113 = PARAM_DIR / "candidate_iter5_real113_params.csv"

# Treatment metadata mappings
TMT_META = {
    # 25SP (XXQL2501)
    ("XXQL2501", 2): {"season": "25SP", "water": "W3", "nitro": "N3", "label": "W3N3 (高水高氮)"},
    ("XXQL2501", 3): {"season": "25SP", "water": "W3", "nitro": "N2", "label": "W3N2 (高水中氮)"},
    ("XXQL2501", 4): {"season": "25SP", "water": "W3", "nitro": "N1", "label": "W3N1 (高水低氮)"},
    ("XXQL2501", 5): {"season": "25SP", "water": "W3", "nitro": "N0", "label": "W3N0 (高水零氮)"},
    ("XXQL2501", 6): {"season": "25SP", "water": "W2", "nitro": "N3", "label": "W2N3 (中水中氮)"},
    ("XXQL2501", 9): {"season": "25SP", "water": "W2", "nitro": "N0", "label": "W2N0 (中水零氮)"},
    ("XXQL2501", 10): {"season": "25SP", "water": "W1", "nitro": "N3", "label": "W1N3 (低水高氮)"},
    ("XXQL2501", 11): {"season": "25SP", "water": "W1", "nitro": "N2", "label": "W1N2 (低水中氮)"},
    ("XXQL2501", 12): {"season": "25SP", "water": "W1", "nitro": "N1", "label": "W1N1 (低水低氮)"},
    ("XXQL2501", 13): {"season": "25SP", "water": "W1", "nitro": "N0", "label": "W1N0 (低水零氮)"},
    ("XXQL2501", 14): {"season": "25SP", "water": "CK", "nitro": "N2", "label": "CKN2 (对照)"},
    # 26SP (XXQL2601)
    ("XXQL2601", 1): {"season": "26SP", "water": "W3", "nitro": "N3", "label": "W3N3 (充分高氮)"},
    ("XXQL2601", 2): {"season": "26SP", "water": "W2", "nitro": "N3", "label": "W2N3 (适水高氮)"},
    ("XXQL2601", 3): {"season": "26SP", "water": "W1", "nitro": "N3", "label": "W1N3 (干旱高氮)"},
    ("XXQL2601", 4): {"season": "26SP", "water": "W3", "nitro": "N2", "label": "W3N2 (充分中氮)"},
    ("XXQL2601", 5): {"season": "26SP", "water": "W2", "nitro": "N2", "label": "W2N2 (适水中氮)"},
    ("XXQL2601", 6): {"season": "26SP", "water": "W1", "nitro": "N2", "label": "W1N2 (干旱中氮)"},
    ("XXQL2601", 7): {"season": "26SP", "water": "W3", "nitro": "N1", "label": "W3N1 (充分低氮)"},
    ("XXQL2601", 8): {"season": "26SP", "water": "W2", "nitro": "N1", "label": "W2N1 (适水低氮)"},
    ("XXQL2601", 9): {"season": "26SP", "water": "W3", "nitro": "N0", "label": "W3N0 (充分零氮)"},
    ("XXQL2601", 10): {"season": "26SP", "water": "W1", "nitro": "N1", "label": "W1N1 (干旱低氮)"},
    ("XXQL2601", 11): {"season": "26SP", "water": "W2", "nitro": "N0", "label": "W2N0 (适水零氮)"},
    ("XXQL2601", 12): {"season": "26SP", "water": "W1", "nitro": "N0", "label": "W1N0 (干旱零氮)"},
    # 25FA (XXQL2502)
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


def run_batch(batch_path: Path, param_csv: Path, out_dir: Path, input_dir: Path = None):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    prep_args = ["--batch", str(batch_path)]
    if input_dir:
        prep_args.extend(["--input-dir", str(input_dir)])
    batch_dest = prepare_run_directory(out_dir, prep_args)
    cmd = [
        sys.executable,
        "-m",
        "src.dssat.run_dssat",
        "--param-csv",
        str(param_csv.resolve()),
        "--batch",
        batch_dest.name,
        "--harvest-var",
        "CHPDT",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    res = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        print(f"Error running DSSAT in {out_dir}: {res.stderr[-500:]}")
        raise RuntimeError("DSSAT execution failed")
    df_h, df_eval = evaluate_run(batch_path, out_dir)
    return df_h, df_eval, out_dir


def evaluate_candidate(cand_name: str, param_csv: Path, base_dir: Path):
    print(f"\n========================================================")
    print(f"Evaluating {cand_name} with SRGF 100cm Updated Bundle")
    print(f"========================================================")
    cand_dir = base_dir / cand_name
    cand_dir.mkdir(parents=True, exist_ok=True)

    # 1. Calibration batch (8 runs)
    calib_dir = cand_dir / "calib"
    df_h_c, df_eval_c, _ = run_batch(CALIB_BATCH, param_csv, calib_dir)
    rmse_c, nrmse_c, d_c, r2_c = calc_metrics(df_h_c["OBS_FRESH_CUM"], df_h_c["SIM_FRESH_CUM"])

    # 2. Validation batch (15 runs)
    valid_dir = cand_dir / "valid"
    df_h_v, df_eval_v, _ = run_batch(VALID_BATCH, param_csv, valid_dir)
    rmse_v, nrmse_v, d_v, r2_v = calc_metrics(df_h_v["OBS_FRESH_CUM"], df_h_v["SIM_FRESH_CUM"])

    # 3. Two Spring Pooled (23 runs)
    df_h_spring = pd.concat([df_h_c, df_h_v], ignore_index=True)
    rmse_sp, nrmse_sp, d_sp, r2_sp = calc_metrics(df_h_spring["OBS_FRESH_CUM"], df_h_spring["SIM_FRESH_CUM"])

    # 4. 25FA Independent test set (12 runs)
    fa_dir = cand_dir / "25fa"
    df_h_fa, df_eval_fa, _ = run_batch(BATCH_25FA, param_csv, fa_dir, input_dir=BUNDLE_25FA)
    rmse_fa, nrmse_fa, d_fa, r2_fa = calc_metrics(df_h_fa["OBS_FRESH_CUM"], df_h_fa["SIM_FRESH_CUM"])

    # Merge all harvest evaluations
    df_all_h = pd.concat([
        df_h_c.assign(batch="Calibration"),
        df_h_v.assign(batch="Validation"),
        df_h_fa.assign(batch="Independent_25FA"),
    ], ignore_index=True)

    # Per-treatment terminal metrics
    term_records = []
    for (excode, tn), group in df_all_h.groupby(["EXCODE", "TN"]):
        # Terminal harvest is last date
        last_row = group.sort_values("DATE").iloc[-1]
        obs_term = float(last_row["OBS_FRESH_CUM"])
        sim_term = float(last_row["SIM_FRESH_CUM"])
        err = sim_term - obs_term
        rel_err = (err / obs_term * 100.0) if obs_term > 0 else 0.0

        # Dynamics metrics across all harvests for this treatment
        rmse_t, nrmse_t, d_t, r2_t = calc_metrics(group["OBS_FRESH_CUM"], group["SIM_FRESH_CUM"])

        meta = TMT_META.get((excode, tn), {"season": excode[:4], "water": "Unknown", "nitro": "Unknown", "label": f"TN{tn}"})
        term_records.append({
            "candidate": cand_name,
            "season": meta["season"],
            "excode": excode,
            "treatment": tn,
            "label": meta["label"],
            "water": meta["water"],
            "nitro": meta["nitro"],
            "batch": last_row["batch"],
            "n_harvests": len(group),
            "obs_terminal": obs_term,
            "sim_terminal": sim_term,
            "bias_kg_ha": err,
            "bias_pct": rel_err,
            "dyn_rmse": rmse_t,
            "dyn_nrmse_pct": nrmse_t,
            "dyn_d_index": d_t,
            "dyn_r2": r2_t,
        })
    df_term = pd.DataFrame(term_records)

    # Water-Nitrogen gradient analysis
    def get_terminal_sim(season_id, water_lvl, nitro_lvl):
        sub = df_term[(df_term["season"] == season_id) & (df_term["water"] == water_lvl) & (df_term["nitro"] == nitro_lvl)]
        if not sub.empty:
            return float(sub.iloc[0]["sim_terminal"])
        return np.nan

    def get_terminal_obs(season_id, water_lvl, nitro_lvl):
        sub = df_term[(df_term["season"] == season_id) & (df_term["water"] == water_lvl) & (df_term["nitro"] == nitro_lvl)]
        if not sub.empty:
            return float(sub.iloc[0]["obs_terminal"])
        return np.nan

    wn_records = []
    # 26SP gradients
    for w in ["W3", "W2", "W1"]:
        sim_n3 = get_terminal_sim("26SP", w, "N3")
        sim_n2 = get_terminal_sim("26SP", w, "N2")
        sim_n1 = get_terminal_sim("26SP", w, "N1")
        sim_n0 = get_terminal_sim("26SP", w, "N0")
        obs_n3 = get_terminal_obs("26SP", w, "N3")
        obs_n0 = get_terminal_obs("26SP", w, "N0")
        wn_records.append({
            "season": "26SP", "water": w,
            "sim_N3": sim_n3, "sim_N2": sim_n2, "sim_N1": sim_n1, "sim_N0": sim_n0,
            "sim_N3_N0_gap": sim_n3 - sim_n0,
            "obs_N3_N0_gap": obs_n3 - obs_n0,
        })
    # 25SP gradients
    for w in ["W3", "W1"]:
        sim_n3 = get_terminal_sim("25SP", w, "N3")
        sim_n2 = get_terminal_sim("25SP", w, "N2")
        sim_n1 = get_terminal_sim("25SP", w, "N1")
        sim_n0 = get_terminal_sim("25SP", w, "N0")
        obs_n3 = get_terminal_obs("25SP", w, "N3")
        obs_n0 = get_terminal_obs("25SP", w, "N0")
        wn_records.append({
            "season": "25SP", "water": w,
            "sim_N3": sim_n3, "sim_N2": sim_n2, "sim_N1": sim_n1, "sim_N0": sim_n0,
            "sim_N3_N0_gap": sim_n3 - sim_n0,
            "obs_N3_N0_gap": obs_n3 - obs_n0,
        })
    df_wn = pd.DataFrame(wn_records)

    summary_stats = {
        "candidate": cand_name,
        "calib_nrmse_pct": nrmse_c,
        "calib_d_index": d_c,
        "calib_r2": r2_c,
        "valid_nrmse_pct": nrmse_v,
        "valid_d_index": d_v,
        "valid_r2": r2_v,
        "spring_pooled_nrmse_pct": nrmse_sp,
        "spring_pooled_d_index": d_sp,
        "spring_pooled_r2": r2_sp,
        "25fa_nrmse_pct": nrmse_fa,
        "25fa_d_index": d_fa,
        "25fa_r2": r2_fa,
        "26SP_W2_sim_gap": df_wn.loc[(df_wn["season"]=="26SP") & (df_wn["water"]=="W2"), "sim_N3_N0_gap"].values[0],
        "26SP_W1_sim_gap": df_wn.loc[(df_wn["season"]=="26SP") & (df_wn["water"]=="W1"), "sim_N3_N0_gap"].values[0],
        "25SP_W3_sim_gap": df_wn.loc[(df_wn["season"]=="25SP") & (df_wn["water"]=="W3"), "sim_N3_N0_gap"].values[0],
        "25SP_W1_sim_gap": df_wn.loc[(df_wn["season"]=="25SP") & (df_wn["water"]=="W1"), "sim_N3_N0_gap"].values[0],
    }

    return summary_stats, df_term, df_wn, df_all_h


def main():
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    cands = [
        ("iter4_real118", PARAMS_R118),
        ("iter5_real113", PARAMS_R113),
    ]

    all_summaries = []
    all_terms = []
    all_wns = []

    for name, p_csv in cands:
        s_stat, df_t, df_w, df_h = evaluate_candidate(name, p_csv, EVAL_DIR)
        all_summaries.append(s_stat)
        all_terms.append(df_t)
        all_wns.append(df_w.assign(candidate=name))
        
        # Save individual candidate tables
        df_t.to_csv(EVAL_DIR / f"{name}_treatment_metrics.csv", index=False)
        df_w.to_csv(EVAL_DIR / f"{name}_water_nitrogen_response.csv", index=False)
        df_h.to_csv(EVAL_DIR / f"{name}_harvest_evaluations.csv", index=False)

    df_sum = pd.DataFrame(all_summaries)
    df_sum.to_csv(EVAL_DIR / "candidates_summary_comparison.csv", index=False)
    
    df_all_terms = pd.concat(all_terms, ignore_index=True)
    df_all_terms.to_csv(EVAL_DIR / "all_treatments_metrics_comparison.csv", index=False)

    print("\n" + "=" * 80)
    print("SUMMARY COMPARISON (100cm SRGF BUNDLE)")
    print("=" * 80)
    print(df_sum.to_string(index=False))

    print("\n" + "=" * 80)
    print("WATER-NITROGEN GAPS COMPARISON (N3 - N0, kg/ha)")
    print("=" * 80)
    for name in ["iter4_real118", "iter5_real113"]:
        sub_wn = pd.concat(all_wns)[pd.concat(all_wns)["candidate"] == name]
        print(f"\n--- {name} ---")
        print(sub_wn[["season", "water", "sim_N3", "sim_N2", "sim_N1", "sim_N0", "sim_N3_N0_gap", "obs_N3_N0_gap"]].to_string(index=False))


if __name__ == "__main__":
    main()
