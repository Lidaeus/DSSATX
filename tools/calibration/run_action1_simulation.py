#!/usr/bin/env python3
"""run_action1_simulation.py — 
Evaluate the effect of Action 1 (Enhanced deep SRGF + RWUMX) on 25SP W1 nitrogen response gradient.
Compares:
1. Baseline: Best candidate from SASC=0.945 150x5 run (standard soil SRGF & RWUMX=0.04)
2. Action 1: Best candidate + Deep SRGF (80cm=0.35, 100cm=0.30, 140cm=0.15, 180cm=0.05) + RWUMX=0.07
3. Action 1 + Action 2: Action 1 + ICNS_25SP=0.70 (calibrated active soil mineral N)
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
FROZEN_BOUNDS_CSV = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_full_gen_page22_sasc0945_20260918.csv"
CASE_PREFIX = "full_gen_p22_s0945_150x5"

BATCH_25SP = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch.v48"
BUNDLE_25SP = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2501_v20260917_refresh"

TMT_LABELS_25SP = {
    2: "W3N3", 3: "W3N2", 4: "W3N1", 5: "W3N0",
    6: "W2N3", 9: "W2N0",
    10: "W1N3", 11: "W1N2", 12: "W1N1", 13: "W1N0",
    14: "CKN2",
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


def create_action1_soil_sol(src_soil_path: Path, dst_soil_path: Path):
    """Create SOIL.SOL with enhanced deep SRGF for XXSL2501 (and XXSL2601):
    Layer 7 (80 cm): 0.350
    Layer 8 (100 cm): 0.300
    Layer 9 (140 cm): 0.150
    Layer 10 (180 cm): 0.050
    """
    lines = src_soil_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    in_xxsl = False

    for line in lines:
        if line.startswith("*XXSL2501") or line.startswith("*XXSL2601"):
            in_xxsl = True
            new_lines.append(line)
        elif line.startswith("*") and in_xxsl and not (line.startswith("*XXSL2501") or line.startswith("*XXSL2601")):
            in_xxsl = False
            new_lines.append(line)
        elif in_xxsl and line.strip() and not line.strip().startswith(("@", "!", "$", "*")):
            # Check layer depth
            parts = line.split()
            if len(parts) >= 6:
                try:
                    depth = int(parts[0])
                    srgf = float(parts[5])
                    if depth == 80:
                        line = line[:29] + f"{0.350:6.3f}" + line[35:]
                    elif depth == 100:
                        line = line[:29] + f"{0.300:6.3f}" + line[35:]
                    elif depth == 140:
                        line = line[:29] + f"{0.150:6.3f}" + line[35:]
                    elif depth == 180:
                        line = line[:29] + f"{0.050:6.3f}" + line[35:]
                except ValueError:
                    pass
            new_lines.append(line)
        else:
            new_lines.append(line)

    dst_soil_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"Action 1 SOIL.SOL created at {dst_soil_path}")


def run_simulation(out_dir: Path, param_csv: Path, soil_sol_path: Path = None):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    prep_args = ["--batch", str(BATCH_25SP), "--input-dir", str(BUNDLE_25SP)]
    batch_dest = prepare_run_directory(out_dir, prep_args)

    # Override SOIL.SOL if provided
    if soil_sol_path and soil_sol_path.exists():
        shutil.copy2(soil_sol_path, out_dir / "SOIL.SOL")
        shutil.copy2(soil_sol_path, out_dir / "SOIL.SOL.base")

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
        raise RuntimeError(f"Simulation failed in {out_dir}:\n{res.stderr[-400:]}")

    df_h, _ = evaluate_run(batch_dest, out_dir)
    return df_h, out_dir


def extract_treatment_results(df_h: pd.DataFrame, label_tag: str):
    records = []
    for tn, group in df_h.groupby("TN"):
        last_row = group.sort_values("DATE").iloc[-1]
        obs = float(last_row["OBS_FRESH_CUM"])
        sim = float(last_row["SIM_FRESH_CUM"])
        lbl = TMT_LABELS_25SP.get(tn, f"TN{tn}")
        water = lbl[:2] if len(lbl) >= 2 else "Unknown"
        nitro = lbl[2:] if len(lbl) >= 4 else "Unknown"
        records.append({
            "config": label_tag,
            "treatment": tn,
            "label": lbl,
            "water": water,
            "nitro": nitro,
            "obs_kg_ha": obs,
            "sim_kg_ha": sim,
            "bias_kg_ha": sim - obs,
            "bias_pct": (sim - obs) / obs * 100.0 if obs > 0 else 0.0,
        })
    return pd.DataFrame(records)


def main():
    phi_csv = RUN_DIR / f"{CASE_PREFIX}.phi.actual.csv"
    if not phi_csv.exists():
        print(f"Waiting for {phi_csv}...")
        return 1

    df_phi = pd.read_csv(phi_csv)
    last_iter = len(df_phi) - 1
    par_csv = RUN_DIR / f"{CASE_PREFIX}.{last_iter}.par.csv"
    if not par_csv.exists():
        par_csv = RUN_DIR / f"{CASE_PREFIX}.par.csv"
    df_par = pd.read_csv(par_csv)

    valid_reals = set(df_par["real_name"].astype(str))
    cols = [c for c in df_phi.columns if str(c) in valid_reals and str(c).lower() != "base"]
    phi_series = df_phi.iloc[last_iter][cols].astype(float)
    best_real = str(phi_series.idxmin())
    best_phi = float(phi_series.min())

    print(f"\n================ Selected Best Candidate from 150x5 Run ================")
    print(f"Candidate: iter{last_iter}_real{best_real}, Phi = {best_phi:.2f}")

    # 1. Build baseline parameter CSV
    base_param_csv = RUN_DIR / f"candidate_best_sasc0945_params.csv"
    build_candidate_param_csv(best_real, df_par, FROZEN_BOUNDS_CSV, base_param_csv)

    # 2. Build Action 1 parameter CSV (add/update RWUMX=0.07)
    action1_param_csv = RUN_DIR / "candidate_action1_params.csv"
    df_p1 = pd.read_csv(base_param_csv)
    if "RWUMX" in df_p1["name"].values:
        df_p1.loc[df_p1["name"] == "RWUMX", "value"] = 0.07
    else:
        df_p1 = pd.concat([df_p1, pd.DataFrame([{"name": "RWUMX", "value": 0.07}])], ignore_index=True)
    df_p1.to_csv(action1_param_csv, index=False)

    # 3. Build Action 1 + Action 2 parameter CSV (RWUMX=0.07 + ICNS_25SP=0.70)
    action1_2_param_csv = RUN_DIR / "candidate_action1_action2_params.csv"
    df_p12 = pd.read_csv(action1_param_csv)
    if "ICNS_25SP" in df_p12["name"].values:
        df_p12.loc[df_p12["name"] == "ICNS_25SP", "value"] = 0.70
    else:
        df_p12 = pd.concat([df_p12, pd.DataFrame([{"name": "ICNS_25SP", "value": 0.70}])], ignore_index=True)
    df_p12.to_csv(action1_2_param_csv, index=False)

    # 4. Create Action 1 SOIL.SOL
    action1_soil = RUN_DIR / "SOIL_action1.SOL"
    raw_soil = PROJECT_ROOT / "data" / "raw" / "soil" / "SOIL.SOL"
    create_action1_soil_sol(raw_soil, action1_soil)

    # ─── Execute 3 Runs ───
    print("\n--- Running 1: Baseline Simulation ---")
    df_h_base, dir_base = run_simulation(RUN_DIR / "sim_baseline_25sp", base_param_csv)
    res_base = extract_treatment_results(df_h_base, "1. Baseline (SASC=0.945)")

    print("\n--- Running 2: Action 1 Simulation (Deep SRGF + RWUMX=0.07) ---")
    df_h_act1, dir_act1 = run_simulation(RUN_DIR / "sim_action1_25sp", action1_param_csv, action1_soil)
    res_act1 = extract_treatment_results(df_h_act1, "2. Action 1 (Deep SRGF + RWUMX=0.07)")

    print("\n--- Running 3: Action 1 + Action 2 (Deep SRGF + RWUMX=0.07 + ICNS_25SP=0.70) ---")
    df_h_act12, dir_act12 = run_simulation(RUN_DIR / "sim_action1_2_25sp", action1_2_param_csv, action1_soil)
    res_act12 = extract_treatment_results(df_h_act12, "3. Action 1+2 (+ ICNS_25SP=0.70)")

    df_all = pd.concat([res_base, res_act1, res_act12], ignore_index=True)
    df_all.to_csv(RUN_DIR / "action1_comparison_treatment_details.csv", index=False)

    # Summary table
    summary_rows = []
    for cfg_name, sub in df_all.groupby("config"):
        rmse, nrmse, d, r2 = calc_metrics(sub["obs_kg_ha"], sub["sim_kg_ha"])
        
        def get_val(w, n):
            r = sub[(sub["water"] == w) & (sub["nitro"] == n)]
            return float(r["sim_kg_ha"].iloc[0]) if len(r) > 0 else np.nan

        w1n3 = get_val("W1", "N3")
        w1n2 = get_val("W1", "N2")
        w1n1 = get_val("W1", "N1")
        w1n0 = get_val("W1", "N0")
        delta_w1 = (w1n3 - w1n0) / 1000.0

        w3n3 = get_val("W3", "N3")
        w3n0 = get_val("W3", "N0")
        delta_w3 = (w3n3 - w3n0) / 1000.0

        summary_rows.append({
            "Configuration": cfg_name,
            "25SP NRMSE%": f"{nrmse:.2f}%",
            "d-index": f"{d:.4f}",
            "W1N3 (t)": f"{w1n3/1000.0:.2f}",
            "W1N2 (t)": f"{w1n2/1000.0:.2f}",
            "W1N1 (t)": f"{w1n1/1000.0:.2f}",
            "W1N0 (t)": f"{w1n0/1000.0:.2f}",
            "W1 Delta (N3-N0 t)": f"{delta_w1:+.2f}t",
            "W3 Delta (N3-N0 t)": f"{delta_w3:+.2f}t",
        })

    obs_w1n3 = 71.137
    obs_w1n2 = 72.151
    obs_w1n1 = 71.915
    obs_w1n0 = 59.547
    obs_w1_delta = obs_w1n3 - obs_w1n0
    obs_w3_delta = 72.323 - 68.228

    summary_rows.append({
        "Configuration": "* Observed (Ground Truth)",
        "25SP NRMSE%": "0.00%",
        "d-index": "1.0000",
        "W1N3 (t)": f"{obs_w1n3:.2f}",
        "W1N2 (t)": f"{obs_w1n2:.2f}",
        "W1N1 (t)": f"{obs_w1n1:.2f}",
        "W1N0 (t)": f"{obs_w1n0:.2f}",
        "W1 Delta (N3-N0 t)": f"{obs_w1_delta:+.2f}t",
        "W3 Delta (N3-N0 t)": f"{obs_w3_delta:+.2f}t",
    })

    df_summary = pd.DataFrame(summary_rows)
    df_summary.to_csv(RUN_DIR / "action1_comparison_summary.csv", index=False)

    print("\n================ 25SP W1 NITROGEN RESPONSE COMPARISON ================")
    print(df_summary.to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
