"""Compact Experiment: Test SADC (anion adsorption coefficient) across a wide range [0.0, 0.05, 0.10, 0.20, 0.50, 1.0, 2.0]
on the 13-layer soil profile (SLB = [5, 10, 20, 30, 40, 50, 60, 80, 100, 120, 140, 160, 180])
and evaluate its impact on N0 treatments, drainage DRNC, leaching NLCC, uptake NUCM, and yield.
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

ROOT = Path(__file__).resolve().parents[2]
BASE_PARAMS_CSV = ROOT / "workspace/runs/eval_soil_layer_0_60cm_plow_20260822/params_balanced_lfmax170.csv"
EXP_25_13L = ROOT / "data/user/experiments/xxql2501_pldp8_13layer_20260822"
EXP_26_13L = ROOT / "data/user/experiments/xxql2601_pldp8_13layer_20260822"

MAPPING_SRC = ROOT / "workspace/runs/e02_arm_d_full_synergy_50x3_20260820/deterministic_best_17/two_season_water_n_mapping_from_filex.csv"
WORK_DIR = ROOT / "workspace/runs/exp_sadc_13layer_ladder_20260822"

SADC_LADDER = [0.0, 0.05, 0.10, 0.20, 0.50, 1.00, 2.00]

ALL_TMTS_25SP = [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]
ALL_TMTS_26SP = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

N0_TMTS_25SP = [5, 9, 13]  # W3N0, W2N0, W1N0
N0_TMTS_26SP = [9, 11, 12] # W3N0, W2N0, W1N0


def modify_soil_sadc(soil_file: Path, sadc_val: float):
    """Update SADC column in IBTM910017 soil profile in SOIL.SOL."""
    lines = soil_file.read_text(encoding="utf-8").splitlines()
    new_lines = []
    in_target = False
    in_layer_table = False

    for l in lines:
        if l.startswith("*IBTM910017"):
            in_target = True
            new_lines.append(l)
        elif in_target and l.startswith("*") and not l.startswith("*IBTM910017"):
            in_target = False
            in_layer_table = False
            new_lines.append(l)
        elif in_target and "@  SLB" in l:
            in_layer_table = True
            new_lines.append(l)
        elif in_target and in_layer_table and l.strip() and not l.startswith("@") and not l.startswith("!"):
            tokens = l.split()
            if len(tokens) >= 16:
                # Replace the last token (SADC)
                tokens[-1] = f"{sadc_val:5.2f}"
                # Format properly with fixed widths
                # @  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC
                formatted = f"   {int(tokens[0]):>3d}   {tokens[1]:>3s} {float(tokens[2]):>5.3f} {float(tokens[3]):>5.3f} {float(tokens[4]):>5.3f} {float(tokens[5]):>5.3f} {float(tokens[6]):>5.2f} {float(tokens[7]):>5.2f} {float(tokens[8]):>5.2f} {float(tokens[9]):>5.1f} {float(tokens[10]):>5.1f}   {tokens[11]:>3s} {tokens[12]:>5s} {tokens[13]:>5s}   {tokens[14]:>3s}   {tokens[15]:>3s} {sadc_val:>5.2f}"
                new_lines.append(formatted)
            else:
                new_lines.append(l)
        else:
            new_lines.append(l)

    soil_file.write_text("\n".join(new_lines), encoding="utf-8")


def parse_soil_water_and_nitrogen(sdir: Path, season_id: str):
    """Parse DRNC, NLCC, NUCM, NITD from SoilWat.OUT and SoilNi.OUT."""
    water_dict = {}
    sw_file = sdir / "SoilWat.OUT"
    if sw_file.exists():
        cur_tn = None
        for l in sw_file.read_text().splitlines():
            if "TREATMENT" in l:
                parts = l.split()
                idx_t = parts.index("TREATMENT")
                cur_tn = int(parts[idx_t + 1])
            elif cur_tn is not None and l.strip() and not l.startswith("@") and not l.startswith("!") and not l.startswith("*"):
                # 2025 198   154   140   0.0   2.9   0.0   0.0 514.0   0.0   0.0  ...
                # @YEAR DOY   DAS   DAP  TIRR  AIRR  PREC  ROFC  DRNC  SW1D ...
                tokens = l.split()
                if len(tokens) >= 9 and tokens[0].isdigit():
                    try:
                        drnc = float(tokens[8])
                        water_dict[cur_tn] = {"DRNC": drnc}
                    except ValueError:
                        pass

    ni_dict = {}
    sni_file = sdir / "SoilNi.OUT"
    if sni_file.exists():
        cur_tn = None
        for l in sni_file.read_text().splitlines():
            if "TREATMENT" in l:
                parts = l.split()
                idx_t = parts.index("TREATMENT")
                cur_tn = int(parts[idx_t + 1])
            elif cur_tn is not None and l.strip() and not l.startswith("@") and not l.startswith("!") and not l.startswith("*"):
                # @YEAR DOY   DAS   DAP  NITD  NITC  NMNC  NUCM  NLCC ...
                tokens = l.split()
                if len(tokens) >= 9 and tokens[0].isdigit():
                    try:
                        nitd = float(tokens[4])
                        nitc = float(tokens[5])
                        nmnc = float(tokens[6])
                        nucm = float(tokens[7])
                        nlcc = float(tokens[8])
                        ni_dict[cur_tn] = {"NITD": nitd, "NITC": nitc, "NMNC": nmnc, "NUCM": nucm, "NLCC": nlcc}
                    except ValueError:
                        pass

    combined = {}
    all_tns = set(water_dict.keys()) | set(ni_dict.keys())
    for tn in all_tns:
        w = water_dict.get(tn, {"DRNC": np.nan})
        n = ni_dict.get(tn, {"NITD": np.nan, "NITC": np.nan, "NMNC": np.nan, "NUCM": np.nan, "NLCC": np.nan})
        combined[tn] = {**w, **n}
    return combined


def run_experiment():
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(ROOT / "tools/analysis"))
    from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare, compute_metrics

    df_map = pd.read_csv(MAPPING_SRC)
    tmt_dict_25 = dict(zip(df_map[df_map["season_id"] == "25SP"]["treatment"], df_map[df_map["season_id"] == "25SP"]["water_level"] + df_map[df_map["season_id"] == "25SP"]["nitrogen_level"]))
    tmt_dict_26 = dict(zip(df_map[df_map["season_id"] == "26SP"]["treatment"], df_map[df_map["season_id"] == "26SP"]["water_level"] + df_map[df_map["season_id"] == "26SP"]["nitrogen_level"]))

    results_all = []

    for sadc in SADC_LADDER:
        sub_dir = WORK_DIR / f"sadc_{sadc:.2f}".replace(".", "_")
        sub_dir.mkdir(parents=True, exist_ok=True)

        t25 = sub_dir / "exp25"
        t26 = sub_dir / "exp26"
        shutil.copytree(EXP_25_13L, t25)
        shutil.copytree(EXP_26_13L, t26)

        # Modify SADC in SOIL.SOL
        modify_soil_sadc(t25 / "SOIL.SOL", sadc)
        modify_soil_sadc(t26 / "SOIL.SOL", sadc)

        # Create joint design
        design = {
            "schema_version": 1,
            "design_id": f"sadc_{sadc:.2f}",
            "cultivar_identity": "TM0008",
            "shared_parameter_scope": f"SADC={sadc:.2f} on 13-Layer Soil",
            "bounds_id": "eggplant_e02_v25_full_root_state_9layer_20260822",
            "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
            "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
            "initial_condition_policy": "13-layer soil with SADC ladder",
            "nitrogen_response_objective": {"enabled": False},
            "water_response_objective": {"enabled": False},
            "harvest_dry_objective": {
                "enabled": True,
                "mode": "increment_plus_terminal",
                "variable": "CHPDT",
                "process_lambda_per_season": 200.0,
                "terminal_lambda_per_season": 300.0
            },
            "process_state_objective": {
                "enabled": True,
                "mode": "signed_difference_plus_terminal",
                "variables": ["LAID", "LWAD", "SWAD"]
            },
            "seasons": [
                {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(t25), "role": "calibration", "treatments": ALL_TMTS_25SP},
                {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(t26), "role": "calibration", "treatments": ALL_TMTS_26SP}
            ]
        }
        with open(sub_dir / "joint_design.json", "w", encoding="utf-8") as f:
            json.dump(design, f, indent=2)

        env = os.environ.copy()
        env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"

        print(f"Running simulation for SADC = {sadc:.2f}...")
        subprocess.run([
            sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
            "--design", str(sub_dir / "joint_design.json"),
            "--param-csv", str(BASE_PARAMS_CSV),
            "--prefix", f"sim_sadc_{sadc:.2f}",
            "--harvest-var", "CHPDT",
            "--keep-nitrogen-outputs"
        ], cwd=sub_dir, env=env, check=True)

        for season, tdict, tmts in [("25SP", tmt_dict_25, ALL_TMTS_25SP), ("26SP", tmt_dict_26, ALL_TMTS_26SP)]:
            sdir = sub_dir / "_seasons" / season
            h_comp = build_season_harvest_compare(sdir, season)
            soil_stats = parse_soil_water_and_nitrogen(sdir, season)

            last_h = h_comp.sort_values(["TN", "HNO"]).groupby("TN").last().reset_index()
            for idx, row in last_h.iterrows():
                tn = int(row["TN"])
                tlabel = tdict.get(tn, f"TN{tn}")
                s_stat = soil_stats.get(tn, {})
                is_n0 = ("N0" in tlabel)

                results_all.append({
                    "sadc": sadc,
                    "season": season,
                    "treatment": tn,
                    "treatment_label": tlabel,
                    "is_n0": is_n0,
                    "obs_dry": row["OBS_DRY_CUM"],
                    "sim_dry": row["SIM_DRY_CUM"],
                    "obs_fresh": row["OBS_FRESH_CUM"],
                    "sim_fresh": row["SIM_FRESH_CUM"],
                    "bias_dry_kg": row["SIM_DRY_CUM"] - row["OBS_DRY_CUM"],
                    "bias_dry_pct": (row["SIM_DRY_CUM"] - row["OBS_DRY_CUM"]) / row["OBS_DRY_CUM"] * 100.0,
                    "drnc_mm": s_stat.get("DRNC", np.nan),
                    "nlcc_kgN": s_stat.get("NLCC", np.nan),
                    "nucm_kgN": s_stat.get("NUCM", np.nan),
                    "nitd_kgN": s_stat.get("NITD", np.nan),
                })

    df_res = pd.DataFrame(results_all)
    out_csv = WORK_DIR / "sadc_ladder_all_treatments_results.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\nAll SADC ladder simulations finished! Results saved to {out_csv}")

    # Summarize N0 Treatments Across SADC Ladder
    print("\n" + "="*110)
    print(f"=== N0 Treatments Response to SADC Ladder on 13-Layer Soil Profile ===")
    print("="*110)
    print(f"{'SADC':<6s} | {'Season':<6s} | {'Label':<6s} | {'Obs Dry':>8s} | {'Sim Dry':>8s} | {'Bias (%)':>9s} | {'DRNC(mm)':>9s} | {'NLCC(kgN)':>10s} | {'NUCM(kgN)':>10s} | {'NITD(kgN)':>10s}")
    print("-" * 110)
    for sadc in SADC_LADDER:
        sub_n0 = df_res[(df_res["sadc"] == sadc) & (df_res["is_n0"] == True)]
        for idx, row in sub_n0.iterrows():
            print(f"{row['sadc']:<6.2f} | {row['season']:<6s} | {row['treatment_label']:<6s} | {row['obs_dry']:>8.1f} | {row['sim_dry']:>8.1f} | {row['bias_dry_pct']:>+8.1f}% | {row['drnc_mm']:>9.1f} | {row['nlcc_kgN']:>10.2f} | {row['nucm_kgN']:>10.2f} | {row['nitd_kgN']:>10.2f}")
        print("-" * 110)


if __name__ == "__main__":
    run_experiment()
