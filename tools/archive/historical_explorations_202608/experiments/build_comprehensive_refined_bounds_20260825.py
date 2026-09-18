"""Build Comprehensive Refined Bounds Proposal based on Phase 2 Boundary Hit Audit.

Improvements:
1. Phenology & Harvest: Broaden lower bounds for EM-FL, FL-SD, FL-SH, PODUR, PL-EM, JU-R0, LNGSH, THRSH
   to match continuous eggplant fruit setting and multi-harvest dynamics.
2. Source-Sink & Biomass: Broaden upper bounds for XFRT (0.80), FINREF (350), SIZREF (450), SLAVR (280),
   PHTMAX (95), PARMAX (55), RWUMX (0.12).
3. Temperature Cardinals: Adjust stages 1-3 to wider realistic ranges while strictly enforcing:
   - TO11.upper <= TO21.lower
   - TO12.upper <= TO22.lower
   - TO22.upper <= TM2.lower
   - TO13.upper <= TO23.lower
   - TO23.upper <= TM3.lower
4. Developmental Stages: XMAGE [10.0, 48.0], XFPHT [48.5, 75.0] strictly enforcing XMAGE.upper <= XFPHT.lower.
5. Nitrogen & Soil: Include full active nitrogen stress and uptake parameters (RTNO3, RTNH4, NSTFAC, NMOBMX,
   NVSMOB, NRCVR, LNREF, NSLOPE, NSLA, SOIL_SLPF).
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
PHASE3_BEST_PARAMS = ROOT / "workspace/runs/calib_25sp_nresp_phase3_20260825/deterministic_best_base/best_params.csv"

BOUNDS_ID = "eggplant_calib_refined_comprehensive_20260825"
PROPOSAL_CSV = ROOT / f"data/parameter_registry/bounds_proposals/{BOUNDS_ID}.csv"


REFINED_BOUNDS = {
    # 1. Phenology & Harvest (Lower Bound Fixes)
    "EM-FL": (18.0, 48.0, 25.0),
    "FL-SD": (6.0, 30.0, 10.0),
    "FL-SH": (3.0, 20.0, 5.0),
    "PODUR": (8.0, 45.0, 15.0),
    "PL-EM": (3.0, 12.0, 5.0),
    "JU-R0": (1.0, 20.0, 2.0),
    "LNGSH": (20.0, 48.8, 29.2),
    "THRSH": (3.0, 15.0, 6.0),
    "EM-V1": (35.0, 42.0, 38.0),
    "PM09": (0.80, 0.999, 0.95),

    # 2. Photosynthesis & Canopy
    "KCAN": (0.35, 0.85, 0.45),
    "KC_SLOPE": (0.005, 0.20, 0.015),
    "PHTMAX": (45.0, 95.0, 75.0),
    "PARMAX": (35.0, 58.0, 48.0),
    "LFANGB": (1.0, 3.5, 1.8),
    "SLAVR": (120.0, 280.0, 200.0),
    "SLAMIN": (120.0, 450.0, 220.0),
    "SLAMAX": (250.0, 800.0, 480.0),
    "SLAREF": (180.0, 550.0, 350.0),

    # 3. Source-Sink & Biomass Allocation (Upper Bound Fixes)
    "XFRT": (0.40, 0.82, 0.72),
    "FINREF": (160.0, 360.0, 280.0),
    "SIZREF": (220.0, 480.0, 350.0),
    "CMOBMX": (0.01, 0.20, 0.12),
    "FRLFF": (0.15, 0.50, 0.22),
    "FRSTMF": (0.18, 0.68, 0.30),
    "RHGHT": (0.30, 1.30, 0.50),
    "RWDTH": (0.60, 2.00, 1.00),
    "VSSINK": (1.20, 7.50, 2.80),

    # 4. Root & Water
    "RWUMX": (0.02, 0.15, 0.08),
    "RTEXF": (0.15, 0.80, 0.30),
    "DSWBAR": (5.0, 30.0, 10.0),
    "PORMIN": (0.005, 0.060, 0.010),
    "XFINT": (0.12, 0.45, 0.25),

    # 5. Photoperiod
    "CSDL": (11.5, 13.5, 12.66),
    "PPSEN": (0.0, 0.30, 0.0),

    # 6. Senescence
    "SENDAY": (0.001, 0.100, 0.025),
    "SENRTE": (0.20, 2.80, 0.60),

    # 7. Developmental Stage Durations (Strictly XMAGE.upper <= XFPHT.lower)
    "XMAGE": (10.0, 48.0, 40.0),
    "XFPHT": (48.5, 75.0, 52.0),

    # 8. Temperature Stages 1-3 (Strict Monotonic Non-Overlapping Cardinal Constraints)
    # Stage 1: Emergence to Flower
    "TB1": (4.0, 10.0, 7.0),
    "TO11": (20.0, 28.0, 27.5),
    "TO21": (28.5, 34.0, 32.0),
    "TM1": (36.0, 48.0, 44.0),

    # Stage 2: Flower to Fruit/Seed
    "TB2": (5.0, 11.0, 9.0),
    "TO12": (16.0, 27.0, 24.0),
    "TO22": (27.5, 35.0, 33.0),
    "TM2": (36.0, 48.0, 45.0),

    # Stage 3: Fruit Growth & Maturity
    "TB3": (6.0, 12.0, 10.0),
    "TO13": (16.0, 27.0, 24.0),
    "TO23": (27.5, 35.0, 33.0),
    "TM3": (36.0, 48.0, 44.0),

    # 9. Nitrogen Uptake, Stress & Reallocation Parameters
    "RTNO3": (0.003, 0.035, 0.015),
    "RTNH4": (0.003, 0.035, 0.015),
    "NREXP": (0.30, 0.95, 0.77),
    "NRMIN": (0.30, 0.95, 0.90),
    "NSTFAC": (0.10, 0.95, 0.85),
    "NMOBMX": (0.02, 0.35, 0.05),
    "NVSMOB": (0.05, 0.40, 0.15),
    "NRCVR": (0.15, 0.85, 0.25),
    "LNREF": (3.0, 6.0, 4.6),
    "NSLOPE": (0.05, 0.60, 0.20),
    "NSLA": (0.50, 3.00, 1.50),
    "SOIL_SLPF": (0.75, 1.00, 0.95),

    # Organ protein dynamics
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
}


def build_refined_proposal():
    df_p2 = pd.read_csv(PHASE2_FROZEN)
    
    # Load previous best values from Phase 2 and Phase 3
    best_vals = {}
    if PHASE2_BEST_PARAMS.exists():
        df_p2_best = pd.read_csv(PHASE2_BEST_PARAMS)
        best_vals.update(dict(zip(df_p2_best["name"].str.lower(), df_p2_best["value"])))
    if PHASE3_BEST_PARAMS.exists():
        df_p3_best = pd.read_csv(PHASE3_BEST_PARAMS)
        best_vals.update(dict(zip(df_p3_best["name"].str.lower(), df_p3_best["value"])))

    rows = []
    n_active = 0
    for idx, r in df_p2.iterrows():
        pname_orig = r["name"]
        pname = str(pname_orig).upper()
        pargp = r["pargp"]
        loc = r["location"]
        fl = r["file"]
        cult = r["cultivar"]
        eco = r["ecotype"]
        mode = r["mode"]
        
        curr_val = best_vals.get(pname_orig.lower(), r["init"])
        try:
            curr_val = float(curr_val)
        except:
            curr_val = float(r["init"])

        if pname in REFINED_BOUNDS:
            lb, ub, default_init = REFINED_BOUNDS[pname]
            if pname in PHYSICAL_BOUNDS:
                phys_lb, phys_ub = PHYSICAL_BOUNDS[pname]
                lb = max(lb, phys_lb)
                ub = min(ub, phys_ub)
            
            init = max(lb, min(ub, curr_val))
            status = "active"
            n_active += 1
        elif str(pname_orig).startswith("soil_sbdm_"):
            init = curr_val
            lb = round(max(1.10, curr_val - 0.05), 4)
            ub = round(min(1.70, curr_val + 0.05), 4)
            status = "active"
            n_active += 1
        elif pname == "FL-VS":
            # FL-VS is always fixed at 100.0 per project convention
            init = 100.0
            lb = 100.0
            ub = 100.0
            status = "fixed"
        else:
            # Check if active in Phase 2
            if r["status"] == "active":
                lb = float(r["lower"])
                ub = float(r["upper"])
                init = max(lb, min(ub, curr_val))
                status = "active"
                n_active += 1
            else:
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
    print(f"Generated Comprehensive Refined Bounds Proposal with {n_active} active parameters: {PROPOSAL_CSV}")

    # Freeze bounds via tools/freeze_bounds.py
    cmd_freeze = [
        sys.executable, str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(PROPOSAL_CSV),
        "--crop", "eggplant",
        "--bounds-id", BOUNDS_ID,
        "--notes", "Comprehensive boundary refinement resolving Phase 2 boundary hits and integrating full nitrogen dynamics"
    ]
    subprocess.run(cmd_freeze, cwd=str(ROOT), check=True)
    print(f"Successfully frozen Comprehensive Refined bounds: {BOUNDS_ID}")


if __name__ == "__main__":
    build_refined_proposal()
