"""Targeted Parameter Profiling Runner for Biomass and Yield Scale (S2 Diagnostic Step).

Anchors on Member 19 parameters and profiles:
- Canopy source & assimilation: LFMAX, SIZREF, SLAVR, TRIFL, PARMAX
- Fruit sink & allocation: XFRT, XFRMAX, PODUR, SFDUR, PGEFF

Evaluates deterministic 25SP & 26SP responses and calculates:
- Terminal yield bias & NSE
- Leaf/stem dry mass bias & NSE
- LAI bias & NSE
- Objective Phi reduction
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools/analysis") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools/analysis"))

from render_arm_d_best17_diagnostics_20260820 import (
    build_season_harvest_compare,
    build_season_process_compare,
    compute_metrics,
)

BASE_PARAM_FILE = ROOT / "workspace/runs/e02_from_scratch_s5_formal_20260826/candidates/cand1_lowest_phi_params.csv"
PROFILE_DIR = ROOT / "workspace/runs/e02_biomass_scale_profiles_20260827"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

PROFILES = {
    # Canopy source parameters
    "LFMAX": [0.80, 1.00, 1.20, 1.40, 1.60, 1.80, 2.00],
    "SIZREF": [120.0, 160.0, 200.0, 240.0, 280.0, 320.0],
    "SLAVR": [180.0, 220.0, 260.0, 300.0, 350.0, 400.0],
    "TRIFL": [0.15, 0.20, 0.25, 0.30, 0.35, 0.40],
    # Fruit sink parameters
    "XFRT": [0.80, 0.85, 0.90, 0.95, 0.98],
    "PODUR": [10.0, 15.0, 20.0, 25.0, 30.0],
    "SFDUR": [15.0, 20.0, 25.0, 30.0, 35.0, 40.0],
    "PGEFF": [0.60, 0.70, 0.80, 0.85, 0.90, 0.95],
}


def run_deterministic_eval(param_csv: Path, run_id: str) -> dict[str, Any]:
    """Run 25SP & 26SP deterministic simulation and return summary metrics."""
    eval_dir = PROFILE_DIR / run_id
    if eval_dir.exists():
        shutil.rmtree(eval_dir)
    eval_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    cmd = [
        sys.executable,
        str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(ROOT / "configs/runs/e02_from_scratch_10L_B_s5_design_20260826.json"),
        "--param-csv", str(param_csv),
        "--harvest-var", "CHPDT",
        "--prefix", "prof_eval",
        "--keep-nitrogen-outputs",
    ]
    res = subprocess.run(cmd, cwd=str(eval_dir), env=env, capture_output=True, text=True)
    if res.returncode != 0:
        return {"status": "error", "error": res.stderr}

    metrics = {}
    for s in ["25SP", "26SP"]:
        sdir = eval_dir / "_seasons" / s
        if not sdir.is_dir():
            continue
        h_comp = build_season_harvest_compare(sdir, s)
        p_comp = build_season_process_compare(sdir, s)

        m_dry_cum = compute_metrics(h_comp["OBS_DRY_CUM"].to_numpy(float), h_comp["SIM_DRY_CUM"].to_numpy(float))
        m_swad = compute_metrics(p_comp["OBS_SWAD"].to_numpy(float), p_comp["SIM_SWAD"].to_numpy(float))
        m_lwad = compute_metrics(p_comp["OBS_LWAD"].to_numpy(float), p_comp["SIM_LWAD"].to_numpy(float))
        m_laid = compute_metrics(p_comp["OBS_LAID"].to_numpy(float), p_comp["SIM_LAID"].to_numpy(float))

        metrics[f"{s}_DRY_CUM_BIAS"] = m_dry_cum["bias"]
        metrics[f"{s}_DRY_CUM_NSE"] = m_dry_cum["nse"]
        metrics[f"{s}_SWAD_NSE"] = m_swad["nse"]
        metrics[f"{s}_SWAD_BIAS"] = m_swad["bias"]
        metrics[f"{s}_LWAD_NSE"] = m_lwad["nse"]
        metrics[f"{s}_LWAD_BIAS"] = m_lwad["bias"]
        metrics[f"{s}_LAID_NSE"] = m_laid["nse"]

    return {"status": "success", **metrics}


def main() -> int:
    print("====================================================================")
    print("   Starting Biomass & Yield Scale Parameter Profiling Suite")
    print("====================================================================")

    df_base = pd.read_csv(BASE_PARAM_FILE)
    base_dict = dict(zip(df_base["name"].astype(str).str.lower(), df_base["value"].astype(float)))

    # 1. Evaluate baseline (Member 19)
    base_res = run_deterministic_eval(BASE_PARAM_FILE, "baseline_member19")
    print("\n[Baseline Member 19 Results]")
    for k, v in sorted(base_res.items()):
        if k != "status":
            print(f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")

    results = []
    # 2. Iterate through single parameter profiles
    for param_name, test_vals in PROFILES.items():
        p_key = param_name.lower()
        orig_val = base_dict.get(p_key, np.nan)
        print(f"\n--- Profiling {param_name} (Original: {orig_val}) ---")

        for val in test_vals:
            run_id = f"prof_{param_name}_{val}"
            df_p = df_base.copy()
            match = df_p["name"].astype(str).str.lower() == p_key
            if match.any():
                df_p.loc[match, "value"] = val
            else:
                df_p = pd.concat([df_p, pd.DataFrame([{"name": param_name, "value": val}])], ignore_index=True)

            p_file = PROFILE_DIR / f"{run_id}_params.csv"
            df_p.to_csv(p_file, index=False)

            eval_res = run_deterministic_eval(p_file, run_id)
            if eval_res.get("status") == "success":
                rec = {
                    "parameter": param_name,
                    "profile_value": val,
                    "orig_value": orig_val,
                    **{k: v for k, v in eval_res.items() if k != "status"}
                }
                results.append(rec)
                print(f"  Val = {val:6.2f} | 25SP Yld Bias: {rec.get('25SP_DRY_CUM_BIAS', 0):+7.1f} | 26SP Yld Bias: {rec.get('26SP_DRY_CUM_BIAS', 0):+7.1f} | 25SP SWAD NSE: {rec.get('25SP_SWAD_NSE', 0):5.3f} | 26SP SWAD NSE: {rec.get('26SP_SWAD_NSE', 0):5.3f}")

    df_results = pd.DataFrame(results)
    out_csv = ROOT / "workspace/reports/e02_from_scratch_10L_B_20260826/e02_biomass_scale_profiling_results.csv"
    df_results.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nSaved profiling results to: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
