#!/usr/bin/env python3
"""Evaluate 3 concrete soil initial nitrogen adjustment schemes based on relative content:
Scheme 1: Relative Proportional Scaling (Scale existing SNO3 by 0.25, keeping inter-plot and vertical gradients)
Scheme 2: Block-Averaged Homogenization (Average 25SP vertical profile: 9.0, 4.5, 1.5, 1.0, 1.0 ppm -> ~35 kg N/ha)
Scheme 3: Dual-Season Harmonized Baseline (6.0, 3.0, 1.0, 0.5, 0.5 ppm -> ~25 kg N/ha)
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

RUN_DIR_BASE = PROJECT_ROOT / "workspace/runs/e02_small_v41_nresp10x_scheme4_60x3_20260830/best_member_13_two_season_deterministic_20260830"
BASE_PARAMS_PATH = RUN_DIR_BASE / "best_member_13_params.csv"
OUT_DIR = PROJECT_ROOT / "workspace/reports/relative_initial_n_schemes_20260830"
OUT_DIR.mkdir(parents=True, exist_ok=True)

from tools.calibration.explore_soil_layering_for_nitrogen_response import patch_filex_mesol


def patch_filex_relative_scaling(filex_path: Path, scale_factor: float = 0.25) -> None:
    """Scale existing SNO3 and SNH4 by scale_factor while preserving relative spatial & vertical patterns."""
    lines = filex_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    new_lines = []
    in_ic = False
    for l in lines:
        if l.startswith("*INITIAL CONDITIONS"):
            new_lines.append(l)
            in_ic = True
            continue
        elif l.startswith("*") and in_ic:
            in_ic = False
            new_lines.append(l)
            continue
            
        if in_ic:
            if l.startswith("@C"):
                new_lines.append(l)
            elif l.startswith(" ") and len(l.split()) >= 5:
                parts = l.split()
                try:
                    c = int(parts[0])
                    icbl = float(parts[1])
                    sh2o = float(parts[2])
                    snh4 = max(0.1, float(parts[3]) * scale_factor)
                    sno3 = max(0.5, float(parts[4]) * scale_factor)
                    new_line = f" {c:2d} {icbl:5.0f} {sh2o:5.3f} {snh4:5.1f} {sno3:5.1f}"
                    new_lines.append(new_line)
                except:
                    new_lines.append(l)
            else:
                new_lines.append(l)
        else:
            new_lines.append(l)
            
    filex_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def patch_filex_uniform_profile(filex_path: Path, profile_sno3: list[float], profile_snh4: list[float]) -> None:
    """Set a uniform vertical profile for all treatments."""
    lines = filex_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    new_lines = []
    in_ic = False
    for l in lines:
        if l.startswith("*INITIAL CONDITIONS"):
            new_lines.append(l)
            in_ic = True
            continue
        elif l.startswith("*") and in_ic:
            in_ic = False
            new_lines.append(l)
            continue
            
        if in_ic:
            if l.startswith("@C"):
                new_lines.append(l)
            elif l.startswith(" ") and len(l.split()) >= 5:
                parts = l.split()
                try:
                    c = int(parts[0])
                    icbl = float(parts[1])
                    sh2o = float(parts[2])
                    depths = [20, 40, 60, 80, 100]
                    idx = 0
                    for i, d in enumerate(depths):
                        if icbl <= d:
                            idx = i
                            break
                    idx = min(len(profile_sno3) - 1, idx)
                    sno3 = profile_sno3[idx]
                    snh4 = profile_snh4[idx]
                    new_line = f" {c:2d} {icbl:5.0f} {sh2o:5.3f} {snh4:5.1f} {sno3:5.1f}"
                    new_lines.append(new_line)
                except:
                    new_lines.append(l)
            else:
                new_lines.append(l)
        else:
            new_lines.append(l)
            
    filex_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def evaluate_adjustment_scheme(scheme_name: str, mode: str, arg: object) -> dict[str, object]:
    scen_dir = OUT_DIR / scheme_name
    scen_dir.mkdir(parents=True, exist_ok=True)
    
    bdir25 = scen_dir / "25SP_bundle"
    if bdir25.exists(): shutil.rmtree(bdir25)
    shutil.copytree(PROJECT_ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830", bdir25)
    
    bdir26 = scen_dir / "26SP_bundle"
    if bdir26.exists(): shutil.rmtree(bdir26)
    shutil.copytree(PROJECT_ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830", bdir26)
    
    filex25 = next(bdir25.glob("*.TMX"))
    filex26 = next(bdir26.glob("*.TMX"))
    patch_filex_mesol(filex25)
    patch_filex_mesol(filex26)
    
    if mode == "scale":
        patch_filex_relative_scaling(filex25, float(arg))
    elif mode == "uniform":
        sno3_p, snh4_p = arg
        patch_filex_uniform_profile(filex25, sno3_p, snh4_p)
        
    base_design = json.loads((PROJECT_ROOT / "configs/runs/e02_small_v41_nresp10x_scheme4_60x3_20260830.json").read_text(encoding="utf-8"))
    base_design["design_id"] = f"scen_{scheme_name}"
    base_design["seasons"] = [
        {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(bdir25), "role": "calibration", "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]},
        {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(bdir26), "role": "calibration", "treatments": list(range(1, 13))},
    ]
    base_design["diagnostic_only"] = {"25SP": [], "26SP": []}
    
    df_file = scen_dir / "design.json"
    df_file.write_text(json.dumps(base_design, indent=2), encoding="utf-8")
    
    param_csv = scen_dir / "params.csv"
    shutil.copy2(BASE_PARAMS_PATH, param_csv)
    
    cmd = [
        PYTHON, str(PROJECT_ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(df_file),
        "--param-csv", str(param_csv),
        "--prefix", "det",
        "--harvest-var", "CHFPW",
    ]
    subprocess.run(cmd, cwd=str(scen_dir), capture_output=True, text=True)
    
    from src.reporting.analyze_results import deterministic_harvest_compare, deterministic_process_compare
    for sid, fx, tmts in [("25SP", filex25, [2,3,4,5,9,10,11,12,13,14]), ("26SP", filex26, list(range(1,13)))]:
        sdir = scen_dir / "_seasons" / sid
        batch = sdir / "analysis_batch.v48"
        batch.write_text("\n".join(f"{fx.resolve()} {int(tn)} 1 0 0 0" for tn in tmts) + "\n", encoding="utf-8")
        deterministic_harvest_compare(sid, str(batch), run_dir=str(sdir))
        deterministic_process_compare(sid, str(batch), var_names=["LAID", "LWAD", "SWAD"], run_dir=str(sdir))
        
    h25 = pd.read_csv(scen_dir / "_seasons/25SP/25SP_deterministic_harvest_compare.csv")
    h26 = pd.read_csv(scen_dir / "_seasons/26SP/26SP_deterministic_harvest_compare.csv")
    
    max25 = h25["HNO"].max()
    max26 = h26["HNO"].max()
    t25 = h25[h25["HNO"] == max25].set_index("TN")
    t26 = h26[h26["HNO"] == max26].set_index("TN")
    
    def _nse(obs, sim):
        ok = np.isfinite(obs) & np.isfinite(sim) & (obs != -99) & (sim != -99)
        o, s = obs[ok], sim[ok]
        sst = np.sum((o - o.mean()) ** 2)
        return float(1.0 - np.sum((s - o) ** 2) / sst) if sst > 0 else np.nan
        
    def _rrmse(obs, sim):
        ok = np.isfinite(obs) & np.isfinite(sim) & (obs != -99) & (sim != -99)
        o, s = obs[ok], sim[ok]
        return float(100.0 * np.sqrt(np.mean((s - o) ** 2)) / np.mean(np.abs(o))) if len(o) > 0 else np.nan
        
    return {
        "scheme": scheme_name,
        "25SP_W3_diff_sim": float(t25.loc[2, "SIM_FRESH_CUM"] - t25.loc[5, "SIM_FRESH_CUM"]),
        "25SP_W3_diff_obs": float(t25.loc[2, "OBS_FRESH_CUM"] - t25.loc[5, "OBS_FRESH_CUM"]),
        "25SP_W1_diff_sim": float(t25.loc[10, "SIM_FRESH_CUM"] - t25.loc[13, "SIM_FRESH_CUM"]),
        "25SP_W1_diff_obs": float(t25.loc[10, "OBS_FRESH_CUM"] - t25.loc[13, "OBS_FRESH_CUM"]),
        "26SP_W2_diff_sim": float(t26.loc[2, "SIM_FRESH_CUM"] - t26.loc[11, "SIM_FRESH_CUM"]),
        "26SP_W2_diff_obs": float(t26.loc[2, "OBS_FRESH_CUM"] - t26.loc[11, "OBS_FRESH_CUM"]),
        "26SP_W1_diff_sim": float(t26.loc[3, "SIM_FRESH_CUM"] - t26.loc[12, "SIM_FRESH_CUM"]),
        "26SP_W1_diff_obs": float(t26.loc[3, "OBS_FRESH_CUM"] - t26.loc[12, "OBS_FRESH_CUM"]),
        "25SP_FRESH_NSE": _nse(h25["OBS_FRESH_CUM"].to_numpy(float), h25["SIM_FRESH_CUM"].to_numpy(float)),
        "26SP_FRESH_NSE": _nse(h26["OBS_FRESH_CUM"].to_numpy(float), h26["SIM_FRESH_CUM"].to_numpy(float)),
        "25SP_FRESH_RRMSE": _rrmse(h25["OBS_FRESH_CUM"].to_numpy(float), h25["SIM_FRESH_CUM"].to_numpy(float)),
        "26SP_FRESH_RRMSE": _rrmse(h26["OBS_FRESH_CUM"].to_numpy(float), h26["SIM_FRESH_CUM"].to_numpy(float)),
        "25SP_TN2_W3N3_yield": float(t25.loc[2, "SIM_FRESH_CUM"]),
        "25SP_TN5_W3N0_yield": float(t25.loc[5, "SIM_FRESH_CUM"]),
        "25SP_TN10_W1N3_yield": float(t25.loc[10, "SIM_FRESH_CUM"]),
        "25SP_TN13_W1N0_yield": float(t25.loc[13, "SIM_FRESH_CUM"]),
    }


def main():
    schemes = [
        # Baseline
        ("00_Baseline_Original_IC", "none", None),
        
        # Scheme A: Relative Proportional Scaling (Scale factor 0.30)
        ("Scheme_A_Relative_Scale_0.30", "scale", 0.30),
        ("Scheme_A_Relative_Scale_0.20", "scale", 0.20),
        
        # Scheme B: Block-Averaged Vertical Profile (9.0, 4.5, 1.5, 1.0, 1.0 ppm)
        ("Scheme_B_Block_Mean_Profile", "uniform", ([9.0, 4.5, 1.5, 1.0, 1.0], [0.5, 0.3, 0.2, 0.1, 0.1])),
        
        # Scheme C: Moderate Greenhouse Clean Baseline (6.0, 3.0, 1.0, 0.5, 0.5 ppm)
        ("Scheme_C_Moderate_Baseline", "uniform", ([6.0, 3.0, 1.0, 0.5, 0.5], [0.3, 0.2, 0.1, 0.1, 0.1])),
    ]
    
    results = []
    for name, mode, arg in schemes:
        print(f"[RUN] Testing {name}...")
        res = evaluate_adjustment_scheme(name, mode, arg)
        results.append(res)
        print(f"      25SP W3 N-diff: {res['25SP_W3_diff_sim']:+7.1f} (Obs: {res['25SP_W3_diff_obs']:+7.1f}) | W1 N-diff: {res['25SP_W1_diff_sim']:+7.1f} (Obs: {res['25SP_W1_diff_obs']:+7.1f})")
        print(f"      25SP Fresh Yield -> TN2(W3N3): {res['25SP_TN2_W3N3_yield']:.0f} | TN5(W3N0): {res['25SP_TN5_W3N0_yield']:.0f}")
        print(f"      Fresh Yield NSE -> 25SP: {res['25SP_FRESH_NSE']:.3f}, 26SP: {res['26SP_FRESH_NSE']:.3f}\n")
        
    df = pd.DataFrame(results)
    out_csv = OUT_DIR / "relative_initial_n_schemes_comparison.csv"
    df.to_csv(out_csv, index=False)
    print(f"[DONE] Results written to {out_csv}")


if __name__ == "__main__":
    main()
