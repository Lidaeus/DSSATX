#!/usr/bin/env python3
r"""Run DSSAT simulation directly using the original initial SNO3 and SNH4 conditions
from D:\Tomato_Cal\data\user\experiments\XXQL2501\XXQL2501.TMX, and report detailed
observed vs simulated comparison across all 25SP treatments.
"""

from __future__ import annotations

import json
import re
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
OUT_DIR = PROJECT_ROOT / "workspace/reports/simulation_xxql2501_direct_tmx_20260830"
OUT_DIR.mkdir(parents=True, exist_ok=True)

from tools.calibration.explore_soil_layering_for_nitrogen_response import patch_filex_mesol
from src.common.project import sha256_file

TREATMENTS_25SP = [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]


def parse_tmx_ic(tmx_path: Path):
    text = tmx_path.read_text(encoding="utf-8", errors="ignore")
    ic_match = re.search(r"\*INITIAL CONDITIONS.*?\n(.*?)(?:\n\*[A-Z]|\Z)", text, re.DOTALL)
    ic_data = {}
    if ic_match:
        current_ic = None
        for line in ic_match.group(1).splitlines():
            if line.startswith("@C") or not line.strip() or line.strip().startswith("*"):
                continue
            parts = line.split()
            if len(parts) >= 10:
                try: current_ic = int(parts[0])
                except: pass
            elif len(parts) >= 4 and current_ic is not None:
                floats = re.findall(r"[-+]?(?:\d*\.\d+|\d+)", line)
                if len(floats) >= 5:
                    c = int(floats[0])
                    icbl = float(floats[1])
                    sh2o = float(floats[2])
                    snh4 = float(floats[3])
                    sno3 = float(floats[4])
                    ic_data.setdefault(c, []).append({
                        "icbl": icbl, "sh2o": sh2o, "snh4": snh4, "sno3": sno3
                    })
    return ic_data


def write_bundle_manifest(bundle_dir: Path):
    manifest = {
        "bundle_id": bundle_dir.name,
        "files": [
            {
                "name": p.name,
                "bytes": p.stat().st_size,
                "sha256": sha256_file(p),
            }
            for p in sorted(bundle_dir.iterdir())
            if p.is_file() and p.name != "input_manifest.json"
        ],
    }
    (bundle_dir / "input_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main():
    print("==================== PREPARING EXPERIMENT BUNDLE WITH DIRECT XXQL2501.TMX ====================")
    bdir25 = OUT_DIR / "25SP_bundle"
    bdir26 = OUT_DIR / "26SP_bundle"
    if bdir25.exists(): shutil.rmtree(bdir25)
    if bdir26.exists(): shutil.rmtree(bdir26)
    
    # Base bundle with manifests and Scheme 4 soil
    shutil.copytree(PROJECT_ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830", bdir25)
    shutil.copytree(PROJECT_ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830", bdir26)
    
    # Copy exact FileX from D:\Tomato_Cal\data\user\experiments\XXQL2501\XXQL2501.TMX
    source_tmx = PROJECT_ROOT / "data/user/experiments/XXQL2501/XXQL2501.TMX"
    dest_tmx = bdir25 / "XXQL2501.TMX"
    shutil.copy2(source_tmx, dest_tmx)
    
    filex25 = dest_tmx
    filex26 = next(bdir26.glob("*.TMX"))
    patch_filex_mesol(filex25)
    patch_filex_mesol(filex26)
    
    # Re-generate input_manifest.json for both bundles so hashes match
    write_bundle_manifest(bdir25)
    write_bundle_manifest(bdir26)
    
    # Audit initial nitrogen from data/user/experiments/XXQL2501/XXQL2501.TMX
    ic_data_25 = parse_tmx_ic(filex25)
    
    base_design_tpl = json.loads((PROJECT_ROOT / "configs/runs/e02_small_v41_nresp10x_scheme4_60x3_20260830.json").read_text())
    base_design = dict(base_design_tpl)
    base_design["design_id"] = "xxql2501_direct_simulation"
    base_design["seasons"] = [
        {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(bdir25.resolve()), "role": "calibration", "treatments": TREATMENTS_25SP},
        {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(bdir26.resolve()), "role": "calibration", "treatments": list(range(1, 13))},
    ]
    base_design["diagnostic_only"] = {"25SP": [], "26SP": []}
    
    df_file = OUT_DIR / "design.json"
    df_file.write_text(json.dumps(base_design, indent=2))
    param_csv = OUT_DIR / "params.csv"
    shutil.copy2(BASE_PARAMS_PATH, param_csv)
    
    print("\n==================== RUNNING MULTI-SEASON DETERMINISTIC SIMULATION ====================")
    cmd = [
        PYTHON, str((PROJECT_ROOT / "src/calibration/run_multiseason.py").resolve()),
        "--design", str(df_file.resolve()),
        "--param-csv", str(param_csv.resolve()),
        "--prefix", "det_direct",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    res = subprocess.run(cmd, cwd=str(OUT_DIR.resolve()), capture_output=True, text=True)
    if res.returncode != 0:
        print("Simulation error:\n", res.stderr)
        return
        
    from src.reporting.analyze_results import deterministic_harvest_compare, deterministic_process_compare
    for sid, fx, tmts in [("25SP", filex25, TREATMENTS_25SP), ("26SP", filex26, list(range(1,13)))]:
        sdir = OUT_DIR / "_seasons" / sid
        sdir.mkdir(parents=True, exist_ok=True)
        batch = sdir / "analysis_batch.v48"
        batch.write_text("\n".join(f"{fx.resolve()} {int(tn)} 1 0 0 0" for tn in tmts) + "\n", encoding="utf-8")
        deterministic_harvest_compare(sid, str(batch), run_dir=str(sdir))
        deterministic_process_compare(sid, str(batch), var_names=["LAID", "LWAD", "SWAD", "CHTD"], run_dir=str(sdir))
        
    h25 = pd.read_csv(OUT_DIR / "_seasons/25SP/25SP_deterministic_harvest_compare.csv")
    p25 = pd.read_csv(OUT_DIR / "_seasons/25SP/25SP_deterministic_process_compare.csv")
    
    m25 = pd.read_csv(PROJECT_ROOT / "configs/runs/e02_mapping_26sp_w2_w1_20260830.csv")
    m25_sub = m25[m25["season_id"] == "25SP"].set_index("treatment")
    
    summary_rows = []
    max25 = h25["HNO"].max()
    t25_map = h25[h25["HNO"] == max25].set_index("TN")
    
    for tn in TREATMENTS_25SP:
        layers = ic_data_25.get(tn, [])
        prev_d = 0.0
        tot_no3_kg = 0.0
        tot_nh4_kg = 0.0
        sno3_strs = []
        snh4_strs = []
        for l in layers:
            thick = l["icbl"] - prev_d
            prev_d = l["icbl"]
            bd = 1.45
            tot_no3_kg += l["sno3"] * bd * thick * 0.1
            tot_nh4_kg += l["snh4"] * bd * thick * 0.1
            sno3_strs.append(f"{l['icbl']:.0f}cm:{l['sno3']:.1f}")
            snh4_strs.append(f"{l['icbl']:.0f}cm:{l['snh4']:.1f}")
            
        w = m25_sub.loc[tn, "water_level"]
        n = m25_sub.loc[tn, "nitrogen_level"]
        n_kg = m25_sub.loc[tn, "nitrogen_kg_ha"]
        role = m25_sub.loc[tn, "objective_role"]
        
        obs_f = float(t25_map.loc[tn, "OBS_FRESH_CUM"])
        sim_f = float(t25_map.loc[tn, "SIM_FRESH_CUM"])
        err_f = sim_f - obs_f
        pbias_f = 100.0 * err_f / obs_f
        
        obs_d = float(t25_map.loc[tn, "OBS_DRY_CUM"])
        sim_d = float(t25_map.loc[tn, "SIM_DRY_CUM"])
        err_d = sim_d - obs_d
        pbias_d = 100.0 * err_d / obs_d
        
        summary_rows.append({
            "TN": tn, "Water": w, "N_Level": n, "Fert_N_kg": n_kg, "Role": role,
            "Init_SNO3_kg_ha": round(tot_no3_kg, 1),
            "Init_SNH4_kg_ha": round(tot_nh4_kg, 1),
            "Total_Init_MinN_kg_ha": round(tot_no3_kg + tot_nh4_kg, 1),
            "Total_N_Supply_kg_ha": round(tot_no3_kg + tot_nh4_kg + float(n_kg), 1),
            "OBS_Fresh_Yield": obs_f, "SIM_Fresh_Yield": sim_f,
            "Fresh_Error_kg": round(err_f, 1), "Fresh_PBIAS_pct": round(pbias_f, 2),
            "OBS_Dry_Yield": obs_d, "SIM_Dry_Yield": sim_d,
            "Dry_Error_kg": round(err_d, 1), "Dry_PBIAS_pct": round(pbias_d, 2),
            "SNO3_layers_ppm": " | ".join(sno3_strs),
            "SNH4_layers_ppm": " | ".join(snh4_strs),
        })
        
    sum_df = pd.DataFrame(summary_rows)
    sum_df.to_csv(OUT_DIR / "25SP_direct_simulation_summary.csv", index=False)
    
    def _calc_stats(obs, sim):
        ok = np.isfinite(obs) & np.isfinite(sim) & (obs != -99) & (sim != -99)
        o, s = obs[ok], sim[ok]
        sst = np.sum((o - o.mean()) ** 2)
        nse = float(1.0 - np.sum((s - o) ** 2) / sst) if sst > 0 else np.nan
        rrmse = float(100.0 * np.sqrt(np.mean((s - o) ** 2)) / np.mean(np.abs(o))) if len(o) > 0 else np.nan
        r2 = float(np.corrcoef(o, s)[0, 1] ** 2) if len(o) > 1 else np.nan
        d_idx = float(1.0 - np.sum((s - o)**2) / np.sum((np.abs(s - o.mean()) + np.abs(o - o.mean()))**2)) if sst > 0 else np.nan
        return r2, nse, d_idx, rrmse
        
    print("\n========================== 25SP DIRECT SIMULATION SUMMARY ==========================")
    print(sum_df[["TN", "Water", "N_Level", "Fert_N_kg", "Init_SNO3_kg_ha", "Total_Init_MinN_kg_ha", "OBS_Fresh_Yield", "SIM_Fresh_Yield", "Fresh_Error_kg", "Fresh_PBIAS_pct", "OBS_Dry_Yield", "SIM_Dry_Yield", "Dry_PBIAS_pct"]].to_string(index=False))
    
    r2_f, nse_f, d_f, rrmse_f = _calc_stats(h25["OBS_FRESH_CUM"].to_numpy(float), h25["SIM_FRESH_CUM"].to_numpy(float))
    r2_d, nse_d, d_d, rrmse_d = _calc_stats(h25["OBS_DRY_CUM"].to_numpy(float), h25["SIM_DRY_CUM"].to_numpy(float))
    r2_l, nse_l, d_l, rrmse_l = _calc_stats(p25["OBS_LAID"].to_numpy(float), p25["SIM_LAID"].to_numpy(float))
    r2_lw, nse_lw, d_lw, rrmse_lw = _calc_stats(p25["OBS_LWAD"].to_numpy(float), p25["SIM_LWAD"].to_numpy(float))
    r2_sw, nse_sw, d_sw, rrmse_sw = _calc_stats(p25["OBS_SWAD"].to_numpy(float), p25["SIM_SWAD"].to_numpy(float))
    
    print("\n========================== 25SP OVERALL SCORECARD ==========================")
    metrics_table = [
        {"Variable": "Fresh Fruit Yield (FRESH_CUM)", "R2": round(r2_f, 4), "NSE": round(nse_f, 4), "d_index": round(d_f, 4), "RRMSE_%": round(rrmse_f, 2)},
        {"Variable": "Dry Fruit Yield (DRY_CUM)", "R2": round(r2_d, 4), "NSE": round(nse_d, 4), "d_index": round(d_d, 4), "RRMSE_%": round(rrmse_d, 2)},
        {"Variable": "Canopy LAI (LAID)", "R2": round(r2_l, 4), "NSE": round(nse_l, 4), "d_index": round(d_l, 4), "RRMSE_%": round(rrmse_l, 2)},
        {"Variable": "Leaf Dry Mass (LWAD)", "R2": round(r2_lw, 4), "NSE": round(nse_lw, 4), "d_index": round(d_lw, 4), "RRMSE_%": round(rrmse_lw, 2)},
        {"Variable": "Stem Dry Mass (SWAD)", "R2": round(r2_sw, 4), "NSE": round(nse_sw, 4), "d_index": round(d_sw, 4), "RRMSE_%": round(rrmse_sw, 2)},
    ]
    print(pd.DataFrame(metrics_table).to_string(index=False))
    
    w3_diff = sum_df.loc[sum_df["TN"] == 2, "SIM_Fresh_Yield"].values[0] - sum_df.loc[sum_df["TN"] == 5, "SIM_Fresh_Yield"].values[0]
    w1_diff = sum_df.loc[sum_df["TN"] == 10, "SIM_Fresh_Yield"].values[0] - sum_df.loc[sum_df["TN"] == 13, "SIM_Fresh_Yield"].values[0]
    w3_obs = sum_df.loc[sum_df["TN"] == 2, "OBS_Fresh_Yield"].values[0] - sum_df.loc[sum_df["TN"] == 5, "OBS_Fresh_Yield"].values[0]
    w1_obs = sum_df.loc[sum_df["TN"] == 10, "OBS_Fresh_Yield"].values[0] - sum_df.loc[sum_df["TN"] == 13, "OBS_Fresh_Yield"].values[0]
    
    print("\n========================== NITROGEN RESPONSE CONTRASTS (N3 - N0) ==========================")
    print(f"25SP W3 (TN2 - TN5)  -> Direct Sim: {w3_diff:+7.1f} kg/ha | Obs: {w3_obs:+7.1f} kg/ha")
    print(f"25SP W1 (TN10 - TN13) -> Direct Sim: {w1_diff:+7.1f} kg/ha | Obs: {w1_obs:+7.1f} kg/ha")


if __name__ == "__main__":
    main()
