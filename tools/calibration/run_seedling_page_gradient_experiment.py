#!/usr/bin/env python3
"""Seedling Transplant Age (PAGE) Gradient Experiment for CROPGRO-Eggplant.

Investigate the impact of seedling age (PAGE in [10, 25] days) on model performance:
- Evaluates across 35 treatments (Calib 8, Valid 15, 25FA 12).
- Assesses metrics (NRMSE, d-index, R2) and water-nitrogen response fidelity.
- Conducts gradients for:
    Base 1: candidate_iter7_real11 (Balanced Champion, SASC=0.9210)
    Base 2: candidate_iter7_real0 (Statistical Precision Champion, SASC=0.9428)
Gradient levels: [10, 13, 16, 19, 22, 24, 25] days.
"""

import os
import sys
import shutil
import subprocess
import time
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.run_dssat import prepare_run_directory
from tools.eval_full_gen98 import evaluate_run, calc_metrics

RUN_BASE = PROJECT_ROOT / "workspace" / "runs" / "full_gen_century_sasc094_scale200x7_20260918"
OUT_DIR = PROJECT_ROOT / "workspace" / "runs" / "experiment_seedling_page_20260918"

CALIB_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_calib.v48"
VALID_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_valid.v48"
BATCH_25FA = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_v20260917_refresh" / "DSSBatch.v48"
BUNDLE_25FA = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_v20260917_refresh"

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


def evaluate_page_level(base_name: str, base_param_path: Path, page_days: int):
    run_tag = f"{base_name}_PAGE_{page_days:02d}d"
    work_dir = OUT_DIR / run_tag
    work_dir.mkdir(parents=True, exist_ok=True)

    # Prepare customized parameter CSV with modified PAGE
    df_p = pd.read_csv(base_param_path)
    # Update PAGE_25SP, PAGE_26SP, and generic PAGE
    p_dict = dict(zip(df_p["name"].str.upper(), df_p["value"]))
    p_dict["PAGE_25SP"] = float(page_days)
    p_dict["PAGE_26SP"] = float(page_days)
    p_dict["PAGE"] = float(page_days)
    
    # Write updated params
    out_p_csv = work_dir / "params.csv"
    items = [{"name": k, "value": v} for k, v in p_dict.items()]
    pd.DataFrame(items).to_csv(out_p_csv, index=False)

    # 1. Calibration (8 runs)
    calib_dir = work_dir / "calib"
    df_h_c, _ = run_batch(CALIB_BATCH, out_p_csv, calib_dir)
    rmse_c, nrmse_c, d_c, r2_c = calc_metrics(df_h_c["OBS_FRESH_CUM"], df_h_c["SIM_FRESH_CUM"])

    # 2. Validation (15 runs)
    valid_dir = work_dir / "valid"
    df_h_v, _ = run_batch(VALID_BATCH, out_p_csv, valid_dir)
    rmse_v, nrmse_v, d_v, r2_v = calc_metrics(df_h_v["OBS_FRESH_CUM"], df_h_v["SIM_FRESH_CUM"])

    # 3. Two Spring Pooled (23 runs)
    df_h_sp = pd.concat([df_h_c, df_h_v], ignore_index=True)
    rmse_sp, nrmse_sp, d_sp, r2_sp = calc_metrics(df_h_sp["OBS_FRESH_CUM"], df_h_sp["SIM_FRESH_CUM"])

    # 4. 25FA Independent generalization (12 runs)
    fa_dir = work_dir / "25fa"
    df_h_fa, _ = run_batch(BATCH_25FA, out_p_csv, fa_dir, input_dir=BUNDLE_25FA)
    rmse_fa, nrmse_fa, d_fa, r2_fa = calc_metrics(df_h_fa["OBS_FRESH_CUM"], df_h_fa["SIM_FRESH_CUM"])

    # 5. Grand Pooled (All 35 runs)
    df_h_all = pd.concat([df_h_sp, df_h_fa], ignore_index=True)
    rmse_all, nrmse_all, d_all, r2_all = calc_metrics(df_h_all["OBS_FRESH_CUM"], df_h_all["SIM_FRESH_CUM"])

    # Merge tagged data
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
            "run_tag": run_tag,
            "base_name": base_name,
            "page_days": page_days,
            "season": meta["season"],
            "excode": excode,
            "treatment": tn,
            "water": meta["water"],
            "nitro": meta["nitro"],
            "batch": last_row["batch"],
            "obs_terminal_kg_ha": obs_term,
            "sim_terminal_kg_ha": sim_term,
            "bias_kg_ha": err,
            "bias_pct": rel_err,
            "dyn_nrmse_pct": nrmse_t,
            "dyn_d_index": d_t,
        })
    df_term = pd.DataFrame(term_records)

    def get_term_sim(season_id, water_lvl, nitro_lvl):
        sub = df_term[(df_term["season"] == season_id) & (df_term["water"] == water_lvl) & (df_term["nitro"] == nitro_lvl)]
        return float(sub.iloc[0]["sim_terminal_kg_ha"]) / 1000.0 if not sub.empty else np.nan

    w2_26_sim = get_term_sim("26SP", "W2", "N3") - get_term_sim("26SP", "W2", "N0")
    w1_26_sim = get_term_sim("26SP", "W1", "N3") - get_term_sim("26SP", "W1", "N0")
    w3_26_sim = get_term_sim("26SP", "W3", "N3") - get_term_sim("26SP", "W3", "N0")
    w3_25_sim = get_term_sim("25SP", "W3", "N3") - get_term_sim("25SP", "W3", "N0")
    w1_25_sim = get_term_sim("25SP", "W1", "N3") - get_term_sim("25SP", "W1", "N0")

    # Clean intermediate batch dirs to save disk space
    shutil.rmtree(calib_dir, ignore_errors=True)
    shutil.rmtree(valid_dir, ignore_errors=True)
    shutil.rmtree(fa_dir, ignore_errors=True)

    summary_row = {
        "run_tag": run_tag,
        "base_name": base_name,
        "page_days": page_days,
        "nrmse_calib": nrmse_c,
        "nrmse_valid": nrmse_v,
        "nrmse_spring": nrmse_sp,
        "rmse_spring": rmse_sp,
        "d_index_spring": d_sp,
        "r2_spring": r2_sp,
        "nrmse_25fa": nrmse_fa,
        "nrmse_all35": nrmse_all,
        "rmse_all35": rmse_all,
        "d_index_all35": d_all,
        "26SP_W1_gap_t_ha": w1_26_sim,  # field obs: +16.50
        "26SP_W2_gap_t_ha": w2_26_sim,  # field obs: +9.50
        "26SP_W3_gap_t_ha": w3_26_sim,  # field obs: +16.00
        "25SP_W1_gap_t_ha": w1_25_sim,  # field obs: +11.60
        "25SP_W3_gap_t_ha": w3_25_sim,  # field obs: +4.10
    }
    return summary_row, df_term


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page_levels = [10, 13, 16, 19, 22, 24, 25]

    bases = [
        ("iter7_real11", RUN_BASE / "candidate_iter7_real11_params.csv"),
        ("iter7_real0", RUN_BASE / "candidate_iter7_real0_params.csv"),
    ]

    all_summaries = []
    all_details = []

    print(f"Starting Seedling PAGE Gradient Experiment across levels: {page_levels}...")
    t_start = time.time()

    for base_name, base_csv in bases:
        print(f"\n================ Base: {base_name} ================")
        for page in page_levels:
            t0 = time.time()
            print(f"Evaluating PAGE={page:02d} days...", end="", flush=True)
            s_row, df_t = evaluate_page_level(base_name, base_csv, page)
            all_summaries.append(s_row)
            all_details.append(df_t)
            elapsed = time.time() - t0
            print(f" Done ({elapsed:.1f}s) | Spring NRMSE: {s_row['nrmse_spring']:.2f}%, All-35: {s_row['nrmse_all35']:.2f}% | 26W1_gap: {s_row['26SP_W1_gap_t_ha']:+.2f}t, 25W1_gap: {s_row['25SP_W1_gap_t_ha']:+.2f}t, 25W3_gap: {s_row['25SP_W3_gap_t_ha']:+.2f}t")

    total_elapsed = time.time() - t_start
    print(f"\nCompleted in {total_elapsed:.1f}s.")

    df_sum = pd.DataFrame(all_summaries)
    df_sum.to_csv(OUT_DIR / "page_gradient_summary.csv", index=False)

    df_det = pd.concat(all_details, ignore_index=True)
    df_det.to_csv(OUT_DIR / "page_gradient_treatments_detail.csv", index=False)

    print("\n================ PAGE GRADIENT RESULTS SUMMARY ================")
    cols_show = ["base_name", "page_days", "nrmse_spring", "nrmse_all35", "d_index_spring", "26SP_W1_gap_t_ha", "26SP_W2_gap_t_ha", "25SP_W1_gap_t_ha", "25SP_W3_gap_t_ha"]
    print(df_sum[cols_show].to_string(index=False))


if __name__ == "__main__":
    main()
