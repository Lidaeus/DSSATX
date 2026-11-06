#!/usr/bin/env python3
"""apply_7l_merged_bundle_20260918.py — 
Implement 7-layer merged soil profile (30-100cm unified) and weighted initial conditions for 25SP:
1. Modifies XXSL2501 in data/raw/soil/SOIL.SOL to 7 layers:
   - 2, 4, 15, 30, 100, 140, 180 cm
   - 30-100cm (SLB=100) has mass/thickness-weighted parameters and SRGF=0.850
   - 140cm and 180cm have SRGF=0.000
2. Modifies XXQL2501.TMX Section @C ICBL to 7 layers:
   - 2, 4, 15, 30, 100, 140, 180 cm
   - 30-100cm has thickness-weighted SH2O and mass-weighted SNH4, SNO3
3. Syncs to:
   - data/user/experiments/xxql2501_v20260917_refresh
   - data/user/experiments/XXQL2501
   - data/user/experiments/xxql2501_unified_20260914
   - C:\\DSSAT48\\Soil\\SOIL.SOL
4. Executes sanity check simulation.
"""

import os
import sys
import shutil
import subprocess
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
RAW_SOL = PROJECT_ROOT / "data" / "raw" / "soil" / "SOIL.SOL"
RAW_TMX = PROJECT_ROOT / "data" / "raw" / "experiments" / "XXQL2501.TMX"

C_DSSAT_SOL = Path(r"C:\DSSAT48\Soil\SOIL.SOL")

EXP_ALIASES = [
    PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2501_v20260917_refresh",
    PROJECT_ROOT / "data" / "user" / "experiments" / "XXQL2501",
    PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2501_unified_20260914",
]

# 7-layer XXSL2501 text
XXSL2501_7L = """*XXSL2501    SCS         -99     180 Plot 9 Fields (2025 Spring 7L Scheme)
@SITE        COUNTRY          LAT     LONG SCS FAMILY
 Xinxiang    China         35.160  113.800 Sandy Loam
@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE
   -99  0.13   5.5  0.65  75.0  1.00  .933 IB001 IB001 IB001
@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC
     2   -99 0.142 0.296 0.492 1.000  3.50  1.36  0.90  15.0  20.0     0 0.081  8.13   -99   -99   -99
     4   -99 0.142 0.296 0.492 1.000  3.50  1.36  0.90  15.0  20.0     0 0.081  8.13   -99   -99   -99
    15   -99 0.142 0.296 0.492 1.000  3.50  1.36  0.90  15.0  20.0     0 0.081  8.13   -99   -99   -99
    30   -99 0.149 0.303 0.448 0.900  2.37  1.49  0.71  15.0  20.0     0 0.064  8.05   -99   -99   -99
   100   -99 0.163 0.323 0.462 0.850  1.49  1.52  0.28  15.0  20.0     0 0.027  8.00   -99   -99   -99
   140   -99 0.165 0.300 0.420 0.000  1.00  1.55  0.10  15.0  20.0     0 0.010  8.00   -99   -99   -99
   180   -99 0.160 0.280 0.380 0.000  0.80  1.60  0.08  15.0  20.0     0 0.010  8.00   -99   -99   -99"""


def update_soil_sol(file_path: Path):
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    new_lines = []
    in_target = False

    for l in lines:
        if l.startswith("*XXSL2501"):
            in_target = True
            new_lines.append(XXSL2501_7L)
        elif in_target and l.startswith("*") and not l.startswith("*XXSL2501"):
            in_target = False
            new_lines.append(l)
        elif in_target:
            continue
        else:
            new_lines.append(l)

    file_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"Updated XXSL2501 in {file_path}")


def update_tmx_ic(tmx_path: Path):
    lines = tmx_path.read_text(encoding="utf-8").splitlines()
    
    # Sub-layer mass weighting constants for 30-100cm:
    # 40cm (dz=10, mass=15.5), 60cm (dz=20, mass=31.2), 80cm (dz=20, mass=30.2), 100cm (dz=20, mass=29.4)
    # Total dz = 70, total mass = 106.3
    dz = [10, 20, 20, 20]
    mass = [15.5, 31.2, 30.2, 29.4]
    tot_dz = 70.0
    tot_mass = 106.3

    new_lines = []
    in_ic_table = False
    current_block = []

    def flush_block(block_lines):
        if not block_lines:
            return []
        rows = []
        for l in block_lines:
            parts = l.split()
            rows.append({
                "trt": int(parts[0]),
                "slb": int(parts[1]),
                "sh2o": float(parts[2]),
                "snh4": float(parts[3]),
                "sno3": float(parts[4]),
            })
        trt = rows[0]["trt"]
        row_by_depth = {r["slb"]: r for r in rows}

        out_rows = []
        # Depths: 2, 4, 15, 30
        for d in [2, 4, 15, 30]:
            if d in row_by_depth:
                r = row_by_depth[d]
                out_rows.append(f"{trt:2d} {d:5d} {r['sh2o']:5.3f} {r['snh4']:5.2f} {r['sno3']:5.2f}")

        # Merged 100 cm
        sh2o_vals = [row_by_depth[d]["sh2o"] for d in [40, 60, 80, 100] if d in row_by_depth]
        snh4_vals = [row_by_depth[d]["snh4"] for d in [40, 60, 80, 100] if d in row_by_depth]
        sno3_vals = [row_by_depth[d]["sno3"] for d in [40, 60, 80, 100] if d in row_by_depth]

        if len(sh2o_vals) == 4:
            w_sh2o = sum(d * v for d, v in zip(dz, sh2o_vals)) / tot_dz
            w_snh4 = sum(m * v for m, v in zip(mass, snh4_vals)) / tot_mass
            w_sno3 = sum(m * v for m, v in zip(mass, sno3_vals)) / tot_mass
            out_rows.append(f"{trt:2d}   100 {w_sh2o:5.3f} {w_snh4:5.2f} {w_sno3:5.2f}")

        # Depths: 140, 180
        for d in [140, 180]:
            if d in row_by_depth:
                r = row_by_depth[d]
                out_rows.append(f"{trt:2d} {d:5d} {r['sh2o']:5.3f} {r['snh4']:5.2f} {r['sno3']:5.2f}")

        return out_rows

    for line in lines:
        if line.startswith("@C  ICBL"):
            in_ic_table = True
            new_lines.append(line)
        elif in_ic_table and line.startswith(("@", "*", "!")):
            if current_block:
                new_lines.extend(flush_block(current_block))
                current_block = []
            in_ic_table = False
            new_lines.append(line)
        elif in_ic_table:
            stripped = line.strip()
            if not stripped:
                if current_block:
                    new_lines.extend(flush_block(current_block))
                    current_block = []
                new_lines.append(line)
            else:
                parts = stripped.split()
                if len(parts) >= 5 and parts[0].isdigit() and parts[1].isdigit():
                    # Check if new treatment starts
                    if current_block and int(parts[0]) != int(current_block[0].split()[0]):
                        new_lines.extend(flush_block(current_block))
                        current_block = []
                    current_block.append(line)
                else:
                    if current_block:
                        new_lines.extend(flush_block(current_block))
                        current_block = []
                    new_lines.append(line)
        else:
            new_lines.append(line)

    if current_block:
        new_lines.extend(flush_block(current_block))

    tmx_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"Updated Section @C ICBL in {tmx_path}")


def main():
    print("=== Step 1: Updating data/raw/soil/SOIL.SOL ===")
    update_soil_sol(RAW_SOL)
    if C_DSSAT_SOL.exists():
        update_soil_sol(C_DSSAT_SOL)

    print("\n=== Step 2: Updating data/raw/experiments/XXQL2501.TMX ===")
    update_tmx_ic(RAW_TMX)

    print("\n=== Step 3: Synchronizing all 25SP bundles ===")
    for alias_dir in EXP_ALIASES:
        alias_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RAW_SOL, alias_dir / "SOIL.SOL")
        shutil.copy2(RAW_TMX, alias_dir / "XXQL2501.TMX")
        # Also copy TMA, TMT if present
        for ext in ["TMA", "TMT"]:
            f = PROJECT_ROOT / "data" / "raw" / "experiments" / f"XXQL2501.{ext}"
            if f.exists():
                shutil.copy2(f, alias_dir / f.name)
        print(f"Synchronized to {alias_dir}")

    print("\n=== Step 4: Sanity Check Simulation ===")
    from tools.calibration.grid_deep_root_water import init_sim_dir, run_one_sim, extract_metrics, BASE_PARAM_CSV
    check_dir = PROJECT_ROOT / "workspace" / "runs" / "full_gen_page22_sasc0945_150x5_20260918" / "grid_deep_root" / "_sanity_bundle_check"
    batch_dest = init_sim_dir(check_dir)
    df_h = run_one_sim(check_dir, batch_dest, BASE_PARAM_CSV, RAW_SOL)
    m = extract_metrics(df_h)
    print(f"Sanity simulation successful!")
    print(f"25SP NRMSE: {m['nrmse']:.2f}%, d-index: {m['d_index']:.4f}")
    print(f"W1N3: {m['w1n3']:.2f}t, W1N0: {m['w1n0']:.2f}t | W1 Delta: {m['delta_w1']:+.2f}t | W3 Delta: {m['delta_w3']:+.2f}t")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
