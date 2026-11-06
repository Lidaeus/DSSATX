#!/usr/bin/env python3
"""Evaluate Literature-Mapped SSKS on 10-Layer Soil Scheme for candidate iter5_real13.

Mapping of literature Ks measurements to 10L-B DSSAT profile:
  SLB: [2, 4, 15, 30, 40, 60, 80, 100, 140, 180] cm
Literature points:
  20 cm: 2.03 cm/h (sandy loam)
  30 cm: 1.81 cm/h (sandy loam)
  50 cm: 0.33 cm/h (loam)
  80 cm: 2.59 cm/h (sandy loam)
 100 cm: 0.27 cm/h (silty clay)
 120 cm: 0.072 cm/h (clay)
 140 cm: 0.234 cm/h (silty clay)
 160 cm: 0.702 cm/h (silt loam)

Method 1 (Horizon Step-Weighted):
  L01 (0-2 cm): 2.03 cm/h
  L02 (2-4 cm): 2.03 cm/h
  L03 (4-15 cm): 2.03 cm/h
  L04 (15-30 cm): 1.96 cm/h
  L05 (30-40 cm): 1.81 cm/h
  L06 (40-60 cm): 0.33 cm/h
  L07 (60-80 cm): 2.03 cm/h
  L08 (80-100 cm): 1.43 cm/h
  L09 (100-140 cm): 0.16 cm/h
  L10 (140-180 cm): 0.59 cm/h

Method 2 (Continuous Linear-Integral):
  L01 (0-2 cm): 2.03 cm/h
  L02 (2-4 cm): 2.03 cm/h
  L03 (4-15 cm): 2.03 cm/h
  L04 (15-30 cm): 1.96 cm/h
  L05 (30-40 cm): 1.44 cm/h
  L06 (40-60 cm): 0.71 cm/h
  L07 (60-80 cm): 1.84 cm/h
  L08 (80-100 cm): 1.43 cm/h
  L09 (100-140 cm): 0.16 cm/h
  L10 (140-180 cm): 0.59 cm/h
"""
from __future__ import annotations

import os
import sys
import shutil
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd

ROOT_DIR = Path("D:/Tomato_Cal")
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.eval_full_gen98 import evaluate_run, calc_metrics

EXP_DIR = ROOT_DIR / "workspace/experiments/ssks_mapped_10l_eval"
EXP_DIR.mkdir(parents=True, exist_ok=True)

SRC_RUN_DIR = ROOT_DIR / "workspace/runs/full_gen_page22_sasc0925_150x5_20260918"
PARAM_CSV = SRC_RUN_DIR / "candidate_iter5_real13_params.csv"

# Treatment metadata
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


def modify_soil_ssks(soil_text: str, ssks_values: list[float]) -> str:
    """Replace the SSKS column (col 36-42) in *XXSL2501 and *XXSL2601 10-layer profiles."""
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
                    assert len(val_str) == 6
                    new_line = s[:36] + val_str + s[42:] + "\n"
                    out.append(new_line)
                    layer_idx += 1
                    continue

        out.append(line)

    return "".join(out)


def setup_and_run(case_name: str, ssks_values: list[float]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Setup run environment, modify SSKS, run DSSAT for 25SP and 26SP, and extract results."""
    print(f"\n=======================================================")
    print(f"Executing Case: {case_name}")
    print(f"SSKS Values (L1..L10): {ssks_values}")
    print(f"=======================================================")

    case_dir = EXP_DIR / case_name
    case_dir.mkdir(parents=True, exist_ok=True)

    # Also sync C:\DSSAT48\Soil\SOIL.SOL for complete safety
    c_sol = Path(r"C:\DSSAT48\Soil\SOIL.SOL")
    if c_sol.exists():
        c_text = c_sol.read_text(encoding="utf-8", errors="ignore")
        c_mod = modify_soil_ssks(c_text, ssks_values)
        c_sol.write_text(c_mod, encoding="utf-8")

    results_25sp = run_single_season("25SP", case_dir / "run_25SP", ssks_values)
    results_26sp = run_single_season("26SP", case_dir / "run_26SP", ssks_values)

    df_comb = pd.concat([results_25sp, results_26sp], ignore_index=True)
    df_comb["case"] = case_name
    return df_comb, results_25sp, results_26sp


def run_single_season(season: str, run_dir: Path, ssks_values: list[float]) -> pd.DataFrame:
    """Setup directory for a single season, inject SSKS into SOIL.SOL and SOIL.SOL.base, and run DSSAT."""
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    src_season_dir = SRC_RUN_DIR / f"full_season_iter5_real13_{season}"
    if not src_season_dir.exists():
        raise FileNotFoundError(f"Source season dir not found: {src_season_dir}")

    # Copy all files from the pristine baseline run
    for f in src_season_dir.iterdir():
        if f.is_file():
            shutil.copy2(f, run_dir / f.name)

    # Ensure params.csv is present
    shutil.copy2(PARAM_CSV, run_dir / "params.csv")

    # Update SSKS in SOIL.SOL and SOIL.SOL.base
    soil_base = run_dir / "SOIL.SOL.base"
    soil_sol = run_dir / "SOIL.SOL"

    template_soil = soil_sol if soil_sol.exists() else soil_base
    soil_text = template_soil.read_text(encoding="utf-8", errors="ignore")
    modified_soil = modify_soil_ssks(soil_text, ssks_values)

    soil_base.write_text(modified_soil, encoding="utf-8")
    soil_sol.write_text(modified_soil, encoding="utf-8")

    # Run DSSAT
    cmd = [
        sys.executable,
        "-m",
        "src.dssat.run_dssat",
        "--param-csv",
        "params.csv",
        "--batch",
        "DSSBatch.v48",
        "--harvest-var",
        "CHPDT",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    res = subprocess.run(cmd, cwd=run_dir, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        print(f"ERROR: DSSAT run failed in {run_dir}")
        print("STDOUT:", res.stdout[-1000:] if res.stdout else "")
        print("STDERR:", res.stderr[-1000:] if res.stderr else "")
        raise RuntimeError(f"DSSAT execution failed for {season}")

    # Evaluate harvest outputs
    batch_file = run_dir / "DSSBatch.v48"
    df_h, _ = evaluate_run(batch_file, run_dir)

    rows = []
    for tn, group in df_h.groupby("TN"):
        last = group.sort_values("DATE").iloc[-1]
        obs_val = float(last["OBS_FRESH_CUM"])
        sim_val = float(last["SIM_FRESH_CUM"])
        bias = sim_val - obs_val
        rel_bias = (bias / obs_val * 100.0) if obs_val > 0 else 0.0

        meta = TMT_INFO.get((season, tn), {"water": "Unknown", "nitro": "Unknown", "label": f"TN{tn}"})
        rmse_t, nrmse_t, d_t, r2_t = calc_metrics(group["OBS_FRESH_CUM"], group["SIM_FRESH_CUM"])

        rows.append({
            "season": season,
            "treatment": tn,
            "label": meta["label"],
            "water": meta["water"],
            "nitro": meta["nitro"],
            "obs_yield_kg_ha": obs_val,
            "sim_yield_kg_ha": sim_val,
            "obs_yield_t_ha": obs_val / 1000.0,
            "sim_yield_t_ha": sim_val / 1000.0,
            "bias_kg_ha": bias,
            "bias_t_ha": bias / 1000.0,
            "rel_error_pct": rel_bias,
            "dyn_rmse": rmse_t,
            "dyn_nrmse_pct": nrmse_t,
            "dyn_d_index": d_t,
            "dyn_r2": r2_t,
        })

    return pd.DataFrame(rows)


def analyze_and_report(df_all: pd.DataFrame):
    """Compute performance metrics and water-nitrogen gradients across cases."""
    cases = df_all["case"].unique()
    
    summary_rows = []
    gradient_rows = []

    for c in cases:
        sub_c = df_all[df_all["case"] == c]
        for s in ["25SP", "26SP", "Pooled"]:
            if s == "Pooled":
                sub_s = sub_c
            else:
                sub_s = sub_c[sub_c["season"] == s]

            rmse, nrmse, d, r2 = calc_metrics(sub_s["obs_yield_kg_ha"], sub_s["sim_yield_kg_ha"])
            nse = 1.0 - np.sum((sub_s["sim_yield_kg_ha"] - sub_s["obs_yield_kg_ha"])**2) / np.sum((sub_s["obs_yield_kg_ha"] - sub_s["obs_yield_kg_ha"].mean())**2)
            summary_rows.append({
                "case": c,
                "dataset": s,
                "N": len(sub_s),
                "Obs_Mean_t": sub_s["obs_yield_t_ha"].mean(),
                "Sim_Mean_t": sub_s["sim_yield_t_ha"].mean(),
                "Bias_Mean_t": sub_s["bias_t_ha"].mean(),
                "RMSE_t": rmse / 1000.0,
                "NRMSE_pct": nrmse,
                "d_index": d,
                "R2": r2,
                "NSE": nse,
            })

        # Calculate W-N gradients (N3 - N0)
        def get_yield(season, water, nitro):
            match = sub_c[(sub_c["season"] == season) & (sub_c["water"] == water) & (sub_c["nitro"] == nitro)]
            if not match.empty:
                return match["obs_yield_t_ha"].iloc[0], match["sim_yield_t_ha"].iloc[0]
            return np.nan, np.nan

        for season, water_list in [("25SP", ["W3", "W2", "W1"]), ("26SP", ["W3", "W2", "W1"])]:
            for w in water_list:
                obs_n3, sim_n3 = get_yield(season, w, "N3")
                obs_n0, sim_n0 = get_yield(season, w, "N0")
                if np.isfinite(obs_n3) and np.isfinite(obs_n0):
                    obs_gap = obs_n3 - obs_n0
                    sim_gap = sim_n3 - sim_n0
                    gradient_rows.append({
                        "case": c,
                        "season": season,
                        "water": w,
                        "Obs_N3_t": obs_n3,
                        "Obs_N0_t": obs_n0,
                        "Obs_Gap_t": obs_gap,
                        "Sim_N3_t": sim_n3,
                        "Sim_N0_t": sim_n0,
                        "Sim_Gap_t": sim_gap,
                        "Gap_Error_t": sim_gap - obs_gap,
                        "Gap_Ratio_pct": (sim_gap / obs_gap * 100.0) if obs_gap != 0 else np.nan,
                    })

    df_summary = pd.DataFrame(summary_rows)
    df_gradients = pd.DataFrame(gradient_rows)

    return df_summary, df_gradients


def main():
    print("Starting Literature SSKS Mapping Evaluation on 10-Layer Soil Scheme...")

    # Case 0: Baseline 10L (Original 10L-B values: [3.50, 3.50, 3.50, 2.37, 1.80, 1.20, 1.50, 1.60, 1.00, 0.80])
    ssks_baseline = [3.50, 3.50, 3.50, 2.37, 1.80, 1.20, 1.50, 1.60, 1.00, 0.80]

    # Case 1: Horizon Step-Weighted Literature Ks Mapping
    ssks_step = [2.03, 2.03, 2.03, 1.96, 1.81, 0.33, 2.03, 1.43, 0.16, 0.59]

    # Case 2: Continuous Linear-Integral Literature Ks Mapping
    ssks_linear = [2.03, 2.03, 2.03, 1.96, 1.44, 0.71, 1.84, 1.43, 0.16, 0.59]

    all_dfs = []

    # Run Baseline
    df_base, _, _ = setup_and_run("10L_Baseline_Original", ssks_baseline)
    all_dfs.append(df_base)

    # Run Case 1: Horizon Step-Weighted
    df_step, _, _ = setup_and_run("10L_Mapped_StepWeighted", ssks_step)
    all_dfs.append(df_step)

    # Run Case 2: Linear-Integral
    df_linear, _, _ = setup_and_run("10L_Mapped_LinearIntegral", ssks_linear)
    all_dfs.append(df_linear)

    df_all = pd.concat(all_dfs, ignore_index=True)
    df_all.to_csv(EXP_DIR / "treatment_results_comparison.csv", index=False)

    df_summary, df_gradients = analyze_and_report(df_all)
    df_summary.to_csv(EXP_DIR / "metrics_summary_comparison.csv", index=False)
    df_gradients.to_csv(EXP_DIR / "wn_gradient_comparison.csv", index=False)

    print("\n========================= METRICS SUMMARY =========================")
    print(df_summary.to_string(index=False))

    print("\n==================== WATER-NITROGEN GRADIENTS ====================")
    print(df_gradients.to_string(index=False))

    print("\n================== TREATMENT LEVEL (Step-Weighted) ==================")
    step_tmt = df_all[df_all["case"] == "10L_Mapped_StepWeighted"][
        ["season", "treatment", "label", "water", "nitro", "obs_yield_t_ha", "sim_yield_t_ha", "bias_t_ha", "rel_error_pct", "dyn_nrmse_pct"]
    ]
    print(step_tmt.to_string(index=False))


if __name__ == "__main__":
    main()
