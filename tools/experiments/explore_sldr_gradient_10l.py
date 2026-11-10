#!/usr/bin/env python3
"""Explore SLDR Gradient (0.1, 0.2, 0.3, 0.4, 0.5, 0.6) on 10-Layer Soil Profile.

Investigate the sensitivity of crop yield and water-nitrogen response gradients
(especially 25SP W1 and 26SP W1/W2/W3) to the soil drainage rate coefficient SLDR.

Uses candidate iter5_real13 from full_gen_page22_sasc0925_150x5_20260918.
Maintains literature-mapped SSKS on the 10L-B soil scheme:
  SSKS = [2.03, 2.03, 2.03, 1.96, 1.81, 0.33, 2.03, 1.43, 0.16, 0.59] cm/h
"""
from __future__ import annotations

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
from tools.experiments.eval_ssks_mapped_10l import TMT_INFO

EXP_DIR = ROOT / "workspace/experiments/sldr_gradient_10l_20260918"
EXP_DIR.mkdir(parents=True, exist_ok=True)

CALIB_BATCH = ROOT / "data/templates/batch/DSSBatch_calib.v48"
VALID_BATCH = ROOT / "data/templates/batch/DSSBatch_valid.v48"
PARAM_CSV = ROOT / "workspace/runs/full_gen_page22_sasc0925_150x5_20260918/candidate_iter5_real13_params.csv"

# Literature mapped SSKS for 10 layers
SSKS_MAPPED = [2.03, 2.03, 2.03, 1.96, 1.81, 0.33, 2.03, 1.43, 0.16, 0.59]

# SLDR gradient
SLDR_GRADIENT = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.65]


def modify_soil_sldr_and_ssks(soil_text: str, sldr_val: float, ssks_values: list[float]) -> str:
    """Modify SLDR in SCOM row and SSKS in layer rows for *XXSL2501 and *XXSL2601."""
    lines = soil_text.splitlines(keepends=True)
    out = []
    in_target = False
    in_layers = False
    layer_idx = 0

    for line in lines:
        s = line.rstrip("\n")
        if s.startswith("*XXSL2501") or s.startswith("*XXSL2601"):
            in_target = True
            in_layers = False
            layer_idx = 0
            out.append(line)
            continue
        elif in_target and s.startswith("*"):
            in_target = False
            in_layers = False
            out.append(line)
            continue

        if in_target:
            if "IB001" in s and ("0." in s or " ." in s):
                # SCOM data row
                tokens = s.split()
                if len(tokens) >= 10:
                    tokens[3] = f"{sldr_val:4.2f}"
                    new_scom = f"   {tokens[0]}  {tokens[1]}   {tokens[2]}  {tokens[3]}  {tokens[4]}  {tokens[5]}  {tokens[6]} {tokens[7]} {tokens[8]} {tokens[9]}\n"
                    out.append(new_scom)
                    continue

            if s.startswith("@") and "SLB" in s and "SSKS" in s:
                in_layers = True
                layer_idx = 0
                out.append(line)
                continue
            elif in_layers:
                if not s.strip() or s.startswith("@") or s.startswith("!"):
                    in_layers = False
                    out.append(line)
                    continue
                if layer_idx < len(ssks_values):
                    val = ssks_values[layer_idx]
                    val_str = f"{val:6.2f}"
                    new_line = s[:36] + val_str + s[42:] + "\n"
                    out.append(new_line)
                    layer_idx += 1
                    continue

        out.append(line)
    return "".join(out)


def run_batch_with_sldr(batch_path: Path, out_dir: Path, sldr_val: float, ssks_values: list[float]):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_dest = prepare_run_directory(out_dir, ["--batch", str(batch_path)])

    # Inject mapped SLDR and SSKS into local SOIL.SOL and SOIL.SOL.base
    for fname in ["SOIL.SOL", "SOIL.SOL.base"]:
        fpath = out_dir / fname
        if fpath.exists():
            mod = modify_soil_sldr_and_ssks(fpath.read_text(encoding="utf-8", errors="ignore"), sldr_val, ssks_values)
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
    print("================================================================================")
    print("Starting SLDR Gradient Exploration on 10-Layer Soil Scheme (iter5_real13)")
    print(f"SLDR Values: {SLDR_GRADIENT}")
    print("================================================================================")

    c_sol = Path(r"C:\DSSAT48\Soil\SOIL.SOL")

    all_treatments_rows = []
    summary_rows = []
    gradient_rows = []

    for sldr in SLDR_GRADIENT:
        case_tag = f"SLDR_{sldr:.2f}"
        print(f"\n--- Running Case {case_tag} ---")
        case_dir = EXP_DIR / case_tag
        case_dir.mkdir(parents=True, exist_ok=True)

        # Sync C:\DSSAT48\Soil\SOIL.SOL for complete safety
        if c_sol.exists():
            c_text = c_sol.read_text(encoding="utf-8", errors="ignore")
            c_mod = modify_soil_sldr_and_ssks(c_text, sldr, SSKS_MAPPED)
            c_sol.write_text(c_mod, encoding="utf-8")

        # Run Calib & Valid
        df_h_c, _ = run_batch_with_sldr(CALIB_BATCH, case_dir / "run_calib", sldr, SSKS_MAPPED)
        df_h_v, _ = run_batch_with_sldr(VALID_BATCH, case_dir / "run_valid", sldr, SSKS_MAPPED)

        df_h_c["batch"] = "Calibration"
        df_h_v["batch"] = "Validation"
        df_all_h = pd.concat([df_h_c, df_h_v], ignore_index=True)

        # Collect terminal yields
        case_term_records = []
        for (excode, tn), group in df_all_h.groupby(["EXCODE", "TN"]):
            last = group.sort_values("DATE").iloc[-1]
            obs = float(last["OBS_FRESH_CUM"])
            sim = float(last["SIM_FRESH_CUM"])
            season = "25SP" if "2501" in excode else "26SP"
            bias = sim - obs
            rel_bias = (bias / obs * 100.0) if obs > 0 else 0.0

            meta = TMT_INFO.get((season, tn), {"water": "Unknown", "nitro": "Unknown", "label": f"TN{tn}"})
            rmse_t, nrmse_t, d_t, r2_t = calc_metrics(group["OBS_FRESH_CUM"], group["SIM_FRESH_CUM"])

            record = {
                "sldr": sldr,
                "case": case_tag,
                "season": season,
                "excode": excode,
                "treatment": tn,
                "label": meta["label"],
                "water": meta["water"],
                "nitro": meta["nitro"],
                "batch": last["batch"],
                "obs_kg_ha": obs,
                "sim_kg_ha": sim,
                "obs_t_ha": obs / 1000.0,
                "sim_t_ha": sim / 1000.0,
                "bias_kg_ha": bias,
                "bias_t_ha": bias / 1000.0,
                "rel_error_pct": rel_bias,
                "dyn_nrmse_pct": nrmse_t,
                "dyn_d_index": d_t,
            }
            case_term_records.append(record)
            all_treatments_rows.append(record)

        df_case_terms = pd.DataFrame(case_term_records)

        # Calculate overall metrics
        for grp_name, sub in [("25SP", df_case_terms[df_case_terms["season"] == "25SP"]),
                              ("26SP", df_case_terms[df_case_terms["season"] == "26SP"]),
                              ("Pooled_Terminal", df_case_terms)]:
            rmse, nrmse, d, r2 = calc_metrics(sub["obs_kg_ha"], sub["sim_kg_ha"])
            summary_rows.append({
                "sldr": sldr,
                "dataset": grp_name,
                "N": len(sub),
                "Obs_Mean_t": sub["obs_t_ha"].mean(),
                "Sim_Mean_t": sub["sim_t_ha"].mean(),
                "Bias_Mean_t": sub["bias_t_ha"].mean(),
                "RMSE_t": rmse / 1000.0,
                "NRMSE_pct": nrmse,
                "d_index": d,
                "R2": r2,
            })

        # Dynamic Multi-Harvest metric (170 observations)
        rmse_dyn, nrmse_dyn, d_dyn, r2_dyn = calc_metrics(df_all_h["OBS_FRESH_CUM"], df_all_h["SIM_FRESH_CUM"])
        summary_rows.append({
            "sldr": sldr,
            "dataset": "Two-Spring_Dynamic",
            "N": len(df_all_h),
            "Obs_Mean_t": df_all_h["OBS_FRESH_CUM"].mean() / 1000.0,
            "Sim_Mean_t": df_all_h["SIM_FRESH_CUM"].mean() / 1000.0,
            "Bias_Mean_t": (df_all_h["SIM_FRESH_CUM"].mean() - df_all_h["OBS_FRESH_CUM"].mean()) / 1000.0,
            "RMSE_t": rmse_dyn / 1000.0,
            "NRMSE_pct": nrmse_dyn,
            "d_index": d_dyn,
            "R2": r2_dyn,
        })

        # Calculate Water-Nitrogen Gradients
        def get_y(season, w, n):
            sub = df_case_terms[(df_case_terms["season"] == season) & (df_case_terms["water"] == w) & (df_case_terms["nitro"] == n)]
            if not sub.empty:
                return sub["obs_t_ha"].iloc[0], sub["sim_t_ha"].iloc[0]
            return np.nan, np.nan

        for s, w_list in [("25SP", ["W3", "W2", "W1"]), ("26SP", ["W3", "W2", "W1"])]:
            for w in w_list:
                o3, s3 = get_y(s, w, "N3")
                o0, s0 = get_y(s, w, "N0")
                if np.isfinite(o3) and np.isfinite(o0):
                    og = o3 - o0
                    sg = s3 - s0
                    gradient_rows.append({
                        "sldr": sldr,
                        "season": s,
                        "water": w,
                        "Obs_N3_t": o3,
                        "Obs_N0_t": o0,
                        "Obs_Gap_t": og,
                        "Sim_N3_t": s3,
                        "Sim_N0_t": s0,
                        "Sim_Gap_t": sg,
                        "Gap_Error_t": sg - og,
                        "Gap_Ratio_pct": (sg / og * 100.0) if og != 0 else np.nan,
                    })

    df_all_terms = pd.DataFrame(all_treatments_rows)
    df_summary = pd.DataFrame(summary_rows)
    df_grads = pd.DataFrame(gradient_rows)

    df_all_terms.to_csv(EXP_DIR / "sldr_treatments_detail.csv", index=False)
    df_summary.to_csv(EXP_DIR / "sldr_summary_comparison.csv", index=False)
    df_grads.to_csv(EXP_DIR / "sldr_wn_gradients.csv", index=False)

    print("\n================================================================================")
    print("SLDR EXPERIMENT COMPLETED")
    print("================================================================================")

    # Print Gradient pivot for 25SP and 26SP
    print("\n=== WATER-NITROGEN RESPONSE GRADIENTS (Sim N3 - N0 Gap in t/ha) across SLDR ===")
    piv_grads = df_grads.pivot(index="sldr", columns=["season", "water"], values="Sim_Gap_t")
    print(piv_grads.to_string())

    print("\n=== TWO-SPRING POOLED DYNAMIC METRICS across SLDR ===")
    dyn_sub = df_summary[df_summary["dataset"] == "Two-Spring_Dynamic"][["sldr", "RMSE_t", "NRMSE_pct", "d_index", "R2"]]
    print(dyn_sub.to_string(index=False))

    print("\n=== 25SP TERMINAL METRICS across SLDR ===")
    p25_sub = df_summary[df_summary["dataset"] == "25SP"][["sldr", "RMSE_t", "NRMSE_pct", "d_index", "R2"]]
    print(p25_sub.to_string(index=False))

    print("\n=== 26SP TERMINAL METRICS across SLDR ===")
    p26_sub = df_summary[df_summary["dataset"] == "26SP"][["sldr", "RMSE_t", "NRMSE_pct", "d_index", "R2"]]
    print(p26_sub.to_string(index=False))


if __name__ == "__main__":
    main()
