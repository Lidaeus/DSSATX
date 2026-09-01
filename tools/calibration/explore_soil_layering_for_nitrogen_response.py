#!/usr/bin/env python3
"""Explore soil profile layering schemes for improving DSSAT nitrogen response.
Tests multiple candidate soil layering schemes (depths SLB) on 25SP and 26SP.
Evaluates the causal effect on:
- 25SP W3 and W1 N3 - N0 terminal fresh yield differences (target: positive)
- 26SP W3 and W1 N3 - N0 terminal fresh yield differences (target: reduce over-response)
- Goodness of fit (LAI NSE, Fresh Yield NSE, RRMSE)
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

OUT_DIR = PROJECT_ROOT / "workspace/reports/soil_layering_n_response_exploration_20260829"
SCRATCH_DIR = OUT_DIR / "runs"

# Master IBTM910017 soil layer properties for continuous depth interpolation
# Format: (depth_bottom_cm, SLLL, SDUL, SSAT, SRGF, SBDM, SLOC, SLNI, SLHW)
MASTER_SOIL_DATA = [
    (5,   0.125, 0.198, 0.294, 1.000, 1.49, 1.73, 0.08, 8.0),
    (15,  0.125, 0.198, 0.294, 0.874, 1.49, 1.73, 0.08, 8.0),
    (25,  0.125, 0.198, 0.294, 0.874, 1.49, 1.73, 0.08, 8.0),
    (34,  0.117, 0.226, 0.323, 0.351, 1.41, 0.40, 0.03, 8.0),
    (43,  0.117, 0.226, 0.323, 0.351, 1.41, 0.40, 0.03, 8.0),
    (53,  0.138, 0.250, 0.332, 0.310, 1.44, 0.20, 0.02, 8.0),
    (64,  0.138, 0.250, 0.332, 0.310, 1.44, 0.20, 0.02, 8.0),
    (102, 0.167, 0.281, 0.331, 0.302, 1.57, 0.14, 0.01, 8.0),
    (145, 0.182, 0.291, 0.334, 0.077, 1.59, 0.16, 0.01, 8.0),
    (175, 0.162, 0.272, 0.320, 0.036, 1.61, 0.09, 0.01, 8.0),
    (203, 0.154, 0.263, 0.319, 0.006, 1.58, 0.03, 0.01, 8.0),
]


def interpolate_soil_layer(layer_bottom: float) -> dict[str, float]:
    """Interpolate physical properties at given layer bottom depth from master profile."""
    depths = [d[0] for d in MASTER_SOIL_DATA]
    slll_vals = [d[1] for d in MASTER_SOIL_DATA]
    sdul_vals = [d[2] for d in MASTER_SOIL_DATA]
    ssat_vals = [d[3] for d in MASTER_SOIL_DATA]
    srgf_vals = [d[4] for d in MASTER_SOIL_DATA]
    sbdm_vals = [d[5] for d in MASTER_SOIL_DATA]
    sloc_vals = [d[6] for d in MASTER_SOIL_DATA]
    slni_vals = [d[7] for d in MASTER_SOIL_DATA]
    slhw_vals = [d[8] for d in MASTER_SOIL_DATA]

    # Calculate root growth factor according to depth (SRGF = 1.0 for top 15cm, decay below)
    if layer_bottom <= 15:
        srgf = 1.000
    else:
        srgf = float(np.exp(-0.02 * (layer_bottom - 15)))

    return {
        "SLB": int(layer_bottom),
        "SLLL": float(np.interp(layer_bottom, depths, slll_vals)),
        "SDUL": float(np.interp(layer_bottom, depths, sdul_vals)),
        "SSAT": float(np.interp(layer_bottom, depths, ssat_vals)),
        "SRGF": max(0.005, min(1.0, srgf)),
        "SBDM": float(np.interp(layer_bottom, depths, sbdm_vals)),
        "SLOC": float(np.interp(layer_bottom, depths, sloc_vals)),
        "SLNI": float(np.interp(layer_bottom, depths, slni_vals)),
        "SLHW": float(np.interp(layer_bottom, depths, slhw_vals)),
    }


def generate_soil_sol_text(layers: list[int]) -> str:
    """Generate SOIL.SOL block for IBTM910017 with user-specified layers."""
    header = """*IBTM910017  SCS         -99     203 Orangeburg Sandy Loam
@SITE        COUNTRY          LAT     LONG SCS FAMILY
 Quincy      USA           30.600  -86.400 Loamy,silic,hyperth Gross. Paleud(17)
@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE
   -99  0.13   9.0  0.27  84.0  1.00  0.96 IB001 IB001 IB001
@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC"""
    
    rows = []
    for lb in layers:
        p = interpolate_soil_layer(lb)
        row = f"{p['SLB']:6d}   -99 {p['SLLL']:5.3f} {p['SDUL']:5.3f} {p['SSAT']:5.3f} {p['SRGF']:5.3f}   -99  {p['SBDM']:4.2f}  {p['SLOC']:4.2f}   -99   -99   -99 {p['SLNI']:5.3f}   {p['SLHW']:3.1f}   -99   -99   -99"
        rows.append(row)
    
    return header + "\n" + "\n".join(rows) + "\n"


def patch_filex_mesol(filex_path: Path) -> None:
    """Ensure FileX has MESOL=2 for user-defined soil layering across all SIMULATION CONTROLS."""
    content = filex_path.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()
    new_lines = []
    for line in lines:
        # Check for ME line under SIMULATION CONTROLS
        # format: 2 ME M M E R S L R 1 P R 2
        if "ME" in line and len(line.split()) >= 13 and line.strip()[0].isdigit():
            parts = line.split()
            # The last token is MESOL, ensure it is 2
            if parts[-1] != "2":
                parts[-1] = "2"
            new_lines.append(f"{parts[0]:>2s} {parts[1]:<2s}              {'     '.join(parts[2:])}")
        else:
            new_lines.append(line)
    filex_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def evaluate_scheme(scheme_name: str, layers: list[int]) -> dict[str, float]:
    run_dir = SCRATCH_DIR / scheme_name
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create season bundle copies and patch SOIL.SOL + FileX
    bundle_root = run_dir / "_bundles"
    bundle_root.mkdir(parents=True, exist_ok=True)

    seasons_cfg = [
        ("25SP", "XXQL2501", PROJECT_ROOT / "data/user/experiments/xxql2501_formal_armab_rrmse_20260828", [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]),
        ("26SP", "XXQL2601", PROJECT_ROOT / "data/user/experiments/xxql2601_formal_armab_rrmse_26spncal_20260828", list(range(1, 13))),
    ]

    soil_text = generate_soil_sol_text(layers)

    season_entries = []
    for sid, excode, orig_bundle, tmts in seasons_cfg:
        s_bdir = bundle_root / sid
        if s_bdir.exists():
            shutil.rmtree(s_bdir)
        shutil.copytree(orig_bundle, s_bdir)

        # Replace IBTM910017 in SOIL.SOL
        soil_sol_path = s_bdir / "SOIL.SOL"
        raw_soil = soil_sol_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        new_soil = []
        i = 0
        while i < len(raw_soil):
            l = raw_soil[i]
            if l.startswith("*IBTM910017"):
                new_soil.append(soil_text.strip())
                i += 1
                # Skip old profile until next soil block
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

    # 2. Design JSON
    design_content = json.loads((PROJECT_ROOT / "configs/runs/e02_formal_v37_fresh_yield_source_sink_200x4_20260829.json").read_text(encoding="utf-8"))
    design_content["design_id"] = f"soil_eval_{scheme_name}"
    design_content["seasons"] = season_entries

    design_file = run_dir / "design.json"
    design_file.write_text(json.dumps(design_content, indent=2), encoding="utf-8")

    # 3. Parameter file (Member #137)
    param_csv = run_dir / "params.csv"
    shutil.copy2(BASE_PARAMS_PATH, param_csv)

    # 4. Run DSSAT multiseason
    cmd = [
        PYTHON,
        str(PROJECT_ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_file),
        "--param-csv", str(param_csv),
        "--prefix", "det",
        "--harvest-var", "CHFPW",
    ]
    res = subprocess.run(cmd, cwd=str(run_dir), capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[ERROR] Simulation failed for {scheme_name}: {res.stderr}")
        return {}

    # 5. Build comparisons
    from src.reporting.analyze_results import deterministic_process_compare, deterministic_harvest_compare
    for sid, _, _, tmts in seasons_cfg:
        sdir = run_dir / "_seasons" / sid
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

    # 6. Parse harvest compares
    h25 = pd.read_csv(run_dir / "_seasons/25SP/25SP_deterministic_harvest_compare.csv")
    h26 = pd.read_csv(run_dir / "_seasons/26SP/26SP_deterministic_harvest_compare.csv")
    p25 = pd.read_csv(run_dir / "_seasons/25SP/25SP_deterministic_process_compare.csv")
    p26 = pd.read_csv(run_dir / "_seasons/26SP/26SP_deterministic_process_compare.csv")

    def _nse(obs, sim):
        ok = np.isfinite(obs) & np.isfinite(sim) & (obs != -99) & (sim != -99)
        o, s = obs[ok], sim[ok]
        if len(o) < 2: return np.nan
        sst = np.sum((o - o.mean()) ** 2)
        if sst <= 0: return np.nan
        return 1.0 - np.sum((s - o) ** 2) / sst

    def _rrmse(obs, sim):
        ok = np.isfinite(obs) & np.isfinite(sim) & (obs != -99) & (sim != -99)
        o, s = obs[ok], sim[ok]
        if len(o) < 1: return np.nan
        return float(100.0 * np.sqrt(np.mean((s - o) ** 2)) / np.mean(np.abs(o)))

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
    fresh_rrmse_25 = _rrmse(h25["OBS_FRESH_CUM"].to_numpy(float), h25["SIM_FRESH_CUM"].to_numpy(float))
    fresh_rrmse_26 = _rrmse(h26["OBS_FRESH_CUM"].to_numpy(float), h26["SIM_FRESH_CUM"].to_numpy(float))

    return {
        "scheme": scheme_name,
        "n_layers": len(layers),
        "layers_str": "-".join(map(str, layers)),
        "25SP_W3_diff_sim": sim_25_w3_diff,
        "25SP_W3_diff_obs": obs_25_w3_diff,
        "25SP_W1_diff_sim": sim_25_w1_diff,
        "25SP_W1_diff_obs": obs_25_w1_diff,
        "26SP_W3_diff_sim": sim_26_w3_diff,
        "26SP_W3_diff_obs": obs_26_w3_diff,
        "26SP_W1_diff_sim": sim_26_w1_diff,
        "26SP_W1_diff_obs": obs_26_w1_diff,
        "25SP_both_pos": bool(sim_25_w3_diff > 0 and sim_25_w1_diff > 0),
        "26SP_err_w3": abs(sim_26_w3_diff - obs_26_w3_diff),
        "26SP_err_w1": abs(sim_26_w1_diff - obs_26_w1_diff),
        "25SP_LAI_NSE": lai_nse_25,
        "26SP_LAI_NSE": lai_nse_26,
        "25SP_FRESH_NSE": fresh_nse_25,
        "26SP_FRESH_NSE": fresh_nse_26,
        "25SP_FRESH_RRMSE": fresh_rrmse_25,
        "26SP_FRESH_RRMSE": fresh_rrmse_26,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    schemes = [
        ("Scheme_4_Rootzone_3L_7L", [10, 30, 60, 90, 120, 150, 180]),
        ("Scheme_4A_8_20_40_60_8L", [8, 20, 40, 60, 90, 120, 150, 180]),
        ("Scheme_4B_10_20_40_60_8L", [10, 20, 40, 60, 90, 120, 150, 180]),
        ("Scheme_4C_12_25_45_65_7L", [12, 25, 45, 65, 95, 130, 180]),
        ("Scheme_4D_10_25_50_75_7L", [10, 25, 50, 75, 105, 140, 180]),
        ("Scheme_4E_8_25_50_80_6L", [8, 25, 50, 80, 120, 180]),
        ("Scheme_4F_12_30_60_90_7L", [12, 30, 60, 90, 120, 150, 180]),
        ("Scheme_4G_15_30_45_60_8L", [15, 30, 45, 60, 90, 120, 150, 180]),
        ("Scheme_4H_10_30_50_70_8L", [10, 30, 50, 70, 90, 120, 150, 180]),
        ("Scheme_4I_15_35_60_90_7L", [15, 35, 60, 90, 120, 150, 180]),
        ("Scheme_4J_18_36_60_90_7L", [18, 36, 60, 90, 120, 150, 180]),
    ]

    results = []
    for name, layers in schemes:
        print(f"[RUN] Evaluating Soil Scheme: {name} (layers: {layers})...")
        res = evaluate_scheme(name, layers)
        if res:
            results.append(res)
            print(f"      25SP W3 N-diff: {res['25SP_W3_diff_sim']:+.1f} (Obs: {res['25SP_W3_diff_obs']:+.1f}), W1: {res['25SP_W1_diff_sim']:+.1f} (Obs: {res['25SP_W1_diff_obs']:+.1f})")
            print(f"      26SP W3 N-diff: {res['26SP_W3_diff_sim']:+.1f} (Obs: {res['26SP_W3_diff_obs']:+.1f}), W1: {res['26SP_W1_diff_sim']:+.1f} (Obs: {res['26SP_W1_diff_obs']:+.1f})")
            print(f"      25SP Fresh NSE: {res['25SP_FRESH_NSE']:.3f}, 26SP Fresh NSE: {res['26SP_FRESH_NSE']:.3f}\n")

    df = pd.DataFrame(results)
    out_csv = OUT_DIR / "soil_layering_nitrogen_response_comparison.csv"
    df.to_csv(out_csv, index=False)
    print(f"\n[SUMMARY] Saved full soil layering comparison to: {out_csv}")


if __name__ == "__main__":
    main()
