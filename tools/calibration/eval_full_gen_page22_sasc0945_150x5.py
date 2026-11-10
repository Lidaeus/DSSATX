#!/usr/bin/env python3
"""Evaluate 150x5 SASC_RATIO=0.945 & PAGE=22 calibration candidates across all 35 treatments:
1. Calibration set (8 runs, DSSBatch_calib.v48)
2. Validation set (15 runs, DSSBatch_valid.v48)
3. 25FA Independent test set (12 runs, xxql2502_v20260917_refresh/DSSBatch.v48)
4. Water-Nitrogen response gradients (26SP W1, 26SP W2, 26SP W3, 25SP W1, 25SP W3)
5. Comprehensive metrics (RMSE, NRMSE%, d-index, R2) for Fresh Yield, LAID, LWAD, SWAD
6. Direct side-by-side comparison against historical benchmarks:
   - baseline_sasc0925_real13
   - baseline_sasc0925_200x8_real72
   - baseline_sasc0925_200x8_real23
7. Selects and ranks top candidates by Balanced Score
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
from src.reporting.analyze_results import deterministic_process_compare

RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / "full_gen_page22_sasc0945_150x5_20260918"
FROZEN_BOUNDS_CSV = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_full_gen_page22_sasc0945_20260918.csv"
CASE_PREFIX = "full_gen_p22_s0945_150x5"

CALIB_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_calib.v48"
VALID_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_valid.v48"
BATCH_25FA = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_v20260917_refresh" / "DSSBatch.v48"
BUNDLE_25FA = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_v20260917_refresh"

BENCHMARK_150X5_REAL13 = PROJECT_ROOT / "workspace" / "runs" / "full_gen_page22_sasc0925_150x5_20260918" / "candidate_iter5_real13_params.csv"
BENCHMARK_200X8_REAL72 = PROJECT_ROOT / "workspace" / "runs" / "full_gen_page22_sasc0925_scale200x8_20260918" / "candidate_iter8_real72_params.csv"
BENCHMARK_200X8_REAL23 = PROJECT_ROOT / "workspace" / "runs" / "full_gen_page22_sasc0925_scale200x8_20260918" / "candidate_iter8_real23_params.csv"

# Metadata for all 35 treatments
TMT_META = {
    # 25SP (XXQL2501)
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
    # 26SP (XXQL2601)
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


def build_candidate_param_csv(real_id: str, df_par: pd.DataFrame, frozen_bounds_path: Path, out_path: Path):
    sub = df_par[df_par["real_name"].astype(str) == str(real_id)]
    if sub.empty:
        raise ValueError(f"Realization {real_id} not found")
    row_dict = {col.lower(): sub.iloc[0][col] for col in df_par.columns if col != "real_name"}

    fb_df = pd.read_csv(frozen_bounds_path)
    items = []
    seen = set()

    for _, r in fb_df.iterrows():
        pname = str(r["name"]).strip()
        pname_lower = pname.lower()
        if pname_lower in row_dict:
            val = row_dict[pname_lower]
        else:
            val = float(r["init"])
        items.append({"name": pname, "value": val})
        seen.add(pname_lower)

    for k, v in row_dict.items():
        if k not in seen:
            items.append({"name": k.upper(), "value": v})

    df_out = pd.DataFrame(items)
    df_out.to_csv(out_path, index=False)
    return df_out


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
        raise RuntimeError(f"DSSAT execution failed in {out_dir}")
    return evaluate_run(batch_path, out_dir)


def calc_stats_clean(obs, sim):
    mask = ~np.isnan(obs) & ~np.isnan(sim) & (obs >= 0)
    o = np.array(obs)[mask]
    s = np.array(sim)[mask]
    if len(o) < 2:
        return np.nan, np.nan, np.nan, np.nan, np.nan
    rmse = np.sqrt(np.mean((s - o)**2))
    nrmse = rmse / np.mean(o) * 100.0 if np.mean(o) > 0 else np.nan
    d_denom = np.sum((np.abs(s - np.mean(o)) + np.abs(o - np.mean(o)))**2)
    d = 1.0 - (np.sum((s - o)**2) / d_denom) if d_denom > 0 else np.nan
    r = np.corrcoef(o, s)[0, 1] if np.std(o) > 1e-6 and np.std(s) > 1e-6 else np.nan
    r2 = r**2 if not np.isnan(r) else np.nan
    bias = np.mean(s - o)
    return len(o), np.mean(o), np.mean(s), rmse, nrmse, d, r2, bias


def evaluate_single_candidate(cand_tag: str, param_csv_path: Path, phi_val: float):
    print(f"\n================ Evaluating Candidate {cand_tag} (Phi={phi_val:.2f}) ================")
    p_csv = param_csv_path

    # 1. Calibration batch (8 runs)
    calib_dir = RUN_DIR / f"cand_{cand_tag}_calib"
    df_h_c, df_eval_c = run_batch(CALIB_BATCH, p_csv, calib_dir)
    rmse_c, nrmse_c, d_c, r2_c = calc_metrics(df_h_c["OBS_FRESH_CUM"], df_h_c["SIM_FRESH_CUM"])

    # 2. Validation batch (15 runs)
    valid_dir = RUN_DIR / f"cand_{cand_tag}_valid"
    df_h_v, df_eval_v = run_batch(VALID_BATCH, p_csv, valid_dir)
    rmse_v, nrmse_v, d_v, r2_v = calc_metrics(df_h_v["OBS_FRESH_CUM"], df_h_v["SIM_FRESH_CUM"])

    # 3. Two Spring Pooled (23 runs: 8 calib + 15 valid)
    df_h_sp = pd.concat([df_h_c, df_h_v], ignore_index=True)
    rmse_sp, nrmse_sp, d_sp, r2_sp = calc_metrics(df_h_sp["OBS_FRESH_CUM"], df_h_sp["SIM_FRESH_CUM"])

    # 4. 25FA Independent generalization (12 runs)
    fa_dir = RUN_DIR / f"cand_{cand_tag}_25fa"
    df_h_fa, df_eval_fa = run_batch(BATCH_25FA, p_csv, fa_dir, input_dir=BUNDLE_25FA)
    rmse_fa, nrmse_fa, d_fa, r2_fa = calc_metrics(df_h_fa["OBS_FRESH_CUM"], df_h_fa["SIM_FRESH_CUM"])

    # 5. Grand Pooled (All 35 runs)
    df_h_all = pd.concat([df_h_sp, df_h_fa], ignore_index=True)
    rmse_all, nrmse_all, d_all, r2_all = calc_metrics(df_h_all["OBS_FRESH_CUM"], df_h_all["SIM_FRESH_CUM"])

    df_all_tagged = pd.concat([
        df_h_c.assign(batch="Calibration"),
        df_h_v.assign(batch="Validation"),
        df_h_fa.assign(batch="Independent_25FA"),
    ], ignore_index=True)

    term_records = []
    for (excode, tn), group in df_all_tagged.groupby(["EXCODE", "TN"]):
        last_row = group.sort_values("DATE").iloc[-1]
        obs_term = float(last_row["OBS_FRESH_CUM"])
        sim_term = float(last_row["SIM_FRESH_CUM"])
        err = sim_term - obs_term
        rel_err = (err / obs_term * 100.0) if obs_term > 0 else 0.0

        rmse_t, nrmse_t, d_t, r2_t = calc_metrics(group["OBS_FRESH_CUM"], group["SIM_FRESH_CUM"])
        meta = TMT_META.get((excode, tn), {"season": excode[:4], "water": "Unknown", "nitro": "Unknown", "label": f"TN{tn}"})
        term_records.append({
            "candidate": cand_tag,
            "season": meta["season"],
            "excode": excode,
            "treatment": tn,
            "label": meta["label"],
            "water": meta["water"],
            "nitro": meta["nitro"],
            "batch": last_row["batch"],
            "n_harvests": len(group),
            "obs_terminal_kg_ha": obs_term,
            "sim_terminal_kg_ha": sim_term,
            "bias_kg_ha": err,
            "bias_pct": rel_err,
            "dyn_rmse": rmse_t,
            "dyn_nrmse_pct": nrmse_t,
            "dyn_d_index": d_t,
            "dyn_r2": r2_t,
        })
    df_term = pd.DataFrame(term_records)

    def get_term_sim(season_id, water_lvl, nitro_lvl):
        sub = df_term[(df_term["season"] == season_id) & (df_term["water"] == water_lvl) & (df_term["nitro"] == nitro_lvl)]
        return float(sub["sim_terminal_kg_ha"].iloc[0]) if len(sub) > 0 else np.nan

    def get_term_obs(season_id, water_lvl, nitro_lvl):
        sub = df_term[(df_term["season"] == season_id) & (df_term["water"] == water_lvl) & (df_term["nitro"] == nitro_lvl)]
        return float(sub["obs_terminal_kg_ha"].iloc[0]) if len(sub) > 0 else np.nan

    # Water-nitrogen responses
    w1_n3_26 = get_term_sim("26SP", "W1", "N3")
    w1_n0_26 = get_term_sim("26SP", "W1", "N0")
    delta_w1_26 = (w1_n3_26 - w1_n0_26) / 1000.0

    w2_n3_26 = get_term_sim("26SP", "W2", "N3")
    w2_n0_26 = get_term_sim("26SP", "W2", "N0")
    delta_w2_26 = (w2_n3_26 - w2_n0_26) / 1000.0

    w3_n3_26 = get_term_sim("26SP", "W3", "N3")
    w3_n0_26 = get_term_sim("26SP", "W3", "N0")
    delta_w3_26 = (w3_n3_26 - w3_n0_26) / 1000.0

    w1_n3_25 = get_term_sim("25SP", "W1", "N3")
    w1_n0_25 = get_term_sim("25SP", "W1", "N0")
    delta_w1_25 = (w1_n3_25 - w1_n0_25) / 1000.0

    w3_n3_25 = get_term_sim("25SP", "W3", "N3")
    w3_n0_25 = get_term_sim("25SP", "W3", "N0")
    delta_w3_25 = (w3_n3_25 - w3_n0_25) / 1000.0
    obs_delta_w3_25 = (get_term_obs("25SP", "W3", "N3") - get_term_obs("25SP", "W3", "N0")) / 1000.0
    w3_fit_pct = (delta_w3_25 / obs_delta_w3_25 * 100.0) if obs_delta_w3_25 > 0 else 0.0

    # Process metrics (LAID, LWAD, SWAD) from calib_dir
    csv_25 = deterministic_process_compare("25SP", str(CALIB_BATCH), var_names=["LAID", "LWAD", "SWAD"], run_dir=str(calib_dir))
    csv_26 = deterministic_process_compare("26SP", str(CALIB_BATCH), var_names=["LAID", "LWAD", "SWAD"], run_dir=str(calib_dir))
    df_p25 = pd.read_csv(csv_25)
    df_p26 = pd.read_csv(csv_26)

    # 25SP organ metrics (RUN 1..4: TN 2, 5, 10, 13)
    p25_sub = df_p25[df_p25["RUN"] <= 4]
    p26_sub = df_p26[df_p26["RUN"] >= 5]

    _, _, _, _, swad_nrmse_25, swad_d_25, swad_r2_25, swad_bias_25 = calc_stats_clean(p25_sub["OBS_SWAD"], p25_sub["SIM_SWAD"])
    _, _, _, _, lwad_nrmse_25, lwad_d_25, lwad_r2_25, lwad_bias_25 = calc_stats_clean(p25_sub["OBS_LWAD"], p25_sub["SIM_LWAD"])
    _, _, _, _, laid_nrmse_25, laid_d_25, laid_r2_25, laid_bias_25 = calc_stats_clean(p25_sub["OBS_LAID"], p25_sub["SIM_LAID"])

    _, _, _, _, swad_nrmse_26, swad_d_26, swad_r2_26, swad_bias_26 = calc_stats_clean(p26_sub["OBS_SWAD"], p26_sub["SIM_SWAD"])
    _, _, _, _, lwad_nrmse_26, lwad_d_26, lwad_r2_26, lwad_bias_26 = calc_stats_clean(p26_sub["OBS_LWAD"], p26_sub["SIM_LWAD"])
    _, _, _, _, laid_nrmse_26, laid_d_26, laid_r2_26, laid_bias_26 = calc_stats_clean(p26_sub["OBS_LAID"], p26_sub["SIM_LAID"])

    # W3N0 terminal LAI (checking senescence stability, TN=5 in 25SP)
    w3n0_25_rows = p25_sub[p25_sub["TN"] == 5]
    w3n0_final_lai_25 = float(w3n0_25_rows.sort_values("DATE").iloc[-1]["SIM_LAID"]) if not w3n0_25_rows.empty else np.nan

    # Balanced penalty score
    resp_bonus = 0.0
    if delta_w1_25 > 0:
        resp_bonus += min(delta_w1_25, 10.0) * 0.3
    if delta_w1_26 > 0:
        resp_bonus += min(delta_w1_26, 12.0) * 0.3
    if delta_w2_26 > 0:
        resp_bonus += min(delta_w2_26, 15.0) * 0.2
    if delta_w3_26 > 0:
        resp_bonus += min(delta_w3_26, 15.0) * 0.2
    w3_penalty = abs(w3_fit_pct - 100.0) * 0.05
    score = nrmse_sp + w3_penalty - resp_bonus

    summary_entry = {
        "candidate": cand_tag,
        "phi": phi_val,
        "calib_nrmse": nrmse_c,
        "calib_d": d_c,
        "valid_nrmse": nrmse_v,
        "valid_d": d_v,
        "spring_pooled_nrmse": nrmse_sp,
        "spring_pooled_d": d_sp,
        "spring_pooled_rmse": rmse_sp,
        "spring_pooled_r2": r2_sp,
        "25fa_nrmse": nrmse_fa,
        "25fa_d": d_fa,
        "all35_nrmse": nrmse_all,
        "all35_d": d_all,
        "delta_25W3_ton": delta_w3_25,
        "match_25W3_pct": w3_fit_pct,
        "delta_25W1_ton": delta_w1_25,
        "delta_26W1_ton": delta_w1_26,
        "delta_26W2_ton": delta_w2_26,
        "delta_26W3_ton": delta_w3_26,
        "swad_d_26": swad_d_26,
        "swad_r2_26": swad_r2_26,
        "lwad_bias_26": lwad_bias_26,
        "w3n0_final_lai_25": w3n0_final_lai_25,
        "balanced_score": score,
    }

    print(f"[{cand_tag}] 2-Spring NRMSE: {nrmse_sp:.2f}%, d: {d_sp:.4f} | 25FA: {nrmse_fa:.2f}% | 25W3: {delta_w3_25:.2f}t ({w3_fit_pct:.1f}%) | 26W1/W2/W3: {delta_w1_26:+.2f}/{delta_w2_26:+.2f}/{delta_w3_26:+.2f}t | Score: {score:.3f}")
    return summary_entry, df_term


def main():
    phi_csv = RUN_DIR / f"{CASE_PREFIX}.phi.actual.csv"
    if not phi_csv.exists():
        print(f"Waiting for {phi_csv}...")
        return 1

    df_phi = pd.read_csv(phi_csv)
    print("Phi table loaded. Total iterations:", len(df_phi))
    last_iter = len(df_phi) - 1
    
    par_csv = RUN_DIR / f"{CASE_PREFIX}.{last_iter}.par.csv"
    if not par_csv.exists():
        par_csv = RUN_DIR / f"{CASE_PREFIX}.par.csv"
    df_par = pd.read_csv(par_csv)
    valid_reals = set(df_par["real_name"].astype(str))
    cols = [c for c in df_phi.columns if str(c) in valid_reals and str(c).lower() != "base"]
    phi_series = df_phi.iloc[last_iter][cols].astype(float)
    sorted_reals = phi_series.sort_values()

    top_candidates = []
    print(f"\n--- Top Candidates at Iteration {last_iter} ---")
    for real, phi_v in sorted_reals.head(10).items():
        p_csv = RUN_DIR / f"candidate_iter{last_iter}_real{real}_params.csv"
        build_candidate_param_csv(real, df_par, FROZEN_BOUNDS_CSV, p_csv)
        top_candidates.append((f"iter{last_iter}_real{real}", p_csv, phi_v))
        print(f"  iter{last_iter}_real{real}: Phi = {phi_v:.2f}")

    # Add historical benchmarks
    if BENCHMARK_150X5_REAL13.exists():
        top_candidates.append(("baseline_sasc0925_real13", BENCHMARK_150X5_REAL13, 597.58))
    if BENCHMARK_200X8_REAL72.exists():
        top_candidates.append(("baseline_sasc0925_real72", BENCHMARK_200X8_REAL72, 609.99))
    if BENCHMARK_200X8_REAL23.exists():
        top_candidates.append(("baseline_sasc0925_real23", BENCHMARK_200X8_REAL23, 556.00))

    summaries = []
    all_term_dfs = []

    for cand_tag, param_csv_path, phi_val in top_candidates:
        s_entry, df_term = evaluate_single_candidate(cand_tag, param_csv_path, phi_val)
        summaries.append(s_entry)
        all_term_dfs.append(df_term)

    df_summary = pd.DataFrame(summaries)
    df_all_terms = pd.concat(all_term_dfs, ignore_index=True)

    summary_out = RUN_DIR / "candidates_35tmt_evaluation_summary.csv"
    terms_out = RUN_DIR / "candidates_treatments_detail.csv"
    df_summary.to_csv(summary_out, index=False)
    df_all_terms.to_csv(terms_out, index=False)

    df_ranked = df_summary.sort_values("balanced_score")
    df_ranked.to_csv(RUN_DIR / "candidates_ranked_balanced.csv", index=False)

    print("\n================ FINAL RANKING OF CANDIDATES (Balanced Score) ================")
    print(df_ranked[["candidate", "phi", "spring_pooled_nrmse", "spring_pooled_d", "25fa_nrmse", "delta_25W3_ton", "match_25W3_pct", "delta_25W1_ton", "delta_26W1_ton", "delta_26W2_ton", "delta_26W3_ton", "swad_d_26", "balanced_score"]].to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
