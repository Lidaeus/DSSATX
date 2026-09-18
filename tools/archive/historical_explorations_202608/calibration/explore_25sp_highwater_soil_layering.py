#!/usr/bin/env python3
"""Explore soil layering schemes to resolve 25SP High-Water Yield Suppression & N-inversion.
Investigates the causal mechanisms of vegetative over-investment vs fruit sink allocation.
Tests 5 candidate soil profile schemes on both 25SP and 26SP (all 22 treatments).
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
    / "workspace/runs/e02_formal_v40_3x_yield_200x4_20260830"
    / "best_member_125_two_season_deterministic_20260830"
    / "best_member_125_params.csv"
)

OUT_DIR = PROJECT_ROOT / "workspace/reports/explore_25sp_highwater_soil_20260830"
SCRATCH_DIR = OUT_DIR / "runs"

from tools.calibration.explore_soil_layering_for_nitrogen_response import (
    generate_soil_sol_text, patch_filex_mesol
)


def evaluate_candidate(scheme_name: str, layers: list[int]) -> dict[str, object] | None:
    run_dir = SCRATCH_DIR / scheme_name
    run_dir.mkdir(parents=True, exist_ok=True)

    bundle_root = run_dir / "_bundles"
    bundle_root.mkdir(parents=True, exist_ok=True)

    seasons_cfg = [
        ("25SP", "XXQL2501", PROJECT_ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830", [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]),
        ("26SP", "XXQL2601", PROJECT_ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830", list(range(1, 13))),
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
    design_content = json.loads((PROJECT_ROOT / "configs/runs/e02_formal_v40_3x_yield_200x4_20260830.json").read_text(encoding="utf-8"))
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

    sim_26_w2 = float(t26.loc[2, "SIM_FRESH_CUM"] - t26.loc[11, "SIM_FRESH_CUM"])
    obs_26_w2 = float(t26.loc[2, "OBS_FRESH_CUM"] - t26.loc[11, "OBS_FRESH_CUM"])
    sim_26_w1 = float(t26.loc[3, "SIM_FRESH_CUM"] - t26.loc[12, "SIM_FRESH_CUM"])
    obs_26_w1 = float(t26.loc[3, "OBS_FRESH_CUM"] - t26.loc[12, "OBS_FRESH_CUM"])

    fresh_nse_25 = _nse(h25["OBS_FRESH_CUM"].to_numpy(float), h25["SIM_FRESH_CUM"].to_numpy(float))
    fresh_nse_26 = _nse(h26["OBS_FRESH_CUM"].to_numpy(float), h26["SIM_FRESH_CUM"].to_numpy(float))
    dry_nse_25 = _nse(h25["OBS_DRY_CUM"].to_numpy(float), h25["SIM_DRY_CUM"].to_numpy(float))
    dry_nse_26 = _nse(h26["OBS_DRY_CUM"].to_numpy(float), h26["SIM_DRY_CUM"].to_numpy(float))
    lai_nse_25 = _nse(p25["OBS_LAID"].to_numpy(float), p25["SIM_LAID"].to_numpy(float))
    lai_nse_26 = _nse(p26["OBS_LAID"].to_numpy(float), p26["SIM_LAID"].to_numpy(float))

    fresh_rrmse_25 = _rrmse(h25["OBS_FRESH_CUM"].to_numpy(float), h25["SIM_FRESH_CUM"].to_numpy(float))
    fresh_rrmse_26 = _rrmse(h26["OBS_FRESH_CUM"].to_numpy(float), h26["SIM_FRESH_CUM"].to_numpy(float))

    return {
        "scheme": scheme_name,
        "n_layers": len(layers),
        "layers_str": "-".join(map(str, layers)),
        "25SP_W3_diff_sim": sim_25_w3,
        "25SP_W3_diff_obs": obs_25_w3,
        "25SP_W1_diff_sim": sim_25_w1,
        "25SP_W1_diff_obs": obs_25_w1,
        "26SP_W2_diff_sim": sim_26_w2,
        "26SP_W2_diff_obs": obs_26_w2,
        "26SP_W1_diff_sim": sim_26_w1,
        "26SP_W1_diff_obs": obs_26_w1,
        "25SP_W3_yield_N3": float(t25.loc[2, "SIM_FRESH_CUM"]),
        "25SP_W3_yield_N0": float(t25.loc[5, "SIM_FRESH_CUM"]),
        "25SP_W1_yield_N3": float(t25.loc[10, "SIM_FRESH_CUM"]),
        "25SP_W1_yield_N0": float(t25.loc[13, "SIM_FRESH_CUM"]),
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
        ("Baseline_Scheme_4", [10, 30, 60, 90, 120, 150, 180]),
        ("Scheme_A_Plough12_Buffer35", [12, 35, 65, 95, 125, 155, 180]),
        ("Scheme_B_Plough14_Stratified", [14, 30, 50, 75, 105, 140, 180]),
        ("Scheme_C_DeepInfil_4Tier", [12, 28, 48, 70, 100, 140, 180]),
        ("Scheme_D_UniformDrain_6Tier", [13, 30, 55, 80, 115, 150, 180]),
        ("Scheme_E_ExtendedRoot_10_25_45", [10, 25, 45, 70, 100, 140, 180]),
        ("Scheme_F_Plough15_Sub40", [15, 40, 65, 95, 125, 155, 180]),
        ("Scheme_G_Plough12_Sub28_50", [12, 28, 50, 75, 105, 140, 180]),
    ]

    results = []
    for name, layers in candidate_schemes:
        print(f"[RUN] Evaluating: {name} (layers: {layers})...")
        res = evaluate_candidate(name, layers)
        if res is not None:
            results.append(res)
            print(f"      25SP W3 N-diff (Sim vs Obs): {res['25SP_W3_diff_sim']:+.1f} vs {res['25SP_W3_diff_obs']:+.1f}")
            print(f"      25SP W1 N-diff (Sim vs Obs): {res['25SP_W1_diff_sim']:+.1f} vs {res['25SP_W1_diff_obs']:+.1f}")
            print(f"      26SP W2 N-diff (Sim vs Obs): {res['26SP_W2_diff_sim']:+.1f} vs {res['26SP_W2_diff_obs']:+.1f}")
            print(f"      26SP W1 N-diff (Sim vs Obs): {res['26SP_W1_diff_sim']:+.1f} vs {res['26SP_W1_diff_obs']:+.1f}")
            print(f"      Fresh Yield NSE -> 25SP: {res['25SP_FRESH_NSE']:.3f}, 26SP: {res['26SP_FRESH_NSE']:.3f}\n")

    df = pd.DataFrame(results)
    out_csv = OUT_DIR / "25sp_highwater_soil_layering_comparison.csv"
    df.to_csv(out_csv, index=False)
    print(f"\n[DONE] Saved results to: {out_csv}")


if __name__ == "__main__":
    main()
