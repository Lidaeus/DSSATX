"""v28 Formal Super-Balanced Calibration Launcher:
- 5-Layer 0-60cm single deep plow soil structure.
- Center-anchored prior: ALL parameter initial values (init) set EXACTLY to the Physiological Balanced Base.
- Physically guarded safe hyper-cube corridors:
  * FL-SH: [2.40, 2.80], EM-FL: [25.5, 27.5], FL-SD: [7.5, 10.0]
  * SENRTE: [0.25, 0.40], SETMAX: [0.28, 0.35], SRMAX: [0.28, 0.35]
  * XFRT: [0.72, 0.76], PODUR: [17.0, 19.0], SFDUR: [21.5, 24.5]
  * LFMAX: [1.65, 1.75], SDPDV: [180.0, 225.0], SLAVR: [180.0, 220.0], SIZLF: [300.0, 335.0]
  * PLWT: [8.8, 10.2], RTDEPI: [14.0, 16.5], PLDP: [7.5, 8.5], SOIL_SLNF: [3.05, 3.35]
- 200 realizations x 5 iterations x 6 parallel agents.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CASE_NAME = "e02_v28_formal_super_balanced_0_60cm_200x5_20260822"
RUN_DIR = ROOT / "workspace/runs" / CASE_NAME
BOUNDS_ID = "eggplant_e02_v28_formal_super_balanced_0_60cm_20260822"

N_REALS = 200
NOPTMAX = 5
N_AGENTS = 6
SEED = 20260822

EXP_25_5L = ROOT / "data/user/experiments/xxql2501_rootzone_5layer_60cm_20260822"
EXP_26_5L = ROOT / "data/user/experiments/xxql2601_rootzone_5layer_60cm_20260822"

BOUNDS_SRC = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v25_full_root_state_9layer_20260822.csv"
BALANCED_BASE_PARAMS = ROOT / "workspace/runs/eval_soil_layer_0_60cm_plow_20260822/params_balanced_lfmax170.csv"


def prepare_v28_frozen_bounds():
    frame = pd.read_csv(BOUNDS_SRC, encoding="utf-8-sig")
    df_base = pd.read_csv(BALANCED_BASE_PARAMS)
    base_dict = dict(zip(df_base["name"].str.upper(), df_base["value"]))

    # Core Parameters with Tight Physiologically Guarded Corridors
    tight_specs = {
        "EM-FL": (26.6395, 25.5, 27.5, "active"),
        "FL-SH": (2.5854, 2.40, 2.80, "active"),
        "FL-SD": (8.5214, 7.5, 10.0, "active"),
        "SD-PM": (400.0, 400.0, 400.0, "fixed"),
        "FL-LF": (400.0, 400.0, 400.0, "fixed"),
        "SENRTE": (0.3059, 0.25, 0.40, "active"),
        "SETMAX": (0.3000, 0.28, 0.35, "active"),
        "SRMAX": (0.3000, 0.28, 0.35, "active"),
        "XFRT": (0.7400, 0.72, 0.76, "active"),
        "PODUR": (18.0000, 17.0, 19.0, "active"),
        "SFDUR": (22.9567, 21.5, 24.5, "active"),
        "SDPDV": (197.2940, 180.0, 225.0, "active"),
        "SLAVR": (194.6630, 180.0, 220.0, "active"),
        "SIZLF": (314.5260, 300.0, 335.0, "active"),
        "LFMAX": (1.7000, 1.65, 1.75, "active"),
        "PLWT": (9.4420, 8.8, 10.2, "active"),
        "RTDEPI": (14.7718, 14.0, 16.5, "active"),
        "SOIL_SLNF": (3.2000, 3.05, 3.35, "active"),
        "SOIL_SLPF": (0.9300, 0.92, 0.96, "active"),
        "PGEFF": (0.0550, 0.045, 0.065, "active"),
        "RTNO3": (0.0150, 0.0135, 0.0150, "active"),
        "RTNH4": (0.0150, 0.0135, 0.0150, "active"),
        "RWUMX": (0.0430, 0.040, 0.048, "active"),
        "KDIF": (0.75, 0.65, 0.85, "active"),
        "LFANGB": (1.80, 1.50, 2.20, "active"),
        "WTPSD": (0.0040, 0.0040, 0.0040, "fixed"),
        "PLDP": (8.0, 7.5, 8.5, "active"),
    }

    for pname, (init_v, low_v, up_v, stat_v) in tight_specs.items():
        idx_p = frame.index[frame["name"].str.upper() == pname].tolist()
        if idx_p:
            frame.loc[idx_p[0], ["init", "lower", "upper", "status"]] = [init_v, low_v, up_v, stat_v]
        else:
            loc = "SPE" if pname in ["SETMAX", "SRMAX", "PGEFF", "RTNO3", "RTNH4", "RWUMX", "KDIF", "LFANGB"] else ("IC" if pname == "PLDP" else "CUL")
            fn = "TMGRO048.SPE" if loc == "SPE" else ("XXQL2501.TMX" if loc == "IC" else "TM0008.CUL")
            new_row = {
                "name": pname, "init": init_v, "lower": low_v, "upper": up_v,
                "status": stat_v, "pargp": "crop", "location": loc,
                "file": fn, "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
            }
            frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # 5-Layer Field Capacity (SOIL_SDUL) tightly around measured values (+/- 2%)
    sdul_measured_5l = [
        ("SOIL_SDUL_01", 0.320, 0.314, 0.326),
        ("SOIL_SDUL_02", 0.330, 0.324, 0.336),
        ("SOIL_SDUL_03", 0.340, 0.334, 0.346),
        ("SOIL_SDUL_04", 0.305, 0.299, 0.311),
        ("SOIL_SDUL_05", 0.290, 0.284, 0.296),
    ]
    for sname, init_v, low_v, up_v in sdul_measured_5l:
        idx_sd = frame.index[frame["name"].str.upper() == sname].tolist()
        if idx_sd:
            frame.loc[idx_sd[0], ["init", "lower", "upper", "status"]] = [init_v, low_v, up_v, "active"]
        else:
            new_row = {
                "name": sname, "init": init_v, "lower": low_v, "upper": up_v,
                "status": "active", "pargp": "soil", "location": "SOIL",
                "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
            }
            frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # 5-Layer SLLL & SSAT
    slll_measured_5l = [
        ("SOIL_SLLL_01", 0.150, 0.145, 0.155),
        ("SOIL_SLLL_02", 0.157, 0.152, 0.162),
        ("SOIL_SLLL_03", 0.166, 0.160, 0.172),
        ("SOIL_SLLL_04", 0.173, 0.167, 0.179),
        ("SOIL_SLLL_05", 0.176, 0.170, 0.182),
    ]
    for sname, init_v, low_v, up_v in slll_measured_5l:
        idx_sl = frame.index[frame["name"].str.upper() == sname].tolist()
        if idx_sl:
            frame.loc[idx_sl[0], ["init", "lower", "upper", "status"]] = [init_v, low_v, up_v, "active"]

    ssat_measured_5l = [
        ("SOIL_SSAT_01", 0.450, 0.435, 0.465),
        ("SOIL_SSAT_02", 0.460, 0.445, 0.475),
        ("SOIL_SSAT_03", 0.510, 0.495, 0.525),
        ("SOIL_SSAT_04", 0.400, 0.385, 0.415),
        ("SOIL_SSAT_05", 0.350, 0.335, 0.365),
    ]
    for sname, init_v, low_v, up_v in ssat_measured_5l:
        idx_ss = frame.index[frame["name"].str.upper() == sname].tolist()
        if idx_ss:
            frame.loc[idx_ss[0], ["init", "lower", "upper", "status"]] = [init_v, low_v, up_v, "active"]

    # 5-Layer Organic Carbon (SOIL_SLOC) around measured values (+/- 3%)
    sloc_measured_5l = [
        ("SOIL_SLOC_01", 0.650, 0.630, 0.670),
        ("SOIL_SLOC_02", 0.180, 0.175, 0.185),
        ("SOIL_SLOC_03", 0.100, 0.095, 0.105),
    ]
    for sname, init_v, low_v, up_v in sloc_measured_5l:
        idx_sl = frame.index[frame["name"].str.upper() == sname].tolist()
        if idx_sl:
            frame.loc[idx_sl[0], ["init", "lower", "upper", "status"]] = [init_v, low_v, up_v, "active"]
        else:
            new_row = {
                "name": sname, "init": init_v, "lower": low_v, "upper": up_v,
                "status": "active", "pargp": "soil", "location": "SOIL",
                "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
            }
            frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # Disable extra soil layers (> 5) for SDUL, SLLL, SSAT, SLOC, SBDM, SRGF
    for prefix in ["SOIL_SDUL_", "SOIL_SLLL_", "SOIL_SSAT_", "SOIL_SLOC_", "SOIL_SBDM_", "SOIL_SRGF_"]:
        for extra_idx in range(6, 14):
            sname = f"{prefix}{extra_idx:02d}"
            idx_extra = frame.index[frame["name"].str.upper() == sname].tolist()
            if idx_extra:
                frame.loc[idx_extra[0], "status"] = "disabled"

    # Organ Nitrogen Concentration and Protein Safe Corridors
    for pname, init_v, low_v, up_v in [
        ("PROLFI", 0.28, 0.24, 0.32),
        ("PROLFG", 0.22, 0.18, 0.26),
        ("PROLFF", 0.10, 0.07, 0.13),
        ("PROSTI", 0.18, 0.15, 0.21),
        ("PROSTG", 0.11, 0.09, 0.13),
        ("PROSTF", 0.06, 0.045, 0.075),
        ("PRORTI", 0.14, 0.130, 0.155),
        ("PRORTG", 0.12, 0.110, 0.130),
        ("PRORTF", 0.06, 0.054, 0.066),
        ("PROSHI", 0.21, 0.190, 0.230),
        ("PROSHG", 0.15, 0.135, 0.165),
        ("PROSHF", 0.11, 0.100, 0.120),
        ("LNREF", 5.049, 4.80, 5.30),
        ("NRCVR", 0.357, 0.30, 0.42),
    ]:
        idx_p = frame.index[frame["name"].str.upper() == pname].tolist()
        if idx_p:
            frame.loc[idx_p[0], ["init", "lower", "upper", "status"]] = [init_v, low_v, up_v, "active"]
        else:
            new_row = {
                "name": pname, "init": init_v, "lower": low_v, "upper": up_v,
                "status": "active", "pargp": "species", "location": "SPE",
                "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
            }
            frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # Sanity check: Ensure all active parameters have lower <= init <= upper
    for idx, row in frame.iterrows():
        if row["status"] == "active":
            i_val = float(row["init"])
            l_val = float(row["lower"])
            u_val = float(row["upper"])
            if i_val < l_val or i_val > u_val:
                # auto-center or adjust bounds
                frame.loc[idx, "init"] = max(l_val, min(u_val, i_val))

    proposal_csv = ROOT / "data/parameter_registry/bounds_proposals" / f"{BOUNDS_ID}.csv"
    frozen_csv = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv"
    proposal_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(proposal_csv, index=False, encoding="utf-8-sig")

    if frozen_csv.exists():
        os.remove(frozen_csv)
    meta_path = frozen_csv.parent / f"{BOUNDS_ID}.yaml"
    if meta_path.exists():
        os.remove(meta_path)

    subprocess.run([
        sys.executable, str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(proposal_csv), "--crop", "eggplant",
        "--bounds-id", BOUNDS_ID, "--notes", "v28 Formal Super-Balanced 0-60cm bounds center-anchored on Physiological Base with safe hyper-cube corridors"
    ], cwd=ROOT, check=True)
    print(f"Frozen bounds prepared & registered: {BOUNDS_ID}")


def build_and_launch():
    # Make sure 5-layer 0-60cm bundles are cleanly up to date
    sys.path.insert(0, str(ROOT / "tools/experiments"))
    import clean_build_5layer_bundles_20260822
    clean_build_5layer_bundles_20260822.main()

    prepare_v28_frozen_bounds()

    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)

    design_path = ROOT / "configs/runs" / f"{CASE_NAME}.json"
    design_content = {
        "schema_version": 1,
        "design_id": CASE_NAME,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "v28 Super-Balanced 0-60cm Deep Plow Calibration Center-Anchored on Physiological Base",
        "bounds_id": BOUNDS_ID,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Pure measured FileX IC values with 5-layer 0-60cm deep plow soil",
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
            {
                "season_id": "25SP",
                "experiment_code": "XXQL2501",
                "bundle_path": str(EXP_25_5L),
                "role": "calibration",
                "treatments": [2, 5, 10, 13]
            },
            {
                "season_id": "26SP",
                "experiment_code": "XXQL2601",
                "bundle_path": str(EXP_26_5L),
                "role": "calibration",
                "treatments": [2, 11, 3, 12]
            }
        ],
        "pest_ies": {
            "num_reals": N_REALS,
            "noptmax": NOPTMAX,
            "par_sigma_range": 4.0,
            "lambda_mults": [0.1, 1.0, 10.0],
            "subreg": True,
            "subreg_how": "par_sigma_range"
        }
    }

    with open(design_path, "w", encoding="utf-8") as f:
        json.dump(design_content, f, indent=2)

    print(f"\n=======================================================")
    print(f"   Building v28 Calibration Task: {CASE_NAME}")
    print(f"   Config: {N_REALS} reals x {NOPTMAX} iters x {N_AGENTS} agents")
    print(f"=======================================================")

    builder_cmd = [
        sys.executable, str(ROOT / "tools/calibration/build_fixed_soil_joint_v3_20260813.py"),
        "--variant", "official",
        "--case", CASE_NAME,
        "--design", str(design_path),
        "--bounds-id", BOUNDS_ID,
        "--noptmax", str(NOPTMAX),
        "--ies-num-reals", str(N_REALS),
        "--random-seed", str(SEED)
    ]
    subprocess.run(builder_cmd, cwd=ROOT, check=True)

    cmd_parallel = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(RUN_DIR),
        "--case", CASE_NAME,
        "--mode", "ies",
        "--n-agents", str(N_AGENTS),
        "--wait"
    ]
    print(f"Launching {N_AGENTS}-Agent Parallel IES for {CASE_NAME}...")
    subprocess.run(cmd_parallel, cwd=ROOT, check=True)
    print(f"\nv28 Super-Balanced Calibration completed successfully!")


if __name__ == "__main__":
    build_and_launch()
