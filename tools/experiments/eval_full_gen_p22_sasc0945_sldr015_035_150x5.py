#!/usr/bin/env python3
"""Comprehensive evaluation script for full_gen_page22_sasc0945_sldr015_035_150x5_20260919 run.

Extracts best parameter set from IES calibration, runs deterministic evaluation on:
  - 25SP: 11 treatments (calib + valid)
  - 26SP: 12 treatments (calib + valid)
Computes observed vs simulated yield, LAI, biomass metrics and water-nitrogen gradients.
"""
from __future__ import annotations

import os
import sys
import shutil
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RUN_DIR = PROJECT_ROOT / "workspace/runs/full_gen_page22_sasc0945_sldr015_035_150x5_20260919"
CASE = "full_gen_p22_s0945_sldr015_035_150x5"

# Metadata for 25SP and 26SP treatments
TMT_INFO = {
    # 25SP
    ("25SP", 2): {"water": "W3", "nitro": "N3", "label": "W3N3", "obs": 72323.0},
    ("25SP", 3): {"water": "W3", "nitro": "N2", "label": "W3N2", "obs": 73021.0},
    ("25SP", 4): {"water": "W3", "nitro": "N1", "label": "W3N1", "obs": 71380.0},
    ("25SP", 5): {"water": "W3", "nitro": "N0", "label": "W3N0", "obs": 68228.0},
    ("25SP", 6): {"water": "W2", "nitro": "N3", "label": "W2N3", "obs": 75624.0},
    ("25SP", 9): {"water": "W2", "nitro": "N0", "label": "W2N0", "obs": 67503.0},
    ("25SP", 10): {"water": "W1", "nitro": "N3", "label": "W1N3", "obs": 71137.0},
    ("25SP", 11): {"water": "W1", "nitro": "N2", "label": "W1N2", "obs": 72151.0},
    ("25SP", 12): {"water": "W1", "nitro": "N1", "label": "W1N1", "obs": 71915.0},
    ("25SP", 13): {"water": "W1", "nitro": "N0", "label": "W1N0", "obs": 59547.0},
    ("25SP", 14): {"water": "CK", "nitro": "N2", "label": "CKN2", "obs": 72903.0},
    # 26SP
    ("26SP", 1): {"water": "W3", "nitro": "N3", "label": "W3N3", "obs": 66681.0},
    ("26SP", 2): {"water": "W2", "nitro": "N3", "label": "W2N3", "obs": 71870.0},
    ("26SP", 3): {"water": "W1", "nitro": "N3", "label": "W1N3", "obs": 68076.0},
    ("26SP", 4): {"water": "W3", "nitro": "N2", "label": "W3N2", "obs": 70486.0},
    ("26SP", 5): {"water": "W2", "nitro": "N2", "label": "W2N2", "obs": 74315.0},
    ("26SP", 6): {"water": "W1", "nitro": "N2", "label": "W1N2", "obs": 65617.0},
    ("26SP", 7): {"water": "W3", "nitro": "N1", "label": "W3N1", "obs": 62825.0},
    ("26SP", 8): {"water": "W2", "nitro": "N1", "label": "W2N1", "obs": 65648.0},
    ("26SP", 9): {"water": "W3", "nitro": "N0", "label": "W3N0", "obs": 60892.0},
    ("26SP", 10): {"water": "W1", "nitro": "N1", "label": "W1N1", "obs": 64087.0},
    ("26SP", 11): {"water": "W2", "nitro": "N0", "label": "W2N0", "obs": 62347.0},
    ("26SP", 12): {"water": "W1", "nitro": "N0", "label": "W1N0", "obs": 51579.0},
}


def analyze_phi(run_dir: Path, case: str):
    phi_meas = run_dir / f"{case}.phi.meas.csv"
    phi_actual = run_dir / f"{case}.phi.actual.csv"
    target_phi = phi_actual if phi_actual.exists() else phi_meas
    if not target_phi.exists():
        print(f"Phi file not found in {run_dir}")
        return None

    df_phi = pd.read_csv(target_phi)
    print(f"Loaded Phi from {target_phi.name}, iterations: {len(df_phi)}")
    std_col = "standard_deviation" if "standard_deviation" in df_phi.columns else "std"
    print(df_phi[["iteration", "mean", "min", "max", std_col]])

    best_iter = int(df_phi.loc[df_phi["min"].idxmin(), "iteration"])
    min_phi = df_phi["min"].min()
    print(f"\nBest iteration by min phi: iteration {best_iter} (min phi = {min_phi:.2f})")

    print("\n--- SOIL_SLDR Trajectory across iterations ---")
    for it in df_phi["iteration"]:
        par_file = run_dir / f"{case}.{int(it)}.par.csv"
        if par_file.exists():
            df_par = pd.read_csv(par_file)
            col = [c for c in df_par.columns if c.lower() == "soil_sldr"]
            if col:
                c = col[0]
                vals = df_par[c]
                print(f"  Iter {int(it)}: min={vals.min():.4f}, mean={vals.mean():.4f}, median={vals.median():.4f}, max={vals.max():.4f}, std={vals.std():.4f}")

    par_best_file = run_dir / f"{case}.{best_iter}.par.csv"
    if not par_best_file.exists():
        return None
    df_best_par = pd.read_csv(par_best_file)

    non_reals = {"iteration", "total_runs", "mean", "standard_deviation", "min", "max", "std"}
    reals = [c for c in df_phi.columns if c not in non_reals]
    sub = df_phi[df_phi["iteration"] == best_iter].iloc[0][reals]
    best_real_name = str(sub.idxmin())
    min_phi_val = float(sub.min())
    print(f"Best realization in iter {best_iter}: real {best_real_name} with phi={min_phi_val:.2f}")

    match_row = df_best_par[df_best_par["real_name"].astype(str) == str(best_real_name)]
    if match_row.empty:
        match_row = df_best_par.iloc[[0]]
        best_real_name = match_row["real_name"].iloc[0]

    best_series = match_row.iloc[0]
    print(f"\nSelected best member: iter {best_iter}, real {best_real_name}")
    col_sldr = [c for c in best_series.index if c.lower() == "soil_sldr"]
    if col_sldr:
        print(f"-> Calibrated SOIL_SLDR: {best_series[col_sldr[0]]:.5f}")

    frozen_csv = PROJECT_ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_full_gen_p22_sasc0945_sldr015_035_20260919.csv"
    df_frozen = pd.read_csv(frozen_csv)
    param_dict = dict(zip(df_frozen["name"], df_frozen["init"]))

    for k, v in best_series.items():
        kl = str(k).strip().lower()
        for fk in param_dict:
            if fk.lower() == kl:
                param_dict[fk] = float(v)
                break

    out_csv = RUN_DIR / f"candidate_iter{best_iter}_real{best_real_name}_params.csv"
    with open(out_csv, "w") as f:
        f.write("name,value\n")
        for k, v in sorted(param_dict.items()):
            f.write(f"{k},{v}\n")
    shutil.copy2(out_csv, RUN_DIR / "best_member_params.csv")
    print(f"Saved complete parameter dictionary to {out_csv} and best_member_params.csv")

    return {
        "best_iter": best_iter,
        "best_real_name": best_real_name,
        "param_csv": out_csv,
        "best_params": param_dict,
    }


def run_deterministic_eval(param_csv: Path, out_dir: Path, batches: list[Path]):
    from tools.eval_full_gen98 import evaluate_run
    out_dir.mkdir(parents=True, exist_ok=True)
    all_results = {}

    for batch_path in batches:
        b_name = batch_path.stem
        sub_dir = out_dir / b_name
        if sub_dir.exists():
            shutil.rmtree(sub_dir)
        sub_dir.mkdir(parents=True, exist_ok=True)

        from src.calibration.run_dssat import prepare_run_directory
        batch_dest = prepare_run_directory(sub_dir, ["--batch", str(batch_path)])

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
        res = subprocess.run(cmd, cwd=sub_dir, capture_output=True, text=True, env=env)
        if res.returncode != 0:
            print(f"Error running DSSAT in {sub_dir}:\n{res.stderr[-1000:]}")
            continue

        df_h, _ = evaluate_run(batch_path, sub_dir)
        for (excode, tn), group in df_h.groupby(["EXCODE", "TN"]):
            last = group.sort_values("DATE").iloc[-1]
            season = "25SP" if "2501" in str(excode) else "26SP"
            all_results[(season, int(tn))] = {
                "season": season,
                "tn": int(tn),
                "sim_fresh": float(last["SIM_FRESH_CUM"]),
                "obs_fresh": float(last["OBS_FRESH_CUM"]),
            }
    return all_results


def calculate_metrics(obs: list[float], sim: list[float]):
    o = np.array(obs, dtype=float)
    s = np.array(sim, dtype=float)
    rmse = np.sqrt(np.mean((s - o) ** 2))
    nrmse = rmse / np.mean(o) * 100.0
    ss_res = np.sum((o - s) ** 2)
    ss_tot = np.sum((o - np.mean(o)) ** 2)
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else np.nan
    d_den = np.sum((np.abs(s - np.mean(o)) + np.abs(o - np.mean(o))) ** 2)
    d = 1.0 - (ss_res / d_den) if d_den > 0 else np.nan
    return {"rmse": rmse, "nrmse": nrmse, "r2": r2, "d": d}


def print_evaluation_report(results: dict):
    print("\n" + "=" * 90)
    print(f"{'SEASON':<6} {'TN':<4} {'TREATMENT':<8} {'WATER':<6} {'NITRO':<6} {'OBS_YIELD':<12} {'SIM_YIELD':<12} {'RESIDUAL':<10} {'REL_ERR(%)':<10}")
    print("-" * 90)

    for season in ["25SP", "26SP"]:
        sub_keys = [k for k in sorted(TMT_INFO.keys()) if k[0] == season]
        obs_list = []
        sim_list = []
        for k in sub_keys:
            info = TMT_INFO[k]
            obs = info["obs"]
            sim_info = results.get(k, {})
            sim = sim_info.get("sim_fresh", np.nan)
            diff = sim - obs
            rel = (diff / obs) * 100.0 if obs else np.nan
            obs_list.append(obs)
            sim_list.append(sim)
            print(f"{season:<6} {k[1]:<4} {info['label']:<8} {info['water']:<6} {info['nitro']:<6} {obs:<12.1f} {sim:<12.1f} {diff:<+10.1f} {rel:<+10.2f}")

        m = calculate_metrics(obs_list, sim_list)
        print("-" * 90)
        print(f"[{season} Summary] Fresh Yield: RMSE = {m['rmse']:.1f} kg/ha | NRMSE = {m['nrmse']:.2f}% | R2 = {m['r2']:.4f} | d-index = {m['d']:.4f}")
        print("-" * 90)

    print("\n" + "=" * 90)
    print("WATER-NITROGEN RESPONSE GRADIENTS (W1, W2, W3)")
    print("=" * 90)

    # 25SP W1
    w1_25_obs = [TMT_INFO[("25SP", 13)]["obs"], TMT_INFO[("25SP", 12)]["obs"], TMT_INFO[("25SP", 11)]["obs"], TMT_INFO[("25SP", 10)]["obs"]]
    w1_25_sim = [results.get(("25SP", 13), {}).get("sim_fresh", np.nan),
                 results.get(("25SP", 12), {}).get("sim_fresh", np.nan),
                 results.get(("25SP", 11), {}).get("sim_fresh", np.nan),
                 results.get(("25SP", 10), {}).get("sim_fresh", np.nan)]
    print("\n[25SP W1 Low-Water Response (N0 -> N1 -> N2 -> N3)]")
    print(f"  Observed:  {w1_25_obs[0]:.0f} -> {w1_25_obs[1]:.0f} -> {w1_25_obs[2]:.0f} -> {w1_25_obs[3]:.0f} kg/ha  (Total Delta = {w1_25_obs[3]-w1_25_obs[0]:+.0f} kg/ha)")
    print(f"  Simulated: {w1_25_sim[0]:.0f} -> {w1_25_sim[1]:.0f} -> {w1_25_sim[2]:.0f} -> {w1_25_sim[3]:.0f} kg/ha  (Total Delta = {w1_25_sim[3]-w1_25_sim[0]:+.0f} kg/ha, Ratio = {(w1_25_sim[3]-w1_25_sim[0])/(w1_25_obs[3]-w1_25_obs[0])*100:.1f}%)")

    # 26SP W1
    w1_26_obs = [TMT_INFO[("26SP", 12)]["obs"], TMT_INFO[("26SP", 10)]["obs"], TMT_INFO[("26SP", 6)]["obs"], TMT_INFO[("26SP", 3)]["obs"]]
    w1_26_sim = [results.get(("26SP", 12), {}).get("sim_fresh", np.nan),
                 results.get(("26SP", 10), {}).get("sim_fresh", np.nan),
                 results.get(("26SP", 6), {}).get("sim_fresh", np.nan),
                 results.get(("26SP", 3), {}).get("sim_fresh", np.nan)]
    print("\n[26SP W1 Low-Water Response (N0 -> N1 -> N2 -> N3)]")
    print(f"  Observed:  {w1_26_obs[0]:.0f} -> {w1_26_obs[1]:.0f} -> {w1_26_obs[2]:.0f} -> {w1_26_obs[3]:.0f} kg/ha  (Total Delta = {w1_26_obs[3]-w1_26_obs[0]:+.0f} kg/ha)")
    print(f"  Simulated: {w1_26_sim[0]:.0f} -> {w1_26_sim[1]:.0f} -> {w1_26_sim[2]:.0f} -> {w1_26_sim[3]:.0f} kg/ha  (Total Delta = {w1_26_sim[3]-w1_26_sim[0]:+.0f} kg/ha, Ratio = {(w1_26_sim[3]-w1_26_sim[0])/(w1_26_obs[3]-w1_26_obs[0])*100:.1f}%)")

    # 25SP W3
    w3_25_obs = [TMT_INFO[("25SP", 5)]["obs"], TMT_INFO[("25SP", 4)]["obs"], TMT_INFO[("25SP", 3)]["obs"], TMT_INFO[("25SP", 2)]["obs"]]
    w3_25_sim = [results.get(("25SP", 5), {}).get("sim_fresh", np.nan),
                 results.get(("25SP", 4), {}).get("sim_fresh", np.nan),
                 results.get(("25SP", 3), {}).get("sim_fresh", np.nan),
                 results.get(("25SP", 2), {}).get("sim_fresh", np.nan)]
    print("\n[25SP W3 High-Water Response (N0 -> N1 -> N2 -> N3)]")
    print(f"  Observed:  {w3_25_obs[0]:.0f} -> {w3_25_obs[1]:.0f} -> {w3_25_obs[2]:.0f} -> {w3_25_obs[3]:.0f} kg/ha  (Total Delta = {w3_25_obs[3]-w3_25_obs[0]:+.0f} kg/ha)")
    print(f"  Simulated: {w3_25_sim[0]:.0f} -> {w3_25_sim[1]:.0f} -> {w3_25_sim[2]:.0f} -> {w3_25_sim[3]:.0f} kg/ha  (Total Delta = {w3_25_sim[3]-w3_25_sim[0]:+.0f} kg/ha)")

    # 26SP W3
    w3_26_obs = [TMT_INFO[("26SP", 9)]["obs"], TMT_INFO[("26SP", 7)]["obs"], TMT_INFO[("26SP", 4)]["obs"], TMT_INFO[("26SP", 1)]["obs"]]
    w3_26_sim = [results.get(("26SP", 9), {}).get("sim_fresh", np.nan),
                 results.get(("26SP", 7), {}).get("sim_fresh", np.nan),
                 results.get(("26SP", 4), {}).get("sim_fresh", np.nan),
                 results.get(("26SP", 1), {}).get("sim_fresh", np.nan)]
    print("\n[26SP W3 High-Water Response (N0 -> N1 -> N2 -> N3)]")
    print(f"  Observed:  {w3_26_obs[0]:.0f} -> {w3_26_obs[1]:.0f} -> {w3_26_obs[2]:.0f} -> {w3_26_obs[3]:.0f} kg/ha  (Total Delta = {w3_26_obs[3]-w3_26_obs[0]:+.0f} kg/ha)")
    print(f"  Simulated: {w3_26_sim[0]:.0f} -> {w3_26_sim[1]:.0f} -> {w3_26_sim[2]:.0f} -> {w3_26_sim[3]:.0f} kg/ha  (Total Delta = {w3_26_sim[3]-w3_26_sim[0]:+.0f} kg/ha)")
    print("=" * 90 + "\n")


def main():
    print("=== Analyzing PEST++ IES Run Results ===")
    analysis = analyze_phi(RUN_DIR, CASE)
    if not analysis:
        print("Analysis could not be completed.")
        return 1

    print("\n=== Running Deterministic Multi-Treatment Evaluation ===")
    det_dir = RUN_DIR / "det_eval"
    batches = [
        PROJECT_ROOT / "data/templates/batch/DSSBatch_calib.v48",
        PROJECT_ROOT / "data/templates/batch/DSSBatch_valid.v48",
    ]
    results = run_deterministic_eval(analysis["param_csv"], det_dir, batches)
    print_evaluation_report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
