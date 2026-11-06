#!/usr/bin/env python3
"""Multi-directional exploration of soil profile layering schemes for DSSAT crop model.
Explores 5 distinct structural directions (22 candidate schemes) on 25SP & 26SP (all 22 treatments).
Ranks schemes using a multi-objective scientific fitness index:
- N-Response fidelity in 26SP (reduction of over-response)
- N-Response recovery in 25SP (mitigation of inversion)
- Fresh/dry fruit yield NSE & RRMSE across both spring seasons
- Process state dynamics (LAI, biomass)
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

OUT_DIR = PROJECT_ROOT / "workspace/reports/multidirectional_soil_exploration_20260830"
SCRATCH_DIR = OUT_DIR / "runs"

from tools.calibration.explore_soil_layering_for_nitrogen_response import (
    generate_soil_sol_text, patch_filex_mesol
)


def evaluate_single_scheme(scheme_name: str, direction: str, layers: list[int]) -> dict[str, object] | None:
    run_dir = SCRATCH_DIR / scheme_name
    run_dir.mkdir(parents=True, exist_ok=True)

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
    design_content["design_id"] = f"soil_eval_{scheme_name}"
    design_content["seasons"] = season_entries

    design_file = run_dir / "design.json"
    design_file.write_text(json.dumps(design_content, indent=2), encoding="utf-8")

    # Params
    param_csv = run_dir / "params.csv"
    shutil.copy2(BASE_PARAMS_PATH, param_csv)

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
        print(f"[FAIL] {scheme_name} crashed: {res.stderr[:200]}")
        return None

    # Comparisons
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
        return float(1.0 - np.sum((s - o) ** 2) / sst)

    def _rrmse(obs, sim):
        ok = np.isfinite(obs) & np.isfinite(sim) & (obs != -99) & (sim != -99)
        o, s = obs[ok], sim[ok]
        if len(o) < 1: return np.nan
        return float(100.0 * np.sqrt(np.mean((s - o) ** 2)) / np.mean(np.abs(o)))

    max25 = h25["HNO"].max()
    max26 = h26["HNO"].max()
    t25 = h25[h25["HNO"] == max25].set_index("TN")
    t26 = h26[h26["HNO"] == max26].set_index("TN")

    sim_25_w3 = float(t25.loc[2, "SIM_FRESH_CUM"] - t25.loc[5, "SIM_FRESH_CUM"])
    obs_25_w3 = float(t25.loc[2, "OBS_FRESH_CUM"] - t25.loc[5, "OBS_FRESH_CUM"])
    sim_25_w1 = float(t25.loc[10, "SIM_FRESH_CUM"] - t25.loc[13, "SIM_FRESH_CUM"])
    obs_25_w1 = float(t25.loc[10, "OBS_FRESH_CUM"] - t25.loc[13, "OBS_FRESH_CUM"])

    sim_26_w3 = float(t26.loc[1, "SIM_FRESH_CUM"] - t26.loc[9, "SIM_FRESH_CUM"])
    obs_26_w3 = float(t26.loc[1, "OBS_FRESH_CUM"] - t26.loc[9, "OBS_FRESH_CUM"])
    sim_26_w1 = float(t26.loc[3, "SIM_FRESH_CUM"] - t26.loc[12, "SIM_FRESH_CUM"])
    obs_26_w1 = float(t26.loc[3, "OBS_FRESH_CUM"] - t26.loc[12, "OBS_FRESH_CUM"])

    lai_nse_25 = _nse(p25["OBS_LAID"].to_numpy(float), p25["SIM_LAID"].to_numpy(float))
    lai_nse_26 = _nse(p26["OBS_LAID"].to_numpy(float), p26["SIM_LAID"].to_numpy(float))
    fresh_nse_25 = _nse(h25["OBS_FRESH_CUM"].to_numpy(float), h25["SIM_FRESH_CUM"].to_numpy(float))
    fresh_nse_26 = _nse(h26["OBS_FRESH_CUM"].to_numpy(float), h26["SIM_FRESH_CUM"].to_numpy(float))
    dry_nse_25 = _nse(h25["OBS_DRY_CUM"].to_numpy(float), h25["SIM_DRY_CUM"].to_numpy(float))
    dry_nse_26 = _nse(h26["OBS_DRY_CUM"].to_numpy(float), h26["SIM_DRY_CUM"].to_numpy(float))

    fresh_rrmse_25 = _rrmse(h25["OBS_FRESH_CUM"].to_numpy(float), h25["SIM_FRESH_CUM"].to_numpy(float))
    fresh_rrmse_26 = _rrmse(h26["OBS_FRESH_CUM"].to_numpy(float), h26["SIM_FRESH_CUM"].to_numpy(float))

    err_26_w3 = abs(sim_26_w3 - obs_26_w3)
    err_26_w1 = abs(sim_26_w1 - obs_26_w1)
    err_25_w3 = abs(sim_25_w3 - obs_25_w3)
    err_25_w1 = abs(sim_25_w1 - obs_25_w1)

    return {
        "scheme": scheme_name,
        "direction": direction,
        "n_layers": len(layers),
        "layers_str": "-".join(map(str, layers)),
        "25SP_W3_diff_sim": sim_25_w3,
        "25SP_W1_diff_sim": sim_25_w1,
        "26SP_W3_diff_sim": sim_26_w3,
        "26SP_W1_diff_sim": sim_26_w1,
        "26SP_err_w3": err_26_w3,
        "26SP_err_w1": err_26_w1,
        "25SP_err_w3": err_25_w3,
        "25SP_err_w1": err_25_w1,
        "25SP_both_pos": bool(sim_25_w3 > 0 and sim_25_w1 > 0),
        "25SP_w1_pos": bool(sim_25_w1 > 0),
        "25SP_FRESH_NSE": fresh_nse_25,
        "26SP_FRESH_NSE": fresh_nse_26,
        "25SP_DRY_NSE": dry_nse_25,
        "26SP_DRY_NSE": dry_nse_26,
        "25SP_LAI_NSE": lai_nse_25,
        "26SP_LAI_NSE": lai_nse_26,
        "25SP_FRESH_RRMSE": fresh_rrmse_25,
        "26SP_FRESH_RRMSE": fresh_rrmse_26,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    candidate_schemes = [
        # Baseline Reference
        ("Ref_Scheme_4_10_30_60cm", "Reference", [10, 30, 60, 90, 120, 150, 180]),
        ("Ref_Scheme_4F_12_30_60cm", "Reference", [12, 30, 60, 90, 120, 150, 180]),

        # Direction 1: Plough-Layer & Root-Zone Granularity Modulation (12~18cm Top Layer)
        ("Dir1_A_12_25_50_75_105_140_180", "D1_PloughDepth", [12, 25, 50, 75, 105, 140, 180]),
        ("Dir1_B_14_28_50_75_105_140_180", "D1_PloughDepth", [14, 28, 50, 75, 105, 140, 180]),
        ("Dir1_C_15_30_50_75_105_140_180", "D1_PloughDepth", [15, 30, 50, 75, 105, 140, 180]),
        ("Dir1_D_16_32_55_80_110_145_180", "D1_PloughDepth", [16, 32, 55, 80, 110, 145, 180]),
        ("Dir1_E_18_35_60_85_115_150_180", "D1_PloughDepth", [18, 35, 60, 85, 115, 150, 180]),

        # Direction 2: 4-Layer Fine-Root Zone in 0-60cm (8 Layers Total)
        ("Dir2_A_8_18_35_60_90_120_150_180", "D2_FourLayerRoot", [8, 18, 35, 60, 90, 120, 150, 180]),
        ("Dir2_B_10_22_38_60_90_120_150_180", "D2_FourLayerRoot", [10, 22, 38, 60, 90, 120, 150, 180]),
        ("Dir2_C_12_24_40_60_90_120_150_180", "D2_FourLayerRoot", [12, 24, 40, 60, 90, 120, 150, 180]),
        ("Dir2_D_14_26_42_60_90_120_150_180", "D2_FourLayerRoot", [14, 26, 42, 60, 90, 120, 150, 180]),
        ("Dir2_E_10_20_35_55_80_110_145_180", "D2_FourLayerRoot", [10, 20, 35, 55, 80, 110, 145, 180]),

        # Direction 3: Asymmetric Infiltration Profile (Geometric Layer Stretching)
        ("Dir3_A_7_17_32_55_85_125_180", "D3_GeometricStretching", [7, 17, 32, 55, 85, 125, 180]),
        ("Dir3_B_9_20_36_60_95_135_180", "D3_GeometricStretching", [9, 20, 36, 60, 95, 135, 180]),
        ("Dir3_C_11_24_42_68_102_140_180", "D3_GeometricStretching", [11, 24, 42, 68, 102, 140, 180]),
        ("Dir3_D_13_27_46_72_105_142_180", "D3_GeometricStretching", [13, 27, 46, 72, 105, 142, 180]),

        # Direction 4: Two-Tier Root Zone + Compact Deep Subsoil
        ("Dir4_A_12_30_50_70_100_140_180", "D4_TwoTierSubsoil", [12, 30, 50, 70, 100, 140, 180]),
        ("Dir4_B_14_30_48_68_95_135_180", "D4_TwoTierSubsoil", [14, 30, 48, 68, 95, 135, 180]),
        ("Dir4_C_11_28_48_70_100_140_180", "D4_TwoTierSubsoil", [11, 28, 48, 70, 100, 140, 180]),
        ("Dir4_D_13_30_52_75_105_145_180", "D4_TwoTierSubsoil", [13, 30, 52, 75, 105, 145, 180]),

        # Direction 5: Drip-Zone Mulched Layering (Thin Surface + Deep Soil Buffer)
        ("Dir5_A_6_16_30_50_75_110_150_180", "D5_DripMulched", [6, 16, 30, 50, 75, 110, 150, 180]),
        ("Dir5_B_8_18_32_52_78_112_150_180", "D5_DripMulched", [8, 18, 32, 52, 78, 112, 150, 180]),
        ("Dir5_C_10_22_36_56_82_115_150_180", "D5_DripMulched", [10, 22, 36, 56, 82, 115, 150, 180]),
        ("Dir5_D_12_25_40_62_90_125_155_180", "D5_DripMulched", [12, 25, 40, 62, 90, 125, 155, 180]),
    ]

    results = []
    for idx, (name, dir_name, layers) in enumerate(candidate_schemes, 1):
        print(f"[{idx}/{len(candidate_schemes)}] Testing [{dir_name}] {name} (layers: {layers})...")
        res = evaluate_single_scheme(name, dir_name, layers)
        if res is not None:
            results.append(res)
            print(f"      25SP N-diff -> W3: {res['25SP_W3_diff_sim']:+.1f}, W1: {res['25SP_W1_diff_sim']:+.1f}")
            print(f"      26SP N-diff -> W3: {res['26SP_W3_diff_sim']:+.1f} (Err: {res['26SP_err_w3']:.0f}), W1: {res['26SP_W1_diff_sim']:+.1f} (Err: {res['26SP_err_w1']:.0f})")
            print(f"      Fresh NSE -> 25SP: {res['25SP_FRESH_NSE']:.3f}, 26SP: {res['26SP_FRESH_NSE']:.3f}\n")

    df = pd.DataFrame(results)

    # Calculate Scientific Composite Score (Higher is Better)
    # Score rewards: high 25SP & 26SP Fresh/Dry NSE, low N-response errors, positive 25SP W1/W3
    norm_26_err = (df["26SP_err_w3"] + df["26SP_err_w1"]) / 10000.0
    norm_25_w1_bonus = np.clip(df["25SP_W1_diff_sim"] / 5000.0, -1.0, 1.0)
    norm_25_w3_bonus = np.clip(df["25SP_W3_diff_sim"] / 5000.0, -1.0, 1.0)
    
    df["composite_score"] = (
        0.30 * df["26SP_FRESH_NSE"]
        + 0.25 * df["25SP_FRESH_NSE"]
        + 0.15 * df["26SP_DRY_NSE"]
        + 0.10 * df["25SP_DRY_NSE"]
        - 0.15 * norm_26_err
        + 0.05 * norm_25_w1_bonus
    )

    df_sorted = df.sort_values("composite_score", ascending=False)
    out_csv = OUT_DIR / "multidirectional_soil_layering_comparison.csv"
    df_sorted.to_csv(out_csv, index=False)
    print(f"\n[DONE] Explored {len(df)} schemes. Full ranking saved to: {out_csv}")
    print("\nTop 5 Champion Schemes:")
    cols_show = ["scheme", "direction", "composite_score", "25SP_W1_diff_sim", "26SP_W3_diff_sim", "26SP_W1_diff_sim", "25SP_FRESH_NSE", "26SP_FRESH_NSE"]
    print(df_sorted[cols_show].head(5).to_string(index=False))


if __name__ == "__main__":
    main()
