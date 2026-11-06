"""Build Phase 3 Nitrogen Stress, Response, and Reallocation Parameter Bounds Proposal.

Setup:
- Anchor all general crop genetic parameters (phenology, temperature cardinals, base morphology) 
  at Phase 2 best posterior values.
- Unfreeze and activate all Nitrogen Stress, Uptake, Mobilization, Recovery, Photosynthesis response,
  and Organ Protein parameters.
- Target treatments: 25SP N0 zero nitrogen treatments (TRNO 5 W3N0, TRNO 13 W1N0) + High/Med N controls (TRNO 2 W3N3, TRNO 10 W1N3).
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

PHASE2_FROZEN = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_calib_25sp_6treat_phase2_20260825.csv"
PHASE2_BEST_PARAMS = ROOT / "workspace/runs/calib_25sp_6treat_phase2_20260825/deterministic_best_base/best_params.csv"
PROPOSAL_CSV = ROOT / "data/parameter_registry/bounds_proposals/eggplant_calib_25sp_nresp_phase3_20260825.csv"
BOUNDS_ID = "eggplant_calib_25sp_nresp_phase3_20260825"


# Nitrogen-specific active parameter ranges
NITROGEN_ACTIVE_BOUNDS = {
    # N uptake & extraction
    "RTNO3": (0.003, 0.035, 0.015),
    "RTNH4": (0.003, 0.035, 0.015),
    "NREXP": (0.30, 0.95, 0.65),
    "NRMIN": (0.30, 0.95, 0.70),

    # N stress & mobilization
    "NSTFAC": (0.10, 0.90, 0.45),
    "NMOBMX": (0.02, 0.35, 0.12),
    "NVSMOB": (0.05, 0.40, 0.22),
    "NRCVR": (0.15, 0.85, 0.45),

    # N photosynthesis response & leaf N
    "LNREF": (3.0, 6.0, 4.8),
    "NSLOPE": (0.05, 0.60, 0.18),
    "NSLA": (0.50, 3.00, 1.50),

    # Soil profile fertility multiplier
    "SOIL_SLPF": (0.75, 1.00, 0.95),

    # Organ protein dynamics (Critical for N partitioning and demand)
    "PROLFI": (0.15, 0.40, 0.26),
    "PROLFG": (0.10, 0.35, 0.22),
    "PROLFF": (0.03, 0.18, 0.08),

    "PROSTI": (0.08, 0.25, 0.18),
    "PROSTG": (0.04, 0.16, 0.11),
    "PROSTF": (0.02, 0.10, 0.06),

    "PRORTI": (0.08, 0.22, 0.15),
    "PRORTG": (0.05, 0.16, 0.12),
    "PRORTF": (0.03, 0.09, 0.06),

    "PROSHI": (0.10, 0.30, 0.21),
    "PROSHG": (0.06, 0.20, 0.15),
    "PROSHF": (0.04, 0.15, 0.11),

    # Key interactive parameters
    "XFINT": (0.15, 0.45, 0.28),
    "XFRT": (0.40, 0.70, 0.55),
    "SENRTE": (0.20, 2.50, 0.80),
    "SENDAY": (0.001, 0.10, 0.025),
    "CMOBMX": (0.01, 0.15, 0.05),
}


def build_proposal():
    df_p2 = pd.read_csv(PHASE2_FROZEN)
    
    best_vals = {}
    if PHASE2_BEST_PARAMS.exists():
        df_best = pd.read_csv(PHASE2_BEST_PARAMS)
        best_vals = dict(zip(df_best["name"].str.lower(), df_best["value"]))
        print(f"Loaded Phase 2 best posterior parameters ({len(best_vals)} values)")

    rows = []
    n_activated_n = 0
    for idx, r in df_p2.iterrows():
        pname_orig = r["name"]
        pname = str(pname_orig).upper()
        pargp = r["pargp"]
        loc = r["location"]
        fl = r["file"]
        cult = r["cultivar"]
        eco = r["ecotype"]
        mode = r["mode"]
        
        # Get anchored value from Phase 2 best
        curr_val = best_vals.get(pname_orig.lower(), r["init"])
        try:
            curr_val = float(curr_val)
        except:
            curr_val = float(r["init"])

        if pname in NITROGEN_ACTIVE_BOUNDS:
            # Active in Phase 3
            lb, ub, default_init = NITROGEN_ACTIVE_BOUNDS[pname]
            if pname in PHYSICAL_BOUNDS:
                phys_lb, phys_ub = PHYSICAL_BOUNDS[pname]
                lb = max(lb, phys_lb)
                ub = min(ub, phys_ub)
            
            init = max(lb, min(ub, curr_val))
            status = "active"
            n_activated_n += 1
        elif str(pname_orig).startswith("soil_sbdm_"):
            # Soil bulk density layers: retain active with narrow search range
            init = curr_val
            lb = round(max(1.10, curr_val - 0.04), 4)
            ub = round(min(1.70, curr_val + 0.04), 4)
            status = "active"
        else:
            # Fixed at Phase 2 best value
            lb = curr_val
            ub = curr_val
            init = curr_val
            status = "fixed"

        rows.append({
            "name": pname_orig, "init": init, "lower": lb, "upper": ub,
            "status": status, "pargp": pargp, "location": loc, "file": fl,
            "cultivar": cult, "ecotype": eco, "mode": mode
        })

    df_prop = pd.DataFrame(rows)
    PROPOSAL_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_prop.to_csv(PROPOSAL_CSV, index=False)
    print(f"Generated Phase 3 bounds proposal with {n_activated_n} active Nitrogen response/reallocation parameters: {PROPOSAL_CSV}")

    # Freeze bounds via tools/freeze_bounds.py
    cmd_freeze = [
        sys.executable, str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(PROPOSAL_CSV),
        "--crop", "eggplant",
        "--bounds-id", BOUNDS_ID,
        "--notes", "Phase 3: Unfreeze N stress, response, uptake, and reallocation parameters with 25SP N0 treatments"
    ]
    subprocess.run(cmd_freeze, cwd=str(ROOT), check=True)
    print(f"Successfully frozen Phase 3 bounds: {BOUNDS_ID}")


if __name__ == "__main__":
    build_proposal()
