"""Build Phase 2 Parameter Bounds Proposal based on Phase 1 Hit-Bound Audit and Eggplant Physiology.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.param_registry import PHYSICAL_BOUNDS

PHASE1_FROZEN = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_calib_25sp_6treat_phase1_20260825.csv"
PHASE1_PAR_ITER5 = ROOT / "workspace/runs/calib_25sp_6treat_phase1_20260825/calib_25sp_6treat_phase1_20260825.5.par.csv"
PROPOSAL_CSV = ROOT / "data/parameter_registry/bounds_proposals/eggplant_calib_25sp_6treat_phase2_20260825.csv"
BOUNDS_ID = "eggplant_calib_25sp_6treat_phase2_20260825"


# Specific targeted adjustments for Phase 2 based on Phase 1 hits and crop physiology
TARGETED_BOUNDS = {
    # Phenology & Reproductive Development
    "EM-FL": (25.0, 48.0, 35.0),
    "FL-SH": (5.0, 22.0, 12.0),
    "FL-SD": (10.0, 30.0, 18.0),
    "PODUR": (15.0, 45.0, 25.0),
    "SFDUR": (20.0, 50.0, 35.0),
    "SDPDV": (80.0, 350.0, 180.0),
    "THRSH": (6.0, 12.0, 8.5),
    "WTFSD": (0.25, 0.70, 0.45),
    "WTPSD": (0.003, 0.010, 0.005),
    "PPSEN": (0.0, 0.25, 0.05),

    # Photosynthesis & Partitioning
    "XFRT": (0.35, 0.72, 0.52),
    "FRSTMF": (0.30, 0.68, 0.48),
    "FRLFF": (0.22, 0.50, 0.35),
    "KCAN": (0.45, 0.85, 0.65),
    "KDIF": (0.60, 1.00, 0.85),
    "SLAMIN": (150.0, 450.0, 220.0),
    "SLAMAX": (350.0, 850.0, 550.0),
    "SLAREF": (180.0, 400.0, 260.0),
    "VSSINK": (1.50, 7.50, 3.50),
    "PORPT": (0.15, 0.45, 0.28),
    "PORMIN": (0.005, 0.06, 0.02),
    "CMOBMX": (0.01, 0.12, 0.05),
    "TRIFL": (0.50, 1.00, 0.75),
    "RHGHT": (0.50, 1.30, 0.85),
    "RWDTH": (1.00, 2.00, 1.60),
    "XFINT": (0.12, 0.45, 0.28),
    "XMAGE": (12.0, 42.0, 25.0),
    "XFPHT": (43.0, 65.0, 50.0),
    "PL-EM": (5.0, 12.0, 8.0),
    "PM06": (0.25, 0.65, 0.45),
    "SETMAX": (0.15, 0.70, 0.40),
    "SHLAG": (0.05, 0.90, 0.30),
    "XFRMAX": (0.05, 0.60, 0.30),
    "SENRTE": (0.20, 2.50, 0.80),
    "TURSLA": (0.40, 2.50, 1.00),
    "NSLA": (0.50, 2.50, 1.50),

    # Temperature Cardinals (strictly non-overlapping: TB < TO1 < TO2 < TM)
    "TB1": (6.0, 11.0, 8.5),
    "TO11": (22.0, 27.5, 25.0),
    "TO21": (28.0, 34.0, 31.0),
    "TM1": (35.0, 44.0, 40.0),

    "TB2": (7.0, 11.0, 8.5),
    "TO12": (18.0, 27.5, 23.0),
    "TO22": (28.0, 33.0, 30.0),
    "TM2": (34.0, 45.0, 38.0),

    "TB3": (8.0, 12.0, 10.0),
    "TO13": (18.0, 27.5, 22.0),
    "TO23": (28.0, 33.5, 30.0),
    "TM3": (34.0, 46.0, 38.0),

    # Composition & Tissue Fractions
    "PROLFF": (0.03, 0.20, 0.08),
    "PROLFG": (0.12, 0.35, 0.22),
    "PROLFI": (0.15, 0.40, 0.26),
    "PROSHF": (0.08, 0.16, 0.11),
    "PROSHG": (0.11, 0.20, 0.15),
    "PROSHI": (0.15, 0.28, 0.21),
    "PROSTF": (0.03, 0.12, 0.06),
    "PROSTG": (0.07, 0.16, 0.11),
    "PROSTI": (0.12, 0.26, 0.18),
    "PRORTG": (0.09, 0.16, 0.12),
    "PRORTI": (0.11, 0.19, 0.15),
}


def build_proposal():
    df_p1 = pd.read_csv(PHASE1_FROZEN)
    
    # Load calibrated values from iteration 5 best member
    best_vals = {}
    if PHASE1_PAR_ITER5.exists():
        df_iter5 = pd.read_csv(PHASE1_PAR_ITER5, index_col=0)
        target_real = "20" if "20" in df_iter5.index else ("base" if "base" in df_iter5.index else df_iter5.index[0])
        best_vals = df_iter5.loc[target_real].to_dict()
        print(f"Loaded calibrated values from Phase 1 Iteration 5 realization '{target_real}'")

    rows = []
    n_adjusted = 0
    for idx, r in df_p1.iterrows():
        pname = str(r["name"]).upper()
        pname_orig = r["name"]
        status = r["status"]
        lb = float(r["lower"])
        ub = float(r["upper"])
        init = float(r["init"])
        pargp = r["pargp"]
        loc = r["location"]
        fl = r["file"]
        cult = r["cultivar"]
        eco = r["ecotype"]
        mode = r["mode"]

        if status == "active":
            if pname in TARGETED_BOUNDS:
                new_lb, new_ub, default_init = TARGETED_BOUNDS[pname]
                if pname in PHYSICAL_BOUNDS:
                    phys_lb, phys_ub = PHYSICAL_BOUNDS[pname]
                    new_lb = max(new_lb, phys_lb)
                    new_ub = min(new_ub, phys_ub)
                
                c_val = best_vals.get(pname_orig, best_vals.get(pname, default_init))
                try:
                    c_val = float(c_val)
                    new_init = max(new_lb, min(new_ub, c_val))
                except:
                    new_init = default_init

                lb = new_lb
                ub = new_ub
                init = new_init
                n_adjusted += 1
            else:
                if pname_orig in best_vals:
                    c_val = float(best_vals[pname_orig])
                    init = max(lb, min(ub, c_val))

        rows.append({
            "name": pname_orig, "init": init, "lower": lb, "upper": ub,
            "status": status, "pargp": pargp, "location": loc, "file": fl,
            "cultivar": cult, "ecotype": eco, "mode": mode
        })

    df_prop = pd.DataFrame(rows)
    PROPOSAL_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_prop.to_csv(PROPOSAL_CSV, index=False)
    print(f"Generated Phase 2 bounds proposal with {n_adjusted} adjusted parameter ranges: {PROPOSAL_CSV}")

    # Freeze bounds via tools/freeze_bounds.py
    cmd_freeze = [
        sys.executable, str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(PROPOSAL_CSV),
        "--crop", "eggplant",
        "--bounds-id", BOUNDS_ID,
        "--notes", "Phase 2: Expanded bounds based on Phase 1 hits and multi-harvest eggplant physiology"
    ]
    subprocess.run(cmd_freeze, cwd=str(ROOT), check=True)
    print(f"Successfully frozen Phase 2 bounds: {BOUNDS_ID}")


if __name__ == "__main__":
    build_proposal()
