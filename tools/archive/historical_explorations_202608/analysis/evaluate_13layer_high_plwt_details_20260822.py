"""Detailed Evaluation of 13-Layer Soil combined with High Seedling Weight (PLWT = 3.0, 5.0, 7.0, 9.0 g)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd
import numpy as np

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
BEST_PARAMS = ROOT / "workspace/runs/e02_v23_formal_full_synergy_200x6_20260821/deterministic_candidates/best_phi_member31_two_season_20260821/best_member_31_params.csv"

EXP_25_13L = ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v4_13layer_20260820"
EXP_26_13L = ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v4_13layer_20260820"


def run_13layer_plwt(plwt_val: float) -> dict:
    case_name = f"det_13layer_plwt_{int(plwt_val)}g"
    run_dir = ROOT / "workspace/runs" / case_name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    
    t25 = run_dir / "exp25"
    t26 = run_dir / "exp26"
    shutil.copytree(EXP_25_13L, t25)
    shutil.copytree(EXP_26_13L, t26)
    
    for dst, sname, yr in [(t25, "XXQL2501", "25"), (t26, "XXQL2601", "26")]:
        tmx = dst / f"{sname}.TMX"
        lines = tmx.read_text(encoding="utf-8").splitlines()
        new_lines = []
        for l in lines:
            if l.strip().startswith("2 ") and f"{yr}075" in l:
                # Exact fixed format with PLWT = plwt_val
                new_lines.append(f" 2 {yr}075   -99   2.7   2.7     T     R    90    90     8   {plwt_val:3.1f}    60    25     1     8                        Eggplant")
            else:
                new_lines.append(l)
        tmx.write_text("\n".join(new_lines), encoding="utf-8")
        
    design = {
        "schema_version": 1, "design_id": case_name, "cultivar_identity": "TM0008",
        "shared_parameter_scope": case_name, "bounds_id": "eggplant_e02_v23_formal_full_synergy_20260821",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Pure measured FileX IC values with 13-layer soil",
        "nitrogen_response_objective": {"enabled": False}, "water_response_objective": {"enabled": False},
        "harvest_dry_objective": {"enabled": True, "mode": "increment_plus_terminal", "variable": "CHPDT", "process_lambda_per_season": 200.0, "terminal_lambda_per_season": 300.0},
        "process_state_objective": {"enabled": True, "mode": "signed_difference_plus_terminal", "variables": ["LAID", "LWAD", "SWAD"]},
        "seasons": [
            {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(t25), "role": "calibration", "treatments": [2, 5, 10, 13]},
            {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(t26), "role": "calibration", "treatments": [2, 11, 3, 12]}
        ]
    }
    with open(run_dir / "joint_design.json", "w", encoding="utf-8") as f:
        json.dump(design, f, indent=2)
        
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    subprocess.run([
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(run_dir / "joint_design.json"),
        "--param-csv", str(BEST_PARAMS),
        "--prefix", "sim", "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs"
    ], cwd=run_dir, env=env, check=True, capture_output=True)
    
    sys.path.insert(0, str(ROOT / "tools/analysis"))
    from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare
    
    res = {"plwt_g": plwt_val}
    for s in ["25SP", "26SP"]:
        sdir = run_dir / "_seasons" / s
        h_df = build_season_harvest_compare(sdir, s)
        
        pg_file = sdir / "PlantGro.OUT"
        pn_file = sdir / "PlantN.OUT"
        sni_file = sdir / "SoilNi.OUT"
        
        n3_tn = 2
        n0_tn = 5 if s == "25SP" else 11
        
        # PlantGro
        pg_lines = pg_file.read_text(errors="ignore").splitlines()
        header, cur_tn, recs = None, None, []
        for l in pg_lines:
            if l.startswith("*RUN"):
                m = re.search(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", l)
                if m: cur_tn = int(m.group(2))
            elif l.startswith("@YEAR"):
                header = l.replace("@", "").split()
            elif cur_tn in [n3_tn, n0_tn] and header and l.strip() and not l.startswith("*") and not l.startswith("@"):
                parts = l.split()
                if len(parts) >= len(header) and parts[0].isdigit():
                    r = {header[i]: float(parts[i]) for i in range(len(header))}
                    r["TN"] = cur_tn
                    recs.append(r)
        df_pg = pd.DataFrame(recs)
        
        # PlantN
        pn_lines = pn_file.read_text(errors="ignore").splitlines()
        header_n, cur_tn, recs_n = None, None, []
        for l in pn_lines:
            if l.startswith("*RUN"):
                m = re.search(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", l)
                if m: cur_tn = int(m.group(2))
            elif l.startswith("@YEAR"):
                header_n = l.replace("@", "").split()
            elif cur_tn in [n3_tn, n0_tn] and header_n and l.strip() and not l.startswith("*") and not l.startswith("@"):
                parts = l.split()
                if len(parts) >= len(header_n) and parts[0].isdigit():
                    r = {header_n[i]: float(parts[i]) for i in range(len(header_n))}
                    r["TN"] = cur_tn
                    recs_n.append(r)
        df_pn = pd.DataFrame(recs_n)
        
        for tn, tname in [(n3_tn, "N3"), (n0_tn, "N0")]:
            sub_h = h_df[h_df["TN"] == tn]
            sub_pg = df_pg[df_pg["TN"] == tn]
            sub_pn = df_pn[df_pn["TN"] == tn]
            
            res[f"{s}_{tname}_sim_dry"] = sub_h["SIM_DRY_CUM"].iloc[-1]
            res[f"{s}_{tname}_obs_dry"] = sub_h["OBS_DRY_CUM"].iloc[-1]
            res[f"{s}_{tname}_bias_pct"] = (sub_h["SIM_DRY_CUM"].iloc[-1] - sub_h["OBS_DRY_CUM"].iloc[-1]) / sub_h["OBS_DRY_CUM"].iloc[-1] * 100
            res[f"{s}_{tname}_root_wt"] = sub_pg["RWAD"].iloc[-1]
            res[f"{s}_{tname}_root_dep"] = sub_pg["RDPD"].iloc[-1]
            res[f"{s}_{tname}_n_uptk"] = sub_pn["NUPC"].iloc[-1]
            res[f"{s}_{tname}_leaf_n"] = sub_pn["LN%D"].iloc[-1]
            
            d35_pg = sub_pg[sub_pg["DAP"] == 35]
            d35_pn = sub_pn[sub_pn["DAP"] == 35]
            if not d35_pg.empty:
                res[f"{s}_{tname}_d35_lai"] = d35_pg.iloc[0].get("LAID", np.nan)
                res[f"{s}_{tname}_d35_root_wt"] = d35_pg.iloc[0].get("RWAD", np.nan)
            if not d35_pn.empty:
                res[f"{s}_{tname}_d35_leaf_n"] = d35_pn.iloc[0].get("LN%D", np.nan)
                res[f"{s}_{tname}_d35_n_uptk"] = d35_pn.iloc[0].get("NUPC", np.nan)
                
    return res


def main():
    plwt_ladder = [3.0, 5.0, 7.0, 9.0]
    results = []
    for w in plwt_ladder:
        print(f"Evaluating 13-layer soil with PLWT = {w}g...")
        r = run_13layer_plwt(w)
        results.append(r)
        
    df = pd.DataFrame(results)
    
    print("\n==========================================================================================")
    print("           13-Layer Soil Combined with High Seedling Weight (PLWT) Details")
    print("==========================================================================================")
    
    cols_25 = [
        "plwt_g",
        "25SP_N3_obs_dry", "25SP_N3_sim_dry", "25SP_N3_bias_pct",
        "25SP_N0_obs_dry", "25SP_N0_sim_dry", "25SP_N0_bias_pct",
        "25SP_N0_d35_lai", "25SP_N0_d35_n_uptk", "25SP_N0_root_wt", "25SP_N0_n_uptk"
    ]
    print("\n>>> 25SP Dynamics <<<")
    print(df[cols_25].to_string(index=False))
    
    cols_26 = [
        "plwt_g",
        "26SP_N3_obs_dry", "26SP_N3_sim_dry", "26SP_N3_bias_pct",
        "26SP_N0_obs_dry", "26SP_N0_sim_dry", "26SP_N0_bias_pct",
        "26SP_N0_d35_lai", "26SP_N0_d35_n_uptk", "26SP_N0_root_wt", "26SP_N0_n_uptk"
    ]
    print("\n>>> 26SP Dynamics <<<")
    print(df[cols_26].to_string(index=False))


if __name__ == "__main__":
    main()
