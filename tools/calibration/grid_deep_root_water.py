#!/usr/bin/env python3
"""grid_deep_root_water.py — 
Grid experiment for deep root water uptake in 25SP with ICNS_25SP=1.0 and SRGF=0 below 140cm.

Explores:
1. SRGF profiles in 30-100cm (with 140cm=0, 180cm=0)
2. RWUMX levels (0.044 to 0.100)
3. Evaluates W1N3, W1N2, W1N1, W1N0, W1 Delta (N3-N0), W3 Delta, 25SP NRMSE and d-index.
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

RUN_DIR = PROJECT_ROOT / "workspace" / "runs" / "full_gen_page22_sasc0945_150x5_20260918"
GRID_WORK_DIR = RUN_DIR / "grid_deep_root"
FROZEN_BOUNDS_CSV = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_full_gen_page22_sasc0945_20260918.csv"
BASE_PARAM_CSV = RUN_DIR / "candidate_best_sasc0945_params.csv"
RAW_SOIL = PROJECT_ROOT / "data" / "raw" / "soil" / "SOIL.SOL"

BATCH_25SP = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch.v48"
BUNDLE_25SP = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2501_v20260917_refresh"

TMT_LABELS_25SP = {
    2: "W3N3", 3: "W3N2", 4: "W3N1", 5: "W3N0",
    6: "W2N3", 9: "W2N0",
    10: "W1N3", 11: "W1N2", 12: "W1N1", 13: "W1N0",
    14: "CKN2",
}

OBS_FRESH = {
    "W3N3": 72323.0, "W3N2": 73021.0, "W3N1": 71380.0, "W3N0": 68228.0,
    "W2N3": 75624.0, "W2N0": 67503.0,
    "W1N3": 71137.0, "W1N2": 72151.0, "W1N1": 71915.0, "W1N0": 59547.0,
    "CKN2": 72903.0,
}

# SRGF Profiles to test (depths: 30, 40, 60, 80, 100; 140=0, 180=0)
# Original: 30:0.90, 40:0.80, 60:0.65, 80:0.20, 100:0.20, 140:0.05, 180:0.00
SRGF_PROFILES = {
    "P0_Baseline": {
        # Original but 140=0, 180=0
        30: 0.90, 40: 0.80, 60: 0.65, 80: 0.20, 100: 0.20, 140: 0.00, 180: 0.00
    },
    "P1_Gentle_80": {
        30: 0.90, 40: 0.80, 60: 0.65, 80: 0.35, 100: 0.20, 140: 0.00, 180: 0.00
    },
    "P2_Mod_80_100": {
        30: 0.90, 40: 0.80, 60: 0.65, 80: 0.45, 100: 0.30, 140: 0.00, 180: 0.00
    },
    "P3_Linear_60_100": {
        30: 0.90, 40: 0.80, 60: 0.70, 80: 0.55, 100: 0.40, 140: 0.00, 180: 0.00
    },
    "P4_High_60_100": {
        30: 0.90, 40: 0.85, 60: 0.75, 80: 0.65, 100: 0.50, 140: 0.00, 180: 0.00
    },
    "P5_Merged_30_100": {
        # Mimics merging 30-100 into a high uniform root zone
        30: 0.90, 40: 0.85, 60: 0.80, 80: 0.75, 100: 0.65, 140: 0.00, 180: 0.00
    },
    "P6_Strong_30_100": {
        30: 0.95, 40: 0.90, 60: 0.85, 80: 0.80, 100: 0.75, 140: 0.00, 180: 0.00
    },
}

RWUMX_LEVELS = [0.044, 0.060, 0.075, 0.090, 0.110]


def build_soil_sol(srgf_dict: dict, src_soil_path: Path, dst_soil_path: Path):
    lines = src_soil_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    in_target = False

    for line in lines:
        if line.startswith("*XXSL2501"):
            in_target = True
            new_lines.append(line)
        elif line.startswith("*") and in_target and not line.startswith("*XXSL2501"):
            in_target = False
            new_lines.append(line)
        elif in_target and line.strip() and not line.strip().startswith(("@", "!", "$", "*")):
            parts = line.split()
            if len(parts) >= 6:
                try:
                    depth = int(parts[0])
                    if depth in srgf_dict:
                        new_val = srgf_dict[depth]
                        line = line[:29] + f"{new_val:6.3f}" + line[35:]
                except ValueError:
                    pass
            new_lines.append(line)
        else:
            new_lines.append(line)

    dst_soil_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def build_param_file(rwumx_val: float, src_param_csv: Path, dst_param_csv: Path):
    df = pd.read_csv(src_param_csv)
    # strictly enforce ICNS_25SP = 1.0
    if "ICNS_25SP" in df["name"].values:
        df.loc[df["name"] == "ICNS_25SP", "value"] = 1.000
    else:
        df = pd.concat([df, pd.DataFrame([{"name": "ICNS_25SP", "value": 1.000}])], ignore_index=True)

    if "RWUMX" in df["name"].values:
        df.loc[df["name"] == "RWUMX", "value"] = rwumx_val
    else:
        df = pd.concat([df, pd.DataFrame([{"name": "RWUMX", "value": rwumx_val}])], ignore_index=True)

    df.to_csv(dst_param_csv, index=False)


def init_sim_dir(out_dir: Path):
    if out_dir.exists():
        try:
            shutil.rmtree(out_dir)
        except Exception:
            pass
    out_dir.mkdir(parents=True, exist_ok=True)
    prep_args = ["--batch", str(BATCH_25SP), "--input-dir", str(BUNDLE_25SP)]
    batch_dest = prepare_run_directory(out_dir, prep_args)
    return batch_dest


def run_one_sim(out_dir: Path, batch_dest: Path, param_csv: Path, soil_sol: Path):
    shutil.copy2(soil_sol, out_dir / "SOIL.SOL")
    shutil.copy2(soil_sol, out_dir / "SOIL.SOL.base")

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
        raise RuntimeError(f"Simulation failed in {out_dir}")

    df_h, _ = evaluate_run(batch_dest, out_dir)
    return df_h


def extract_metrics(df_h: pd.DataFrame):
    tmt_sims = {}
    for tn, group in df_h.groupby("TN"):
        last_row = group.sort_values("DATE").iloc[-1]
        tmt_sims[tn] = float(last_row["SIM_FRESH_CUM"])

    obs_list = []
    sim_list = []
    for tn, lbl in TMT_LABELS_25SP.items():
        if tn in tmt_sims:
            obs_list.append(OBS_FRESH[lbl])
            sim_list.append(tmt_sims[tn])

    rmse, nrmse, d, r2 = calc_metrics(pd.Series(obs_list), pd.Series(sim_list))

    w1n3 = tmt_sims.get(10, np.nan) / 1000.0
    w1n2 = tmt_sims.get(11, np.nan) / 1000.0
    w1n1 = tmt_sims.get(12, np.nan) / 1000.0
    w1n0 = tmt_sims.get(13, np.nan) / 1000.0
    delta_w1 = w1n3 - w1n0

    w3n3 = tmt_sims.get(2, np.nan) / 1000.0
    w3n0 = tmt_sims.get(5, np.nan) / 1000.0
    delta_w3 = w3n3 - w3n0

    w2n3 = tmt_sims.get(6, np.nan) / 1000.0
    w2n0 = tmt_sims.get(9, np.nan) / 1000.0
    delta_w2 = w2n3 - w2n0

    return {
        "nrmse": nrmse,
        "d_index": d,
        "w1n3": w1n3,
        "w1n2": w1n2,
        "w1n1": w1n1,
        "w1n0": w1n0,
        "delta_w1": delta_w1,
        "w3n3": w3n3,
        "w3n0": w3n0,
        "delta_w3": delta_w3,
        "delta_w2": delta_w2,
    }


def main():
    if not BASE_PARAM_CSV.exists():
        print(f"Error: {BASE_PARAM_CSV} does not exist.")
        return 1

    GRID_WORK_DIR.mkdir(parents=True, exist_ok=True)
    temp_sim_dir = GRID_WORK_DIR / "_sim_worker"
    batch_dest = init_sim_dir(temp_sim_dir)

    results = []
    total_runs = len(SRGF_PROFILES) * len(RWUMX_LEVELS)
    run_idx = 0

    print(f"\n================ STARTING DEEP ROOT WATER GRID SEARCH ================")
    print(f"Total configurations: {total_runs} (7 SRGF profiles x 5 RWUMX levels)")
    print(f"Constraints enforced: ICNS_25SP = 1.000 (locked), SRGF(140cm)=0.0, SRGF(180cm)=0.0")
    print(f"Target Ground Truth: W1N3=71.14t, W1N0=59.55t, W1 Delta=+11.59t\n")

    for prof_name, srgf_dict in SRGF_PROFILES.items():
        soil_file = GRID_WORK_DIR / f"SOIL_{prof_name}.SOL"
        build_soil_sol(srgf_dict, RAW_SOIL, soil_file)

        for rwumx in RWUMX_LEVELS:
            run_idx += 1
            cfg_name = f"{prof_name}_rw{int(rwumx*1000):03d}"
            param_file = GRID_WORK_DIR / f"params_{cfg_name}.csv"
            build_param_file(rwumx, BASE_PARAM_CSV, param_file)

            try:
                df_h = run_one_sim(temp_sim_dir, batch_dest, param_file, soil_file)
                m = extract_metrics(df_h)
                res_entry = {
                    "config": cfg_name,
                    "profile": prof_name,
                    "rwumx": rwumx,
                    "srgf_80": srgf_dict.get(80, 0.20),
                    "srgf_100": srgf_dict.get(100, 0.20),
                    "NRRMSE%": m["nrmse"],
                    "d_index": m["d_index"],
                    "W1N3_t": m["w1n3"],
                    "W1N2_t": m["w1n2"],
                    "W1N1_t": m["w1n1"],
                    "W1N0_t": m["w1n0"],
                    "W1_Delta_t": m["delta_w1"],
                    "W3_Delta_t": m["delta_w3"],
                    "W2_Delta_t": m["delta_w2"],
                }
                results.append(res_entry)
                print(f"[{run_idx:02d}/{total_runs}] {cfg_name:24s} -> NRMSE: {m['nrmse']:5.2f}%, d: {m['d_index']:.4f} | W1N3: {m['w1n3']:5.2f}t, W1N0: {m['w1n0']:5.2f}t | W1 Delta: {m['delta_w1']:+5.2f}t | W3 Delta: {m['delta_w3']:+5.2f}t")
            except Exception as e:
                print(f"[{run_idx:02d}/{total_runs}] {cfg_name:24s} -> FAILED: {type(e).__name__}")

    df_res = pd.DataFrame(results)
    out_csv = GRID_WORK_DIR / "grid_results_summary.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\nSaved full grid results to {out_csv}")

    # Rank by best W1 Delta opening while maintaining NRMSE < 12%
    print("\n================ TOP CONFIGURATIONS BY W1 DELTA (N3 - N0) ================")
    top_w1 = df_res.sort_values("W1_Delta_t", ascending=False)
    print(top_w1[["config", "profile", "rwumx", "NRRMSE%", "d_index", "W1N3_t", "W1N0_t", "W1_Delta_t", "W3_Delta_t"]].head(10).to_string(index=False))

    print("\n================ TOP CONFIGURATIONS BY BALANCED SCORE ================")
    # Balanced score: penalizes NRMSE and penalizes distance of W1_Delta from target +11.59t
    df_res["target_dist"] = np.abs(df_res["W1_Delta_t"] - 11.59)
    df_res["balanced_rank"] = df_res["NRRMSE%"] * 0.5 + df_res["target_dist"] * 1.0 - (df_res["d_index"] * 10)
    top_balanced = df_res.sort_values("balanced_rank")
    print(top_balanced[["config", "profile", "rwumx", "NRRMSE%", "d_index", "W1N3_t", "W1N0_t", "W1_Delta_t", "W3_Delta_t", "balanced_rank"]].head(10).to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
