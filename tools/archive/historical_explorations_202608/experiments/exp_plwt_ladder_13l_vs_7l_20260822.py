"""Comprehensive Grid Test: PLWT Ladder (3.0, 5.0, 7.0, 9.0, 11.0 g) on BOTH 13-Layer and 7-Layer Soils."""
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

EXP_25_7L = ROOT / "data/user/experiments/xxql2501_rootzone_7layer_20260822"
EXP_26_7L = ROOT / "data/user/experiments/xxql2601_rootzone_7layer_20260822"


def run_soil_plwt_case(soil_type: str, plwt_val: float, base_exp25: Path, base_exp26: Path) -> dict:
    case_name = f"test_{soil_type}_plwt_{int(plwt_val)}g"
    run_dir = ROOT / "workspace/runs" / case_name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    
    t_exp25 = run_dir / "exp25"
    t_exp26 = run_dir / "exp26"
    shutil.copytree(base_exp25, t_exp25)
    shutil.copytree(base_exp26, t_exp26)
    
    for dst, sname in [(t_exp25, "XXQL2501"), (t_exp26, "XXQL2601")]:
        tmx = dst / f"{sname}.TMX"
        lines = tmx.read_text(encoding="utf-8").splitlines()
        new_lines = []
        in_p = False
        for l in lines:
            if l.startswith("*PLANTING DETAILS"):
                in_p = True
                new_lines.append(l)
            elif in_p and l.startswith("@P"):
                new_lines.append(l)
            elif in_p and l.strip() and not l.startswith("*") and not l.startswith("@"):
                parts = l.split()
                p_code, pdate, edate, ppop, ppoe, plme, plds, plrs, plrd, pldp, _, page, penv = parts[:13]
                plph = parts[13] if len(parts) > 13 else "1"
                sprl = parts[14] if len(parts) > 14 else "8"
                plname = "Eggplant"
                formatted = f" {int(p_code):1d} {pdate:5s} {edate:>5s}  {float(ppop):4.1f}  {float(ppoe):4.1f}     {plme:1s}     {plds:1s}    {plrs:>2s}    {plrd:>2s}     {pldp:>1s}   {plwt_val:4.1f}    {page:>2s}    {penv:>2s}     {plph:>1s}     {sprl:>1s}                        {plname:s}"
                new_lines.append(formatted)
                in_p = False
            else:
                new_lines.append(l)
        tmx.write_text("\n".join(new_lines), encoding="utf-8")
        
    design_content = {
        "schema_version": 1,
        "design_id": case_name,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": case_name,
        "bounds_id": "eggplant_e02_v23_formal_full_synergy_20260821",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": f"Pure measured FileX IC values with {soil_type}",
        "nitrogen_response_objective": {"enabled": False},
        "water_response_objective": {"enabled": False},
        "harvest_dry_objective": {
            "enabled": True, "mode": "increment_plus_terminal", "variable": "CHPDT",
            "process_lambda_per_season": 200.0, "terminal_lambda_per_season": 300.0
        },
        "process_state_objective": {
            "enabled": True, "mode": "signed_difference_plus_terminal", "variables": ["LAID", "LWAD", "SWAD"]
        },
        "seasons": [
            {
                "season_id": "25SP",
                "experiment_code": "XXQL2501",
                "bundle_path": str(t_exp25),
                "role": "calibration",
                "treatments": [2, 5, 10, 13]
            },
            {
                "season_id": "26SP",
                "experiment_code": "XXQL2601",
                "bundle_path": str(t_exp26),
                "role": "calibration",
                "treatments": [2, 11, 3, 12]
            }
        ]
    }
    
    design_path = run_dir / "joint_design.json"
    with open(design_path, "w", encoding="utf-8") as f:
        json.dump(design_content, f, indent=2)
        
    cmd_run = [
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_path),
        "--param-csv", str(BEST_PARAMS),
        "--prefix", "sim_det",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    subprocess.run(cmd_run, cwd=run_dir, env=env, check=True)
    
    sys.path.insert(0, str(ROOT / "tools/analysis"))
    from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare
    
    res = {"soil_type": soil_type, "plwt_g": plwt_val}
    for season in ["25SP", "26SP"]:
        sdir = run_dir / "_seasons" / season
        df_h = build_season_harvest_compare(sdir, season)
        
        pg_file = sdir / "PlantGro.OUT"
        pn_file = sdir / "PlantN.OUT"
        sni_file = sdir / "SoilNi.OUT"
        
        n3_tn = 2
        n0_tn = 5 if season == "25SP" else 11
        
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
            sub_h = df_h[df_h["TN"] == tn]
            sub_pg = df_pg[df_pg["TN"] == tn]
            sub_pn = df_pn[df_pn["TN"] == tn]
            
            last_h = sub_h.iloc[-1] if not sub_h.empty else {}
            last_pg = sub_pg.iloc[-1] if not sub_pg.empty else {}
            last_pn = sub_pn.iloc[-1] if not sub_pn.empty else {}
            
            res[f"{season}_{tname}_sim_dry"] = last_h.get("SIM_DRY_CUM", np.nan)
            res[f"{season}_{tname}_root_wt"] = last_pg.get("RWAD", np.nan)
            res[f"{season}_{tname}_root_dep"] = last_pg.get("RDPD", np.nan)
            res[f"{season}_{tname}_n_uptk"] = last_pn.get("NUPC", np.nan)
            res[f"{season}_{tname}_leaf_n"] = last_pn.get("LN%D", np.nan)
            
            d35_pg = sub_pg[sub_pg["DAP"] == 35]
            d35_pn = sub_pn[sub_pn["DAP"] == 35]
            if not d35_pg.empty:
                res[f"{season}_{tname}_d35_lai"] = d35_pg.iloc[0].get("LAID", np.nan)
                res[f"{season}_{tname}_d35_root_wt"] = d35_pg.iloc[0].get("RWAD", np.nan)
            if not d35_pn.empty:
                res[f"{season}_{tname}_d35_leaf_n"] = d35_pn.iloc[0].get("LN%D", np.nan)
                res[f"{season}_{tname}_d35_n_uptk"] = d35_pn.iloc[0].get("NUPC", np.nan)
                
    return res


def main():
    plwt_ladder = [3.0, 5.0, 7.0, 9.0]
    results = []
    
    # 1. 13-Layer soil
    print("=== Testing 13-Layer Soil Grid ===")
    for w in plwt_ladder:
        print(f"Running 13-Layer PLWT = {w}g...")
        r = run_soil_plwt_case("13layer", w, EXP_25_13L, EXP_26_13L)
        results.append(r)
        
    # 2. 7-Layer Root-Zone soil
    print("\n=== Testing 7-Layer Root-Zone Soil Grid ===")
    for w in plwt_ladder:
        print(f"Running 7-Layer PLWT = {w}g...")
        r = run_soil_plwt_case("7layer", w, EXP_25_7L, EXP_26_7L)
        results.append(r)
        
    df = pd.DataFrame(results)
    out_csv = ROOT / "workspace/runs/plwt_ladder_13l_vs_7l_comparison_20260822.csv"
    df.to_csv(out_csv, index=False)
    
    print("\n==========================================================================================")
    print("      PLWT Ladder (3.0, 5.0, 7.0, 9.0 g) on 13-Layer vs 7-Layer Root-Zone Soils")
    print("==========================================================================================")
    cols_25 = ["soil_type", "plwt_g", "25SP_N3_sim_dry", "25SP_N0_sim_dry", "25SP_N0_d35_lai", "25SP_N0_d35_leaf_n", "25SP_N0_d35_n_uptk", "25SP_N0_root_wt", "25SP_N0_n_uptk"]
    print("\n>>> 25SP Dynamics <<<")
    print(df[cols_25].to_string(index=False))
    
    cols_26 = ["soil_type", "plwt_g", "26SP_N3_sim_dry", "26SP_N0_sim_dry", "26SP_N0_d35_lai", "26SP_N0_d35_leaf_n", "26SP_N0_d35_n_uptk", "26SP_N0_root_wt", "26SP_N0_n_uptk"]
    print("\n>>> 26SP Dynamics <<<")
    print(df[cols_26].to_string(index=False))


if __name__ == "__main__":
    main()
