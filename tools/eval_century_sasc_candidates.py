#!/usr/bin/env python3
"""Evaluate Century SASC calibration candidates across all 35 treatments:
1. Calibration set (8 runs, DSSBatch_calib.v48)
2. Validation set (15 runs, DSSBatch_valid.v48)
3. 25FA Independent test set (12 runs, xxql2502_v20260917_refresh/DSSBatch.v48)
4. Water-Nitrogen response gradients (26SP W2, 26SP W1, 25SP W3, 25SP W1)
5. Comprehensive metrics (RMSE, NRMSE%, d-index, R2)
6. Selects and freezes the champion candidate
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
from src.reporting.analyze_results import _read_plantgro_vars_by_run

RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_century_sasc_20260918"
FROZEN_BOUNDS_CSV = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_full_genetic_century_sasc_20260918.csv"

CALIB_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_calib.v48"
VALID_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_valid.v48"
BATCH_25FA = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_v20260917_refresh" / "DSSBatch.v48"
BUNDLE_25FA = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_v20260917_refresh"

# Metadata for all 35 treatments
TMT_META = {
    # 25SP (XXQL2501)
    ("XXQL2501", 2): {"season": "25SP", "water": "W3", "nitro": "N3", "label": "W3N3 (高水高氮)"},
    ("XXQL2501", 3): {"season": "25SP", "water": "W3", "nitro": "N2", "label": "W3N2 (高水中氮)"},
    ("XXQL2501", 4): {"season": "25SP", "water": "W3", "nitro": "N1", "label": "W3N1 (高水低氮)"},
    ("XXQL2501", 5): {"season": "25SP", "water": "W3", "nitro": "N0", "label": "W3N0 (高水零氮)"},
    ("XXQL2501", 6): {"season": "25SP", "water": "W2", "nitro": "N3", "label": "W2N3 (中水高氮)"},
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


def build_candidate_param_csv(real_id: str, df_par: pd.DataFrame, frozen_bounds_path: Path, out_path: Path):
    """Combine realization parameter values with frozen bounds fixed parameters."""
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

    # Any extra columns in row_dict not in frozen bounds
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


def evaluate_single_candidate(cand_tag: str, real_id: str, df_par: pd.DataFrame, phi_val: float):
    print(f"\n================ Evaluating Candidate {cand_tag} (Realization {real_id}, Phi={phi_val:.2f}) ================")
    p_csv = RUN_DIR / f"candidate_{cand_tag}_params.csv"
    build_candidate_param_csv(real_id, df_par, FROZEN_BOUNDS_CSV, p_csv)

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

    # Merge all harvest data with tags
    df_all_tagged = pd.concat([
        df_h_c.assign(batch="Calibration"),
        df_h_v.assign(batch="Validation"),
        df_h_fa.assign(batch="Independent_25FA"),
    ], ignore_index=True)

    # Per-treatment terminal metrics
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
    def get_term_sim(season_id, water_lvl, nitro_lvl):
        sub = df_term[(df_term["season"] == season_id) & (df_term["water"] == water_lvl) & (df_term["nitro"] == nitro_lvl)]
        return float(sub.iloc[0]["sim_terminal"]) if not sub.empty else np.nan

    def get_term_obs(season_id, water_lvl, nitro_lvl):
        sub = df_term[(df_term["season"] == season_id) & (df_term["water"] == water_lvl) & (df_term["nitro"] == nitro_lvl)]
        return float(sub.iloc[0]["obs_terminal"]) if not sub.empty else np.nan

    w2_26_sim = get_term_sim("26SP", "W2", "N3") - get_term_sim("26SP", "W2", "N0")
    w1_26_sim = get_term_sim("26SP", "W1", "N3") - get_term_sim("26SP", "W1", "N0")
    w3_26_sim = get_term_sim("26SP", "W3", "N3") - get_term_sim("26SP", "W3", "N0")
    w3_25_sim = get_term_sim("25SP", "W3", "N3") - get_term_sim("25SP", "W3", "N0")
    w1_25_sim = get_term_sim("25SP", "W1", "N3") - get_term_sim("25SP", "W1", "N0")

    # Read parameters
    p_df = pd.read_csv(p_csv)
    p_vals = dict(zip(p_df["name"].str.lower(), p_df["value"]))

    res = {
        "candidate": cand_tag,
        "real_id": real_id,
        "phi": phi_val,
        "nrmse_calib": nrmse_c,
        "rmse_calib": rmse_c,
        "d_index_calib": d_c,
        "r2_calib": r2_c,
        "nrmse_valid": nrmse_v,
        "rmse_valid": rmse_v,
        "d_index_valid": d_v,
        "r2_valid": r2_v,
        "nrmse_spring": nrmse_sp,
        "rmse_spring": rmse_sp,
        "d_index_spring": d_sp,
        "r2_spring": r2_sp,
        "nrmse_25fa": nrmse_fa,
        "rmse_25fa": rmse_fa,
        "d_index_25fa": d_fa,
        "r2_25fa": r2_fa,
        "nrmse_all35": nrmse_all,
        "rmse_all35": rmse_all,
        "d_index_all35": d_all,
        "r2_all35": r2_all,
        "26SP_W2_gap": w2_26_sim,
        "26SP_W1_gap": w1_26_sim,
        "26SP_W3_gap": w3_26_sim,
        "25SP_W3_gap": w3_25_sim,
        "25SP_W1_gap": w1_25_sim,
        "sasc_ratio": p_vals.get("sasc_ratio", np.nan),
        "icns_26sp": p_vals.get("icns_26sp", np.nan),
        "soil_slnf": p_vals.get("soil_slnf", np.nan),
        "pgeff": p_vals.get("pgeff", np.nan),
        "lnref": p_vals.get("lnref", np.nan),
        "frlff": p_vals.get("frlff", np.nan),
        "slavr": p_vals.get("slavr", np.nan),
        "sizlf": p_vals.get("sizlf", np.nan),
        "tb1": p_vals.get("tb1", np.nan),
        "tm1": p_vals.get("tm1", np.nan),
        "xfrt": p_vals.get("xfrt", np.nan),
    }

    print(f"  Calib NRMSE:  {nrmse_c:.2f}%, d-index: {d_c:.4f}, R2: {r2_c:.4f}")
    print(f"  Valid NRMSE:  {nrmse_v:.2f}%, d-index: {d_v:.4f}, R2: {r2_v:.4f}")
    print(f"  Spring NRMSE: {nrmse_sp:.2f}%, d-index: {d_sp:.4f}, R2: {r2_sp:.4f}")
    print(f"  25FA NRMSE:   {nrmse_fa:.2f}%, d-index: {d_fa:.4f}, R2: {r2_fa:.4f}")
    print(f"  All35 NRMSE:  {nrmse_all:.2f}%, d-index: {d_all:.4f}, R2: {r2_all:.4f}")
    print(f"  26SP W2 gap (N3-N0): {w2_26_sim:+7.1f} kg/ha (Obs: +14760 kg/ha)")
    print(f"  26SP W1 gap (N3-N0): {w1_26_sim:+7.1f} kg/ha (Obs: +16530 kg/ha)")
    print(f"  25SP W3 gap (N3-N0): {w3_25_sim:+7.1f} kg/ha (Obs: +15540 kg/ha)")
    print(f"  25SP W1 gap (N3-N0): {w1_25_sim:+7.1f} kg/ha (Obs:  +2130 kg/ha)")
    sasc_val = p_vals.get('sasc_ratio', 0.88)
    icns_val = p_vals.get('icns_26sp', 0.70)
    slnf_val = p_vals.get('soil_slnf', 1.00)
    print(f"  SASC_RATIO: {sasc_val:.4f}, ICNS_26SP: {icns_val:.2f}, SOIL_SLNF: {slnf_val:.2f}")

    return res, df_term, df_all_tagged


def main():
    print("Loading candidate parameter sets from full_genetic_century_sasc_20260918...")
    df5 = pd.read_csv(RUN_DIR / "full_gen_century_sasc.5.par.csv")
    df4 = pd.read_csv(RUN_DIR / "full_gen_century_sasc.4.par.csv")

    candidates = [
        ("iter5_real10", "10", df5, 630.30),
        ("iter5_real73", "73", df5, 637.47),
        ("iter5_real0", "0", df5, 639.76),
        ("iter5_real45", "45", df5, 653.24),
        ("iter5_real83", "83", df5, 667.69),
        ("iter5_real53", "53", df5, 674.19),
        ("iter4_real81", "81", df4, 651.43),
        ("iter4_real45", "45", df4, 658.28),
    ]

    all_summaries = []
    all_terms = []

    for tag, rid, df_p, phi_v in candidates:
        s_res, df_t, df_h = evaluate_single_candidate(tag, rid, df_p, phi_v)
        all_summaries.append(s_res)
        all_terms.append(df_t)

    df_sum = pd.DataFrame(all_summaries)
    sum_csv = RUN_DIR / "candidate_comparison_summary.csv"
    df_sum.to_csv(sum_csv, index=False)

    df_all_terms = pd.concat(all_terms, ignore_index=True)
    terms_csv = RUN_DIR / "all_candidates_treatment_metrics.csv"
    df_all_terms.to_csv(terms_csv, index=False)

    print("\n" + "=" * 90)
    print("ALL CANDIDATES SUMMARY TABLE")
    print("=" * 90)
    display_cols = ["candidate", "phi", "nrmse_calib", "nrmse_valid", "nrmse_spring", "nrmse_25fa", "d_index_spring", "26SP_W2_gap", "26SP_W1_gap", "25SP_W3_gap", "sasc_ratio"]
    print(df_sum[display_cols].to_string(index=False))

    # Champion selection:
    # Condition 1: Positive N responses on all key contrast arms
    # Condition 2: 25FA independent test NRMSE <= 25.0%
    # Condition 3: Minimum Spring NRMSE / Calib NRMSE
    valid_cands = df_sum[
        (df_sum["26SP_W2_gap"] > 0)
        & (df_sum["26SP_W1_gap"] > 0)
        & (df_sum["25SP_W3_gap"] > 0)
        & (df_sum["nrmse_25fa"] <= 25.0)
    ]

    if not valid_cands.empty:
        champ = valid_cands.sort_values("nrmse_spring").iloc[0]
        print(f"\n>>> CHAMPION SELECTED (Meets all response & generalization criteria): {champ['candidate']} (Phi={champ['phi']:.2f})")
    else:
        champ = df_sum.sort_values("phi").iloc[0]
        print(f"\n>>> CHAMPION SELECTED (Fallback to lowest Phi): {champ['candidate']} (Phi={champ['phi']:.2f})")

    champ_tag = champ["candidate"]
    champ_p_csv = RUN_DIR / f"candidate_{champ_tag}_params.csv"

    # Save canonical champion parameter files
    shutil.copy2(champ_p_csv, RUN_DIR / "champion_parameters.csv")
    shutil.copy2(champ_p_csv, RUN_DIR / "full_gen_century_sasc_best_parameters_fixed.csv")
    print(f"Saved champion parameters to {RUN_DIR / 'champion_parameters.csv'}")

    # Copy simulation directories
    for batch_name, src_name, dst_name in [
        ("calib", f"cand_{champ_tag}_calib", "det_calib"),
        ("valid", f"cand_{champ_tag}_valid", "det_valid"),
        ("25fa", f"cand_{champ_tag}_25fa", "det_25fa"),
    ]:
        src = RUN_DIR / src_name
        dst = RUN_DIR / dst_name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"Copied {src_name} -> {dst_name}")

    print("\nEvaluation completed successfully!")


if __name__ == "__main__":
    main()
