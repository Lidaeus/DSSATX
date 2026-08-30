"""v27 Formal Calibration Launcher:
- 5-Layer 0-60cm single deep plow soil structure.
- Tight measured constraints for SDUL (field capacity) and SLOC (organic carbon).
- Dynamic transplant state: PLWT [8.0, 11.0] g/plant, PLDP [7.0, 10.0] cm.
- Enhanced photosynthesis: LFMAX [1.55, 1.85], PGEFF [0.040, 0.070], SOIL_SLPF [0.92, 1.00].
- Strict vegetative maintenance constraints: XFRT [0.70, 0.76], PODUR [16.0, 19.5], SFDUR [21.0, 26.0].
- Open multi-harvest fruit set smoothing: SDPDV [160.0, 350.0], SETMAX [0.35, 0.70], SRMAX [0.35, 0.70].
- Mineralization factor: SOIL_SLNF [2.90, 3.50].
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
CASE_NAME = "e02_v27_formal_0_60cm_200x5_20260822"
RUN_DIR = ROOT / "workspace/runs" / CASE_NAME
BOUNDS_ID = "eggplant_e02_v27_formal_0_60cm_20260822"

N_REALS = 200
NOPTMAX = 5
N_AGENTS = 6
SEED = 20260822

EXP_25_5L = ROOT / "data/user/experiments/xxql2501_rootzone_5layer_60cm_20260822"
EXP_26_5L = ROOT / "data/user/experiments/xxql2601_rootzone_5layer_60cm_20260822"

BOUNDS_SRC = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v25_full_root_state_9layer_20260822.csv"


def prepare_v27_frozen_bounds():
    frame = pd.read_csv(BOUNDS_SRC, encoding="utf-8-sig")

    # 1. Update/Add PLDP (Planting Depth)
    idx_pldp = frame.index[frame["name"].str.upper() == "PLDP"].tolist()
    if idx_pldp:
        frame.loc[idx_pldp[0], ["init", "lower", "upper", "status", "location"]] = [8.0, 7.0, 10.0, "active", "IC"]
    else:
        new_row = {
            "name": "PLDP", "init": 8.0, "lower": 7.0, "upper": 10.0,
            "status": "active", "pargp": "ic", "location": "IC",
            "file": "XXQL2501.TMX", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
        }
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # 2. Update PLWT (Transplant Biomass)
    idx_plwt = frame.index[frame["name"].str.upper() == "PLWT"].tolist()
    if idx_plwt:
        frame.loc[idx_plwt[0], ["init", "lower", "upper", "status", "location"]] = [9.5, 8.0, 11.0, "active", "IC"]

    # 3. Update RTDEPI (Initial Root Depth)
    idx_rtdepi = frame.index[frame["name"].str.upper() == "RTDEPI"].tolist()
    if idx_rtdepi:
        frame.loc[idx_rtdepi[0], ["init", "lower", "upper", "status"]] = [16.0, 14.0, 20.0, "active"]

    # 4. Update LFMAX (Max Leaf Photosynthesis)
    idx_lfmax = frame.index[frame["name"].str.upper() == "LFMAX"].tolist()
    if idx_lfmax:
        frame.loc[idx_lfmax[0], ["init", "lower", "upper", "status"]] = [1.70, 1.55, 1.85, "active"]

    # 5. Update PGEFF (Gross Photosynthetic Efficiency)
    idx_pgeff = frame.index[frame["name"].str.upper() == "PGEFF"].tolist()
    if idx_pgeff:
        frame.loc[idx_pgeff[0], ["init", "lower", "upper", "status"]] = [0.055, 0.040, 0.070, "active"]
    else:
        new_row = {
            "name": "PGEFF", "init": 0.055, "lower": 0.040, "upper": 0.070,
            "status": "active", "pargp": "species", "location": "SPE",
            "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
        }
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # 6. Update SOIL_SLPF (Soil Fertility Factor)
    idx_slpf = frame.index[frame["name"].str.upper() == "SOIL_SLPF"].tolist()
    if idx_slpf:
        frame.loc[idx_slpf[0], ["init", "lower", "upper", "status"]] = [0.96, 0.92, 1.00, "active"]
    else:
        new_row = {
            "name": "SOIL_SLPF", "init": 0.96, "lower": 0.92, "upper": 1.00,
            "status": "active", "pargp": "soil", "location": "SOIL",
            "file": "SOIL.SOL", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
        }
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # 7. Strict XFRT (Fruit Partitioning: Keep in [0.70, 0.76])
    idx_xfrt = frame.index[frame["name"].str.upper() == "XFRT"].tolist()
    if idx_xfrt:
        frame.loc[idx_xfrt[0], ["init", "lower", "upper", "status"]] = [0.74, 0.70, 0.76, "active"]

    # 8. Strict PODUR (Pod/Fruit Growth Duration: Keep in [16.0, 19.5])
    idx_podur = frame.index[frame["name"].str.upper() == "PODUR"].tolist()
    if idx_podur:
        frame.loc[idx_podur[0], ["init", "lower", "upper", "status"]] = [18.0, 16.0, 19.5, "active"]

    # 9. SFDUR (Seed/Fruit Addition Duration)
    idx_sfdur = frame.index[frame["name"].str.upper() == "SFDUR"].tolist()
    if idx_sfdur:
        frame.loc[idx_sfdur[0], ["init", "lower", "upper", "status"]] = [23.5, 21.0, 26.0, "active"]

    # 10. Open SDPDV (Pod/Fruit Addition Potential per Day)
    idx_sdpdv = frame.index[frame["name"].str.upper() == "SDPDV"].tolist()
    if idx_sdpdv:
        frame.loc[idx_sdpdv[0], ["init", "lower", "upper", "status"]] = [220.0, 160.0, 350.0, "active"]

    # 11. Open SETMAX (Maximum Fruit Set Fraction)
    idx_setmax = frame.index[frame["name"].str.upper() == "SETMAX"].tolist()
    if idx_setmax:
        frame.loc[idx_setmax[0], ["init", "lower", "upper", "status"]] = [0.45, 0.35, 0.70, "active"]
    else:
        new_row = {
            "name": "SETMAX", "init": 0.45, "lower": 0.35, "upper": 0.70,
            "status": "active", "pargp": "species", "location": "SPE",
            "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
        }
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # 12. Open SRMAX (Maximum Seed/Fruit Addition Rate)
    idx_srmax = frame.index[frame["name"].str.upper() == "SRMAX"].tolist()
    if idx_srmax:
        frame.loc[idx_srmax[0], ["init", "lower", "upper", "status"]] = [0.45, 0.35, 0.70, "active"]
    else:
        new_row = {
            "name": "SRMAX", "init": 0.45, "lower": 0.35, "upper": 0.70,
            "status": "active", "pargp": "species", "location": "SPE",
            "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001", "mode": "eggplant_stage2"
        }
        frame = pd.concat([frame, pd.DataFrame([new_row])], ignore_index=True)

    # 13. SOIL_SLNF (Mineralization Factor)
    idx_slnf = frame.index[frame["name"].str.upper() == "SOIL_SLNF"].tolist()
    if idx_slnf:
        frame.loc[idx_slnf[0], ["init", "lower", "upper", "status"]] = [3.20, 2.90, 3.50, "active"]

    # 14. 5-Layer Field Capacity (SOIL_SDUL) around measured values (+/- 3%)
    # Measured SDUL for 5 layers: 0.320, 0.330, 0.340, 0.305, 0.290
    sdul_measured_5l = [
        ("SOIL_SDUL_01", 0.320, 0.310, 0.330),
        ("SOIL_SDUL_02", 0.330, 0.320, 0.340),
        ("SOIL_SDUL_03", 0.340, 0.330, 0.350),
        ("SOIL_SDUL_04", 0.305, 0.295, 0.315),
        ("SOIL_SDUL_05", 0.290, 0.280, 0.300),
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

    # Disable extra SDUL layers (> 5) if present
    for extra_idx in range(6, 14):
        sname = f"SOIL_SDUL_{extra_idx:02d}"
        idx_extra = frame.index[frame["name"].str.upper() == sname].tolist()
        if idx_extra:
            frame.loc[idx_extra[0], "status"] = "disabled"

    # 15. 5-Layer Organic Carbon (SOIL_SLOC) around measured values (+/- 4%)
    # Measured SLOC for top 3 layers: 0.650, 0.180, 0.100
    sloc_measured_5l = [
        ("SOIL_SLOC_01", 0.650, 0.620, 0.680),
        ("SOIL_SLOC_02", 0.180, 0.170, 0.190),
        ("SOIL_SLOC_03", 0.100, 0.090, 0.110),
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

    # Disable extra SLOC layers (> 3) if present
    for extra_idx in range(4, 14):
        sname = f"SOIL_SLOC_{extra_idx:02d}"
        idx_extra = frame.index[frame["name"].str.upper() == sname].tolist()
        if idx_extra:
            frame.loc[idx_extra[0], "status"] = "disabled"

    # 16. Key Physiological, Canopy & Root Parameters
    for pname, init_v, low_v, up_v in [
        ("KDIF", 0.75, 0.55, 0.95),
        ("LFANGB", 1.80, 1.20, 2.50),
        ("SLAVR", 280.0, 180.0, 310.0),
        ("SIZLF", 315.0, 270.0, 340.0),
        ("SLAMAX", 650.0, 450.0, 850.0),
        ("SLAMIN", 350.0, 220.0, 480.0),
        ("TURSLA", 1.20, 0.60, 1.80),
        ("NSLA", 1.00, 0.60, 1.40),
        ("FRLFMX", 0.70, 0.55, 0.85),
        ("DSWBAR", 20.0, 12.0, 28.0),
        ("XFRMAX", 0.25, 0.10, 0.40),
        ("SHLAG", 0.40, 0.15, 0.65),
        ("CMOBMX", 0.030, 0.015, 0.045),
        ("CADSTF", 0.60, 0.40, 0.80),
        ("CADPR1", 0.30, 0.15, 0.45),
        ("RTNO3", 0.0145, 0.010, 0.015),
        ("RTNH4", 0.0145, 0.010, 0.015),
        ("RWUMX", 0.045, 0.035, 0.065),
        ("PROLFI", 0.28, 0.22, 0.34),
        ("PROLFG", 0.22, 0.16, 0.28),
        ("PROLFF", 0.10, 0.06, 0.14),
        ("PROSTI", 0.18, 0.145, 0.215),
        ("PROSTG", 0.11, 0.090, 0.135),
        ("PROSTF", 0.06, 0.045, 0.075),
        ("PRORTI", 0.14, 0.130, 0.155),
        ("PRORTG", 0.12, 0.108, 0.130),
        ("PRORTF", 0.06, 0.054, 0.066),
        ("PROSHI", 0.21, 0.190, 0.230),
        ("PROSHG", 0.15, 0.135, 0.165),
        ("PROSHF", 0.11, 0.100, 0.120),
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
        "--bounds-id", BOUNDS_ID, "--notes", "v27 Formal 0-60cm deep plow bounds with tight SDUL/SLOC, strict XFRT/PODUR, open SDPDV/SETMAX/SRMAX, and full root state"
    ], cwd=ROOT, check=True)
    print(f"Frozen bounds prepared & registered: {BOUNDS_ID}")


def build_and_launch():
    # Make sure 5-layer 0-60cm bundles are cleanly up to date
    sys.path.insert(0, str(ROOT / "tools/experiments"))
    import clean_build_5layer_bundles_20260822
    clean_build_5layer_bundles_20260822.main()

    prepare_v27_frozen_bounds()

    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)

    design_path = ROOT / "configs/runs" / f"{CASE_NAME}.json"
    design_content = {
        "schema_version": 1,
        "design_id": CASE_NAME,
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "v27 Formal 0-60cm Deep Plow Joint Calibration with Full Root/Canopy Dynamics",
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
    print(f"   Building v27 Calibration Task: {CASE_NAME}")
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
    print(f"\nv27 Formal 0-60cm Calibration completed successfully!")


if __name__ == "__main__":
    build_and_launch()
