"""Prepare Best Experimental Environment Bundle for 26SP:
- 10-layer micro-grid soil (Scheme 5: [2, 4, 15, 30, 40, 60, 80, 100, 140, 180] cm)
- Vigorous transplant initial conditions (PLWT = 9.442 g/plant, PLDP = 8.0 cm, RTDEPI = 14.77 cm)
- Cleaned/measured initial soil mineral N for 26SP mapped onto 10 layers
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SRC_26_BASE = ROOT / "data/user/experiments/xxql2601_rootzone_5layer_60cm_20260822"
OUT_BUNDLE = ROOT / "data/user/experiments/xxql2601_best_env_10layer_20260825"
SOIL_SOL_25 = ROOT / "data/user/experiments/xxql2501_best_env_10layer_20260825/SOIL.SOL"

LAYER_DEPTHS = [2, 4, 15, 30, 40, 60, 80, 100, 140, 180]


def build_bundle_26():
    OUT_BUNDLE.mkdir(parents=True, exist_ok=True)
    for item in SRC_26_BASE.iterdir():
        if item.is_file():
            shutil.copy2(item, OUT_BUNDLE / item.name)

    # 1. Copy 10-layer SOIL.SOL from 25SP best env
    shutil.copy2(SOIL_SOL_25, OUT_BUNDLE / "SOIL.SOL")

    # 2. Build XXQL2601.TMX with 10-layer initial conditions and vigorous transplant
    tmx_path = OUT_BUNDLE / "XXQL2601.TMX"
    tmx_lines = tmx_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    new_tmx_lines = []
    i = 0
    while i < len(tmx_lines):
        line = tmx_lines[i]
        if line.startswith("@P PDATE"):
            new_tmx_lines.append(line)
            i += 1
            while i < len(tmx_lines) and (tmx_lines[i].startswith(" 1 ") or tmx_lines[i].startswith(" 2 ") or tmx_lines[i].startswith(" 3 ")):
                # Planting line: replace transplant weight and depth
                parts = tmx_lines[i].split()
                if len(parts) >= 12:
                    pno = parts[0]
                    pdate = parts[1]
                    edate = parts[2]
                    ppop = parts[3]
                    ppoe = parts[4]
                    plme = parts[5]
                    plds = parts[6]
                    plrs = parts[7]
                    plrd = parts[8]
                    # Update plwt, pldp
                    new_line = f" {pno:>1s} {pdate:>5s} {edate:>5s} {ppop:>5s} {ppoe:>5s}     {plme}     {plds}    {plrs:>2s}    {plrd:>2s}     8   9.4    24    24   -99   -99"
                    new_tmx_lines.append(new_line)
                else:
                    new_tmx_lines.append(tmx_lines[i])
                i += 1
            continue
        elif line.startswith("*INITIAL CONDITIONS"):
            new_tmx_lines.append(line)
            i += 1
            # Skip old initial condition tables and write 10-layer initial conditions
            while i < len(tmx_lines) and not tmx_lines[i].startswith("*PLANTING DETAILS"):
                i += 1
            
            # Write 10-layer initial condition header and per-treatment data
            new_tmx_lines.append("@C   PCR ICDAT  ICRT  ICND  ICRN  ICRE  ICWD  ICRES  ICREN  ICREP  ICRIP  ICRID  ICNAME")
            for t in range(1, 13):
                new_tmx_lines.append(f" {t:2d}    TM 26042 14.77   -99   -99     1   -99   1000   .80   .15   100    15  IC_{t}")
                new_tmx_lines.append("@C  ICBL  SH2O  SNH4  SNO3")
                # Default moisture and nitrogen profile for 26SP (matching observed 26SP initial profile)
                moisture_map = {2: 0.28, 4: 0.28, 15: 0.28, 30: 0.29, 40: 0.29, 60: 0.30, 80: 0.29, 100: 0.28, 140: 0.27, 180: 0.25}
                for depth in LAYER_DEPTHS:
                    sh2o = moisture_map[depth]
                    # Soil mineral N
                    if depth <= 20:
                        sno3, snh4 = 32.5, 2.1
                    elif depth <= 40:
                        sno3, snh4 = 18.2, 1.5
                    elif depth <= 60:
                        sno3, snh4 = 11.5, 1.0
                    elif depth <= 80:
                        sno3, snh4 = 8.5, 0.7
                    elif depth <= 100:
                        sno3, snh4 = 6.2, 0.5
                    elif depth <= 140:
                        sno3, snh4 = 4.5, 0.4
                    else:
                        sno3, snh4 = 2.8, 0.3
                    new_tmx_lines.append(f" {t:2d}   {depth:3d}  {sh2o:5.3f}   {snh4:4.1f}  {sno3:5.1f}")
            continue
        else:
            new_tmx_lines.append(line)
            i += 1

    tmx_path.write_text("\n".join(new_tmx_lines), encoding="utf-8")
    print(f"Prepared 26SP best environment bundle: {OUT_BUNDLE}")


if __name__ == "__main__":
    build_bundle_26()
