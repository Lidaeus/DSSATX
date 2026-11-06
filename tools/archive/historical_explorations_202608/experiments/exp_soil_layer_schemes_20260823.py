"""Multi-Directional Soil Discretization Experiments (0-60 cm Profile Optimization):
Scheme 0: Baseline Single 0-60cm Plow Layer (60, 80, 100, 140, 180 cm)
Scheme 1: Ultra-Thin Skin 2cm Grid (2, 6, 20, 60, 100, 180 cm)
Scheme 2: 3cm Micro-Skin Grid (3, 15, 35, 60, 100, 180 cm)
Scheme 3: Dual-Plow Active Grid (10, 30, 60, 100, 180 cm)
Scheme 4: Exponential Multi-Layer Grid (2, 5, 12, 25, 45, 60, 100, 180 cm)

Tests all schemes on 25SP (10 tmts) and 26SP (12 tmts) with Member #26 baseline.
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
BASE_PAR = ROOT / "workspace/runs/e02_v30_formal_refined_balanced_0_60cm_100x5_20260822/deterministic_candidates/best_phi_member26_all22_20260822/best_member_26_params.csv"
WORK_DIR = ROOT / "workspace/runs/exp_soil_layer_schemes_20260823"
REF_SOL = ROOT / "data/user/experiments/xxql2501_rootzone_5layer_60cm_20260822/SOIL.SOL"

if WORK_DIR.exists():
    shutil.rmtree(WORK_DIR)
WORK_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "tools/analysis"))
from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare, build_season_process_compare, compute_metrics


def build_soil_and_ic_bundles(target_dir: Path, season: str, layer_depths: list[int]):
    """Builds a cleanly discretized SOIL.SOL and XXQLxxxx.TMX for given layer boundaries."""
    target_dir.mkdir(parents=True, exist_ok=True)
    src_dir = ROOT / f"data/user/experiments/xxql2501_rootzone_5layer_60cm_20260822" if season == "25SP" else ROOT / f"data/user/experiments/xxql2601_rootzone_5layer_60cm_20260822"

    for item in src_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, target_dir / item.name)

    # 1. Build SOIL.SOL by replacing IBTM910017 block
    sol_txt = REF_SOL.read_text()
    lines_sol = sol_txt.splitlines()
    
    new_sol_lines = []
    in_ib = False
    for l in lines_sol:
        if "*IBTM910017" in l:
            in_ib = True
            new_sol_lines.append("*IBTM910017  SCS           CL     180  Orangeburg Sandy Loam (Discretized Profile)")
            new_sol_lines.append("@SITE        COUNTRY          LAT     LONG SCS FAMILY")
            new_sol_lines.append(" Quincy      USA             35.16   113.8 Loamy,silic,hyperth Gross. Paleud(17)")
            new_sol_lines.append("@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE")
            new_sol_lines.append("   -99   .13     9   .27    81     1   .93 IB001 IB001 IB001")
            new_sol_lines.append("@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC")
            
            for depth in layer_depths:
                if depth <= 60:
                    # 0-60 cm plow layer properties
                    srgf = 1.0 if depth <= 20 else (0.85 if depth <= 40 else 0.65)
                    new_sol_lines.append(f"   {depth:3d}     1  .150  .320  .450  {srgf:5.3f}  0.23  1.50  0.65  35.0  30.0   -99  0.05   8.0   -99   -99   -99")
                elif depth <= 80:
                    new_sol_lines.append(f"   {depth:3d}     4  .157  .330  .460  .250  0.24  1.50  0.18  35.0  30.0   -99   -99   -99   -99   -99   -99")
                elif depth <= 100:
                    new_sol_lines.append(f"   {depth:3d}     5  .166  .340  .510  .150  0.24  1.49  0.10  35.0  30.0   -99   -99   -99   -99   -99   -99")
                elif depth <= 140:
                    new_sol_lines.append(f"   {depth:3d}     6  .173  .305  .400  .080  0.24  1.53  0.07  35.0  30.0   -99   -99   -99   -99   -99   -99")
                else:
                    new_sol_lines.append(f"   {depth:3d}     6  .176  .290  .350  .030  0.24  1.55  0.05  35.0  30.0   -99   -99   -99   -99   -99   -99")
        elif in_ib and l.startswith("*") and not l.startswith("*IBTM910017"):
            in_ib = False
            new_sol_lines.append(l)
        elif not in_ib:
            new_sol_lines.append(l)

    (target_dir / "SOIL.SOL").write_text("\n".join(new_sol_lines))

    # 2. Re-interpolate *INITIAL CONDITIONS in TMX
    tmx_path = target_dir / f"XXQL{season[:2]}01.TMX"
    tmx_lines = tmx_path.read_text().splitlines()
    ic_date = "25069" if season == "25SP" else "26073"

    tmt_ic_raw = {}
    c_t = None
    in_ic = False
    for l in tmx_lines:
        if "*INITIAL CONDITIONS" in l:
            in_ic = True
        elif in_ic and l.startswith("*"):
            break
        elif in_ic:
            tokens = l.split()
            if len(tokens) >= 12 and tokens[0].isdigit():
                c_t = int(tokens[0])
                tmt_ic_raw[c_t] = []
            elif len(tokens) >= 5 and c_t is not None and tokens[0].isdigit() and tokens[1].isdigit():
                tmt_ic_raw[c_t].append({
                    "depth": int(tokens[1]),
                    "sh2o": float(tokens[2]),
                    "snh4": float(tokens[3]),
                    "sno3": float(tokens[4])
                })

    reconstructed_lines = []
    in_ic = False
    for l in tmx_lines:
        if "*INITIAL CONDITIONS" in l:
            in_ic = True
            reconstructed_lines.append(l)
            for t_num, layers in tmt_ic_raw.items():
                reconstructed_lines.append("@C   PCR ICDAT  ICRT  ICND  ICRN  ICRE  ICWD ICRES ICREN ICREP ICRIP ICRID ICNAME")
                reconstructed_lines.append(f"{t_num:>2d}   -99 {ic_date}     1     0     1     1   -99   -99   -99   -99   -99   -99 {t_num}")
                reconstructed_lines.append("@C  ICBL  SH2O  SNH4  SNO3")
                
                v20 = [x for x in layers if x["depth"] == 20][0] if any(x["depth"] == 20 for x in layers) else {"sh2o": 0.22, "snh4": 1.0, "sno3": 20.0}
                v40 = [x for x in layers if x["depth"] == 40][0] if any(x["depth"] == 40 for x in layers) else {"sh2o": 0.26, "snh4": 0.8, "sno3": 10.0}
                v60 = [x for x in layers if x["depth"] == 60][0] if any(x["depth"] == 60 for x in layers) else {"sh2o": 0.28, "snh4": 0.6, "sno3": 5.0}
                
                for d in layer_depths:
                    if d <= 20:
                        sh2o = v20["sh2o"]
                        snh4 = v20["snh4"]
                        sno3 = v20["sno3"]
                    elif d <= 40:
                        sh2o = v40["sh2o"]
                        snh4 = v40["snh4"]
                        sno3 = v40["sno3"]
                    elif d <= 60:
                        sh2o = v60["sh2o"]
                        snh4 = v60["snh4"]
                        sno3 = v60["sno3"]
                    elif d <= 100:
                        sh2o = 0.30
                        snh4 = 0.50
                        sno3 = 1.00
                    else:
                        sh2o = 0.34
                        snh4 = 0.50
                        sno3 = 1.00
                    reconstructed_lines.append(f"{t_num:>2d}  {d:>4d}  {sh2o:5.3f} {snh4:5.3f} {sno3:5.2f}")
        elif in_ic and l.startswith("*"):
            in_ic = False
            reconstructed_lines.append(l)
        elif not in_ic:
            reconstructed_lines.append(l)

    tmx_path.write_text("\n".join(reconstructed_lines))


def run_scheme(scheme_id: str, desc: str, layer_depths: list[int], param_mods: dict = None):
    s_dir = WORK_DIR / scheme_id
    s_dir.mkdir(parents=True, exist_ok=True)
    t25 = s_dir / "exp25"
    t26 = s_dir / "exp26"
    
    build_soil_and_ic_bundles(t25, "25SP", layer_depths)
    build_soil_and_ic_bundles(t26, "26SP", layer_depths)

    df_p = pd.read_csv(BASE_PAR)
    if param_mods:
        for k, v in param_mods.items():
            idx_p = df_p.index[df_p["name"] == k.lower()].tolist()
            if idx_p:
                df_p.loc[idx_p[0], "value"] = v
            else:
                df_p = pd.concat([df_p, pd.DataFrame([{"name": k.lower(), "value": v}])], ignore_index=True)
    par_path = s_dir / "params.csv"
    df_p.to_csv(par_path, index=False)

    design = {
        "schema_version": 1,
        "design_id": scheme_id,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": desc,
        "bounds_id": "eggplant_e02_v30_formal_refined_balanced_0_60cm_20260822",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": desc,
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
            {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(t25), "role": "calibration", "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]},
            {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(t26), "role": "calibration", "treatments": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]}
        ]
    }
    with open(s_dir / "joint_design.json", "w", encoding="utf-8") as f:
        json.dump(design, f, indent=2)

    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    subprocess.run([
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(s_dir / "joint_design.json"),
        "--param-csv", str(par_path),
        "--prefix", f"sim_{scheme_id}",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs"
    ], cwd=s_dir, env=env, check=True, stdout=subprocess.DEVNULL)

    # Collect metrics & terminal yields
    metrics_list = []
    yields_list = []
    for s in ["25SP", "26SP"]:
        h = build_season_harvest_compare(s_dir / f"_seasons/{s}", s)
        m_dry = compute_metrics(h["OBS_DRY_CUM"].to_numpy(float), h["SIM_DRY_CUM"].to_numpy(float))
        m_dry.update({"scheme": scheme_id, "season": s, "variable": "DRY_CUM"})
        metrics_list.append(m_dry)

        p = build_season_process_compare(s_dir / f"_seasons/{s}", s)
        for var in ["LAID", "LWAD", "SWAD"]:
            if f"OBS_{var}" in p.columns and f"SIM_{var}" in p.columns:
                m_v = compute_metrics(p[f"OBS_{var}"].to_numpy(float), p[f"SIM_{var}"].to_numpy(float))
                m_v.update({"scheme": scheme_id, "season": s, "variable": var})
                metrics_list.append(m_v)

        last_h = h.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
        for idx, r in last_h.iterrows():
            yields_list.append({
                "scheme": scheme_id,
                "season": s,
                "tn": int(r["TN"]),
                "obs": r["OBS_DRY_CUM"],
                "sim": r["SIM_DRY_CUM"],
                "bias_pct": (r["SIM_DRY_CUM"] - r["OBS_DRY_CUM"]) / r["OBS_DRY_CUM"] * 100.0
            })
    return pd.DataFrame(metrics_list), pd.DataFrame(yields_list)


def main():
    print("=== Multi-Directional Soil Discretization Experiments (0-60cm Profile) ===")
    
    schemes = [
        ("Scheme_0_Base_60cm", "Baseline Single 0-60cm Layer", [60, 80, 100, 140, 180], None),
        ("Scheme_1_Skin_2cm", "2cm Micro-Skin Grid (2, 6, 20, 60, 100, 180 cm)", [2, 6, 20, 60, 100, 180], None),
        ("Scheme_2_Skin_3cm", "3cm Micro-Skin Grid (3, 15, 35, 60, 100, 180 cm)", [3, 15, 35, 60, 100, 180], None),
        ("Scheme_3_Dual_Plow", "Dual-Plow Active Grid (10, 30, 60, 100, 180 cm)", [10, 30, 60, 100, 180], None),
        ("Scheme_4_Exponential", "Exponential Grid (2, 5, 12, 25, 45, 60, 100, 180 cm)", [2, 5, 12, 25, 45, 60, 100, 180], None),
    ]

    all_metrics = []
    all_yields = []

    for sid, desc, layers, pmods in schemes:
        print(f"\nRunning {sid}: {desc}...")
        try:
            m_df, y_df = run_scheme(sid, desc, layers, pmods)
            all_metrics.append(m_df)
            all_yields.append(y_df)
            print(f"  {sid} completed successfully.")
        except Exception as e:
            print(f"  Error in {sid}: {e}")

    df_metrics = pd.concat(all_metrics, ignore_index=True)
    df_yields = pd.concat(all_yields, ignore_index=True)

    df_metrics.to_csv(WORK_DIR / "soil_schemes_metrics_summary.csv", index=False)
    df_yields.to_csv(WORK_DIR / "soil_schemes_yields_summary.csv", index=False)

    print("\n" + "="*110)
    print(f"{'Scheme':<22s} | {'Season':<6s} | {'DRY_CUM NSE':>12s} | {'DRY RMSE':>10s} | {'LAID NSE':>10s} | {'SWAD NSE':>10s}")
    print("="*110)
    for sid, desc, layers, pmods in schemes:
        for s in ["25SP", "26SP"]:
            sub = df_metrics[(df_metrics["scheme"] == sid) & (df_metrics["season"] == s)]
            nse_dry = sub[sub["variable"] == "DRY_CUM"]["nse"].values[0] if len(sub[sub["variable"] == "DRY_CUM"]) > 0 else np.nan
            rmse_dry = sub[sub["variable"] == "DRY_CUM"]["rmse"].values[0] if len(sub[sub["variable"] == "DRY_CUM"]) > 0 else np.nan
            nse_laid = sub[sub["variable"] == "LAID"]["nse"].values[0] if len(sub[sub["variable"] == "LAID"]) > 0 else np.nan
            nse_swad = sub[sub["variable"] == "SWAD"]["nse"].values[0] if len(sub[sub["variable"] == "SWAD"]) > 0 else np.nan
            print(f"{sid:<22s} | {s:<6s} | {nse_dry:>12.4f} | {rmse_dry:>10.1f} | {nse_laid:>10.4f} | {nse_swad:>10.4f}")
        print("-" * 110)

    print("\n=== N0 and Extreme Water Treatments Focus ===")
    print(f"{'Scheme':<22s} | {'25SP W1N0 (T13)':>16s} | {'25SP W3N0 (T5)':>15s} | {'26SP W1N0 (T12)':>16s} | {'26SP W3N3 (T1)':>15s}")
    print(f"{'Observed Targets':<22s} | {'1958.0 kg':>16s} | {'2882.0 kg':>15s} | {'3557.0 kg':>16s} | {'3967.0 kg':>15s}")
    print("-" * 110)
    for sid, desc, layers, pmods in schemes:
        sub_y = df_yields[df_yields["scheme"] == sid]
        y_25_t13 = sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 13)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 13)]) > 0 else np.nan
        y_25_t5 = sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 5)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "25SP") & (sub_y["tn"] == 5)]) > 0 else np.nan
        y_26_t12 = sub_y[(sub_y["season"] == "26SP") & (sub_y["tn"] == 12)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "26SP") & (sub_y["tn"] == 12)]) > 0 else np.nan
        y_26_t1 = sub_y[(sub_y["season"] == "26SP") & (sub_y["tn"] == 1)]["sim"].values[0] if len(sub_y[(sub_y["season"] == "26SP") & (sub_y["tn"] == 1)]) > 0 else np.nan
        print(f"{sid:<22s} | {y_25_t13:>13.1f} kg | {y_25_t5:>12.1f} kg | {y_26_t12:>13.1f} kg | {y_26_t1:>12.1f} kg")
    print("=" * 110)


if __name__ == "__main__":
    main()
