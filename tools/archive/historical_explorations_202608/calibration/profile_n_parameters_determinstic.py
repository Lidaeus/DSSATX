#!/usr/bin/env python3
"""Step 1: Deterministic single-parameter profiling & FNPGN 2D grid.
Base anchor: Iteration 3 Member #137 parameters from v37 formal calibration.
Evaluates the causal effect of NSTFAC, RTNO3, NMOBMX, PROLFI, and FNPGN1xFNPGN2
on 25SP & 26SP Nitrogen Responses (N3 - N0) and overall goodness of fit.
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

BASE_PARAMS_PATH = (
    PROJECT_ROOT
    / "workspace/runs/e02_formal_v37_fresh_yield_source_sink_200x4_20260829"
    / "best_member_137_two_season_deterministic_20260829"
    / "best_member_137_params.csv"
)
BASE_DESIGN_PATH = PROJECT_ROOT / "configs/runs/e02_formal_v37_fresh_yield_source_sink_200x4_20260829.json"

OUT_DIR = PROJECT_ROOT / "workspace/reports/nitrogen_investigation_20260829"
SCRATCH_DIR = OUT_DIR / "scratch_runs"


def _run_deterministic(param_dict: dict[str, float], run_id: str) -> dict[str, float]:
    run_path = SCRATCH_DIR / run_id
    run_path.mkdir(parents=True, exist_ok=True)

    # Load base params and update
    base_df = pd.read_csv(BASE_PARAMS_PATH)
    param_map = base_df.set_index("name")["value"].to_dict()
    param_map.update(param_dict)

    # Write temp param csv
    param_csv = run_path / "params.csv"
    p_df = pd.DataFrame([{"name": k, "value": v} for k, v in param_map.items()])
    p_df.to_csv(param_csv, index=False)

    # Design config based on formal v37
    base_design = json.loads(BASE_DESIGN_PATH.read_text(encoding="utf-8"))
    base_design["design_id"] = f"det_profile_{run_id}"
    design_file = run_path / "design.json"
    design_file.write_text(json.dumps(base_design, indent=2), encoding="utf-8")

    cmd = [
        PYTHON,
        str(PROJECT_ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_file),
        "--param-csv", str(param_csv),
        "--prefix", "det",
        "--harvest-var", "CHFPW",
    ]
    # DSSAT writes legacy Windows bytes to stdout/stderr.  Decode explicitly
    # with replacement so a non-UTF-8 banner cannot crash the reader thread
    # or hide the actual return code of the deterministic run.
    res = subprocess.run(
        cmd, cwd=str(run_path), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if res.returncode != 0:
        print(f"[ERROR] Simulation failed for {run_id}: {res.stderr}")
        return {}

    # Run comparisons for both seasons
    from src.reporting.analyze_results import deterministic_process_compare, deterministic_harvest_compare
    for sid, tns in [("25SP", [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]), ("26SP", list(range(1, 13)))]:
        sdir = run_path / "_seasons" / sid
        filex = next(sdir.glob("*.TMX"))
        batch = sdir / "analysis_batch.v48"
        batch.write_text(
            "\n".join(f"{filex.resolve()} {int(tn)} 1 0 0 0" for tn in tns) + "\n",
            encoding="utf-8",
        )
        deterministic_process_compare(
            sid, str(batch),
            var_names=["L#SD", "LAID", "LWAD", "SWAD", "CHTD"],
            run_dir=str(sdir),
        )
        deterministic_harvest_compare(sid, str(batch), run_dir=str(sdir))

    # Parse harvest compares
    h25 = pd.read_csv(run_path / "_seasons/25SP/25SP_deterministic_harvest_compare.csv")
    h26 = pd.read_csv(run_path / "_seasons/26SP/26SP_deterministic_harvest_compare.csv")
    p25 = pd.read_csv(run_path / "_seasons/25SP/25SP_deterministic_process_compare.csv")
    p26 = pd.read_csv(run_path / "_seasons/26SP/26SP_deterministic_process_compare.csv")

    def _nse(obs, sim):
        ok = np.isfinite(obs) & np.isfinite(sim) & (obs != -99) & (sim != -99)
        o, s = obs[ok], sim[ok]
        if len(o) < 2: return np.nan
        sst = np.sum((o - o.mean()) ** 2)
        if sst <= 0: return np.nan
        return 1.0 - np.sum((s - o) ** 2) / sst

    # Terminal yields
    max25 = h25["HNO"].max()
    max26 = h26["HNO"].max()
    t25 = h25[h25["HNO"] == max25].set_index("TN")
    t26 = h26[h26["HNO"] == max26].set_index("TN")

    sim_25_w3_diff = float(t25.loc[2, "SIM_FRESH_CUM"] - t25.loc[5, "SIM_FRESH_CUM"])
    obs_25_w3_diff = float(t25.loc[2, "OBS_FRESH_CUM"] - t25.loc[5, "OBS_FRESH_CUM"])

    sim_25_w1_diff = float(t25.loc[10, "SIM_FRESH_CUM"] - t25.loc[13, "SIM_FRESH_CUM"])
    obs_25_w1_diff = float(t25.loc[10, "OBS_FRESH_CUM"] - t25.loc[13, "OBS_FRESH_CUM"])

    sim_26_w3_diff = float(t26.loc[1, "SIM_FRESH_CUM"] - t26.loc[9, "SIM_FRESH_CUM"])
    obs_26_w3_diff = float(t26.loc[1, "OBS_FRESH_CUM"] - t26.loc[9, "OBS_FRESH_CUM"])

    sim_26_w1_diff = float(t26.loc[3, "SIM_FRESH_CUM"] - t26.loc[12, "SIM_FRESH_CUM"])
    obs_26_w1_diff = float(t26.loc[3, "OBS_FRESH_CUM"] - t26.loc[12, "OBS_FRESH_CUM"])

    lai_nse_25 = _nse(p25["OBS_LAID"].to_numpy(float), p25["SIM_LAID"].to_numpy(float))
    lai_nse_26 = _nse(p26["OBS_LAID"].to_numpy(float), p26["SIM_LAID"].to_numpy(float))
    fresh_nse_25 = _nse(h25["OBS_FRESH_CUM"].to_numpy(float), h25["SIM_FRESH_CUM"].to_numpy(float))
    fresh_nse_26 = _nse(h26["OBS_FRESH_CUM"].to_numpy(float), h26["SIM_FRESH_CUM"].to_numpy(float))

    return {
        "25SP_W3_diff_sim": sim_25_w3_diff,
        "25SP_W3_diff_obs": obs_25_w3_diff,
        "25SP_W1_diff_sim": sim_25_w1_diff,
        "25SP_W1_diff_obs": obs_25_w1_diff,
        "26SP_W3_diff_sim": sim_26_w3_diff,
        "26SP_W3_diff_obs": obs_26_w3_diff,
        "26SP_W1_diff_sim": sim_26_w1_diff,
        "26SP_W1_diff_obs": obs_26_w1_diff,
        "25SP_LAI_NSE": lai_nse_25,
        "26SP_LAI_NSE": lai_nse_26,
        "25SP_FRESH_NSE": fresh_nse_25,
        "26SP_FRESH_NSE": fresh_nse_26,
        "25SP_both_pos": bool(sim_25_w3_diff > 0 and sim_25_w1_diff > 0),
        "26SP_err_w3": abs(sim_26_w3_diff - obs_26_w3_diff),
        "26SP_err_w1": abs(sim_26_w1_diff - obs_26_w1_diff),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    # 1. Baseline Anchor
    print("[1/6] Evaluating Base Anchor (Member #137)...")
    res_base = _run_deterministic({}, "base_member_137")
    res_base.update({"experiment": "baseline", "param_name": "none", "param_value": np.nan})
    results.append(res_base)

    # 2. NSTFAC profile
    print("[2/6] Profiling NSTFAC...")
    for val in [0.10, 0.25, 0.424, 0.60, 0.85, 1.10]:
        r = _run_deterministic({"NSTFAC": val}, f"nstfac_{val}")
        r.update({"experiment": "profile_NSTFAC", "param_name": "NSTFAC", "param_value": val})
        results.append(r)

    # 3. RTNO3 profile
    print("[3/6] Profiling RTNO3...")
    for val in [0.010, 0.025, 0.0459, 0.070, 0.100, 0.150]:
        r = _run_deterministic({"RTNO3": val}, f"rtno3_{val}")
        r.update({"experiment": "profile_RTNO3", "param_name": "RTNO3", "param_value": val})
        results.append(r)

    # 4. NMOBMX profile
    print("[4/6] Profiling NMOBMX...")
    for val in [0.10, 0.25, 0.40, 0.544, 0.70, 0.85]:
        r = _run_deterministic({"NMOBMX": val}, f"nmobmx_{val}")
        r.update({"experiment": "profile_NMOBMX", "param_name": "NMOBMX", "param_value": val})
        results.append(r)

    # 5. PROLFI profile
    print("[5/6] Profiling PROLFI...")
    for val in [0.12, 0.16, 0.2097, 0.26, 0.32, 0.38]:
        r = _run_deterministic({"PROLFI": val}, f"prolfi_{val}")
        r.update({"experiment": "profile_PROLFI", "param_name": "PROLFI", "param_value": val})
        results.append(r)

    # 6. FNPGN1 x FNPGN2 narrow grid
    print("[6/6] Profiling FNPGN1 x FNPGN2 2D grid...")
    for f1 in [0.30, 0.554, 0.80, 1.10]:
        for f2 in [2.20, 2.80, 3.559, 4.20]:
            r = _run_deterministic({"FNPGN1": f1, "FNPGN2": f2}, f"fnpgn_{f1}_{f2}")
            r.update({
                "experiment": "grid_FNPGN",
                "param_name": f"F1={f1}_F2={f2}",
                "param_value": f1,
                "fnpgn1": f1,
                "fnpgn2": f2,
            })
            results.append(r)

    df = pd.DataFrame(results)
    out_csv = OUT_DIR / "step1_single_parameter_profile_results.csv"
    df.to_csv(out_csv, index=False)
    print(f"\n[DONE] Profile results saved to: {out_csv}")


if __name__ == "__main__":
    main()
