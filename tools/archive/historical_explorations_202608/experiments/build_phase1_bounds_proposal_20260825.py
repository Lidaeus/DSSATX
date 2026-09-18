"""Build and freeze Phase 1 Bounds Proposal for 25SP 6-Treatment Calibration:
- Focus on ~70 active crop genetic parameters (Phenology, Photosynthesis, Allocation, Canopy, Root, Senescence, Temperature)
- Set initial values based on historical optimal balanced parameters (LFMAX=1.70, XFRT=0.74, PODUR=18.0, PGEFF=0.055, etc.)
- Strict physiological boundaries
- For fixed parameters, ensure lower == init == upper
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
BOUNDS_SRC = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v26_maximum_scope_full_root_20260822.csv"
OUT_CSV = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_calib_25sp_6treat_phase1_20260825.csv"
OUT_YAML = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_calib_25sp_6treat_phase1_20260825.yaml"


def main():
    df = pd.read_csv(BOUNDS_SRC, encoding="utf-8-sig")

    # 1. Ensure initial values and bounds are physiologically centered
    # LFMAX: locked to [1.45, 1.75] with init 1.70
    idx_lfmax = df.index[df["name"].str.upper() == "LFMAX"].tolist()
    if idx_lfmax:
        df.loc[idx_lfmax[0], ["init", "lower", "upper", "status"]] = [1.70, 1.45, 1.75, "active"]

    # XFRT: locked to [0.70, 0.76] with init 0.74
    idx_xfrt = df.index[df["name"].str.upper() == "XFRT"].tolist()
    if idx_xfrt:
        df.loc[idx_xfrt[0], ["init", "lower", "upper", "status"]] = [0.740, 0.700, 0.760, "active"]

    # PODUR: init 18.0, lower 15.0, upper 24.0
    idx_podur = df.index[df["name"].str.upper() == "PODUR"].tolist()
    if idx_podur:
        df.loc[idx_podur[0], ["init", "lower", "upper", "status"]] = [18.0, 15.0, 24.0, "active"]

    # PGEFF: init 0.055, lower 0.040, upper 0.070
    idx_pgeff = df.index[df["name"].str.upper() == "PGEFF"].tolist()
    if idx_pgeff:
        df.loc[idx_pgeff[0], ["init", "lower", "upper", "status"]] = [0.055, 0.040, 0.070, "active"]

    # Fix soil parameters that are already calibrated in SOIL.SOL (to avoid soil disturbance during genetic calibration)
    soil_params = df[df["location"] == "SOIL"]["name"].tolist()
    for sp in soil_params:
        idx_sp = df.index[df["name"] == sp].tolist()
        if idx_sp:
            df.loc[idx_sp[0], "status"] = "fixed"

    # Fix IC parameters that are already set in TMX
    ic_params = ["PLWT", "PLDP"]
    for ip in ic_params:
        idx_ip = df.index[df["name"].str.upper() == ip].tolist()
        if idx_ip:
            df.loc[idx_ip[0], "status"] = "fixed"

    # Fix Nitrogen response parameters for Phase 1 (they will be calibrated in Phase 3)
    n_params = ["nrexp", "nrmin", "swbar_rec", "yswbar_mid", "nmobmx", "nrcvr", "nslope", "nstfac", "nvsmob"]
    for np_name in n_params:
        idx_np = df.index[df["name"].str.lower() == np_name.lower()].tolist()
        if idx_np:
            df.loc[idx_np[0], "status"] = "fixed"

    # Enforce lower == init == upper for all fixed parameters
    for i, r in df.iterrows():
        if r["status"] == "fixed":
            init_v = r["init"]
            df.at[i, "lower"] = init_v
            df.at[i, "upper"] = init_v

    active_count = len(df[df["status"] == "active"])
    print(f"Total active parameters for Phase 1: {active_count}")

    # Save Frozen Bounds CSV
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    # Save metadata YAML
    meta = {
        "bounds_id": "eggplant_calib_25sp_6treat_phase1_20260825",
        "crop": "eggplant",
        "parent_bounds_id": "eggplant_e02_v26_maximum_scope_full_root_20260822",
        "active_parameters": int(active_count),
        "target_season": "25SP (6 treatments: W3N3, W3N2, W3N1, W1N3, W1N2, W1N1)",
        "notes": "Phase 1 Crop Genetic Parameter Calibration under Scheme 5 10-layer Soil & Cleaned Soil N"
    }
    with open(OUT_YAML, "w", encoding="utf-8") as f:
        yaml.dump(meta, f, sort_keys=False)

    print(f"Frozen bounds saved to: {OUT_CSV}")


if __name__ == "__main__":
    main()
