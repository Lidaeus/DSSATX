#!/usr/bin/env python3
"""Three-season (25SP, 26SP, 25FA) 35-treatment diagnostic suite for
CROPGRO-Eggplant champion candidate (iter4_real81 base with SASC_RATIO=0.94,
SRGF_80_100=0.15, SRGF_140=0.05).

Executes deterministic DSSAT simulations reproducing the exact grid experiment
results (CALIB_BATCH + VALID_BATCH + 25FA), assembles per-season runs (25SP: 11,
26SP: 12, 25FA: 12), generates the full diagnostic suite (timeseries WxN,
cross-season scatter, residuals, response structure audit, metrics heatmaps),
and exports complete statistical metrics tables.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation
from src.calibration.nitrogen_response import derive_filex_water_n_mapping
from src.reporting.analyze_results import (
    deterministic_harvest_compare,
    deterministic_process_compare,
)
from tools.calibration.run_sasc_srgf_grid_experiment import (
    run_batch_with_soil,
    CALIB_BATCH,
    VALID_BATCH,
    BATCH_25FA,
    BUNDLE_25FA,
    TMT_META,
    calc_metrics,
)

CASE = "sasc_0.94_srgf_0.15_0.05"
RUN_DIR = ROOT / "workspace" / "runs" / "grid_sasc_srgf_20260918" / CASE
PARAM_CSV = RUN_DIR / "params.csv"
SOIL_SOL = RUN_DIR / "SOIL.SOL"

WORK = ROOT / "workspace" / "reports" / "sasc094_srgf015_005_3season_20260918"
DET_ROOT = WORK / "det_engine"
OUT_ROOT = ROOT / "figture" / "sasc094_srgf015_005_3season_full_suite_20260918"

CALIB_TMTS = {
    ("XXQL2501", 2),   # 25SP W3N3
    ("XXQL2501", 5),   # 25SP W3N0
    ("XXQL2501", 10),  # 25SP W1N3
    ("XXQL2501", 13),  # 25SP W1N0
    ("XXQL2601", 2),   # 26SP W2N3
    ("XXQL2601", 3),   # 26SP W1N3
    ("XXQL2601", 11),  # 26SP W2N0
    ("XXQL2601", 12),  # 26SP W1N0
}

SEASONS_CONFIG = [
    {
        "season_id": "25SP",
        "excode": "XXQL2501",
        "treatments": [2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14],
        "bundle": ROOT / "data/user/experiments/xxql2501_v20260917_refresh",
    },
    {
        "season_id": "26SP",
        "excode": "XXQL2601",
        "treatments": list(range(1, 13)),
        "bundle": ROOT / "data/user/experiments/xxql2601_v20260917_refresh",
    },
    {
        "season_id": "25FA",
        "excode": "XXQL2502",
        "treatments": list(range(1, 13)),
        "bundle": ROOT / "data/user/experiments/xxql2502_v20260917_refresh",
    },
]


def assemble_out_file(source_runs: list[tuple[Path, int]], dest_path: Path, outname: str):
    """Assemble a combined PlantGro.OUT or FreshWt.OUT from source directory runs."""
    new_runs_content = {}
    first_path = source_runs[0][0] / outname

    for (src_dir, src_run), new_run in zip(source_runs, range(1, len(source_runs) + 1)):
        src_path = src_dir / outname
        lines = src_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        cur_run = None
        run_lines = []
        for l in lines:
            m = re.match(r"\*RUN\s+(\d+)", l)
            if m:
                if cur_run == src_run:
                    break
                cur_run = int(m.group(1))
                if cur_run == src_run:
                    run_lines.append(re.sub(r"\*RUN\s+\d+", f"*RUN  {new_run:04d}", l))
            elif cur_run == src_run:
                run_lines.append(l)
        new_runs_content[new_run] = run_lines

    header_lines = []
    for l in first_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True):
        if l.startswith("*RUN"):
            break
        header_lines.append(l)

    full_content = "".join(header_lines)
    for nr in range(1, len(source_runs) + 1):
        full_content += "".join(new_runs_content[nr])
    dest_path.write_text(full_content, encoding="utf-8")


def run_and_assemble_all():
    """Run calibration, validation, and 25FA batches, then assemble per-season runs."""
    print("Executing Calib (8 runs), Valid (15 runs), and 25FA (12 runs) batches...")
    batch_work = WORK / "_raw_batches"
    calib_dir = batch_work / "calib"
    valid_dir = batch_work / "valid"
    fa_dir = batch_work / "25fa"

    df_h_c, _ = run_batch_with_soil(CALIB_BATCH, PARAM_CSV, SOIL_SOL, calib_dir)
    print("  Calibration batch completed.")
    df_h_v, _ = run_batch_with_soil(VALID_BATCH, PARAM_CSV, SOIL_SOL, valid_dir)
    print("  Validation batch completed.")
    df_h_fa, _ = run_batch_with_soil(BATCH_25FA, PARAM_CSV, SOIL_SOL, fa_dir, input_dir=BUNDLE_25FA)
    print("  25FA batch completed.")

    # Assemble 25SP: 11 treatments [2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14]
    runs_25sp = [
        (calib_dir, 1),  # TN 2
        (valid_dir, 1),  # TN 3
        (valid_dir, 2),  # TN 4
        (calib_dir, 2),  # TN 5
        (valid_dir, 3),  # TN 6
        (valid_dir, 4),  # TN 9
        (calib_dir, 3),  # TN 10
        (valid_dir, 5),  # TN 11
        (valid_dir, 6),  # TN 12
        (calib_dir, 4),  # TN 13
        (valid_dir, 7),  # TN 14
    ]
    sdir_25sp = DET_ROOT / "_seasons" / "25SP"
    sdir_25sp.mkdir(parents=True, exist_ok=True)
    assemble_out_file(runs_25sp, sdir_25sp / "PlantGro.OUT", "PlantGro.OUT")
    assemble_out_file(runs_25sp, sdir_25sp / "FreshWt.OUT", "FreshWt.OUT")
    for f in Path("data/user/experiments/xxql2501_v20260917_refresh").glob("XXQL2501.*"):
        shutil.copy2(f, sdir_25sp / f.name)
    shutil.copy2(SOIL_SOL, sdir_25sp / "SOIL.SOL")
    trts_25 = [2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14]
    filex_25 = sdir_25sp / "XXQL2501.TMX"
    (sdir_25sp / "analysis_batch.v48").write_text(
        "\n".join(f"{filex_25.resolve()} {tn} 1 0 0 0" for tn in trts_25) + "\n", encoding="utf-8"
    )
    deterministic_harvest_compare("25SP", str(sdir_25sp / "analysis_batch.v48"), run_dir=str(sdir_25sp))
    deterministic_process_compare("25SP", str(sdir_25sp / "analysis_batch.v48"), var_names=["L#SD", "LAID", "LWAD", "SWAD", "CHTD"], run_dir=str(sdir_25sp))

    # Assemble 26SP: 12 treatments [1..12]
    runs_26sp = [
        (valid_dir, 8),   # TN 1
        (calib_dir, 5),   # TN 2
        (calib_dir, 6),   # TN 3
        (valid_dir, 9),   # TN 4
        (valid_dir, 10),  # TN 5
        (valid_dir, 11),  # TN 6
        (valid_dir, 12),  # TN 7
        (valid_dir, 13),  # TN 8
        (valid_dir, 14),  # TN 9
        (valid_dir, 15),  # TN 10
        (calib_dir, 7),   # TN 11
        (calib_dir, 8),   # TN 12
    ]
    sdir_26sp = DET_ROOT / "_seasons" / "26SP"
    sdir_26sp.mkdir(parents=True, exist_ok=True)
    assemble_out_file(runs_26sp, sdir_26sp / "PlantGro.OUT", "PlantGro.OUT")
    assemble_out_file(runs_26sp, sdir_26sp / "FreshWt.OUT", "FreshWt.OUT")
    for f in Path("data/user/experiments/xxql2601_v20260917_refresh").glob("XXQL2601.*"):
        shutil.copy2(f, sdir_26sp / f.name)
    shutil.copy2(SOIL_SOL, sdir_26sp / "SOIL.SOL")
    filex_26 = sdir_26sp / "XXQL2601.TMX"
    (sdir_26sp / "analysis_batch.v48").write_text(
        "\n".join(f"{filex_26.resolve()} {tn} 1 0 0 0" for tn in range(1, 13)) + "\n", encoding="utf-8"
    )
    deterministic_harvest_compare("26SP", str(sdir_26sp / "analysis_batch.v48"), run_dir=str(sdir_26sp))
    deterministic_process_compare("26SP", str(sdir_26sp / "analysis_batch.v48"), var_names=["L#SD", "LAID", "LWAD", "SWAD", "CHTD"], run_dir=str(sdir_26sp))

    # Assemble 25FA: 12 treatments [1..12]
    sdir_25fa = DET_ROOT / "_seasons" / "25FA"
    sdir_25fa.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fa_dir / "PlantGro.OUT", sdir_25fa / "PlantGro.OUT")
    shutil.copy2(fa_dir / "FreshWt.OUT", sdir_25fa / "FreshWt.OUT")
    for f in Path("data/user/experiments/xxql2502_v20260917_refresh").glob("XXQL2502.*"):
        shutil.copy2(f, sdir_25fa / f.name)
    shutil.copy2(SOIL_SOL, sdir_25fa / "SOIL.SOL")
    filex_fa = sdir_25fa / "XXQL2502.TMX"
    (sdir_25fa / "analysis_batch.v48").write_text(
        "\n".join(f"{filex_fa.resolve()} {tn} 1 0 0 0" for tn in range(1, 13)) + "\n", encoding="utf-8"
    )
    deterministic_harvest_compare("25FA", str(sdir_25fa / "analysis_batch.v48"), run_dir=str(sdir_25fa))
    deterministic_process_compare("25FA", str(sdir_25fa / "analysis_batch.v48"), var_names=["L#SD", "LAID", "LWAD", "SWAD", "CHTD"], run_dir=str(sdir_25fa))

    # Generate input_manifest.json for each season
    import hashlib
    for sid in ["25SP", "26SP", "25FA"]:
        sd = DET_ROOT / "_seasons" / sid
        files = [
            {"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
            for p in sorted(sd.iterdir()) if p.is_file()
        ]
        (sd / "input_manifest.json").write_text(
            json.dumps({"bundle_id": f"engine_replay_{sid}", "files": files}, indent=2) + "\n",
            encoding="utf-8",
        )
    print("All 3 seasons successfully assembled.")
    return df_h_c, df_h_v, df_h_fa


def compute_metrics(df_h_c, df_h_v, df_h_fa):
    """Compute exact statistical metrics for all subsets and treatment contrasts."""
    # Pooled Spring
    df_h_sp = pd.concat([df_h_c, df_h_v], ignore_index=True)
    # Grand Pooled
    df_h_all = pd.concat([df_h_sp, df_h_fa], ignore_index=True)

    def eval_set(name, df):
        rmse, nrmse, d, r2 = calc_metrics(df["OBS_FRESH_CUM"], df["SIM_FRESH_CUM"])
        return {
            "Subset": name,
            "Observations": len(df),
            "RMSE_kg_ha": rmse,
            "NRMSE_pct": nrmse,
            "d_index": d,
            "R2": r2,
        }

    summary_df = pd.DataFrame([
        eval_set("Calibration (8 runs, 25SP/26SP extremes)", df_h_c),
        eval_set("Validation (15 runs, 25SP/26SP interior)", df_h_v),
        eval_set("Two-Spring Pooled (23 runs)", df_h_sp),
        eval_set("25FA Independent Generalization (12 runs)", df_h_fa),
        eval_set("Grand Pooled All 35 Treatments", df_h_all),
    ])

    # Tagged all treatments for terminal yield analysis
    df_all_tagged = pd.concat([
        df_h_c.assign(batch="Calibration"),
        df_h_v.assign(batch="Validation"),
        df_h_fa.assign(batch="Independent_25FA"),
    ], ignore_index=True)

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
            "season": meta["season"],
            "excode": excode,
            "treatment": tn,
            "label": meta["label"],
            "water": meta["water"],
            "nitro": meta["nitro"],
            "batch": last_row["batch"],
            "obs_terminal_t_ha": obs_term / 1000.0,
            "sim_terminal_t_ha": sim_term / 1000.0,
            "bias_t_ha": err / 1000.0,
            "bias_pct": rel_err,
            "dyn_nrmse_pct": nrmse_t,
            "dyn_d_index": d_t,
        })
    df_term = pd.DataFrame(term_records)
    return summary_df, df_term


def main() -> int:
    print("=" * 75)
    print("CROPGRO-Eggplant SASC=0.94, SRGF(80/100)=0.15, SRGF(140)=0.05")
    print("3-Season Comprehensive Diagnostic Suite & Scientific Verification")
    print(f"  Params File: {PARAM_CSV}")
    print(f"  Soil File:   {SOIL_SOL}")
    print(f"  Work Dir:    {WORK}")
    print(f"  Figures Out: {OUT_ROOT}")
    print("=" * 75)

    if WORK.exists():
        shutil.rmtree(WORK)
    DET_ROOT.mkdir(parents=True, exist_ok=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    # 1. Execute DSSAT batches & assemble 3-season run directories
    df_h_c, df_h_v, df_h_fa = run_and_assemble_all()

    # 2. Derive full 35-treatment water-nitrogen mapping
    maps = []
    for cfg in SEASONS_CONFIG:
        sid = cfg["season_id"]
        excode = cfg["excode"]
        trts = cfg["treatments"]
        tmx = DET_ROOT / "_seasons" / sid / f"{excode}.TMX"
        m = derive_filex_water_n_mapping(tmx, season_id=sid, treatments=trts)
        maps.append(m)
    all_mapping = pd.concat(maps, ignore_index=True)
    mapping_path = DET_ROOT / "three_season_water_n_mapping.csv"
    all_mapping.to_csv(mapping_path, index=False, encoding="utf-8-sig")

    # 3. Mark status and copy params for evaluation engine
    shutil.copy2(PARAM_CSV, DET_ROOT / "best_member_iter4_real81_params.csv")
    (DET_ROOT / "multiseason_run_status.json").write_text(
        json.dumps({"status": "done", "case": CASE}), encoding="utf-8"
    )

    # 4. Configure and run evaluation engine
    evaluation.RUN_DIR = RUN_DIR
    evaluation.DET_ROOT = DET_ROOT
    evaluation.OUT_ROOT = OUT_ROOT
    evaluation.FIGURE = ROOT / "figture"
    evaluation.CASE = CASE
    evaluation.BEST_MEMBER = "iter4_real81"
    evaluation.SOURCE_ITERATION = 4
    evaluation.BEST_PHI = 651.43
    evaluation.CALIBRATION_STATE = "completed_engineering_validated"
    evaluation.ARTIFACT_TYPE = "three_season_diagnostics_sasc094_srgf015_005_20260918"
    evaluation.SPE = ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    evaluation.HARVEST_OBJECTIVE = "SASC=0.94, SRGF(80/100)=0.15, SRGF(140)=0.05 (iter4_real81 base, 35 treatments)"
    evaluation.SOIL_INJECTION_DESCRIPTION = "Custom SOIL.SOL (SRGF Layer 7&8=0.150, Layer 9=0.050, Layer 10=0.000)"
    evaluation.OBS_REGISTRY = ROOT / "workspace" / "runs" / "nonexistent.csv"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.PLOT_MAPPING_CSV = mapping_path
    evaluation.SEASONS = [
        {
            "season_id": cfg["season_id"],
            "excode": cfg["excode"],
            "treatments": cfg["treatments"],
            "bundle": DET_ROOT / "_seasons" / cfg["season_id"],
        }
        for cfg in SEASONS_CONFIG
    ]
    evaluation.SEASON_IDS = ["25SP", "25FA", "26SP"]
    evaluation.COLORS = {"25SP": "#2878B5", "25FA": "#E67E22", "26SP": "#2A9D55"}
    evaluation.EXTRA_LIMITATIONS = [
        "SASC_RATIO=0.94, SRGF(80/100)=0.15, SRGF(140)=0.05 multi-factor grid champion solution.",
        "Replay covers all 35 treatments across 25SP (11), 26SP (12), and blind 25FA (12).",
        "Diagnostic suite only; posterior/uncertainty figures excluded.",
    ]
    evaluation._swap = lambda: []
    evaluation._restore = lambda replacements: None
    evaluation._export_member = lambda out_path: (shutil.copy2(PARAM_CSV, out_path), len(pd.read_csv(PARAM_CSV)))[1]
    evaluation.EXE = ROOT / "DSCSM048.EXE"
    os.environ["DSSAT_CUSTOM_EXE"] = str(evaluation.EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(evaluation.SPE.resolve())
    os.environ["PYTHONPATH"] = str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")

    # Execute evaluation engine to render figures
    res = int(evaluation.main() or 0)

    # 5. Compute and export statistical metrics
    df_summary, df_term = compute_metrics(df_h_c, df_h_v, df_h_fa)
    summary_path = OUT_ROOT / "harvest_metrics_summary.csv"
    df_summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    term_path = OUT_ROOT / "treatment_terminal_metrics.csv"
    df_term.to_csv(term_path, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 75)
    print("HARVEST FITTING METRICS SUMMARY:")
    print("=" * 75)
    print(df_summary.to_string(index=False))

    print("\n" + "=" * 75)
    print("KEY TREATMENT TERMINAL YIELD (OBS vs SIM, t/ha):")
    print("=" * 75)
    key_tmts = [
        ("26SP", 3, "26SP W1N3"),
        ("26SP", 12, "26SP W1N0"),
        ("26SP", 2, "26SP W2N3"),
        ("26SP", 11, "26SP W2N0"),
        ("25SP", 10, "25SP W1N3"),
        ("25SP", 13, "25SP W1N0"),
        ("25SP", 2, "25SP W3N3"),
        ("25SP", 5, "25SP W3N0"),
    ]
    for s, tn, lbl in key_tmts:
        sub = df_term[(df_term["season"] == s) & (df_term["treatment"] == tn)]
        if not sub.empty:
            r = sub.iloc[0]
            print(f"  {lbl:<12s}: OBS={r['obs_terminal_t_ha']:6.2f} t/ha | SIM={r['sim_terminal_t_ha']:6.2f} t/ha | Bias={r['bias_t_ha']:+6.2f} t/ha ({r['bias_pct']:+5.1f}%) | Dyn NRMSE={r['dyn_nrmse_pct']:5.2f}%")

    print("\n" + "=" * 75)
    print("WATER-NITROGEN RESPONSE GRADIENTS (Delta = N3 - N0, t/ha):")
    print("=" * 75)
    def get_term(season_id, trtno):
        sub = df_term[(df_term["season"] == season_id) & (df_term["treatment"] == trtno)]
        return float(sub.iloc[0]["sim_terminal_t_ha"]) if not sub.empty else np.nan

    def get_obs_term(season_id, trtno):
        sub = df_term[(df_term["season"] == season_id) & (df_term["treatment"] == trtno)]
        return float(sub.iloc[0]["obs_terminal_t_ha"]) if not sub.empty else np.nan

    g_26_w1_sim = get_term("26SP", 3) - get_term("26SP", 12)
    g_26_w1_obs = get_obs_term("26SP", 3) - get_obs_term("26SP", 12)
    g_26_w2_sim = get_term("26SP", 2) - get_term("26SP", 11)
    g_26_w2_obs = get_obs_term("26SP", 2) - get_obs_term("26SP", 11)
    g_26_w3_sim = get_term("26SP", 1) - get_term("26SP", 9)
    g_26_w3_obs = get_obs_term("26SP", 1) - get_obs_term("26SP", 9)
    g_25_w1_sim = get_term("25SP", 10) - get_term("25SP", 13)
    g_25_w1_obs = get_obs_term("25SP", 10) - get_obs_term("25SP", 13)
    g_25_w3_sim = get_term("25SP", 2) - get_term("25SP", 5)
    g_25_w3_obs = get_obs_term("25SP", 2) - get_obs_term("25SP", 5)

    print(f"  26SP W1 N3-N0 Gap: SIM = {g_26_w1_sim:+6.2f} t/ha | FIELD OBS = {g_26_w1_obs:+6.2f} t/ha (Diff: {abs(g_26_w1_sim - g_26_w1_obs):.2f} t/ha)")
    print(f"  26SP W2 N3-N0 Gap: SIM = {g_26_w2_sim:+6.2f} t/ha | FIELD OBS = {g_26_w2_obs:+6.2f} t/ha")
    print(f"  26SP W3 N3-N0 Gap: SIM = {g_26_w3_sim:+6.2f} t/ha | FIELD OBS = {g_26_w3_obs:+6.2f} t/ha")
    print(f"  25SP W1 N3-N0 Gap: SIM = {g_25_w1_sim:+6.2f} t/ha | FIELD OBS = {g_25_w1_obs:+6.2f} t/ha (Diff: {abs(g_25_w1_sim - g_25_w1_obs):.2f} t/ha)")
    print(f"  25SP W3 N3-N0 Gap: SIM = {g_25_w3_sim:+6.2f} t/ha | FIELD OBS = {g_25_w3_obs:+6.2f} t/ha")

    print("\n" + "=" * 75)
    print(f"All diagnostic charts successfully generated in:\n  {OUT_ROOT}")
    print("=" * 75)
    return res


if __name__ == "__main__":
    raise SystemExit(main())
