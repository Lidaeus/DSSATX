#!/usr/bin/env python3
"""Evaluate formal Century SASC [0.89, 0.95] calibration candidates across all 35 treatments:
1. Calibration set (8 runs, DSSBatch_calib.v48)
2. Validation set (15 runs, DSSBatch_valid.v48)
3. 25FA Independent test set (12 runs, xxql2502_v20260917_refresh/DSSBatch.v48)
4. Water-Nitrogen response gradients (26SP W1, 26SP W2, 26SP W3, 25SP W1, 25SP W3)
5. Comprehensive metrics (RMSE, NRMSE%, d-index, R2)
6. Selects and ranks top candidates
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

RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / "full_gen_century_sasc094_formal_20260918"
FROZEN_BOUNDS_CSV = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_full_gen_century_sasc089_095_20260918.csv"

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

    # Water-Nitrogen gradient analysis (in t/ha: kg/ha / 1000.0)
    def get_term_sim(season_id, water_lvl, nitro_lvl):
        sub = df_term[(df_term["season"] == season_id) & (df_term["water"] == water_lvl) & (df_term["nitro"] == nitro_lvl)]
        return float(sub.iloc[0]["sim_terminal_kg_ha"]) / 1000.0 if not sub.empty else np.nan

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
        "26SP_W1_gap_t_ha": w1_26_sim,  # field: +16.50
        "26SP_W2_gap_t_ha": w2_26_sim,  # field: +9.50
        "26SP_W3_gap_t_ha": w3_26_sim,  # field: +16.00
        "25SP_W1_gap_t_ha": w1_25_sim,  # field: +11.60
        "25SP_W3_gap_t_ha": w3_25_sim,  # field: +4.10
        "sasc_ratio": p_vals.get("sasc_ratio", np.nan),
        "icns_26sp": p_vals.get("icns_26sp", np.nan),
        "soil_slnf": p_vals.get("soil_slnf", np.nan),
        "pgeff": p_vals.get("pgeff", np.nan),
        "lnref": p_vals.get("lnref", np.nan),
        "frlff": p_vals.get("frlff", np.nan),
        "slavr": p_vals.get("slavr", np.nan),
        "sizlf": p_vals.get("sizlf", np.nan),
        "tb1": p_vals.get("tb1", np.nan),
    }

    print(f"  Calib NRMSE: {nrmse_c:.2f}%, d={d_c:.4f}, R2={r2_c:.4f}")
    print(f"  Valid NRMSE: {nrmse_v:.2f}%, d={d_v:.4f}, R2={r2_v:.4f}")
    print(f"  Spring NRMSE: {nrmse_sp:.2f}%, d={d_sp:.4f}, R2={r2_sp:.4f}")
    print(f"  25FA NRMSE: {nrmse_fa:.2f}%, d={d_fa:.4f}, R2={r2_fa:.4f}")
    print(f"  All-35 NRMSE: {nrmse_all:.2f}%, d={d_all:.4f}, R2={r2_all:.4f}")
    print(f"  W-N Gaps: 26W1={w1_26_sim:+.2f}t, 26W2={w2_26_sim:+.2f}t, 25W1={w1_25_sim:+.2f}t, 25W3={w3_25_sim:+.2f}t")
    print(f"  Parameters: SASC={res['sasc_ratio']:.4f}, ICNS_26SP={res['icns_26sp']:.3f}, PGEFF={res['pgeff']:.4f}, LNREF={res['lnref']:.3f}")

    return res, df_term


def main():
    phi_df = pd.read_csv(RUN_DIR / "full_gen_century_sasc094.phi.actual.csv")
    par4_df = pd.read_csv(RUN_DIR / "full_gen_century_sasc094.4.par.csv")
    par5_df = pd.read_csv(RUN_DIR / "full_gen_century_sasc094.5.par.csv")

    candidates_to_eval = [
        # Iteration 5 Top 8
        ("iter5_real38", "38", par5_df, float(phi_df.iloc[5]["38"])),
        ("iter5_real8", "8", par5_df, float(phi_df.iloc[5]["8"])),
        ("iter5_real48", "48", par5_df, float(phi_df.iloc[5]["48"])),
        ("iter5_real116", "116", par5_df, float(phi_df.iloc[5]["116"])),
        ("iter5_real67", "67", par5_df, float(phi_df.iloc[5]["67"])),
        ("iter5_real113", "113", par5_df, float(phi_df.iloc[5]["113"])),
        ("iter5_real60", "60", par5_df, float(phi_df.iloc[5]["60"])),
        ("iter5_real22", "22", par5_df, float(phi_df.iloc[5]["22"])),
        # Iteration 4 Top 3
        ("iter4_real46", "46", par4_df, float(phi_df.iloc[4]["46"])),
        ("iter4_real72", "72", par4_df, float(phi_df.iloc[4]["72"])),
        ("iter4_real99", "99", par4_df, float(phi_df.iloc[4]["99"])),
    ]

    all_res = []
    all_terms = []

    for tag, rid, df_p, phi_val in candidates_to_eval:
        res, df_term = evaluate_single_candidate(tag, rid, df_p, phi_val)
        all_res.append(res)
        all_terms.append(df_term)

    summary_df = pd.DataFrame(all_res)
    summary_path = RUN_DIR / "candidates_35tmt_evaluation_summary.csv"
    summary_df.to_csv(summary_path, index=False)

    detail_df = pd.concat(all_terms, ignore_index=True)
    detail_path = RUN_DIR / "candidates_treatments_detail.csv"
    detail_df.to_csv(detail_path, index=False)

    print("\n================ COMPREHENSIVE RANKING (By Spring NRMSE) ================")
    ranked_spring = summary_df.sort_values("nrmse_spring")
    cols_show = ["candidate", "phi", "sasc_ratio", "nrmse_spring", "nrmse_all35", "d_index_spring", "26SP_W1_gap_t_ha", "26SP_W2_gap_t_ha", "25SP_W1_gap_t_ha", "25SP_W3_gap_t_ha"]
    print(ranked_spring[cols_show].to_string(index=False))

    # Calculate Balanced Score
    # Gap penalty against targets: 26W1=16.5, 26W2=9.5, 25W1=11.6, 25W3=4.1
    gap_penalty = (
        (summary_df["26SP_W1_gap_t_ha"] - 16.50).abs() / 16.50 +
        (summary_df["26SP_W2_gap_t_ha"] - 9.50).abs() / 9.50 +
        (summary_df["25SP_W1_gap_t_ha"] - 11.60).abs() / 11.60 +
        (summary_df["25SP_W3_gap_t_ha"] - 4.10).abs() / 4.10
    )
    summary_df["composite_score"] = 0.50 * summary_df["nrmse_spring"] + 0.20 * summary_df["nrmse_all35"] + 0.30 * (gap_penalty * 10.0)
    ranked_balanced = summary_df.sort_values("composite_score")
    ranked_path = RUN_DIR / "candidates_ranked_balanced.csv"
    ranked_balanced.to_csv(ranked_path, index=False)

    print("\n================ COMPREHENSIVE RANKING (By Balanced Composite Score) ================")
    cols_bal = ["candidate", "phi", "sasc_ratio", "nrmse_spring", "nrmse_all35", "d_index_spring", "26SP_W1_gap_t_ha", "26SP_W2_gap_t_ha", "25SP_W1_gap_t_ha", "composite_score"]
    print(ranked_balanced[cols_bal].to_string(index=False))

    print(f"\n[CHAMPION] CANDIDATE: {champion['candidate']} (SASC_RATIO={champion['sasc_ratio']:.4f}, Spring NRMSE={champion['nrmse_spring']:.2f}%, All-35 NRMSE={champion['nrmse_all35']:.2f}%)")


if __name__ == "__main__":
    main()
