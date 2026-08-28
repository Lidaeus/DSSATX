"""Compare Soil Layering Schemes in Top 30cm:
Scheme A: 0-3, 3-15, 15-30, 40, 50, 60, 80, 100, 120, 140, 180 cm (11 layers)
Scheme B: 0-3, 3-30, 40, 50, 60, 80, 100, 120, 140, 180 cm (10 layers)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd
import numpy as np

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
BEST_PARAMS_V25 = ROOT / "workspace/runs/e02_v25_full_root_state_9layer_80x5_20260822/deterministic_candidates/best_phi_member50_two_season_20260822/best_member_50_params.csv"

EXP_25_BASE = ROOT / "data/user/experiments/xxql2501_rootzone_9layer_30cm_20260822"
EXP_26_BASE = ROOT / "data/user/experiments/xxql2601_rootzone_9layer_30cm_20260822"


def generate_soil_sol(src_soil_path: Path, dst_soil_path: Path, scheme: str):
    text = src_soil_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    
    if scheme == "A":
        # 0-3, 3-15, 15-30, 40, 50, 60, 80, 100, 120, 140, 180 (11 layers)
        layer_def = """@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC
     3     1  .138  .310  .490 1.000  0.23  1.38  0.92  35.0  30.0   -99  0.08   8.1   -99   -99   -99
    15     1  .138  .310  .490 1.000  0.23  1.38  0.92  35.0  30.0   -99  0.08   8.1   -99   -99   -99
    30     1  .142  .313  .470  .950  0.23  1.44  0.85  35.0  30.0   -99  0.07   8.1   -99   -99   -99
    40     2  .150  .320  .430  .650  0.23  1.55  0.70  35.0  30.0   -99  0.06   8.0   -99   -99   -99
    50     3  .172  .330  .440  .450  0.24  1.53  0.31  35.0  30.0   -99  0.03   8.0   -99   -99   -99
    60     3  .172  .330  .440  .300  0.24  1.53  0.31  35.0  30.0   -99  0.03   8.0   -99   -99   -99
    80     4  .157  .330  .460  .250  0.24  1.50  0.18  35.0  30.0   -99   -99   -99   -99   -99   -99
   100     5  .166  .340  .510  .150  0.24  1.49  0.10  35.0  30.0   -99   -99   -99   -99   -99   -99
   120     6  .170  .310  .420  .100  0.24  1.52  0.08  35.0  30.0   -99   -99   -99   -99   -99   -99
   140     6  .173  .300  .390  .070  0.24  1.54  0.06  35.0  30.0   -99   -99   -99   -99   -99   -99
   180     6  .176  .290  .350  .030  0.24  1.55  0.05  35.0  30.0   -99   -99   -99   -99   -99   -99"""
    else:
        # Scheme B: 0-3, 3-30, 40, 50, 60, 80, 100, 120, 140, 180 (10 layers)
        layer_def = """@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC
     3     1  .138  .310  .490 1.000  0.23  1.38  0.92  35.0  30.0   -99  0.08   8.1   -99   -99   -99
    30     1  .142  .313  .470  .950  0.23  1.44  0.85  35.0  30.0   -99  0.07   8.1   -99   -99   -99
    40     2  .150  .320  .430  .650  0.23  1.55  0.70  35.0  30.0   -99  0.06   8.0   -99   -99   -99
    50     3  .172  .330  .440  .450  0.24  1.53  0.31  35.0  30.0   -99  0.03   8.0   -99   -99   -99
    60     3  .172  .330  .440  .300  0.24  1.53  0.31  35.0  30.0   -99  0.03   8.0   -99   -99   -99
    80     4  .157  .330  .460  .250  0.24  1.50  0.18  35.0  30.0   -99   -99   -99   -99   -99   -99
   100     5  .166  .340  .510  .150  0.24  1.49  0.10  35.0  30.0   -99   -99   -99   -99   -99   -99
   120     6  .170  .310  .420  .100  0.24  1.52  0.08  35.0  30.0   -99   -99   -99   -99   -99   -99
   140     6  .173  .300  .390  .070  0.24  1.54  0.06  35.0  30.0   -99   -99   -99   -99   -99   -99
   180     6  .176  .290  .350  .030  0.24  1.55  0.05  35.0  30.0   -99   -99   -99   -99   -99   -99"""

    new_lines = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if l.startswith("*IBTM910017"):
            new_lines.append(l)
            i += 1
            while i < len(lines) and not lines[i].startswith("@  SLB"):
                new_lines.append(lines[i])
                i += 1
            new_lines.append(layer_def)
            while i < len(lines) and not lines[i].startswith("*IBPP910015"):
                i += 1
        else:
            new_lines.append(l)
            i += 1
            
    dst_soil_path.write_text("\n".join(new_lines), encoding="utf-8")


def run_scheme(scheme_name: str, scheme_type: str) -> dict:
    case_name = f"test_soil_{scheme_name}_compare_20260822"
    run_dir = ROOT / "workspace/runs" / case_name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    
    t25 = run_dir / "exp25"
    t26 = run_dir / "exp26"
    shutil.copytree(EXP_25_BASE, t25)
    shutil.copytree(EXP_26_BASE, t26)
    
    generate_soil_sol(EXP_25_BASE / "SOIL.SOL", t25 / "SOIL.SOL", scheme_type)
    generate_soil_sol(EXP_26_BASE / "SOIL.SOL", t26 / "SOIL.SOL", scheme_type)
    
    design = {
        "schema_version": 1, "design_id": case_name, "cultivar_identity": "TM0008",
        "shared_parameter_scope": case_name, "bounds_id": "eggplant_e02_v25_full_root_state_9layer_20260822",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": f"Soil scheme {scheme_type}",
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
    res = subprocess.run([
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(run_dir / "joint_design.json"),
        "--param-csv", str(BEST_PARAMS_V25),
        "--prefix", "sim", "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs"
    ], cwd=run_dir, env=env, check=True)
    
    sys.path.insert(0, str(ROOT / "tools/analysis"))
    from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare, build_season_process_compare, compute_metrics

    results = {}
    for season, tmt_map in [("25SP", {2: "W3N3", 10: "W1N3", 5: "W3N0", 13: "W1N0"}),
                            ("26SP", {2: "W3N3", 3: "W1N3", 11: "W3N0", 12: "W1N0"})]:
        sdir = run_dir / "_seasons" / season
        h = build_season_harvest_compare(sdir, season)
        last_h = h.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
        
        # Read plantgro & soil n output
        pgro_file = sdir / "PlantGro.OUT"
        sn_file = sdir / "SoilNi.OUT"
        
        for idx, row in last_h.iterrows():
            tn = int(row["TN"])
            tlabel = tmt_map.get(tn, f"TN{tn}")
            results[(season, tlabel)] = {
                "Obs_Dry": row["OBS_DRY_CUM"],
                "Sim_Dry": row["SIM_DRY_CUM"],
                "Obs_Fresh": row["OBS_FRESH_CUM"],
                "Sim_Fresh": row["SIM_FRESH_CUM"],
                "Bias_Dry_Pct": (row["SIM_DRY_CUM"] - row["OBS_DRY_CUM"]) / row["OBS_DRY_CUM"] * 100.0,
            }
            
        # Compute season metrics
        m_dry = compute_metrics(h["OBS_DRY_CUM"].to_numpy(float), h["SIM_DRY_CUM"].to_numpy(float))
        m_fresh = compute_metrics(h["OBS_FRESH_CUM"].to_numpy(float), h["SIM_FRESH_CUM"].to_numpy(float))
        results[(season, "METRICS")] = {
            "Dry_NSE": m_dry["nse"], "Dry_R2": m_dry["r2"], "Dry_d": m_dry["d_index"],
            "Fresh_NSE": m_fresh["nse"], "Fresh_R2": m_fresh["r2"], "Fresh_d": m_fresh["d_index"],
        }
    return results


def main():
    print("Running Scheme A (0-3, 3-15, 15-30 cm, 11 layers)...")
    res_a = run_scheme("SchemeA_0_3_15_30", "A")
    print("Running Scheme B (0-3, 3-30 cm, 10 layers)...")
    res_b = run_scheme("SchemeB_0_3_30", "B")
    
    print("\n" + "="*95)
    print(f"{'Season':<6s} | {'Treatment':<8s} | {'Obs Dry':>8s} | {'Scheme A (0-3, 3-15, 15-30)':>28s} | {'Scheme B (0-3, 3-30)':>25s}")
    print("="*95)
    
    for season in ["25SP", "26SP"]:
        for tlabel in ["W3N3", "W1N3", "W3N0", "W1N0"]:
            a = res_a.get((season, tlabel), {})
            b = res_b.get((season, tlabel), {})
            print(f"{season:<6s} | {tlabel:<8s} | {a.get('Obs_Dry', 0):>8.1f} | {a.get('Sim_Dry', 0):>8.1f} kg ({a.get('Bias_Dry_Pct', 0):>+6.1f}%) | {b.get('Sim_Dry', 0):>8.1f} kg ({b.get('Bias_Dry_Pct', 0):>+6.1f}%)")
        ma = res_a.get((season, "METRICS"), {})
        mb = res_b.get((season, "METRICS"), {})
        print(f"{season} METRICS -> Scheme A: Dry NSE={ma.get('Dry_NSE', 0):+.3f}, d={ma.get('Dry_d', 0):.3f} | Scheme B: Dry NSE={mb.get('Dry_NSE', 0):+.3f}, d={mb.get('Dry_d', 0):.3f}")
        print("-" * 95)


if __name__ == "__main__":
    main()
