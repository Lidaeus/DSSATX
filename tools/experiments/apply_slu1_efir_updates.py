#!/usr/bin/env python3
"""Apply SLU1=1.0 and EFIR=0.95 updates across soil and TMX experiment files."""
import re
from pathlib import Path

PROJECT_ROOT = Path("D:/Tomato_Cal")

# 1. Update SOIL.SOL files
sol_paths = [
    PROJECT_ROOT / "data/raw/soil/SOIL.SOL",
    PROJECT_ROOT / "data/user/experiments/xxql2501_v20260917_refresh/SOIL.SOL",
    PROJECT_ROOT / "data/user/experiments/xxql2601_v20260917_refresh/SOIL.SOL",
    PROJECT_ROOT / "data/user/experiments/xxql2502_v20260917_refresh/SOIL.SOL",
    Path("C:/DSSAT48/Soil/SOIL.SOL"),
]

for p in sol_paths:
    if not p.exists():
        continue
    txt = p.read_text(encoding="utf-8", errors="ignore")
    # Update SLU1 = 1.0 (exact 6-char formatting)
    txt = txt.replace("   -99  0.13   5.5  0.65  75.0  1.00  .933", "   -99  0.13   1.0  0.65  75.0  1.00  .933")
    txt = txt.replace("   -99  0.13   5.5  0.65  75.0  1.00  .863", "   -99  0.13   1.0  0.65  75.0  1.00  .863")
    # Update Layer 1 & 2 SLLL = 0.180
    txt = txt.replace("     2   -99 0.142 0.296", "     2   -99 0.180 0.296")
    txt = txt.replace("     4   -99 0.142 0.296", "     4   -99 0.180 0.296")
    txt = txt.replace("     2   -99 .1419 .3147", "     2   -99 0.180 .3147")
    txt = txt.replace("     4   -99 .1527 .3091", "     4   -99 0.180 .3091")
    p.write_text(txt, encoding="utf-8")
    print(f"Updated {p}")

# 2. Update TMX files for EFIR=0.95 and IREFF=0.95
tmx_paths = [
    PROJECT_ROOT / "data/raw/experiments/XXQL2501.TMX",
    PROJECT_ROOT / "data/raw/experiments/XXQL2601.TMX",
    PROJECT_ROOT / "data/raw/experiments/XXQL2502.TMX",
    PROJECT_ROOT / "data/user/experiments/xxql2501_v20260917_refresh/XXQL2501.TMX",
    PROJECT_ROOT / "data/user/experiments/xxql2601_v20260917_refresh/XXQL2601.TMX",
    PROJECT_ROOT / "data/user/experiments/xxql2502_v20260917_refresh/XXQL2502.TMX",
]

for p in tmx_paths:
    if not p.exists():
        continue
    txt = p.read_text(encoding="utf-8", errors="ignore")
    # EFIR in @I header block
    txt = re.sub(r"(\*IRRIGATION AND WATER MANAGEMENT\s+@I\s+EFIR[^\n]+\n\s+\d+\s+)[\d\.]+(\s+)", r"\g<1>0.95\g<2>", txt)
    # IREFF in @N IRRIGATION
    txt = re.sub(r"(@N IRRIGATION[^\n]+\n\s+\d+\s+IR\s+\d+\s+\d+\s+\d+\s+\S+\s+\S+\s+\d+\s+)[\d\.]+", r"\g<1>0.95", txt)
    
    # Replace all EFIR lines in @I
    lines = []
    in_i = False
    for l in txt.splitlines():
        if l.startswith("@I  EFIR"):
            in_i = True
            lines.append(l)
            continue
        if in_i:
            if l.startswith("@") or l.startswith("*"):
                in_i = False
            elif l.strip() and l.strip()[0].isdigit() and len(l.split()) >= 7:
                l = re.sub(r"^(\s*\d+\s+)[\d\.]+(\s+)", r"\g<1>0.95\g<2>", l)
        lines.append(l)
    txt = "\n".join(lines) + "\n"
    p.write_text(txt, encoding="utf-8")
    print(f"Updated {p}")

print("All SOIL.SOL and TMX updates completed successfully.")
