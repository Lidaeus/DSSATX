"""Prepare Best Experimental Environment Bundle for 25SP:
- 10-layer micro-grid soil (Scheme 5: [2, 4, 15, 30, 40, 60, 80, 100, 140, 180] cm)
- Vigorous transplant initial conditions (PLWT = 9.442 g/plant, PLDP = 8.0 cm, RTDEPI = 14.77 cm)
- Cleaned outlier-free measured initial soil mineral N (from 25FA measured reference)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SRC_25_BASE = ROOT / "data/user/experiments/xxql2501_rootzone_5layer_60cm_20260822"
OUT_BUNDLE = ROOT / "data/user/experiments/xxql2501_best_env_10layer_20260825"
REF_SOL = ROOT / "data/user/experiments/xxql2501_rootzone_5layer_60cm_20260822/SOIL.SOL"

LAYER_DEPTHS = [2, 4, 15, 30, 40, 60, 80, 100, 140, 180]

def get_clean_soil_n(depth: int) -> tuple[float, float]:
    if depth <= 20:
        return 28.5, 1.8
    elif depth <= 40:
        return 16.8, 1.4
    elif depth <= 60:
        return 12.2, 1.1
    elif depth <= 80:
        return 9.5, 0.8
    elif depth <= 100:
        return 7.2, 0.6
    elif depth <= 140:
        return 5.0, 0.5
    else:
        return 3.0, 0.3


def build_bundle():
    OUT_BUNDLE.mkdir(parents=True, exist_ok=True)
    for item in SRC_25_BASE.iterdir():
        if item.is_file():
            shutil.copy2(item, OUT_BUNDLE / item.name)

    # 1. Build 10-layer SOIL.SOL
    sol_txt = REF_SOL.read_text(encoding="utf-8", errors="ignore")
    lines_sol = sol_txt.splitlines()
    new_sol_lines = []
    in_ib = False
    for l in lines_sol:
        if "*IBTM910017" in l:
            in_ib = True
            new_sol_lines.append("*IBTM910017  SCS           CL     180  Orangeburg Sandy Loam (10-Layer Micro-Grid Scheme 5)")
            new_sol_lines.append("@SITE        COUNTRY          LAT     LONG SCS FAMILY")
            new_sol_lines.append(" Quincy      USA             35.16   113.8 Loamy,silic,hyperth Gross. Paleud(17)")
            new_sol_lines.append("@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE")
            new_sol_lines.append("   -99   .13     9   .27    81     1   .93 IB001 IB001 IB001")
            new_sol_lines.append("@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC")
            for depth in LAYER_DEPTHS:
                if depth <= 60:
                    srgf = 1.0 if depth <= 15 else (0.90 if depth <= 30 else (0.80 if depth <= 40 else 0.65))
                    new_sol_lines.append(f"   {depth:3d}     1  .150  .320  .450  {srgf:5.3f}  0.23  1.50  0.65  35.0  30.0   -99  0.05   8.0   -99   -99   -99")
                elif depth <= 80:
                    new_sol_lines.append(f"   {depth:3d}     4  .157  .330  .460  .250  0.24  1.50  0.18  35.0  30.0   -99   -99   -99   -99   -99   -99")
                elif depth <= 100:
                    new_sol_lines.append(f"   {depth:3d}     5  .166  .340  .510  .150  0.24  1.49  0.10  35.0  30.0   -99   -99   -99   -99   -99   -99")
                elif depth <= 140:
                    new_sol_lines.append(f"   {depth:3d}     6  .173  .305  .400  .080  0.24  1.53  0.07  35.0  30.0   -99   -99   -99   -99   -99   -99")
                else:
                    new_sol_lines.append(f"   {depth:3d}     6  .176  .290  .350  .030  0.24  1.55  0.05  35.0  30.0   -99   -99   -99   -99   -99   -99")
        elif in_ib and l.startswith("*") and not l.startswith("*IBTM910017"):
            in_ib = False
            new_sol_lines.append(l)
        elif not in_ib:
            new_sol_lines.append(l)

    (OUT_BUNDLE / "SOIL.SOL").write_text("\n".join(new_sol_lines), encoding="utf-8")

    # 2. Build XXQL2501.TMX with exact per-treatment block initial conditions
    tmx_path = OUT_BUNDLE / "XXQL2501.TMX"
    tmx_lines = tmx_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    
    new_tmx_lines = []
    i = 0
    while i < len(tmx_lines):
        line = tmx_lines[i]
        if line.startswith("@P PDATE"):
            new_tmx_lines.append(line)
            i += 1
            while i < len(tmx_lines) and tmx_lines[i].startswith(" 1 "):
                # Format:  1 25075 25075   3.5   3.5     T     S    60    40     8   9.4    24    24   -99   -99
                new_tmx_lines.append(" 1 25075 25075   3.5   3.5     T     S    60    40     8   9.4    24    24   -99   -99")
                i += 1
            continue
        elif line.startswith("*INITIAL CONDITIONS"):
            new_tmx_lines.append(line)
            i += 1
            # Skip until next section starts
            while i < len(tmx_lines) and not tmx_lines[i].startswith("*"):
                i += 1
            
            # Write structured per-treatment blocks
            treatments = [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]
            for tnum in treatments:
                new_tmx_lines.append("@C   PCR ICDAT  ICRT  ICND  ICRN  ICRE  ICWD ICRES ICREN ICREP ICRIP ICRID ICNAME")
                new_tmx_lines.append(f"{tnum:2d}   -99 25069     1     0     1     1   -99   -99   -99   -99   -99   -99 {tnum}")
                new_tmx_lines.append("@C  ICBL  SH2O  SNH4  SNO3")
                for depth in LAYER_DEPTHS:
                    no3_val, nh4_val = get_clean_soil_n(depth)
                    sh2o = 0.260 if depth <= 60 else (0.280 if depth <= 80 else 0.290)
                    new_tmx_lines.append(f"{tnum:2d}   {depth:3d}  {sh2o:5.3f} {nh4_val:5.1f} {no3_val:5.1f}")
            continue
        else:
            new_tmx_lines.append(line)
            i += 1

    tmx_path.write_text("\n".join(new_tmx_lines), encoding="utf-8")

    # Update input_manifest.json with all file hashes
    manifest_path = OUT_BUNDLE / "input_manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        man = json.load(f)

    man["bundle_id"] = "xxql2501_best_env_10layer_20260825"
    existing_names = {item["name"] for item in man.get("files", [])}
    for f in OUT_BUNDLE.iterdir():
        if f.is_file() and f.name != "input_manifest.json":
            data = f.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            if f.name in existing_names:
                for item in man["files"]:
                    if item["name"] == f.name:
                        item["sha256"] = sha
                        item["bytes"] = len(data)
            else:
                man["files"].append({
                    "name": f.name,
                    "sha256": sha,
                    "bytes": len(data)
                })

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)

    print(f"Successfully built best experimental environment bundle in: {OUT_BUNDLE}")


if __name__ == "__main__":
    build_bundle()
