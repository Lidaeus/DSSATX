#!/usr/bin/env python3
"""Evaluate iter5_real13 with Literature Mapped SSKS on standard Calib + Valid batches."""

import os
import sys
import shutil
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("D:/Tomato_Cal")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.run_dssat import prepare_run_directory
from tools.eval_full_gen98 import evaluate_run, calc_metrics
from tools.experiments.eval_ssks_mapped_10l import modify_soil_ssks

CALIB_BATCH = ROOT / "data/templates/batch/DSSBatch_calib.v48"
VALID_BATCH = ROOT / "data/templates/batch/DSSBatch_valid.v48"
PARAM_CSV = ROOT / "workspace/runs/full_gen_page22_sasc0925_150x5_20260918/candidate_iter5_real13_params.csv"

WORK_DIR = ROOT / "workspace/experiments/ssks_mapped_10l_eval/standard_split_eval"
WORK_DIR.mkdir(parents=True, exist_ok=True)

SSKS_MAPPED = [2.03, 2.03, 2.03, 1.96, 1.81, 0.33, 2.03, 1.43, 0.16, 0.59]

def run_batch_with_ssks(batch_path: Path, out_dir: Path, ssks: list[float]):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_dest = prepare_run_directory(out_dir, ["--batch", str(batch_path)])

    # Inject mapped SSKS into SOIL.SOL and SOIL.SOL.base
    for fname in ["SOIL.SOL", "SOIL.SOL.base"]:
        fpath = out_dir / fname
        if fpath.exists():
            mod = modify_soil_ssks(fpath.read_text(encoding="utf-8", errors="ignore"), ssks)
            fpath.write_text(mod, encoding="utf-8")

    cmd = [
        sys.executable,
        "-m",
        "src.dssat.run_dssat",
        "--param-csv",
        str(PARAM_CSV.resolve()),
        "--batch",
        batch_dest.name,
        "--harvest-var",
        "CHPDT",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    res = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        print("STDERR:", res.stderr[-500:])
        raise RuntimeError(f"DSSAT failed in {out_dir}")
    return evaluate_run(batch_path, out_dir)

def main():
    print("Running Calib batch with Mapped SSKS...")
    df_h_c, _ = run_batch_with_ssks(CALIB_BATCH, WORK_DIR / "run_calib", SSKS_MAPPED)

    print("Running Valid batch with Mapped SSKS...")
    df_h_v, _ = run_batch_with_ssks(VALID_BATCH, WORK_DIR / "run_valid", SSKS_MAPPED)

    df_h_c["batch"] = "Calibration"
    df_h_v["batch"] = "Validation"
    df_all = pd.concat([df_h_c, df_h_v], ignore_index=True)

    rows = []
    for (excode, tn), group in df_all.groupby(["EXCODE", "TN"]):
        last = group.sort_values("DATE").iloc[-1]
        obs = float(last["OBS_FRESH_CUM"])
        sim = float(last["SIM_FRESH_CUM"])
        season = "25SP" if "2501" in excode else "26SP"
        bias = sim - obs
        rel_bias = (bias / obs * 100.0) if obs > 0 else 0.0
        rows.append({
            "season": season,
            "excode": excode,
            "treatment": tn,
            "batch": last["batch"],
            "obs_kg_ha": obs,
            "sim_kg_ha": sim,
            "obs_t_ha": obs / 1000.0,
            "sim_t_ha": sim / 1000.0,
            "bias_kg_ha": bias,
            "bias_t_ha": bias / 1000.0,
            "rel_error_pct": rel_bias,
        })
    df_res = pd.DataFrame(rows)
    df_res.to_csv(WORK_DIR / "standard_split_treatment_results.csv", index=False)

    print("\n--- Treatment Level Results under Standard Calibration/Validation Split ---")
    print(df_res.sort_values(["season", "treatment"])[["season", "treatment", "batch", "obs_t_ha", "sim_t_ha", "bias_t_ha", "rel_error_pct"]].to_string(index=False))

    # Overall metrics
    for grp_name, sub in [("25SP", df_res[df_res["season"] == "25SP"]),
                          ("26SP", df_res[df_res["season"] == "26SP"]),
                          ("Two-Spring Pooled", df_res)]:
        rmse, nrmse, d, r2 = calc_metrics(sub["obs_kg_ha"], sub["sim_kg_ha"])
        print(f"\n{grp_name}: N={len(sub)}, RMSE={rmse/1000.0:.2f} t/ha, NRMSE={nrmse:.2f}%, d={d:.4f}, R2={r2:.4f}")

if __name__ == "__main__":
    main()
