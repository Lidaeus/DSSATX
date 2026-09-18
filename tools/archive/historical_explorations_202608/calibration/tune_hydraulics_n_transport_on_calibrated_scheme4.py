#!/usr/bin/env python3
"""Fine-tune soil hydraulics (SLDR, SLNF, SLU1) and nitrogen transport/mobilization
(RTNO3, NMOBMX, KCAN, SFDUR) directly on top of the calibrated Member #125 parameters.
Evaluates all 22 treatments in 25SP and 26SP.
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

RUN_DIR_BASE = PROJECT_ROOT / "workspace/runs/e02_formal_v40_3x_yield_200x4_20260830/best_member_125_two_season_deterministic_20260830"
BASE_PARAMS_PATH = RUN_DIR_BASE / "best_member_125_params.csv"
BASE_SOIL_SOL = RUN_DIR_BASE / "_seasons/25SP/SOIL.SOL"

OUT_DIR = PROJECT_ROOT / "workspace/reports/tune_hydraulics_n_transport_20260830"
SCRATCH_DIR = OUT_DIR / "runs"

from tools.calibration.explore_soil_layering_for_nitrogen_response import patch_filex_mesol


def patch_soil_header(raw_text: str, sldr: float = 0.55, slnf: float = 1.00, slu1: float = 7.0) -> str:
    """Patch SLDR, SLNF, SLU1 in IBTM910017 header while preserving calibrated layer properties."""
    lines = raw_text.splitlines()
    new_lines = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if l.startswith("*IBTM910017"):
            new_lines.append(l)
            i += 1
            while i < len(lines) and not lines[i].startswith("@ SCOM"):
                new_lines.append(lines[i])
                i += 1
            if i < len(lines) and lines[i].startswith("@ SCOM"):
                new_lines.append(lines[i])  # header row
                i += 1
                # line with SCOM SALB SLU1 SLDR SLRO SLNF SLPF SMHB SMPX SMKE
                header_line = f"   -99  0.13   {slu1:3.1f}  {sldr:4.2f}  75.0  {slnf:4.2f}  0.92 IB001 IB001 IB001"
                new_lines.append(header_line)
                i += 1
        else:
            new_lines.append(l)
            i += 1
    return "\n".join(new_lines) + "\n"


def evaluate_tuned_case(
    case_name: str,
    sldr: float,
    slnf: float,
    slu1: float,
    param_overrides: dict[str, float],
) -> dict[str, object] | None:
    run_dir = SCRATCH_DIR / case_name
    run_dir.mkdir(parents=True, exist_ok=True)

    bundle_root = run_dir / "_bundles"
    bundle_root.mkdir(parents=True, exist_ok=True)

    seasons_cfg = [
        ("25SP", "XXQL2501", PROJECT_ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830", [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]),
        ("26SP", "XXQL2601", PROJECT_ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830", list(range(1, 13))),
    ]

    base_soil_text = BASE_SOIL_SOL.read_text(encoding="utf-8", errors="ignore")
    patched_soil = patch_soil_header(base_soil_text, sldr=sldr, slnf=slnf, slu1=slu1)

    season_entries = []
    for sid, excode, orig_bundle, tmts in seasons_cfg:
        s_bdir = bundle_root / sid
        if s_bdir.exists():
            shutil.rmtree(s_bdir)
        shutil.copytree(orig_bundle, s_bdir)

        # Write patched SOIL.SOL
        (s_bdir / "SOIL.SOL").write_text(patched_soil, encoding="utf-8")

        # Patch FileX
        patch_filex_mesol(next(s_bdir.glob("*.TMX")))

        season_entries.append({
            "season_id": sid,
            "experiment_code": excode,
            "bundle_path": str(s_bdir),
            "role": "calibration",
            "treatments": tmts,
        })

    # Design JSON
    design_content = json.loads((PROJECT_ROOT / "configs/runs/e02_formal_v40_3x_yield_200x4_20260830.json").read_text(encoding="utf-8"))
    design_content["design_id"] = f"soil_eval_{case_name}"
    design_content["seasons"] = season_entries

    design_file = run_dir / "design.json"
    design_file.write_text(json.dumps(design_content, indent=2), encoding="utf-8")

    # Params
    base_df = pd.read_csv(BASE_PARAMS_PATH)
    p_map = base_df.set_index("name")["value"].to_dict()
    p_map.update(param_overrides)
    p_df = pd.DataFrame([{"name": k, "value": v} for k, v in p_map.items()])
    param_csv = run_dir / "params.csv"
    p_df.to_csv(param_csv, index=False)

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
        print(f"[FAIL] {case_name} failed: {res.stderr[:200]}")
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
        "case": case_name,
        "sldr": sldr,
        "slnf": slnf,
        "25SP_W3_diff_sim": sim_25_w3,
        "25SP_W3_diff_obs": obs_25_w3,
        "25SP_W1_diff_sim": sim_25_w1,
        "25SP_W1_diff_obs": obs_25_w1,
        "26SP_W2_diff_sim": sim_26_w2,
        "26SP_W2_diff_obs": obs_26_w2,
        "26SP_W1_diff_sim": sim_26_w1,
        "26SP_W1_diff_obs": obs_26_w1,
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

    cases = [
        # Baseline Member 125
        ("00_Baseline_Member125", 0.45, 1.00, 7.0, {}),
        
        # SLDR variation (Drainage rate fraction)
        ("01_SLDR_0.60", 0.60, 1.00, 6.0, {}),
        ("02_SLDR_0.75", 0.75, 1.00, 5.0, {}),
        
        # SLNF variation (Nitrification & mineralization rate)
        ("03_SLNF_0.85_SLDR_0.60", 0.60, 0.85, 6.0, {}),
        ("04_SLNF_1.20_SLDR_0.60", 0.60, 1.20, 6.0, {}),

        # N mobilization & root uptake tuning
        ("05_NMOBMX_0.50", 0.55, 1.00, 6.0, {"NMOBMX": 0.50, "CMOBMX": 0.09}),
        ("06_RTNO3_0.025", 0.55, 1.00, 6.0, {"RTNO3": 0.025}),
        ("07_KCAN_0.30_SFDUR_35", 0.55, 1.00, 6.0, {"KCAN": 0.30, "SFDUR": 35.0}),

        # Synergies
        ("08_Synergy_SLDR0.65_SLNF0.85_NMOB0.50", 0.65, 0.85, 5.0, {"NMOBMX": 0.50, "CMOBMX": 0.09, "RTNO3": 0.030}),
        ("09_Synergy_SLDR0.70_KCAN0.28_SFDUR35_NMOB0.52", 0.70, 0.90, 5.0, {"KCAN": 0.28, "SFDUR": 35.0, "NMOBMX": 0.52, "CMOBMX": 0.10}),
        ("10_Synergy_SLDR0.75_KCAN0.28_SFDUR32_NMOB0.55", 0.75, 0.85, 5.0, {"KCAN": 0.28, "SFDUR": 32.0, "NMOBMX": 0.55, "CMOBMX": 0.11, "RTNO3": 0.025}),
    ]

    results = []
    for name, sldr, slnf, slu1, par_ovr in cases:
        print(f"[RUN] Evaluating: {name}...")
        res = evaluate_tuned_case(name, sldr, slnf, slu1, par_ovr)
        if res is not None:
            results.append(res)
            print(f"      25SP W3 N-diff: {res['25SP_W3_diff_sim']:+.1f} (Obs: {res['25SP_W3_diff_obs']:+.1f}) | W1: {res['25SP_W1_diff_sim']:+.1f} (Obs: {res['25SP_W1_diff_obs']:+.1f})")
            print(f"      26SP W2 N-diff: {res['26SP_W2_diff_sim']:+.1f} (Obs: {res['26SP_W2_diff_obs']:+.1f}) | W1: {res['26SP_W1_diff_sim']:+.1f} (Obs: {res['26SP_W1_diff_obs']:+.1f})")
            print(f"      Fresh Yield NSE -> 25SP: {res['25SP_FRESH_NSE']:.3f}, 26SP: {res['26SP_FRESH_NSE']:.3f}\n")

    df = pd.DataFrame(results)
    out_csv = OUT_DIR / "fine_tuned_hydraulics_n_transport_results.csv"
    df.to_csv(out_csv, index=False)
    print(f"\n[DONE] Saved full results to: {out_csv}")


if __name__ == "__main__":
    main()
