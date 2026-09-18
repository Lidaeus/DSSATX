"""Build and audit v26 Comprehensive Frozen Bounds with maximum physical & genetic parameters opened."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BOUNDS_ID = "eggplant_e02_v26_maximum_scope_full_root_20260822"
BOUNDS_SRC = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v25_full_root_state_9layer_20260822.csv"


def main():
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

    # 13. Open Additional Key Active Parameters:
    # Canopy architecture & light: KDIF, LFANGB
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
        "--bounds-id", BOUNDS_ID, "--notes", "v26 Maximum scope bounds with PLDP, PLWT, LFMAX, SFDUR, PODUR, SETMAX, SRMAX"
    ], cwd=ROOT, check=True)

    # Audit active parameters
    df_frozen = pd.read_csv(frozen_csv)
    active_df = df_frozen[df_frozen["status"] == "active"]
    print("\n=======================================================")
    print(f"   v26 Frozen Bounds Audit: {BOUNDS_ID}")
    print(f"   Total Registered Parameters: {len(df_frozen)}")
    print(f"   Total Active Calibratable Parameters: {len(active_df)}")
    print("=======================================================")

    by_pargp = active_df.groupby("pargp").size()
    print("\n>>> Active Parameters Breakdown by Group (pargp) <<<")
    for pargp, cnt in by_pargp.items():
        print(f"  - {pargp:<15s}: {cnt:>3d} parameters")

    by_loc = active_df.groupby("location").size()
    print("\n>>> Active Parameters Breakdown by Location/File <<<")
    for loc, cnt in by_loc.items():
        print(f"  - {loc:<15s}: {cnt:>3d} parameters")

    print("\n>>> Full Active Parameter List <<<")
    for idx, row in active_df.iterrows():
        print(f"  {row['name']:<18s} | Init: {row['init']:>8.4f} | Lower: {row['lower']:>8.4f} | Upper: {row['upper']:>8.4f} | {row['location']:<6s} | {row['pargp']}")


if __name__ == "__main__":
    main()
