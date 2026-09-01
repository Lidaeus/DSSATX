#!/usr/bin/env python3
"""Evaluate whether massive and disparate initial soil mineral nitrogen in 25SP
(378 ~ 862 kg N/ha initial pool) is the root cause of the 25SP yield inversion.
Runs 25SP with Member 13 parameters under:
1. Current FileX Initial Nitrogen (Disparate 378 ~ 862 kg N/ha)
2. Harmonized Standard Initial Nitrogen (SNO3=1.0 ppm ~ 28.9 kg N/ha, matching 26SP)
3. Moderate Initial Nitrogen (SNO3=2.5 ppm ~ 72 kg N/ha)
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
OUT_DIR = PROJECT_ROOT / "workspace/reports/initial_nitrogen_investigation_20260830"
OUT_DIR.mkdir(parents=True, exist_ok=True)

from tools.calibration.explore_soil_layering_for_nitrogen_response import patch_filex_mesol


def patch_filex_initial_nitrogen(filex_path: Path, target_sno3: float, target_snh4: float) -> None:
    """Rewrite *INITIAL CONDITIONS table in FileX with a uniform SNO3/SNH4 value for all treatments."""
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
            if l.startswith("@C") and "PCR" in l:
                new_lines.append(l)
            elif l.startswith("@C") and "ICBL" in l:
                new_lines.append(l)
            elif l.startswith(" ") and len(l.split()) >= 5:
                parts = l.split()
                try:
                    c = int(parts[0])
                    icbl = float(parts[1])
                    sh2o = float(parts[2])
                    new_line = f" {c:2d} {icbl:5.0f} {sh2o:5.3f} {target_snh4:5.1f} {target_sno3:5.1f}"
                    new_lines.append(new_line)
                except:
                    new_lines.append(l)
            else:
                new_lines.append(l)
        else:
            new_lines.append(l)
            
    filex_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def run_25sp_scenario(scenario_name: str, target_sno3: float | None, target_snh4: float | None) -> pd.DataFrame:
    scen_dir = OUT_DIR / scenario_name
    scen_dir.mkdir(parents=True, exist_ok=True)
    
    bdir25 = scen_dir / "25SP_bundle"
    if bdir25.exists():
        shutil.rmtree(bdir25)
    shutil.copytree(PROJECT_ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830", bdir25)
    
    bdir26 = scen_dir / "26SP_bundle"
    if bdir26.exists():
        shutil.rmtree(bdir26)
    shutil.copytree(PROJECT_ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830", bdir26)
    
    filex25 = next(bdir25.glob("*.TMX"))
    filex26 = next(bdir26.glob("*.TMX"))
    patch_filex_mesol(filex25)
    patch_filex_mesol(filex26)
    
    if target_sno3 is not None and target_snh4 is not None:
        patch_filex_initial_nitrogen(filex25, target_sno3, target_snh4)
        
    # Build design JSON based on valid template
    base_design = json.loads((PROJECT_ROOT / "configs/runs/e02_small_v41_nresp10x_scheme4_60x3_20260830.json").read_text(encoding="utf-8"))
    base_design["design_id"] = f"scen_{scenario_name}"
    base_design["seasons"] = [
        {
            "season_id": "25SP",
            "experiment_code": "XXQL2501",
            "bundle_path": str(bdir25),
            "role": "calibration",
            "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
        },
        {
            "season_id": "26SP",
            "experiment_code": "XXQL2601",
            "bundle_path": str(bdir26),
            "role": "calibration",
            "treatments": list(range(1, 13)),
        }
    ]
    base_design["diagnostic_only"] = {"25SP": [], "26SP": []}
    
    df_file = scen_dir / "design.json"
    df_file.write_text(json.dumps(base_design, indent=2), encoding="utf-8")
    
    param_csv = scen_dir / "params.csv"
    shutil.copy2(BASE_PARAMS_PATH, param_csv)
    
    cmd = [
        PYTHON,
        str(PROJECT_ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(df_file),
        "--param-csv", str(param_csv),
        "--prefix", "det",
        "--harvest-var", "CHFPW",
    ]
    res = subprocess.run(cmd, cwd=str(scen_dir), capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[FAIL] {scenario_name} simulation error: {res.stderr[:200]}")
    
    sdir = scen_dir / "_seasons/25SP"
    batch = sdir / "analysis_batch.v48"
    batch.write_text(
        "\n".join(f"{filex25.resolve()} {int(tn)} 1 0 0 0" for tn in [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]) + "\n",
        encoding="utf-8",
    )
    from src.reporting.analyze_results import deterministic_harvest_compare, deterministic_process_compare
    deterministic_harvest_compare("25SP", str(batch), run_dir=str(sdir))
    deterministic_process_compare("25SP", str(batch), var_names=["LAID", "LWAD", "SWAD", "CWAD"], run_dir=str(sdir))
    
    h_df = pd.read_csv(sdir / "25SP_deterministic_harvest_compare.csv")
    max_hno = h_df["HNO"].max()
    t_df = h_df[h_df["HNO"] == max_hno].copy()
    t_df["scenario"] = scenario_name
    return t_df


def main():
    print("[1/3] Running Scenario 1: Current Asymmetrical High Initial N (378 ~ 862 kg N/ha)...")
    res1 = run_25sp_scenario("01_Current_High_Init_N", None, None)
    
    print("[2/3] Running Scenario 2: Harmonized Standard Initial N (SNO3=1.0 ppm ~ 28.9 kg N/ha, matching 26SP)...")
    res2 = run_25sp_scenario("02_Harmonized_Standard_28kgN", 1.0, 0.1)
    
    print("[3/3] Running Scenario 3: Harmonized Moderate Initial N (SNO3=2.5 ppm ~ 72 kg N/ha)...")
    res3 = run_25sp_scenario("03_Harmonized_Moderate_72kgN", 2.5, 0.5)
    
    all_res = pd.concat([res1, res2, res3], ignore_index=True)
    mapping25 = pd.read_csv(PROJECT_ROOT / "configs/runs/e02_mapping_26sp_w2_w1_20260830.csv")
    m25 = mapping25[mapping25["season_id"] == "25SP"]
    all_res = all_res.merge(m25, left_on="TN", right_on="treatment", how="left")
    
    out_csv = OUT_DIR / "initial_n_scenario_comparison.csv"
    all_res.to_csv(out_csv, index=False)
    
    print("\n=== 25SP Yield and N-Response Comparison Across Initial Nitrogen Scenarios ===")
    for sc in ["01_Current_High_Init_N", "02_Harmonized_Standard_28kgN", "03_Harmonized_Moderate_72kgN"]:
        sub = all_res[all_res["scenario"] == sc].set_index("TN")
        w3_n_diff = sub.loc[2, "SIM_FRESH_CUM"] - sub.loc[5, "SIM_FRESH_CUM"]
        w1_n_diff = sub.loc[10, "SIM_FRESH_CUM"] - sub.loc[13, "SIM_FRESH_CUM"]
        print(f"\nScenario: {sc}")
        print(f"  W3-N3 (TN2): {sub.loc[2, 'SIM_FRESH_CUM']:7.1f} | W3-N0 (TN5): {sub.loc[5, 'SIM_FRESH_CUM']:7.1f} -> W3 (N3-N0): {w3_n_diff:+7.1f} kg/ha (Obs: +6,123)")
        print(f"  W1-N3 (TN10): {sub.loc[10, 'SIM_FRESH_CUM']:7.1f} | W1-N0 (TN13): {sub.loc[13, 'SIM_FRESH_CUM']:7.1f} -> W1 (N3-N0): {w1_n_diff:+7.1f} kg/ha (Obs: +15,019)")
        print(f"  TN 2 (W3N3): {sub.loc[2, 'SIM_FRESH_CUM']:7.1f} kg/ha (Obs: 74,753)")
        print(f"  TN 5 (W3N0): {sub.loc[5, 'SIM_FRESH_CUM']:7.1f} kg/ha (Obs: 68,630)")
        print(f"  TN 10 (W1N3): {sub.loc[10, 'SIM_FRESH_CUM']:7.1f} kg/ha (Obs: 76,088)")
        print(f"  TN 13 (W1N0): {sub.loc[13, 'SIM_FRESH_CUM']:7.1f} kg/ha (Obs: 61,069)")


if __name__ == "__main__":
    main()
