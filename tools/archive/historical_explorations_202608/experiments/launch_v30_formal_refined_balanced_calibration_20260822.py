"""v30 Formal Refined Balanced Calibration Launcher:
- 100% of ALL parameters initialized from Physiological Balanced Base (params_balanced_lfmax170.csv).
- Fixed parameters (including XFRMAX, JU-R0, VSSINK, ATOP, KDIF, PGEFF, LFANGB, PROLFI..PROSHF)
  are LOCKED to Physiological Balanced Base values.
- Focused Active Core (~28 parameters) explores tight, physiologically safe corridors (+/- 3% to 8%).
- 100 reals x 5 iters x 6 parallel agents.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
CASE_NAME = "e02_v30_formal_refined_balanced_0_60cm_100x5_20260822"
RUN_DIR = ROOT / "workspace/runs" / CASE_NAME
BOUNDS_ID = "eggplant_e02_v30_formal_refined_balanced_0_60cm_20260822"

N_REALS = 100
NOPTMAX = 5
N_AGENTS = 6
SEED = 20260822

EXP_25_5L = ROOT / "data/user/experiments/xxql2501_rootzone_5layer_60cm_20260822"
EXP_26_5L = ROOT / "data/user/experiments/xxql2601_rootzone_5layer_60cm_20260822"

BOUNDS_SRC = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v25_full_root_state_9layer_20260822.csv"
BALANCED_BASE_PARAMS = ROOT / "workspace/runs/eval_soil_layer_0_60cm_plow_20260822/params_balanced_lfmax170.csv"


def prepare_v30_frozen_bounds():
    frame = pd.read_csv(BOUNDS_SRC, encoding="utf-8-sig")
    df_base = pd.read_csv(BALANCED_BASE_PARAMS)
    base_dict = dict(zip(df_base["name"].str.upper(), df_base["value"]))

    # 1. First ensure ALL parameters in base_dict exist in frame and have init = base_val
    for pname_upper, bval in base_dict.items():
        idx_p = frame.index[frame["name"].str.upper() == pname_upper].tolist()
        if idx_p:
            frame.loc[idx_p[0], "init"] = bval
        else:
            loc = "SPE" if pname_upper in ["SETMAX", "SRMAX", "PGEFF", "RTNO3", "RTNH4", "RWUMX", "KDIF", "LFANGB", "KCAN", "PROLFI", "PROLFG", "PROLFF", "PROSTI", "PROSTG", "PROSTF", "PRORTI", "PRORTG", "PRORTF", "PROSHI", "PROSHG", "PROSHF", "XFRMAX", "JU-R0", "VSSINK", "LNREF", "NRCVR"] else ("IC" if pname_upper in ["PLDP", "PLWT", "RTDEPI"] else "CUL")
            fn = "TMGRO048.SPE" if loc == "SPE" else ("XXQL2501.TMX" if loc == "IC" else "TM0008.CUL")
            new_row = {
                "name": pname_upper, "init": bval, "lower": bval, "upper": bval,
                "status": "fixed", "pargp": "crop", "location": loc,
                "file": fn, "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
            }
            frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # 2. Define Active Focused Core Parameters (~28 parameters) with tight safe corridors
    active_core_bounds = {
        # Phenology
        "EM-FL": (26.6395, 26.0, 27.2),
        "FL-SH": (2.5854, 2.45, 2.75),
        "FL-SD": (8.5214, 8.0, 9.2),
        # Canopy & Photosynthesis
        "LFMAX": (1.7000, 1.65, 1.75),
        "SLAVR": (194.6630, 188.0, 202.0),
        "SIZLF": (314.5260, 305.0, 325.0),
        "SENRTE": (0.305942, 0.285, 0.330),
        # Sink & Harvest
        "XFRT": (0.7400, 0.730, 0.750),
        "PODUR": (18.0000, 17.5, 18.5),
        "SFDUR": (22.9567, 22.0, 24.0),
        "SDPDV": (197.2940, 188.0, 208.0),
        "SETMAX": (0.3000, 0.285, 0.315),
        "SRMAX": (0.3000, 0.285, 0.315),
        "XFRMAX": (0.032311, 0.030, 0.035),
        # Transplant state
        "PLWT": (9.4420, 9.0, 10.0),
        "RTDEPI": (14.7718, 14.0, 15.5),
        "PLDP": (8.0, 7.5, 8.5),
        # Uptake & Nitrogen
        "RTNO3": (0.014575, 0.0138, 0.0152),
        "RTNH4": (0.014575, 0.0138, 0.0152),
        "RWUMX": (0.043038, 0.041, 0.045),
        "LNREF": (5.049090, 4.95, 5.15),
        "NRCVR": (0.356732, 0.34, 0.38),
        "SOIL_SLNF": (3.2000, 3.10, 3.30),
    }

    # 5-Layer Field Capacity (SOIL_SDUL) tightly around measured values (+/- 2%)
    sdul_measured_5l = [
        ("SOIL_SDUL_01", 0.320, 0.314, 0.326),
        ("SOIL_SDUL_02", 0.330, 0.324, 0.336),
        ("SOIL_SDUL_03", 0.340, 0.334, 0.346),
        ("SOIL_SDUL_04", 0.305, 0.299, 0.311),
        ("SOIL_SDUL_05", 0.290, 0.284, 0.296),
    ]

    # 5-Layer SLLL & SSAT
    slll_measured_5l = [
        ("SOIL_SLLL_01", 0.150, 0.147, 0.153),
        ("SOIL_SLLL_02", 0.157, 0.154, 0.160),
        ("SOIL_SLLL_03", 0.166, 0.163, 0.169),
        ("SOIL_SLLL_04", 0.173, 0.170, 0.176),
        ("SOIL_SLLL_05", 0.176, 0.173, 0.179),
    ]

    ssat_measured_5l = [
        ("SOIL_SSAT_01", 0.450, 0.440, 0.460),
        ("SOIL_SSAT_02", 0.460, 0.450, 0.470),
        ("SOIL_SSAT_03", 0.510, 0.500, 0.520),
        ("SOIL_SSAT_04", 0.400, 0.390, 0.410),
        ("SOIL_SSAT_05", 0.350, 0.340, 0.360),
    ]

    # 5-Layer Organic Carbon (SOIL_SLOC) around measured values (+/- 3%)
    sloc_measured_5l = [
        ("SOIL_SLOC_01", 0.650, 0.630, 0.670),
        ("SOIL_SLOC_02", 0.180, 0.175, 0.185),
        ("SOIL_SLOC_03", 0.100, 0.095, 0.105),
    ]

    active_specs = {
        **{k: (v[0], v[1], v[2]) for k, v in active_core_bounds.items()},
        **{k: (v1, v2, v3) for k, v1, v2, v3 in sdul_measured_5l},
        **{k: (v1, v2, v3) for k, v1, v2, v3 in slll_measured_5l},
        **{k: (v1, v2, v3) for k, v1, v2, v3 in ssat_measured_5l},
        **{k: (v1, v2, v3) for k, v1, v2, v3 in sloc_measured_5l},
    }

    # Disable extra soil layers (> 5)
    for prefix in ["SOIL_SDUL_", "SOIL_SLLL_", "SOIL_SSAT_", "SOIL_SLOC_", "SOIL_SBDM_", "SOIL_SRGF_"]:
        for extra_idx in range(6, 14):
            sname = f"{prefix}{extra_idx:02d}"
            idx_extra = frame.index[frame["name"].str.upper() == sname].tolist()
            if idx_extra:
                frame.loc[idx_extra[0], "status"] = "disabled"

    # Set active vs fixed
    for idx, row in frame.iterrows():
        pname = str(row["name"]).upper()
        st = row["status"]
        if st == "disabled":
            continue
        if pname in active_specs:
            init_v, low_v, up_v = active_specs[pname]
            frame.loc[idx, ["init", "lower", "upper", "status"]] = [init_v, low_v, up_v, "active"]
        else:
            # Set to fixed with base value
            if pname in base_dict:
                bval = float(base_dict[pname])
                frame.loc[idx, ["init", "lower", "upper", "status"]] = [bval, bval, bval, "fixed"]
            else:
                ival = float(row["init"])
                frame.loc[idx, ["init", "lower", "upper", "status"]] = [ival, ival, ival, "fixed"]

    # Final pass: Ensure consistency for all rows
    for idx, row in frame.iterrows():
        st = row["status"]
        if st == "fixed":
            i_val = float(row["init"])
            frame.loc[idx, "lower"] = i_val
            frame.loc[idx, "upper"] = i_val
        elif st == "active":
            i_val = float(row["init"])
            l_val = float(row["lower"])
            u_val = float(row["upper"])
            if i_val < l_val or i_val > u_val:
                frame.loc[idx, "init"] = max(l_val, min(u_val, i_val))
        elif st == "disabled":
            l_val = float(row["lower"])
            u_val = float(row["upper"])
            i_val = float(row["init"])
            if i_val < l_val or i_val > u_val:
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
        "--bounds-id", BOUNDS_ID, "--notes", "v30 Formal Refined Balanced Calibration 100% sourced from Physiological Base"
    ], cwd=ROOT, check=True)
    print(f"Frozen bounds prepared & registered: {BOUNDS_ID}")


def build_and_launch():
    # Make sure 5-layer 0-60cm bundles are cleanly up to date
    sys.path.insert(0, str(ROOT / "tools/experiments"))
    import clean_build_5layer_bundles_20260822
    clean_build_5layer_bundles_20260822.main()

    prepare_v30_frozen_bounds()

    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)

    design_path = ROOT / "configs/runs" / f"{CASE_NAME}.json"
    design_content = {
        "schema_version": 1,
        "design_id": CASE_NAME,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "v30 Formal Refined Balanced Calibration 100% Sourced from Physiological Base",
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
    print(f"   Building v30 Calibration Task: {CASE_NAME}")
    print(f"   Config: {N_REALS} reals x {NOPTMAX} iters x {N_AGENTS} agents")
    print(f"=======================================================")

    builder_cmd = [
        sys.executable, str(ROOT / "tools/calibration/build_focused_core_v29_20260822.py"),
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
    print(f"\nv30 Refined Balanced Calibration completed successfully!")


if __name__ == "__main__":
    build_and_launch()
