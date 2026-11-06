#!/usr/bin/env python3
"""run_comprehensive_deep_water_grid.py — 
Comprehensive grid investigation of deep root water uptake in 25SP:
1. Standard 10-layer scheme with varied SRGF in 60-140cm (180cm=0)
2. Merged 30-100cm 7-layer scheme with varied SRGF and RWUMX
Strictly enforces: ICNS_25SP = 1.000, 180cm SRGF = 0.000
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
GRID_DIR = RUN_DIR / "grid_deep_water_comprehensive"
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


def build_10l_soil(srgf_map: dict, src_soil_path: Path, dst_soil_path: Path):
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
                    if depth in srgf_map:
                        new_val = srgf_map[depth]
                        line = line[:29] + f"{new_val:6.3f}" + line[35:]
                except ValueError:
                    pass
            new_lines.append(line)
        else:
            new_lines.append(line)

    dst_soil_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def build_7l_merged_soil(srgf_100: float, srgf_140: float, dst_soil_path: Path):
    # Merged 30-100 scheme
    content = f"""*XXSL2501    SCS         -99     180 Plot 9 Fields (2025 Spring 7L Scheme)
@SITE        COUNTRY          LAT     LONG SCS FAMILY
 Xinxiang    China         35.160  113.800 Sandy Loam
@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE
   -99  0.13   5.5  0.65  75.0  1.00  .933 IB001 IB001 IB001
@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC
     2   -99 0.142 0.296 0.492 1.000  3.50  1.36  0.90  15.0  20.0     0 0.081  8.13   -99   -99   -99
     4   -99 0.142 0.296 0.492 1.000  3.50  1.36  0.90  15.0  20.0     0 0.081  8.13   -99   -99   -99
    15   -99 0.142 0.296 0.492 1.000  3.50  1.36  0.90  15.0  20.0     0 0.081  8.13   -99   -99   -99
    30   -99 0.149 0.303 0.448 0.900  2.37  1.49  0.71  15.0  20.0     0 0.064  8.05   -99   -99   -99
   100   -99 0.162 0.320 0.458{srgf_100:6.3f}  1.50  1.52  0.32  15.0  20.0     0 0.029  8.00   -99   -99   -99
   140   -99 0.165 0.300 0.420{srgf_140:6.3f}  1.00  1.55  0.10  15.0  20.0     0 0.010  8.00   -99   -99   -99
   180   -99 0.160 0.280 0.380 0.000  0.80  1.60  0.08  15.0  20.0     0 0.010  8.00   -99   -99   -99
"""
    dst_soil_path.write_text(content, encoding="utf-8")


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
    }


def main():
    GRID_DIR.mkdir(parents=True, exist_ok=True)
    temp_sim_dir = GRID_DIR / "_worker"
    if temp_sim_dir.exists():
        try:
            shutil.rmtree(temp_sim_dir)
        except Exception:
            pass
    temp_sim_dir.mkdir(parents=True, exist_ok=True)
    prep_args = ["--batch", str(BATCH_25SP), "--input-dir", str(BUNDLE_25SP)]
    batch_dest = prepare_run_directory(temp_sim_dir, prep_args)

    results = []

    # ──────────────────────────────────────────────────────────
    # PART 1: 10-Layer Scheme (Prioritizing SRGF modification)
    # ──────────────────────────────────────────────────────────
    schemes_10l = [
        # (name, {depth: srgf}, rwumx)
        ("10L_Base_orig", {80: 0.20, 100: 0.20, 140: 0.00, 180: 0.00}, 0.044),
        ("10L_P1_80_0.4_100_0.3_140_0.0", {80: 0.40, 100: 0.30, 140: 0.00, 180: 0.00}, 0.044),
        ("10L_P2_80_0.6_100_0.5_140_0.0", {60: 0.75, 80: 0.60, 100: 0.50, 140: 0.00, 180: 0.00}, 0.044),
        ("10L_P3_80_0.8_100_0.7_140_0.0", {30: 0.95, 40: 0.90, 60: 0.85, 80: 0.80, 100: 0.70, 140: 0.00, 180: 0.00}, 0.044),
        
        # With 140cm active (tap roots down to 140, 180=0)
        ("10L_P4_80_0.5_100_0.3_140_0.05", {80: 0.50, 100: 0.30, 140: 0.05, 180: 0.00}, 0.044),
        ("10L_P5_80_0.5_100_0.3_140_0.10", {80: 0.50, 100: 0.30, 140: 0.10, 180: 0.00}, 0.044),
        ("10L_P6_80_0.6_100_0.4_140_0.10", {60: 0.75, 80: 0.60, 100: 0.40, 140: 0.10, 180: 0.00}, 0.044),
        ("10L_P7_80_0.7_100_0.5_140_0.15", {60: 0.80, 80: 0.70, 100: 0.50, 140: 0.15, 180: 0.00}, 0.044),
        ("10L_P8_80_0.7_100_0.5_140_0.15_rw06", {60: 0.80, 80: 0.70, 100: 0.50, 140: 0.15, 180: 0.00}, 0.060),
    ]

    # ──────────────────────────────────────────────────────────
    # PART 2: Merged 7-Layer Scheme (30-100cm unified)
    # ──────────────────────────────────────────────────────────
    schemes_7l = [
        # (name, srgf_100, srgf_140, rwumx)
        ("7L_Merged_100_0.60_140_0.00", 0.60, 0.00, 0.044),
        ("7L_Merged_100_0.75_140_0.00", 0.75, 0.00, 0.044),
        ("7L_Merged_100_0.85_140_0.00", 0.85, 0.00, 0.044),
        ("7L_Merged_100_0.75_140_0.05", 0.75, 0.05, 0.044),
        ("7L_Merged_100_0.75_140_0.10", 0.75, 0.10, 0.044),
        ("7L_Merged_100_0.85_140_0.10", 0.85, 0.10, 0.044),
        ("7L_Merged_100_0.75_140_0.00_rw06", 0.75, 0.00, 0.060),
        ("7L_Merged_100_0.75_140_0.10_rw06", 0.75, 0.10, 0.060),
    ]

    print("Running Part 1: Standard 10-Layer SRGF Variations...")
    for name, srgf_map, rwumx in schemes_10l:
        soil_tmp = GRID_DIR / f"soil_{name}.SOL"
        build_10l_soil(srgf_map, RAW_SOIL, soil_tmp)
        param_tmp = GRID_DIR / f"param_{name}.csv"
        build_param_file(rwumx, BASE_PARAM_CSV, param_tmp)

        df_h = run_one_sim(temp_sim_dir, batch_dest, param_tmp, soil_tmp)
        m = extract_metrics(df_h)
        results.append({
            "Scheme_Type": "10-Layer Standard",
            "Config_Name": name,
            "SRGF_Description": f"80cm={srgf_map.get(80,0.20)}, 100cm={srgf_map.get(100,0.20)}, 140cm={srgf_map.get(140,0.00)}",
            "RWUMX": rwumx,
            "NRMSE%": m["nrmse"],
            "d_index": m["d_index"],
            "W1N3_t": m["w1n3"],
            "W1N2_t": m["w1n2"],
            "W1N1_t": m["w1n1"],
            "W1N0_t": m["w1n0"],
            "W1_Delta_t": m["delta_w1"],
            "W3_Delta_t": m["delta_w3"],
        })
        print(f"  {name:35s} -> NRMSE: {m['nrmse']:5.2f}%, d: {m['d_index']:.4f} | W1N3: {m['w1n3']:5.2f}t, W1N0: {m['w1n0']:5.2f}t | W1 Delta: {m['delta_w1']:+5.2f}t")

    print("\nRunning Part 2: Merged 7-Layer (30-100cm) Variations...")
    for name, s100, s140, rwumx in schemes_7l:
        soil_tmp = GRID_DIR / f"soil_{name}.SOL"
        build_7l_merged_soil(s100, s140, soil_tmp)
        param_tmp = GRID_DIR / f"param_{name}.csv"
        build_param_file(rwumx, BASE_PARAM_CSV, param_tmp)

        df_h = run_one_sim(temp_sim_dir, batch_dest, param_tmp, soil_tmp)
        m = extract_metrics(df_h)
        results.append({
            "Scheme_Type": "7-Layer Merged (30-100cm)",
            "Config_Name": name,
            "SRGF_Description": f"30-100cm={s100:.2f}, 140cm={s140:.2f}, 180cm=0.0",
            "RWUMX": rwumx,
            "NRMSE%": m["nrmse"],
            "d_index": m["d_index"],
            "W1N3_t": m["w1n3"],
            "W1N2_t": m["w1n2"],
            "W1N1_t": m["w1n1"],
            "W1N0_t": m["w1n0"],
            "W1_Delta_t": m["delta_w1"],
            "W3_Delta_t": m["delta_w3"],
        })
        print(f"  {name:35s} -> NRMSE: {m['nrmse']:5.2f}%, d: {m['d_index']:.4f} | W1N3: {m['w1n3']:5.2f}t, W1N0: {m['w1n0']:5.2f}t | W1 Delta: {m['delta_w1']:+5.2f}t")

    df_all = pd.DataFrame(results)
    out_csv = GRID_DIR / "comprehensive_deep_water_grid_summary.csv"
    df_all.to_csv(out_csv, index=False)
    print(f"\nSaved results to {out_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
