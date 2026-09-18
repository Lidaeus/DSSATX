#!/usr/bin/env python3
"""Render 3-Season Comprehensive Diagnostic Suites for 4 formal Century SASC [0.89, 0.95] candidates:
- iter5_real22 (Real 22, Phi=533.14)
- iter5_real48 (Real 48, Phi=522.01)
- iter5_real113 (Real 113, Phi=530.91)
- iter5_real38 (Real 38, Phi=506.31)

For each candidate:
1. Assembles 3-season runs (25SP: 11 tmts, 26SP: 12 tmts, 25FA: 12 tmts) from existing calibrated batches.
2. Generates canonical 3-season diagnostic figure suite (32+ figures/CSVs per candidate).
3. Computes and exports statistical fitting metrics (RMSE, NRMSE%, d-index, R2).
4. Generates cross-candidate comparison tables and reports.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path("D:/Tomato_Cal")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation
from src.calibration.nitrogen_response import derive_filex_water_n_mapping
from src.reporting.analyze_results import (
    deterministic_harvest_compare,
    deterministic_process_compare,
)
from tools.eval_full_gen98 import evaluate_run, calc_metrics

RUN_DIR = ROOT / "workspace" / "runs" / "full_gen_century_sasc094_formal_20260918"
SOIL_SOL = RUN_DIR / "SOIL.SOL"

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

CANDIDATES = [
    {
        "cand_id": "iter5_real22",
        "real_id": "22",
        "phi": 533.136,
        "desc": "Realization 22 (High 26SP W1 gap +12.71t, SASC=0.897)",
    },
    {
        "cand_id": "iter5_real48",
        "real_id": "48",
        "phi": 522.013,
        "desc": "Realization 48 (Balanced SASC=0.940, W2 gap +15.66t, Spring NRMSE=17.13%)",
    },
    {
        "cand_id": "iter5_real113",
        "real_id": "113",
        "phi": 530.906,
        "desc": "Realization 113 (High R2=0.956, SASC=0.941, Spring NRMSE=15.37%)",
    },
    {
        "cand_id": "iter5_real38",
        "real_id": "38",
        "phi": 506.314,
        "desc": "Realization 38 (Lowest Phi=506.31, Lowest Spring NRMSE=14.23%, All-35 NRMSE=14.83%)",
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


def assemble_season_directories(cand_id: str, det_root: Path):
    """Assemble 25SP, 26SP, 25FA season directories from existing simulation runs."""
    calib_dir = RUN_DIR / f"cand_{cand_id}_calib"
    valid_dir = RUN_DIR / f"cand_{cand_id}_valid"
    fa_dir = RUN_DIR / f"cand_{cand_id}_25fa"

    for d in [calib_dir, valid_dir, fa_dir]:
        if not (d / "PlantGro.OUT").exists() or not (d / "FreshWt.OUT").exists():
            raise FileNotFoundError(f"Missing simulation outputs in {d}")

    # 1. Assemble 25SP: 11 treatments [2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14]
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
    sdir_25sp = det_root / "_seasons" / "25SP"
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

    # 2. Assemble 26SP: 12 treatments [1..12]
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
    sdir_26sp = det_root / "_seasons" / "26SP"
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

    # 3. Assemble 25FA: 12 treatments [1..12]
    sdir_25fa = det_root / "_seasons" / "25FA"
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

    # 4. Input manifests
    for sid in ["25SP", "26SP", "25FA"]:
        sd = det_root / "_seasons" / sid
        files = [
            {"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
            for p in sorted(sd.iterdir()) if p.is_file()
        ]
        (sd / "input_manifest.json").write_text(
            json.dumps({"bundle_id": f"engine_replay_{sid}_{cand_id}", "files": files}, indent=2) + "\n",
            encoding="utf-8",
        )


def evaluate_and_plot_candidate(cand_info: dict) -> dict:
    cand_id = cand_info["cand_id"]
    real_id = cand_info["real_id"]
    phi_val = cand_info["phi"]
    desc = cand_info["desc"]

    print(f"\n{'=' * 80}")
    print(f"PROCESSING CANDIDATE: {cand_id} (Realization {real_id}, Phi={phi_val:.2f})")
    print(f"  Description: {desc}")
    print(f"{'=' * 80}")

    work_dir = ROOT / "workspace" / "reports" / f"century_sasc094_formal_{cand_id}"
    det_root = work_dir / "det_engine"
    out_root = ROOT / "figture" / f"century_sasc094_formal_{cand_id}_3season_suite"

    if work_dir.exists():
        shutil.rmtree(work_dir)
    det_root.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)

    param_csv = RUN_DIR / f"candidate_{cand_id}_params.csv"
    if not param_csv.exists():
        raise FileNotFoundError(f"Candidate parameter file not found: {param_csv}")

    # Read parameters
    p_df = pd.read_csv(param_csv)
    p_map = dict(zip(p_df["name"].str.lower(), p_df["value"]))

    # 1. Assemble 3-season run directories
    assemble_season_directories(cand_id, det_root)

    # 2. Derive full 35-treatment water-nitrogen mapping
    maps = []
    for cfg in SEASONS_CONFIG:
        sid = cfg["season_id"]
        excode = cfg["excode"]
        trts = cfg["treatments"]
        tmx = det_root / "_seasons" / sid / f"{excode}.TMX"
        m = derive_filex_water_n_mapping(tmx, season_id=sid, treatments=trts)
        maps.append(m)
    all_mapping = pd.concat(maps, ignore_index=True)
    mapping_path = det_root / "three_season_water_n_mapping.csv"
    all_mapping.to_csv(mapping_path, index=False, encoding="utf-8-sig")

    # 3. Status and parameter copies for evaluation engine
    dest_param_file = det_root / f"best_member_{cand_id}_params.csv"
    shutil.copy2(param_csv, dest_param_file)
    (det_root / "multiseason_run_status.json").write_text(
        json.dumps({"status": "done", "candidate": cand_id, "phi": phi_val}), encoding="utf-8"
    )

    # 4. Configure evaluation engine
    evaluation.RUN_DIR = RUN_DIR
    evaluation.DET_ROOT = det_root
    evaluation.OUT_ROOT = out_root
    evaluation.FIGURE = ROOT / "figture"
    evaluation.CASE = cand_id
    evaluation.BEST_MEMBER = cand_id
    evaluation.SOURCE_ITERATION = 5
    evaluation.BEST_PHI = phi_val
    evaluation.CALIBRATION_STATE = "completed_engineering_validated"
    evaluation.ARTIFACT_TYPE = f"three_season_diagnostics_century_{cand_id}_20260918"
    evaluation.SPE = ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    evaluation.HARVEST_OBJECTIVE = f"Century SASC Formal {cand_id} (Phi={phi_val:.2f}, SASC={p_map.get('sasc_ratio', 0.94):.4f})"
    evaluation.SOIL_INJECTION_DESCRIPTION = "Century Soil Model (SRGF Layer 7&8=0.200, Layer 9=0.050, Layer 10=0.000)"
    evaluation.OBS_REGISTRY = ROOT / "workspace" / "runs" / "nonexistent.csv"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.PLOT_MAPPING_CSV = mapping_path
    evaluation.SEASONS = [
        {
            "season_id": cfg["season_id"],
            "excode": cfg["excode"],
            "treatments": cfg["treatments"],
            "bundle": det_root / "_seasons" / cfg["season_id"],
        }
        for cfg in SEASONS_CONFIG
    ]
    evaluation.SEASON_IDS = ["25SP", "25FA", "26SP"]
    evaluation.COLORS = {"25SP": "#2878B5", "25FA": "#E67E22", "26SP": "#2A9D55"}
    evaluation.EXTRA_LIMITATIONS = [
        f"Century SASC Formal Candidate: {cand_id} (Iteration 5 Realization {real_id}).",
        "Replay covers all 35 treatments across 25SP (11), 26SP (12), and blind 25FA (12).",
        "Diagnostic suite only; posterior/uncertainty figures excluded.",
    ]
    evaluation._swap = lambda: []
    evaluation._restore = lambda replacements: None
    evaluation._export_member = lambda out_path: (shutil.copy2(param_csv, out_path), len(p_df))[1]
    evaluation.EXE = ROOT / "DSCSM048.EXE"
    os.environ["DSSAT_CUSTOM_EXE"] = str(evaluation.EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(evaluation.SPE.resolve())
    os.environ["PYTHONPATH"] = str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")

    # Execute evaluation engine to render figures
    res_code = int(evaluation.main() or 0)
    plt.close("all")

    # 5. Read harvest evaluation datasets
    calib_dir = RUN_DIR / f"cand_{cand_id}_calib"
    valid_dir = RUN_DIR / f"cand_{cand_id}_valid"
    fa_dir = RUN_DIR / f"cand_{cand_id}_25fa"

    df_h_c, _ = evaluate_run(ROOT / "data/templates/batch/DSSBatch_calib.v48", calib_dir)
    df_h_v, _ = evaluate_run(ROOT / "data/templates/batch/DSSBatch_valid.v48", valid_dir)
    df_h_fa, _ = evaluate_run(ROOT / "data/user/experiments/xxql2502_v20260917_refresh/DSSBatch.v48", fa_dir)

    df_h_sp = pd.concat([df_h_c, df_h_v], ignore_index=True)
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
    summary_path = out_root / "harvest_metrics_summary.csv"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    # Per-treatment terminal metrics
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
            "dyn_r2": r2_t,
        })
    df_term = pd.DataFrame(term_records)
    term_path = out_root / "treatment_terminal_metrics.csv"
    df_term.to_csv(term_path, index=False, encoding="utf-8-sig")

    # Gradient calculations
    def get_term(season_id, trtno):
        sub = df_term[(df_term["season"] == season_id) & (df_term["treatment"] == trtno)]
        return float(sub.iloc[0]["sim_terminal_t_ha"]) if not sub.empty else np.nan

    g_26_w1_sim = get_term("26SP", 3) - get_term("26SP", 12)  # field: +16.50
    g_26_w2_sim = get_term("26SP", 2) - get_term("26SP", 11)  # field: +9.50
    g_26_w3_sim = get_term("26SP", 1) - get_term("26SP", 9)   # field: +16.00
    g_25_w1_sim = get_term("25SP", 10) - get_term("25SP", 13) # field: +11.60
    g_25_w3_sim = get_term("25SP", 2) - get_term("25SP", 5)   # field: +4.10

    # Extract metrics summary values
    cal_row = summary_df[summary_df["Subset"].str.startswith("Calibration")].iloc[0]
    val_row = summary_df[summary_df["Subset"].str.startswith("Validation")].iloc[0]
    sp_row = summary_df[summary_df["Subset"].str.startswith("Two-Spring")].iloc[0]
    fa_row = summary_df[summary_df["Subset"].str.startswith("25FA")].iloc[0]
    all_row = summary_df[summary_df["Subset"].str.startswith("Grand")].iloc[0]

    cand_result = {
        "candidate": cand_id,
        "real_id": real_id,
        "phi": phi_val,
        "sasc_ratio": p_map.get("sasc_ratio", np.nan),
        "icns_26sp": p_map.get("icns_26sp", np.nan),
        "pgeff": p_map.get("pgeff", np.nan),
        "lnref": p_map.get("lnref", np.nan),
        "frlff": p_map.get("frlff", np.nan),
        "slavr": p_map.get("slavr", np.nan),
        "sizlf": p_map.get("sizlf", np.nan),
        "tb1": p_map.get("tb1", np.nan),
        "nrmse_calib": cal_row["NRMSE_pct"],
        "rmse_calib": cal_row["RMSE_kg_ha"],
        "d_calib": cal_row["d_index"],
        "r2_calib": cal_row["R2"],
        "nrmse_valid": val_row["NRMSE_pct"],
        "rmse_valid": val_row["RMSE_kg_ha"],
        "d_valid": val_row["d_index"],
        "r2_valid": val_row["R2"],
        "nrmse_spring": sp_row["NRMSE_pct"],
        "rmse_spring": sp_row["RMSE_kg_ha"],
        "d_spring": sp_row["d_index"],
        "r2_spring": sp_row["R2"],
        "nrmse_25fa": fa_row["NRMSE_pct"],
        "rmse_25fa": fa_row["RMSE_kg_ha"],
        "d_25fa": fa_row["d_index"],
        "r2_25fa": fa_row["R2"],
        "nrmse_all35": all_row["NRMSE_pct"],
        "rmse_all35": all_row["RMSE_kg_ha"],
        "d_all35": all_row["d_index"],
        "r2_all35": all_row["R2"],
        "gap_26sp_w1": g_26_w1_sim,
        "gap_26sp_w2": g_26_w2_sim,
        "gap_26sp_w3": g_26_w3_sim,
        "gap_25sp_w1": g_25_w1_sim,
        "gap_25sp_w3": g_25_w3_sim,
        "out_dir": str(out_root),
        "res_code": res_code,
    }
    print(f"Candidate {cand_id} completed successfully.")
    print(f"  Calib NRMSE: {cal_row['NRMSE_pct']:.2f}%, Valid NRMSE: {val_row['NRMSE_pct']:.2f}%")
    print(f"  Two-Spring NRMSE: {sp_row['NRMSE_pct']:.2f}%, d={sp_row['d_index']:.4f}, R2={sp_row['R2']:.4f}")
    print(f"  25FA NRMSE: {fa_row['NRMSE_pct']:.2f}%, All-35 NRMSE: {all_row['NRMSE_pct']:.2f}%")
    print(f"  26SP W1 Gap: {g_26_w1_sim:+.2f} t/ha (Target: +16.50 t/ha)")
    print(f"  25SP W1 Gap: {g_25_w1_sim:+.2f} t/ha (Target: +11.60 t/ha)")
    print(f"  Diagnostic suite written to: {out_root}")
    return cand_result


def main() -> int:
    print("=" * 80)
    print("Century SASC [0.89, 0.95] Formal Calibration Candidate Diagnostic Suite")
    print(f"Evaluating 4 Selected Candidates: {[c['cand_id'] for c in CANDIDATES]}")
    print("=" * 80)

    results = []
    for c in CANDIDATES:
        res = evaluate_and_plot_candidate(c)
        results.append(res)

    res_df = pd.DataFrame(results)
    comp_csv = ROOT / "figture" / "century_sasc094_formal_4candidates_comparison.csv"
    res_df.to_csv(comp_csv, index=False, encoding="utf-8-sig")
    print(f"\nSaved cross-candidate comparison CSV to: {comp_csv}")

    print("\n" + "=" * 90)
    print("FINAL CROSS-CANDIDATE COMPARISON TABLE:")
    print("=" * 90)
    cols = [
        "candidate", "phi", "sasc_ratio", "nrmse_spring", "r2_spring",
        "nrmse_25fa", "r2_25fa", "nrmse_all35", "r2_all35",
        "gap_26sp_w1", "gap_26sp_w2", "gap_25sp_w1"
    ]
    print(res_df[cols].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
