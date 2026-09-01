#!/usr/bin/env python3
"""Explore soil hydraulic coefficients (SLDR, SLU1, SDUL/SLLL) and nitrogen transport/uptake
coefficients (RTNO3, NMOBMX, NSTFAC, FNPGN) under Scheme 4 soil layering (10-30-60-90-120-150-180cm).
Aims to eliminate high-water yield inversion in 25SP and improve overall 22-treatment calibration fidelity.
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

OUT_DIR = PROJECT_ROOT / "workspace/reports/soil_hydraulics_n_transport_scheme4_20260830"
SCRATCH_DIR = OUT_DIR / "runs"

LAYERS = [10, 30, 60, 90, 120, 150, 180]
from tools.calibration.explore_soil_layering_for_nitrogen_response import (
    interpolate_soil_layer, patch_filex_mesol
)


def generate_soil_sol_with_hydraulics(
    layers: list[int],
    sldr: float = 0.45,
    slu1: float = 7.0,
    salb: float = 0.13,
    slro: float = 75.0,
    slnf: float = 1.00,
    slpf: float = 0.915,
    sdul_scale: float = 1.00,
    slll_scale: float = 1.00,
) -> str:
    """Generate SOIL.SOL text with customized hydraulic and nitrogen transport factors."""
    header = f"""*IBTM910017  SCS         -99     203 Orangeburg Sandy Loam
@SITE        COUNTRY          LAT     LONG SCS FAMILY
 Quincy      USA           30.600  -86.400 Loamy,silic,hyperth Gross. Paleud(17)
@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE
   -99  {salb:4.2f}   {slu1:3.1f}  {sldr:4.2f}  {slro:4.1f}  {slnf:4.2f}  {slpf:4.2f} IB001 IB001 IB001
@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC"""

    rows = []
    for lb in layers:
        p = interpolate_soil_layer(lb)
        slll = max(0.04, min(0.35, p["SLLL"] * slll_scale))
        sdul = max(slll + 0.05, min(0.48, p["SDUL"] * sdul_scale))
        ssat = max(sdul + 0.04, min(0.55, p["SSAT"]))
        row = f"{p['SLB']:6d}   -99 {slll:5.3f} {sdul:5.3f} {ssat:5.3f} {p['SRGF']:5.3f}   -99  {p['SBDM']:4.2f}  {p['SLOC']:4.2f}   -99   -99   -99 {p['SLNI']:5.3f}   {p['SLHW']:3.1f}   -99   -99   -99"
        rows.append(row)

    return header + "\n" + "\n".join(rows) + "\n"


def evaluate_hydraulic_n_case(
    case_name: str,
    soil_text: str,
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
        print(f"[FAIL] {case_name} simulation failed: {res.stderr[:200]}")
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

    experiments = [
        # Baseline
        ("00_Baseline_Scheme4", generate_soil_sol_with_hydraulics(LAYERS, sldr=0.27, slu1=9.0), {}),
        
        # Test 1: Enhanced drainage (SLDR: 0.45, 0.60, 0.75) to rapidly evacuate excess gravitational water in W3
        ("01_HighDrain_SLDR_0.45", generate_soil_sol_with_hydraulics(LAYERS, sldr=0.45, slu1=7.0), {}),
        ("02_HighDrain_SLDR_0.60", generate_soil_sol_with_hydraulics(LAYERS, sldr=0.60, slu1=6.0), {}),
        ("03_HighDrain_SLDR_0.75", generate_soil_sol_with_hydraulics(LAYERS, sldr=0.75, slu1=5.0), {}),

        # Test 2: Reduced topsoil field capacity (SDUL -5% ~ -10%) to limit luxury N dissolved in surface water
        ("04_LowAWC_SDUL_0.92", generate_soil_sol_with_hydraulics(LAYERS, sldr=0.55, slu1=6.0, sdul_scale=0.92), {}),
        ("05_LowAWC_SDUL_0.88", generate_soil_sol_with_hydraulics(LAYERS, sldr=0.65, slu1=5.0, sdul_scale=0.88), {}),

        # Test 3: Modulating N transport/uptake & mobilization (NMOBMX, RTNO3, KCAN relaxation)
        ("06_N_Mobilization_NMOBMX_0.45", generate_soil_sol_with_hydraulics(LAYERS, sldr=0.50), {"NMOBMX": 0.45, "CMOBMX": 0.08}),
        ("07_N_Mobilization_NMOBMX_0.55", generate_soil_sol_with_hydraulics(LAYERS, sldr=0.50), {"NMOBMX": 0.55, "CMOBMX": 0.10}),
        ("08_RootNO3_Uptake_RTNO3_0.025", generate_soil_sol_with_hydraulics(LAYERS, sldr=0.50), {"RTNO3": 0.025}),
        ("09_KCAN_Relaxed_0.30", generate_soil_sol_with_hydraulics(LAYERS, sldr=0.50), {"KCAN": 0.30}),
        
        # Test 4: Combined Soil Hydraulics + Canopy Light + N Mobilization Synergies
        ("10_Synergy_SLDR0.60_KCAN0.30_NMOB0.45", generate_soil_sol_with_hydraulics(LAYERS, sldr=0.60, slu1=6.0), {"KCAN": 0.30, "NMOBMX": 0.45, "CMOBMX": 0.09}),
        ("11_Synergy_SLDR0.70_KCAN0.28_NMOB0.50", generate_soil_sol_with_hydraulics(LAYERS, sldr=0.70, slu1=5.0), {"KCAN": 0.28, "NMOBMX": 0.50, "CMOBMX": 0.10, "SFDUR": 35.0}),
        ("12_Synergy_SDUL0.90_SLDR0.65_KCAN0.28", generate_soil_sol_with_hydraulics(LAYERS, sldr=0.65, slu1=5.0, sdul_scale=0.90), {"KCAN": 0.28, "NMOBMX": 0.48, "CMOBMX": 0.10, "SFDUR": 35.0, "RTNO3": 0.030}),
    ]

    results = []
    for name, soil_txt, par_ovr in experiments:
        print(f"[RUN] Evaluating: {name}...")
        res = evaluate_hydraulic_n_case(name, soil_txt, par_ovr)
        if res is not None:
            results.append(res)
            print(f"      25SP W3 N-diff: {res['25SP_W3_diff_sim']:+.1f} (Obs: {res['25SP_W3_diff_obs']:+.1f}) | W1: {res['25SP_W1_diff_sim']:+.1f} (Obs: {res['25SP_W1_diff_obs']:+.1f})")
            print(f"      26SP W2 N-diff: {res['26SP_W2_diff_sim']:+.1f} (Obs: {res['26SP_W2_diff_obs']:+.1f}) | W1: {res['26SP_W1_diff_sim']:+.1f} (Obs: {res['26SP_W1_diff_obs']:+.1f})")
            print(f"      Fresh Yield NSE -> 25SP: {res['25SP_FRESH_NSE']:.3f}, 26SP: {res['26SP_FRESH_NSE']:.3f}\n")

    df = pd.DataFrame(results)
    out_csv = OUT_DIR / "soil_hydraulics_n_transport_comparison.csv"
    df.to_csv(out_csv, index=False)
    print(f"\n[DONE] Saved full results to: {out_csv}")


if __name__ == "__main__":
    main()
