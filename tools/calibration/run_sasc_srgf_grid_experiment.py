#!/usr/bin/env python3
"""SASC_RATIO x SRGF (80/100/140cm) Grid Simulation Experiment for CROPGRO-Eggplant.

Based on champion candidate iter4_real81 (full_genetic_century_sasc_20260918).
Grid Design:
  - SASC_RATIO: [0.85, 0.88, 0.91, 0.94] (4 levels)
  - SRGF_80_100: [0.15, 0.25, 0.35] (3 levels, Layer 7 & 8)
  - SRGF_140: [0.00, 0.05, 0.10, 0.15] (4 levels, Layer 9)
  - SRGF_180: 0.000 (strictly zero, Layer 10)
Total 48 combinations evaluated across:
  1. Calibration (8 runs, 25SP & 26SP)
  2. Validation (15 runs, 25SP & 26SP)
  3. 25FA Independent Generalization (12 runs)
Outputs comprehensive metrics and water-nitrogen response fidelity.
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

from tools.soil.build_dual_plot_soil_profiles_20260917 import (
    PHYSICAL_LAYERS, CHEM_25SP, CHEM_26SP, RAW_SOL
)
from src.calibration.run_dssat import prepare_run_directory
from tools.eval_full_gen98 import evaluate_run, calc_metrics

BASE_PARAMS_CSV = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_century_sasc_20260918" / "candidate_iter4_real81_params.csv"
GRID_OUT_DIR = PROJECT_ROOT / "workspace" / "runs" / "grid_sasc_srgf_20260918"

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

def generate_custom_soil_sol(srgf_80_100: float, srgf_140: float, out_path: Path):
    """Generate SOIL.SOL with specified SRGF for layers 7, 8, 9, 10."""
    custom_layers = []
    for row in PHYSICAL_LAYERS:
        slb, slll, sdul, ssat, srgf, ssks, sbdm, slcl, slsi, slcf = row
        if slb in (80, 100):
            srgf = srgf_80_100
        elif slb == 140:
            srgf = srgf_140
        elif slb == 180:
            srgf = 0.000
        custom_layers.append((slb, slll, sdul, ssat, srgf, ssks, sbdm, slcl, slsi, slcf))

    def format_custom(soil_id, desc, chem_layers):
        lines = [
            f"*{soil_id:10s}  SCS         -99     180 {desc}",
            "@SITE        COUNTRY          LAT     LONG SCS FAMILY",
            " Xinxiang    China         35.160  113.800 Sandy Loam",
            "@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE",
            "   -99  0.13   5.5  0.65  75.0  1.00  .933 IB001 IB001 IB001",
            "@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC",
        ]
        for (slb, slll, sdul, ssat, srgf, ssks, sbdm, slcl, slsi, slcf), (slni, slhw, sloc) in zip(custom_layers, chem_layers):
            line = (
                f"{slb:6d}   -99{slll:6.3f}{sdul:6.3f}{ssat:6.3f}{srgf:6.3f}{ssks:6.2f}"
                f"{sbdm:6.2f}{sloc:6.2f}{slcl:6.1f}{slsi:6.1f}{slcf:6d}{slni:6.3f}{slhw:6.2f}   -99   -99   -99"
            )
            lines.append(line)
        return lines

    p25 = format_custom("XXSL2501", "Plot 9 Fields (2025 Spring 10L-B Scheme)", CHEM_25SP)
    p26 = format_custom("XXSL2601", "Plot 2 Fields (2026 Spring & 2025 Autumn 10L-B Scheme)", CHEM_26SP)
    both = p25 + p26

    text = RAW_SOL.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    xxsl25_idx = None
    for i, l in enumerate(lines):
        if l.startswith("*XXSL2501"):
            xxsl25_idx = i
            break
    if xxsl25_idx is not None:
        target_end = len(lines)
        for j in range(xxsl25_idx + 1, len(lines)):
            if lines[j].startswith("*") and not lines[j].startswith("*XXSL2501") and not lines[j].startswith("*XXSL2601"):
                target_end = j
                break
        new_lines = lines[:xxsl25_idx] + both + lines[target_end:]
    else:
        new_lines = both + lines
    out_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8", newline="\n")


def run_batch_with_soil(batch_path: Path, param_csv: Path, soil_sol_path: Path, out_dir: Path, input_dir: Path = None):
    """Run DSSAT batch ensuring custom SOIL.SOL is used."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    prep_args = ["--batch", str(batch_path)]
    if input_dir:
        prep_args.extend(["--input-dir", str(input_dir)])
    batch_dest = prepare_run_directory(out_dir, prep_args)

    # Overwrite SOIL.SOL and SOIL.SOL.base in out_dir with custom soil
    shutil.copy2(soil_sol_path, out_dir / "SOIL.SOL")
    shutil.copy2(soil_sol_path, out_dir / "SOIL.SOL.base")

    # Update DSSATPRO.v48 SLD to out_dir
    dssatpro = out_dir / "DSSATPRO.v48"
    if dssatpro.exists():
        lines = dssatpro.read_text(encoding="utf-8").splitlines()
        new_lines = []
        drive, rest = os.path.splitdrive(str(out_dir.resolve()))
        for l in lines:
            if l.startswith("SLD "):
                new_lines.append(f"SLD {drive} {rest}")
            else:
                new_lines.append(l)
        dssatpro.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

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


def evaluate_grid_combo(combo_id: str, sasc: float, srgf_80_100: float, srgf_140: float,
                        work_base: Path, base_param_df: pd.DataFrame):
    """Run Calib, Valid, and 25FA for one parameter combination."""
    combo_dir = work_base / combo_id
    combo_dir.mkdir(parents=True, exist_ok=True)

    # 1. Prepare parameter CSV
    p_df = base_param_df.copy()
    p_df.loc[p_df["name"].str.lower() == "sasc_ratio", "value"] = sasc
    param_csv = combo_dir / "params.csv"
    p_df.to_csv(param_csv, index=False)

    # 2. Prepare custom SOIL.SOL
    soil_sol = combo_dir / "SOIL.SOL"
    generate_custom_soil_sol(srgf_80_100, srgf_140, soil_sol)

    # 3. Calibration batch (8 runs)
    calib_dir = combo_dir / "calib"
    df_h_c, df_eval_c = run_batch_with_soil(CALIB_BATCH, param_csv, soil_sol, calib_dir)
    rmse_c, nrmse_c, d_c, r2_c = calc_metrics(df_h_c["OBS_FRESH_CUM"], df_h_c["SIM_FRESH_CUM"])

    # 4. Validation batch (15 runs)
    valid_dir = combo_dir / "valid"
    df_h_v, df_eval_v = run_batch_with_soil(VALID_BATCH, param_csv, soil_sol, valid_dir)
    rmse_v, nrmse_v, d_v, r2_v = calc_metrics(df_h_v["OBS_FRESH_CUM"], df_h_v["SIM_FRESH_CUM"])

    # 5. Two Spring Pooled (23 runs)
    df_h_sp = pd.concat([df_h_c, df_h_v], ignore_index=True)
    rmse_sp, nrmse_sp, d_sp, r2_sp = calc_metrics(df_h_sp["OBS_FRESH_CUM"], df_h_sp["SIM_FRESH_CUM"])

    # 6. 25FA Independent generalization (12 runs)
    fa_dir = combo_dir / "25fa"
    df_h_fa, df_eval_fa = run_batch_with_soil(BATCH_25FA, param_csv, soil_sol, fa_dir, input_dir=BUNDLE_25FA)
    rmse_fa, nrmse_fa, d_fa, r2_fa = calc_metrics(df_h_fa["OBS_FRESH_CUM"], df_h_fa["SIM_FRESH_CUM"])

    # 7. Grand Pooled (All 35 runs)
    df_h_all = pd.concat([df_h_sp, df_h_fa], ignore_index=True)
    rmse_all, nrmse_all, d_all, r2_all = calc_metrics(df_h_all["OBS_FRESH_CUM"], df_h_all["SIM_FRESH_CUM"])

    # Tagged harvest data
    df_all_tagged = pd.concat([
        df_h_c.assign(batch="Calibration"),
        df_h_v.assign(batch="Validation"),
        df_h_fa.assign(batch="Independent_25FA"),
    ], ignore_index=True)

    # Treatment level metrics
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
            "combo_id": combo_id,
            "sasc": sasc,
            "srgf_80_100": srgf_80_100,
            "srgf_140": srgf_140,
            "season": meta["season"],
            "excode": excode,
            "treatment": tn,
            "label": meta["label"],
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

    # Gradients (in t/ha: kg/ha / 1000.0)
    def get_term_sim(season_id, water_lvl, nitro_lvl):
        sub = df_term[(df_term["season"] == season_id) & (df_term["water"] == water_lvl) & (df_term["nitro"] == nitro_lvl)]
        return float(sub.iloc[0]["sim_terminal_kg_ha"]) / 1000.0 if not sub.empty else np.nan

    w2_26_sim = get_term_sim("26SP", "W2", "N3") - get_term_sim("26SP", "W2", "N0")
    w1_26_sim = get_term_sim("26SP", "W1", "N3") - get_term_sim("26SP", "W1", "N0")
    w3_26_sim = get_term_sim("26SP", "W3", "N3") - get_term_sim("26SP", "W3", "N0")
    w3_25_sim = get_term_sim("25SP", "W3", "N3") - get_term_sim("25SP", "W3", "N0")
    w1_25_sim = get_term_sim("25SP", "W1", "N3") - get_term_sim("25SP", "W1", "N0")

    # Water response gaps (W3 vs W1)
    w_gap_26_n3 = get_term_sim("26SP", "W3", "N3") - get_term_sim("26SP", "W1", "N3")
    w_gap_26_n0 = get_term_sim("26SP", "W3", "N0") - get_term_sim("26SP", "W1", "N0")

    # Clean intermediate batch dirs to save disk space
    shutil.rmtree(calib_dir, ignore_errors=True)
    shutil.rmtree(valid_dir, ignore_errors=True)
    shutil.rmtree(fa_dir, ignore_errors=True)

    summary_row = {
        "combo_id": combo_id,
        "sasc_ratio": sasc,
        "srgf_80_100": srgf_80_100,
        "srgf_140": srgf_140,
        # Calibration (8)
        "nrmse_calib": nrmse_c,
        "rmse_calib": rmse_c,
        "d_index_calib": d_c,
        "r2_calib": r2_c,
        # Validation (15)
        "nrmse_valid": nrmse_v,
        "rmse_valid": rmse_v,
        "d_index_valid": d_v,
        "r2_valid": r2_v,
        # Spring pooled (23)
        "nrmse_spring": nrmse_sp,
        "rmse_spring": rmse_sp,
        "d_index_spring": d_sp,
        "r2_spring": r2_sp,
        # 25FA (12)
        "nrmse_25fa": nrmse_fa,
        "rmse_25fa": rmse_fa,
        "d_index_25fa": d_fa,
        "r2_25fa": r2_fa,
        # All 35 pooled
        "nrmse_all35": nrmse_all,
        "rmse_all35": rmse_all,
        "d_index_all35": d_all,
        "r2_all35": r2_all,
        # Nitrogen response gaps (t/ha, simulated)
        "sim_26SP_W1_gap_t_ha": w1_26_sim,  # field obs: +16.50
        "sim_26SP_W2_gap_t_ha": w2_26_sim,  # field obs: +9.50
        "sim_26SP_W3_gap_t_ha": w3_26_sim,  # field obs: +16.00
        "sim_25SP_W1_gap_t_ha": w1_25_sim,  # field obs: +11.60
        "sim_25SP_W3_gap_t_ha": w3_25_sim,  # field obs: +4.10
        # Water response gaps (t/ha, simulated)
        "sim_26SP_N3_Wgap_t_ha": w_gap_26_n3, # W3N3 - W1N3
        "sim_26SP_N0_Wgap_t_ha": w_gap_26_n0, # W3N0 - W1N0
    }
    return summary_row, df_term


def main():
    GRID_OUT_DIR.mkdir(parents=True, exist_ok=True)
    base_param_df = pd.read_csv(BASE_PARAMS_CSV)

    # Grid definition
    sasc_levels = [0.85, 0.88, 0.91, 0.94]
    srgf_80_100_levels = [0.15, 0.25, 0.35]
    srgf_140_levels = [0.00, 0.05, 0.10, 0.15]

    total_runs = len(sasc_levels) * len(srgf_80_100_levels) * len(srgf_140_levels)
    print(f"Starting SASC x SRGF Grid Experiment ({total_runs} combinations)...")
    print(f"  SASC_RATIO: {sasc_levels}")
    print(f"  SRGF_80_100: {srgf_80_100_levels}")
    print(f"  SRGF_140: {srgf_140_levels}")
    print(f"  SRGF_180: [0.000] (fixed)")
    print(f"  Base Parameters: {BASE_PARAMS_CSV.name} (iter4_real81)")

    summary_file = GRID_OUT_DIR / "grid_results_summary.csv"
    detail_file = GRID_OUT_DIR / "grid_treatments_detail.csv"

    # Resume capability
    existing_combos = set()
    summary_records = []
    detail_records = []
    if summary_file.exists():
        df_prev = pd.read_csv(summary_file)
        existing_combos = set(df_prev["combo_id"].astype(str))
        summary_records = df_prev.to_dict(orient="records")
        print(f"Loaded {len(existing_combos)} existing evaluated combinations.")
    if detail_file.exists():
        df_prev_det = pd.read_csv(detail_file)
        detail_records = [df_prev_det]

    start_all = time.time()
    count = len(existing_combos)

    for sasc in sasc_levels:
        for srgf_80_100 in srgf_80_100_levels:
            for srgf_140 in srgf_140_levels:
                combo_id = f"sasc_{sasc:.2f}_srgf_{srgf_80_100:.2f}_{srgf_140:.2f}"
                if combo_id in existing_combos:
                    continue

                count += 1
                t0 = time.time()
                print(f"[{count:02d}/{total_runs:02d}] Evaluating {combo_id} (SASC={sasc:.2f}, SRGF_80_100={srgf_80_100:.2f}, SRGF_140={srgf_140:.2f})...", end="", flush=True)

                s_row, df_term = evaluate_grid_combo(
                    combo_id=combo_id,
                    sasc=sasc,
                    srgf_80_100=srgf_80_100,
                    srgf_140=srgf_140,
                    work_base=GRID_OUT_DIR,
                    base_param_df=base_param_df
                )
                summary_records.append(s_row)
                detail_records.append(df_term)
                existing_combos.add(combo_id)

                elapsed = time.time() - t0
                print(f" Done ({elapsed:.1f}s) | Spring NRMSE: {s_row['nrmse_spring']:.2f}%, 35-all: {s_row['nrmse_all35']:.2f}% | 26W1_gap: {s_row['sim_26SP_W1_gap_t_ha']:+.2f}t, 26W2_gap: {s_row['sim_26SP_W2_gap_t_ha']:+.2f}t, 25W1_gap: {s_row['sim_25SP_W1_gap_t_ha']:+.2f}t")

                # Incremental flush
                pd.DataFrame(summary_records).to_csv(summary_file, index=False)
                pd.concat(detail_records, ignore_index=True).to_csv(detail_file, index=False)

    total_elapsed = time.time() - start_all
    print(f"\nAll {total_runs} grid simulations completed in {total_elapsed:.1f}s.")

    # Multi-criteria analysis & ranking
    df_sum = pd.DataFrame(summary_records)

    # Calculate fidelity to field observation gaps:
    # Field targets: 26SP W1: +16.50 t/ha, 26SP W2: +9.50 t/ha, 25SP W1: +11.60 t/ha, 25SP W3: +4.10 t/ha
    # Response deficit penalty
    gap_penalty = (
        (df_sum["sim_26SP_W1_gap_t_ha"] - 16.50).abs() / 16.50 +
        (df_sum["sim_26SP_W2_gap_t_ha"] - 9.50).abs() / 9.50 +
        (df_sum["sim_25SP_W1_gap_t_ha"] - 11.60).abs() / 11.60 +
        (df_sum["sim_25SP_W3_gap_t_ha"] - 4.10).abs() / 4.10
    )
    df_sum["response_gap_penalty"] = gap_penalty

    # Composite Score: weighted combination of Spring NRMSE%, 25FA NRMSE%, and response fidelity
    # Lower is better
    df_sum["composite_score"] = (
        0.45 * df_sum["nrmse_spring"] +
        0.20 * df_sum["nrmse_25fa"] +
        0.35 * (gap_penalty * 10.0)
    )

    df_ranked = df_sum.sort_values("composite_score").reset_index(drop=True)
    df_ranked.to_csv(GRID_OUT_DIR / "grid_ranking.csv", index=False)

    print("\n================ TOP 5 BALANCED CHAMPIONS (Composite Score) ================")
    top5 = df_ranked.head(5)
    for idx, r in top5.iterrows():
        print(f"Rank {idx+1}: {r['combo_id']}")
        print(f"  Parameters: SASC={r['sasc_ratio']:.2f}, SRGF_80_100={r['srgf_80_100']:.2f}, SRGF_140={r['srgf_140']:.2f}")
        print(f"  Metrics: Spring NRMSE={r['nrmse_spring']:.2f}%, 35-All NRMSE={r['nrmse_all35']:.2f}%, 25FA NRMSE={r['nrmse_25fa']:.2f}%, d={r['d_index_spring']:.4f}")
        print(f"  Nitrogen Gaps (t/ha): 26W1={r['sim_26SP_W1_gap_t_ha']:+.2f} (obs +16.5), 26W2={r['sim_26SP_W2_gap_t_ha']:+.2f} (obs +9.5), 25W1={r['sim_25SP_W1_gap_t_ha']:+.2f} (obs +11.6), 25W3={r['sim_25SP_W3_gap_t_ha']:+.2f} (obs +4.1)")
        print(f"  Composite Score: {r['composite_score']:.3f}\n")

    print(f"Summary saved to: {summary_file}")
    print(f"Rankings saved to: {GRID_OUT_DIR / 'grid_ranking.csv'}")

if __name__ == "__main__":
    main()
