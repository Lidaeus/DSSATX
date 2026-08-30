"""Test 7-Layer Tillage/Measurement Root-Zone Soil (SLB = 20, 40, 60, 80, 100, 140, 180) vs 13-Layer."""
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

EXP_25_7L = ROOT / "data/user/experiments/xxql2501_rootzone_7layer_20260822"
EXP_26_7L = ROOT / "data/user/experiments/xxql2601_rootzone_7layer_20260822"


def build_7layer_bundles():
    for src, dst, sname in [(EXP_25_BASE, EXP_25_7L, "XXQL2501"), (EXP_26_BASE, EXP_26_7L, "XXQL2601")]:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        
        # Modify SOIL.SOL entry for IBTM910017
        sol_file = dst / "SOIL.SOL"
        lines = sol_file.read_text().splitlines()
        new_lines = []
        in_ibtm = False
        in_layers = False
        
        # 7-layer profile matching measured depths: 20, 40, 60, 80, 100, 140, 180
        seven_layers = [
            "    20     1  .138  .310  .490 1.000  0.23  1.38  0.92  35.0  30.0   -99  0.08   8.1   -99   -99   -99",
            "    40     2  .150  .320  .430  .750  0.23  1.55  0.70  35.0  30.0   -99  0.06   8.0   -99   -99   -99",
            "    60     3  .172  .330  .440  .400  0.24  1.53  0.31  35.0  30.0   -99  0.03   8.0   -99   -99   -99",
            "    80     4  .157  .330  .460  .250  0.24  1.50  0.18  35.0  30.0   -99   -99   -99   -99   -99   -99",
            "   100     5  .166  .340  .510  .150  0.24  1.49  0.10  35.0  30.0   -99   -99   -99   -99   -99   -99",
            "   140     6  .172  .305  .405  .085  0.24  1.53  0.07  35.0  30.0   -99   -99   -99   -99   -99   -99",
            "   180     6  .176  .290  .350  .030  0.24  1.55  0.05  35.0  30.0   -99   -99   -99   -99   -99   -99",
        ]
        
        for l in lines:
            if l.startswith("*IBTM910017"):
                in_ibtm = True
                new_lines.append(l)
            elif in_ibtm and l.startswith("@  SLB"):
                new_lines.append(l)
                in_layers = True
                new_lines.extend(seven_layers)
            elif in_ibtm and in_layers:
                if l.startswith("*") or (l.strip() and l.startswith("@SITE")):
                    in_ibtm = False
                    in_layers = False
                    new_lines.append(l)
                elif l.startswith("*"):
                    in_ibtm = False
                    in_layers = False
                    new_lines.append(l)
                # Skip old 13 layers
                continue
            else:
                new_lines.append(l)
        sol_file.write_text("\n".join(new_lines))
        print(f"Created 7-layer bundle: {dst}")


def run_case(case_name: str, exp25: Path, exp26: Path) -> dict:
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
        "initial_condition_policy": "Pure measured FileX IC values",
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
    
    sys.path.insert(0, str(ROOT / "tools/analysis"))
    from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare
    
    res = {"case_name": case_name}
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
            
            res[f"{season}_{tname}_sim_dry"] = last_h.get("SIM_DRY_CUM", np.nan)
            res[f"{season}_{tname}_obs_dry"] = last_h.get("OBS_DRY_CUM", np.nan)
            res[f"{season}_{tname}_root_wt"] = last_pg.get("RWAD", np.nan)
            res[f"{season}_{tname}_root_dep"] = last_pg.get("RDPD", np.nan)
            res[f"{season}_{tname}_n_uptk"] = last_pn.get("NUPC", np.nan)
            res[f"{season}_{tname}_leaf_n"] = last_pn.get("LN%D", np.nan)
            res[f"{season}_{tname}_min_n"] = last_sni.get("NMNC", np.nan)
            
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
    build_7layer_bundles()
    
    print("\n--- 13-Layer Baseline ---")
    r13 = run_case("case_13layer_baseline", EXP_25_BASE, EXP_26_BASE)
    
    print("\n--- 7-Layer Tillage/Measurement Matching ---")
    r7 = run_case("case_7layer_rootzone", EXP_25_7L, EXP_26_7L)
    
    df = pd.DataFrame([r13, r7])
    print("\n==========================================================================================")
    print("                     7-Layer Root-Zone vs 13-Layer Soil Performance")
    print("==========================================================================================")
    cols_25 = ["case_name", "25SP_N3_sim_dry", "25SP_N0_obs_dry", "25SP_N0_sim_dry", "25SP_N0_d35_lai", "25SP_N0_d35_leaf_n", "25SP_N0_d35_n_uptk", "25SP_N0_n_uptk"]
    print("\n>>> 25SP Dynamics <<<")
    print(df[cols_25].to_string(index=False))
    
    cols_26 = ["case_name", "26SP_N3_sim_dry", "26SP_N0_obs_dry", "26SP_N0_sim_dry", "26SP_N0_d35_lai", "26SP_N0_d35_leaf_n", "26SP_N0_d35_n_uptk", "26SP_N0_n_uptk"]
    print("\n>>> 26SP Dynamics <<<")
    print(df[cols_26].to_string(index=False))


if __name__ == "__main__":
    main()
