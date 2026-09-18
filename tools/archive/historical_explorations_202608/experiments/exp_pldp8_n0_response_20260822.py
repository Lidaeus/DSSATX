"""Test Planting Depth (PLDP = 8 cm) and Soil Layer / Hydraulic Modifications on N0 Response.

Tests:
1. Baseline: PLDP = 1 cm (25SP) / 5 cm (26SP) with current 13-layer soil.
2. PLDP = 8 cm with 13-layer soil.
3. PLDP = 8 cm + Merged Topsoil (0-15cm, 15-30cm) to reduce numerical dispersion/excessive early washing.
4. PLDP = 8 cm + Adjusted Drainage/Hydraulic retention (PORMIN, SDUL, SSKS).

Runs deterministic DSSAT simulations with v23 best Member #31 parameters and tracks:
- Root growth depth (RDPD)
- Root dry weight (RWAD)
- Root length density (RL1D-RL6D)
- Nitrogen uptake (NUPC)
- Soil nitrate dynamics in 0-15cm vs 20-50cm
- Final dry harvest yield (CHPDT)
"""
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

EXP_25_BASE = ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v4_13layer_20260820"
EXP_26_BASE = ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v4_13layer_20260820"

EXP_25_PLDP8 = ROOT / "data/user/experiments/xxql2501_pldp8_13layer_20260822"
EXP_26_PLDP8 = ROOT / "data/user/experiments/xxql2601_pldp8_13layer_20260822"


def setup_pldp8_bundles():
    for src, dst, sname in [(EXP_25_BASE, EXP_25_PLDP8, "XXQL2501"), (EXP_26_BASE, EXP_26_PLDP8, "XXQL2601")]:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        
        # Modify TMX planting depth
        tmx_file = dst / f"{sname}.TMX"
        lines = tmx_file.read_text().splitlines()
        new_lines = []
        in_planting = False
        for l in lines:
            if l.startswith("*PLANTING DETAILS"):
                in_planting = True
                new_lines.append(l)
            elif in_planting and l.startswith("@P"):
                new_lines.append(l)
            elif in_planting and l.strip() and not l.startswith("*") and not l.startswith("@"):
                # Replace PLDP (col 9) with 8
                parts = l.split()
                # Format: 2 25075 -99 2.7 2.7 T R 90 90 1 3 60 25 1 3 Eggplant
                # PLDP is index 9 (0-indexed: 0:P, 1:PDATE, 2:EDATE, 3:PPOP, 4:PPOE, 5:PLME, 6:PLDS, 7:PLRS, 8:PLRD, 9:PLDP, 10:PLWT, 11:PAGE, 12:PENV, 13:PLPH, 14:SPRL)
                # Formatted fixed string
                p_code = parts[0]
                pdate = parts[1]
                edate = parts[2]
                ppop = parts[3]
                ppoe = parts[4]
                plme = parts[5]
                plds = parts[6]
                plrs = parts[7]
                plrd = parts[8]
                pldp = "8" # Changed to 8cm
                plwt = parts[10]
                page = parts[11]
                penv = parts[12]
                plph = parts[13] if len(parts) > 13 else "1"
                sprl = "8" # Seedling plug length 8cm
                plname = "Eggplant"
                
                formatted_line = f" {int(p_code):1d} {pdate:5s} {edate:>5s}  {float(ppop):4.1f}  {float(ppoe):4.1f}     {plme:1s}     {plds:1s}    {plrs:>2s}    {plrd:>2s}     {pldp:>1s}     {plwt:>1s}    {page:>2s}    {penv:>2s}     {plph:>1s}     {sprl:>1s}                        {plname:s}"
                new_lines.append(formatted_line)
                in_planting = False
            else:
                new_lines.append(l)
        tmx_file.write_text("\n".join(new_lines))
        print(f"Created PLDP=8 bundle: {dst}")


def run_experiment_case(case_name: str, exp25: Path, exp26: Path) -> dict:
    run_dir = ROOT / "workspace/runs" / case_name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    
    design_path = run_dir / "joint_design.json"
    design_content = {
        "schema_version": 1,
        "design_id": case_name,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": case_name,
        "bounds_id": "eggplant_e02_v23_formal_full_synergy_20260821",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Pure measured FileX IC values with 13-layer soil",
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
                "bundle_path": str(exp25),
                "role": "calibration",
                "treatments": [2, 5, 10, 13]
            },
            {
                "season_id": "26SP",
                "experiment_code": "XXQL2601",
                "bundle_path": str(exp26),
                "role": "calibration",
                "treatments": [2, 11, 3, 12]
            }
        ]
    }
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
    print(f"Running simulation for {case_name}...")
    subprocess.run(cmd_run, cwd=run_dir, env=env, check=True)
    
    # Parse results
    res = {"case_name": case_name}
    sys.path.insert(0, str(ROOT / "tools/analysis"))
    from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare
    
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
        
        # SoilNi
        sni_lines = sni_file.read_text(errors="ignore").splitlines()
        header_s, cur_tn, recs_s = None, None, []
        for l in sni_lines:
            if l.startswith("*RUN"):
                m = re.search(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", l)
                if m: cur_tn = int(m.group(2))
            elif l.startswith("@YEAR"):
                header_s = l.replace("@", "").split()
            elif cur_tn in [n3_tn, n0_tn] and header_s and l.strip() and not l.startswith("*") and not l.startswith("@"):
                parts = l.split()
                if len(parts) >= len(header_s) and parts[0].isdigit():
                    r = {header_s[i]: float(parts[i]) for i in range(len(header_s))}
                    r["TN"] = cur_tn
                    recs_s.append(r)
        df_sni = pd.DataFrame(recs_s)
        
        for tn, tname in [(n3_tn, "N3"), (n0_tn, "N0")]:
            sub_h = df_h[df_h["TN"] == tn]
            sub_pg = df_pg[df_pg["TN"] == tn]
            sub_pn = df_pn[df_pn["TN"] == tn]
            sub_sni = df_sni[df_sni["TN"] == tn]
            
            last_h = sub_h.iloc[-1] if not sub_h.empty else {}
            last_pg = sub_pg.iloc[-1] if not sub_pg.empty else {}
            last_pn = sub_pn.iloc[-1] if not sub_pn.empty else {}
            last_sni = sub_sni.iloc[-1] if not sub_sni.empty else {}
            
            res[f"{season}_{tname}_obs_dry"] = last_h.get("OBS_DRY_CUM", np.nan)
            res[f"{season}_{tname}_sim_dry"] = last_h.get("SIM_DRY_CUM", np.nan)
            res[f"{season}_{tname}_root_wt"] = last_pg.get("RWAD", np.nan)
            res[f"{season}_{tname}_root_dep"] = last_pg.get("RDPD", np.nan)
            res[f"{season}_{tname}_rld_top"] = last_pg.get("RL1D", np.nan)
            res[f"{season}_{tname}_rld_sub"] = last_pg.get("RL2D", np.nan)
            res[f"{season}_{tname}_rld_deep"] = last_pg.get("RL5D", np.nan)
            res[f"{season}_{tname}_n_uptk"] = last_pn.get("NUPC", np.nan)
            res[f"{season}_{tname}_leaf_n"] = last_pn.get("LN%D", np.nan)
            res[f"{season}_{tname}_soil_min_n"] = last_sni.get("NMNC", np.nan)
            res[f"{season}_{tname}_soil_leach_n"] = last_sni.get("NLCC", np.nan)
            
            # Record early growth at DAP 30
            d30_pg = sub_pg[sub_pg["DAP"] == 30]
            d30_pn = sub_pn[sub_pn["DAP"] == 30]
            if not d30_pg.empty:
                res[f"{season}_{tname}_d30_lai"] = d30_pg.iloc[0].get("LAID", np.nan)
                res[f"{season}_{tname}_d30_root_wt"] = d30_pg.iloc[0].get("RWAD", np.nan)
                res[f"{season}_{tname}_d30_root_dep"] = d30_pg.iloc[0].get("RDPD", np.nan)
            if not d30_pn.empty:
                res[f"{season}_{tname}_d30_leaf_n"] = d30_pn.iloc[0].get("LN%D", np.nan)
                res[f"{season}_{tname}_d30_n_uptk"] = d30_pn.iloc[0].get("NUPC", np.nan)
                
    return res


def main():
    setup_pldp8_bundles()
    
    print("\n--- Running Baseline (PLDP = 1/5 cm) ---")
    res_base = run_experiment_case("exp_pldp_baseline_v23_best31", EXP_25_BASE, EXP_26_BASE)
    
    print("\n--- Running PLDP = 8 cm ---")
    res_pldp8 = run_experiment_case("exp_pldp_8cm_v23_best31", EXP_25_PLDP8, EXP_26_PLDP8)
    
    df_all = pd.DataFrame([res_base, res_pldp8])
    out_csv = ROOT / "workspace/runs/pldp_comparison_results_20260822.csv"
    df_all.to_csv(out_csv, index=False)
    
    print("\n==========================================================================================")
    print("                     PLDP = 8 cm vs Baseline Impact on N0 & N3")
    print("==========================================================================================")
    
    cols_25sp = [
        "case_name",
        "25SP_N3_sim_dry", "25SP_N0_obs_dry", "25SP_N0_sim_dry",
        "25SP_N0_d30_lai", "25SP_N0_d30_leaf_n", "25SP_N0_d30_n_uptk",
        "25SP_N0_root_wt", "25SP_N0_n_uptk"
    ]
    print("\n>>> 25SP Season Comparison <<<")
    print(df_all[cols_25sp].to_string(index=False))
    
    cols_26sp = [
        "case_name",
        "26SP_N3_sim_dry", "26SP_N0_obs_dry", "26SP_N0_sim_dry",
        "26SP_N0_d30_lai", "26SP_N0_d30_leaf_n", "26SP_N0_d30_n_uptk",
        "26SP_N0_root_wt", "26SP_N0_n_uptk"
    ]
    print("\n>>> 26SP Season Comparison <<<")
    print(df_all[cols_26sp].to_string(index=False))


if __name__ == "__main__":
    main()
