#!/usr/bin/env python3
"""Evaluate Best Soil Layering Scheme (Scheme 4: 10-30-60-90-120-150-180cm)
on full 22 treatments across 25SP and 26SP.
Generates full set of diagnostic dynamics, scatter, residual, and response audit plots.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PYTHON = sys.executable

SCHEME_NAME = "Scheme_4_Rootzone_3L_7L"
LAYERS = [10, 30, 60, 90, 120, 150, 180]

DET_DIR = PROJECT_ROOT / "workspace/runs/e02_formal_best_soil_scheme4_det_20260830"
OUT_FIG_DIR = PROJECT_ROOT / "figture/e02_formal_best_soil_scheme4_20260830"
OBS_REGISTRY = PROJECT_ROOT / "workspace/runs/e02_formal_v37_fresh_yield_source_sink_200x4_20260829/e02_formal_v37_fresh_source_sink_20260829_observation_registry.csv"
MAPPING_CSV = PROJECT_ROOT / "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv"

BASE_PARAMS_PATH = (
    PROJECT_ROOT
    / "workspace/runs/e02_formal_v37_fresh_yield_source_sink_200x4_20260829"
    / "best_member_137_two_season_deterministic_20260829"
    / "best_member_137_params.csv"
)

from tools.calibration.explore_soil_layering_for_nitrogen_response import (
    generate_soil_sol_text, patch_filex_mesol
)


def run_evaluation():
    if DET_DIR.exists():
        shutil.rmtree(DET_DIR)
    DET_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FIG_DIR.mkdir(parents=True, exist_ok=True)

    bundle_root = DET_DIR / "_bundles"
    bundle_root.mkdir(parents=True, exist_ok=True)

    seasons_cfg = [
        ("25SP", "XXQL2501", PROJECT_ROOT / "data/user/experiments/xxql2501_formal_armab_rrmse_20260828", [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]),
        ("26SP", "XXQL2601", PROJECT_ROOT / "data/user/experiments/xxql2601_formal_armab_rrmse_26spncal_20260828", list(range(1, 13))),
    ]

    soil_text = generate_soil_sol_text(LAYERS)

    season_entries = []
    for sid, excode, orig_bundle, tmts in seasons_cfg:
        s_bdir = bundle_root / sid
        if s_bdir.exists():
            shutil.rmtree(s_bdir)
        shutil.copytree(orig_bundle, s_bdir)

        # Patch SOIL.SOL
        soil_sol_path = s_bdir / "SOIL.SOL"
        raw_soil = soil_sol_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        new_soil = []
        i = 0
        while i < len(raw_soil):
            l = raw_soil[i]
            if l.startswith("*IBTM910017"):
                new_soil.append(soil_text.strip())
                i += 1
                while i < len(raw_soil) and not raw_soil[i].startswith("*IBPP910015") and not raw_soil[i].startswith("*IN00020001"):
                    i += 1
            else:
                new_soil.append(l)
                i += 1
        soil_sol_path.write_text("\n".join(new_soil) + "\n", encoding="utf-8")

        # Patch FileX MESOL
        filex_path = next(s_bdir.glob("*.TMX"))
        patch_filex_mesol(filex_path)

        season_entries.append({
            "season_id": sid,
            "experiment_code": excode,
            "bundle_path": str(s_bdir),
            "role": "calibration",
            "treatments": tmts,
        })

    # Design JSON
    design_content = json.loads((PROJECT_ROOT / "configs/runs/e02_formal_v37_fresh_yield_source_sink_200x4_20260829.json").read_text(encoding="utf-8"))
    design_content["design_id"] = f"soil_eval_{SCHEME_NAME}"
    design_content["seasons"] = season_entries

    design_file = DET_DIR / "design.json"
    design_file.write_text(json.dumps(design_content, indent=2), encoding="utf-8")

    # Params
    param_csv = DET_DIR / "best_params.csv"
    shutil.copy2(BASE_PARAMS_PATH, param_csv)

    print("[RUN] Running forward multiseason DSSAT simulation...")
    cmd = [
        PYTHON,
        str(PROJECT_ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_file),
        "--param-csv", str(param_csv),
        "--prefix", "det",
        "--harvest-var", "CHFPW",
        "--keep-nitrogen-outputs",
    ]
    res = subprocess.run(cmd, cwd=str(DET_DIR), capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"run_multiseason failed: {res.stderr}")
    print("      Forward simulation completed successfully.")

    # Comparisons
    from src.reporting.analyze_results import deterministic_process_compare, deterministic_harvest_compare
    for sid, _, _, tmts in seasons_cfg:
        sdir = DET_DIR / "_seasons" / sid
        filex = next(sdir.glob("*.TMX"))
        batch = sdir / "analysis_batch.v48"
        batch.write_text(
            "\n".join(f"{filex.resolve()} {int(tn)} 1 0 0 0" for tn in tmts) + "\n",
            encoding="utf-8",
        )
        deterministic_process_compare(
            sid, str(batch),
            var_names=["L#SD", "LAID", "LWAD", "SWAD", "CHTD"],
            run_dir=str(sdir),
        )
        deterministic_harvest_compare(sid, str(batch), run_dir=str(sdir))

    # Render plots
    print(f"[PLOT] Rendering 22-treatment diagnostics via plot_dynamics.py -> {OUT_FIG_DIR}...")
    plot_cmd = [
        PYTHON,
        str(PROJECT_ROOT / "tools/calibration/plot_dynamics.py"),
        "--det-root", str(DET_DIR),
        "--out-root", str(OUT_FIG_DIR),
        "--seasons", "25SP,26SP",
        "--mapping-csv", str(MAPPING_CSV),
        "--include-all-treatments",
    ]
    if OBS_REGISTRY.is_file():
        plot_cmd.extend(["--registry-csv", str(OBS_REGISTRY)])
    subprocess.run(plot_cmd, cwd=str(PROJECT_ROOT), check=True)

    # Compute comprehensive metrics table
    metrics_rows = []
    for sid in ["25SP", "26SP"]:
        sdir = DET_DIR / "_seasons" / sid
        proc_csv = sdir / f"{sid}_deterministic_process_compare.csv"
        harv_csv = sdir / f"{sid}_deterministic_harvest_compare.csv"

        if proc_csv.is_file():
            p_df = pd.read_csv(proc_csv)
            for var in ["LAID", "LWAD", "SWAD", "CHTD"]:
                if f"OBS_{var}" in p_df and f"SIM_{var}" in p_df:
                    o = pd.to_numeric(p_df[f"OBS_{var}"], errors="coerce")
                    s = pd.to_numeric(p_df[f"SIM_{var}"], errors="coerce")
                    ok = o.notna() & s.notna() & (o != -99) & (s != -99)
                    if ok.any():
                        y, p = o[ok].to_numpy(float), s[ok].to_numpy(float)
                        e = p - y
                        sst = float(np.sum((y - y.mean()) ** 2))
                        dden = float(np.sum((np.abs(p - y.mean()) + np.abs(y - y.mean())) ** 2))
                        metrics_rows.append({
                            "season": sid, "kind": "process", "variable": var, "n": int(ok.sum()),
                            "rmse": float(np.sqrt(np.mean(e ** 2))),
                            "rrmse_pct": float(100.0 * np.sqrt(np.mean(e ** 2)) / np.mean(np.abs(y))),
                            "mae": float(np.mean(np.abs(e))),
                            "bias": float(np.mean(e)),
                            "nse": float(1.0 - np.sum(e ** 2) / sst) if sst > 0 else np.nan,
                            "d_index": float(1.0 - np.sum(e ** 2) / dden) if dden > 0 else np.nan,
                            "r2": float(np.corrcoef(y, p)[0, 1] ** 2) if len(y) > 1 and np.std(y) > 0 and np.std(p) > 0 else np.nan,
                        })

        if harv_csv.is_file():
            h_df = pd.read_csv(harv_csv)
            for var in ["DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM"]:
                if f"OBS_{var}" in h_df and f"SIM_{var}" in h_df:
                    o = pd.to_numeric(h_df[f"OBS_{var}"], errors="coerce")
                    s = pd.to_numeric(h_df[f"SIM_{var}"], errors="coerce")
                    ok = o.notna() & s.notna() & (o != -99) & (s != -99)
                    if ok.any():
                        y, p = o[ok].to_numpy(float), s[ok].to_numpy(float)
                        e = p - y
                        sst = float(np.sum((y - y.mean()) ** 2))
                        dden = float(np.sum((np.abs(p - y.mean()) + np.abs(y - y.mean())) ** 2))
                        metrics_rows.append({
                            "season": sid, "kind": "harvest", "variable": var, "n": int(ok.sum()),
                            "rmse": float(np.sqrt(np.mean(e ** 2))),
                            "rrmse_pct": float(100.0 * np.sqrt(np.mean(e ** 2)) / np.mean(np.abs(y))),
                            "mae": float(np.mean(np.abs(e))),
                            "bias": float(np.mean(e)),
                            "nse": float(1.0 - np.sum(e ** 2) / sst) if sst > 0 else np.nan,
                            "d_index": float(1.0 - np.sum(e ** 2) / dden) if dden > 0 else np.nan,
                            "r2": float(np.corrcoef(y, p)[0, 1] ** 2) if len(y) > 1 and np.std(y) > 0 and np.std(p) > 0 else np.nan,
                        })

    metrics_df = pd.DataFrame(metrics_rows)
    metrics_csv = OUT_FIG_DIR / "metrics_by_season_variable.csv"
    metrics_df.to_csv(metrics_csv, index=False)

    print("\n=== Final Scorecard for Scheme 4 Soil Layering (Full 22 Treatments) ===")
    print(metrics_df.to_string(index=False))


if __name__ == "__main__":
    run_evaluation()
