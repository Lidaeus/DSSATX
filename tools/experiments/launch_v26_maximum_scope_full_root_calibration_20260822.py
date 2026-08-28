"""v26 Maximum-Scope Full-Root-State Calibration Launcher:
- 9-Layer 0-30cm plow layer soil structure.
- Tight measured constraints for SDUL (field capacity) and SLOC (organic carbon).
- Dynamic transplant state: PLWT [5.0, 12.0] g/plant, PLDP [6.0, 12.0] cm.
- Maximized photosynthesis & sink scope: LFMAX [1.50, 2.20], PGEFF [0.035, 0.075], SOIL_SLPF [0.90, 1.00], XFRT [0.70, 0.90], SFDUR [20.0, 40.0], PODUR [16.0, 32.0], SETMAX [0.25, 0.60], SRMAX [0.20, 0.60], SOIL_SLNF [2.80, 4.20].
- 100 realizations x 5 iterations x 6 parallel agents.
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
CASE_NAME = "e02_v26_maximum_scope_full_root_100x5_20260822"
RUN_DIR = ROOT / "workspace/runs" / CASE_NAME
BOUNDS_ID = "eggplant_e02_v26_maximum_scope_full_root_20260822"

N_REALS = 100
NOPTMAX = 5
N_AGENTS = 6
SEED = 20260822

EXP_25_9L = ROOT / "data/user/experiments/xxql2501_rootzone_9layer_30cm_20260822"
EXP_26_9L = ROOT / "data/user/experiments/xxql2601_rootzone_9layer_30cm_20260822"

BOUNDS_SRC = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v25_full_root_state_9layer_20260822.csv"


def prepare_v26_frozen_bounds():
    frame = pd.read_csv(BOUNDS_SRC, encoding="utf-8-sig")

    # 1. Update/Add PLDP (Planting Depth)
    idx_pldp = frame.index[frame["name"].str.upper() == "PLDP"].tolist()
    if idx_pldp:
        frame.loc[idx_pldp[0], ["init", "lower", "upper", "status", "location"]] = [8.0, 6.0, 12.0, "active", "IC"]
    else:
        new_row = {
            "name": "PLDP", "init": 8.0, "lower": 6.0, "upper": 12.0,
            "status": "active", "pargp": "ic", "location": "IC",
            "file": "XXQL2501.TMX", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
        }
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # 2. Expand PLWT (Transplant Biomass)
    idx_plwt = frame.index[frame["name"].str.upper() == "PLWT"].tolist()
    if idx_plwt:
        frame.loc[idx_plwt[0], ["init", "lower", "upper", "status", "location"]] = [9.5, 5.0, 12.0, "active", "IC"]

    # 3. Expand RTDEPI (Initial Root Depth)
    idx_rtdepi = frame.index[frame["name"].str.upper() == "RTDEPI"].tolist()
    if idx_rtdepi:
        frame.loc[idx_rtdepi[0], ["init", "lower", "upper", "status"]] = [15.0, 10.0, 25.0, "active"]

    # 4. Expand LFMAX (Max Leaf Photosynthesis)
    idx_lfmax = frame.index[frame["name"].str.upper() == "LFMAX"].tolist()
    if idx_lfmax:
        frame.loc[idx_lfmax[0], ["init", "lower", "upper", "status"]] = [1.80, 1.50, 2.20, "active"]

    # 5. Open PGEFF (Gross Photosynthetic Efficiency)
    idx_pgeff = frame.index[frame["name"].str.upper() == "PGEFF"].tolist()
    if idx_pgeff:
        frame.loc[idx_pgeff[0], ["init", "lower", "upper", "status"]] = [0.055, 0.035, 0.075, "active"]
    else:
        new_row = {
            "name": "PGEFF", "init": 0.055, "lower": 0.035, "upper": 0.075,
            "status": "active", "pargp": "species", "location": "SPE",
            "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
        }
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # 6. Open SOIL_SLPF (Soil Fertility Factor)
    idx_slpf = frame.index[frame["name"].str.upper() == "SOIL_SLPF"].tolist()
    if idx_slpf:
        frame.loc[idx_slpf[0], ["init", "lower", "upper", "status"]] = [0.98, 0.90, 1.00, "active"]
    else:
        new_row = {
            "name": "SOIL_SLPF", "init": 0.98, "lower": 0.90, "upper": 1.00,
            "status": "active", "pargp": "soil", "location": "SOIL",
            "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
        }
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # 7. Expand XFRT (Fruit Partitioning)
    idx_xfrt = frame.index[frame["name"].str.upper() == "XFRT"].tolist()
    if idx_xfrt:
        frame.loc[idx_xfrt[0], ["init", "lower", "upper", "status"]] = [0.78, 0.70, 0.90, "active"]

    # 8. Expand SFDUR (Seed/Fruit Addition Duration)
    idx_sfdur = frame.index[frame["name"].str.upper() == "SFDUR"].tolist()
    if idx_sfdur:
        frame.loc[idx_sfdur[0], ["init", "lower", "upper", "status"]] = [28.0, 20.0, 40.0, "active"]

    # 9. Expand PODUR (Pod/Fruit Growth Duration)
    idx_podur = frame.index[frame["name"].str.upper() == "PODUR"].tolist()
    if idx_podur:
        frame.loc[idx_podur[0], ["init", "lower", "upper", "status"]] = [22.0, 16.0, 32.0, "active"]

    # 10. Open SETMAX (Maximum Fruit Set Fraction)
    idx_setmax = frame.index[frame["name"].str.upper() == "SETMAX"].tolist()
    if idx_setmax:
        frame.loc[idx_setmax[0], ["init", "lower", "upper", "status"]] = [0.40, 0.25, 0.60, "active"]
    else:
        new_row = {
            "name": "SETMAX", "init": 0.40, "lower": 0.25, "upper": 0.60,
            "status": "active", "pargp": "species", "location": "SPE",
            "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
        }
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # 11. Open SRMAX (Maximum Seed/Fruit Addition Rate)
    idx_srmax = frame.index[frame["name"].str.upper() == "SRMAX"].tolist()
    if idx_srmax:
        frame.loc[idx_srmax[0], ["init", "lower", "upper", "status"]] = [0.40, 0.20, 0.60, "active"]
    else:
        new_row = {
            "name": "SRMAX", "init": 0.40, "lower": 0.20, "upper": 0.60,
            "status": "active", "pargp": "species", "location": "SPE",
            "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
        }
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # 12. Expand SOIL_SLNF (Mineralization Factor)
    idx_slnf = frame.index[frame["name"].str.upper() == "SOIL_SLNF"].tolist()
    if idx_slnf:
        frame.loc[idx_slnf[0], ["init", "lower", "upper", "status"]] = [3.20, 2.80, 4.20, "active"]

    # 13. Tighten Field Capacity (SOIL_SDUL) around measured values (+/- 3%)
    # Measured SDUL values for 9 layers: 0.313, 0.334, 0.334, 0.348, 0.335, 0.290, 0.272, 0.271
    sdul_measured = [
        ("SOIL_SDUL_01", 0.313, 0.304, 0.322),
        ("SOIL_SDUL_02", 0.334, 0.324, 0.344),
        ("SOIL_SDUL_03", 0.334, 0.324, 0.344),
        ("SOIL_SDUL_04", 0.348, 0.338, 0.358),
        ("SOIL_SDUL_05", 0.335, 0.325, 0.345),
        ("SOIL_SDUL_06", 0.290, 0.281, 0.299),
        ("SOIL_SDUL_07", 0.272, 0.264, 0.280),
        ("SOIL_SDUL_08", 0.271, 0.263, 0.279),
    ]
    for sname, init_v, low_v, up_v in sdul_measured:
        idx_sd = frame.index[frame["name"].str.upper() == sname].tolist()
        if idx_sd:
            frame.loc[idx_sd[0], ["init", "lower", "upper", "status"]] = [init_v, low_v, up_v, "active"]

    # 14. Tighten Organic Carbon (SOIL_SLOC) around measured values (+/- 4%)
    sloc_measured = [
        ("SOIL_SLOC_01", 0.922, 0.885, 0.959),
        ("SOIL_SLOC_02", 0.696, 0.668, 0.724),
        ("SOIL_SLOC_03", 0.313, 0.301, 0.326),
    ]
    for sname, init_v, low_v, up_v in sloc_measured:
        idx_sl = frame.index[frame["name"].str.upper() == sname].tolist()
        if idx_sl:
            frame.loc[idx_sl[0], ["init", "lower", "upper", "status"]] = [init_v, low_v, up_v, "active"]

    # 15. Open other key physiological parameters
    for pname, init_v, low_v, up_v in [
        ("KDIF", 0.75, 0.50, 1.00),
        ("LFANGB", 1.80, 1.00, 3.00),
        ("SLAMAX", 650.0, 400.0, 900.0),
        ("SLAMIN", 350.0, 200.0, 500.0),
        ("TURSLA", 1.20, 0.50, 2.00),
        ("NSLA", 1.00, 0.50, 1.50),
        ("FRLFMX", 0.70, 0.50, 0.90),
        ("DSWBAR", 20.0, 10.0, 30.0),
        ("XFRMAX", 0.25, 0.05, 0.50),
        ("SHLAG", 0.40, 0.10, 0.80),
        ("CMOBMX", 0.030, 0.010, 0.050),
        ("CADSTF", 0.60, 0.30, 0.90),
        ("CADPR1", 0.30, 0.10, 0.50),
        ("PROLFI", 0.28, 0.20, 0.35),
        ("PROLFG", 0.22, 0.15, 0.30),
        ("PROLFF", 0.10, 0.05, 0.15),
        ("PROSTI", 0.18, 0.145, 0.220),
        ("PROSTG", 0.11, 0.090, 0.140),
        ("PROSTF", 0.06, 0.040, 0.080),
        ("PRORTI", 0.14, 0.1296, 0.1584),
        ("PRORTG", 0.12, 0.1071, 0.1309),
        ("PRORTF", 0.06, 0.0540, 0.0660),
        ("PROSHI", 0.21, 0.189, 0.231),
        ("PROSHG", 0.15, 0.135, 0.165),
        ("PROSHF", 0.11, 0.099, 0.121),
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
        "--bounds-id", BOUNDS_ID, "--notes", "v26 Maximum scope bounds with tight SDUL/SLOC, PLDP, PLWT, LFMAX, SFDUR, PODUR, SETMAX, SRMAX"
    ], cwd=ROOT, check=True)
    print(f"Frozen bounds prepared & registered: {BOUNDS_ID}")


def build_and_launch():
    # Make sure 9-layer bundles are up to date
    sys.path.insert(0, str(ROOT / "tools/experiments"))
    import clean_build_9layer_bundles_20260822
    clean_build_9layer_bundles_20260822.main()

    prepare_v26_frozen_bounds()

    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)

    design_path = ROOT / "configs/runs" / f"{CASE_NAME}.json"
    design_content = {
        "schema_version": 1,
        "design_id": CASE_NAME,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "v26 Maximum Scope Calibration with Tight SDUL/SLOC and Full Root/Canopy Dynamics",
        "bounds_id": BOUNDS_ID,
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "initial_condition_policy": "Pure measured FileX IC values with 9-layer 0-30cm plow soil",
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
                "bundle_path": str(EXP_25_9L),
                "role": "calibration",
                "treatments": [2, 5, 10, 13]
            },
            {
                "season_id": "26SP",
                "experiment_code": "XXQL2601",
                "bundle_path": str(EXP_26_9L),
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
    print(f"   Building v26 Calibration Task: {CASE_NAME}")
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
    print(f"\nv26 Maximum Scope Calibration completed successfully!")


if __name__ == "__main__":
    build_and_launch()
