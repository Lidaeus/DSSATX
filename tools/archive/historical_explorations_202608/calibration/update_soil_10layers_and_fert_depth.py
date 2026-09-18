"""Update experiment bundles with:
1. 10-layer refined SOIL.SOL (*IBTM910017) preserving all measured physical properties and integrating IBSB910026-style SRGF.
2. Update TMX files so topdressing fertilizer applications (after the first basal application) have FDEP = 5 cm.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

BUNDLES = [
    ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v2_20260819",
    ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v2_20260819",
    ROOT / "_seasons/25SP",
    ROOT / "_seasons/26SP",
]

# 10-layer refined IBTM910017 profile preserving measured physical data
REFINED_IBTM910017 = """*IBTM910017  SCS           CL     180  Orangeburg Sandy Loam (10-Layer Refined)
@SITE        COUNTRY          LAT     LONG SCS FAMILY
 Quincy      USA             35.16   113.8 Loamy,silic,hyperth Gross. Paleud(17)
@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE
   -99   .13     9   .27    81     1   .93 IB001 IB001 IB001
@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC
     5     1  .138  .310  .490 1.000  0.23  1.38  0.92  35.0  30.0   -99  0.08   8.1   -99   -99   -99
    10     1  .138  .310  .490 1.000  0.23  1.38  0.92  35.0  30.0   -99  0.08   8.1   -99   -99   -99
    20     1  .138  .310  .490 1.000  0.23  1.38  0.92  35.0  30.0   -99  0.08   8.1   -99   -99   -99
    30     2  .150  .320  .430  .850  0.23  1.55  0.70  35.0  30.0   -99  0.06   8.0   -99   -99   -99
    40     2  .150  .320  .430  .650  0.23  1.55  0.70  35.0  30.0   -99  0.06   8.0   -99   -99   -99
    50     3  .172  .330  .440  .450  0.24  1.53  0.31  35.0  30.0   -99  0.03   8.0   -99   -99   -99
    60     3  .172  .330  .440  .300  0.24  1.53  0.31  35.0  30.0   -99  0.03   8.0   -99   -99   -99
    80     4  .157  .330  .460  .180  0.24  1.50  0.18  35.0  30.0   -99   -99   -99   -99   -99   -99
   100     5  .166  .340  .510  .080  0.24  1.49  0.10  35.0  30.0   -99   -99   -99   -99   -99   -99
   180     6  .176  .290  .350  .010  0.24  1.55  0.05   -99   -99   -99   -99   -99   -99   -99   -99
"""


def update_soil_sol(bundle: Path) -> None:
    sol_file = bundle / "SOIL.SOL"
    if not sol_file.exists():
        return
    text = sol_file.read_text(encoding="utf-8", errors="ignore")
    # Replace *IBTM910017 block
    pattern = r"\*IBTM910017[\s\S]*?(?=\n\*[A-Z0-9]|\Z)"
    if re.search(pattern, text):
        new_text = re.sub(pattern, REFINED_IBTM910017.strip(), text, count=1)
        sol_file.write_text(new_text, encoding="utf-8")
        print(f"Updated SOIL.SOL in {bundle.name}")
    else:
        # Append if not found
        sol_file.write_text(text.rstrip() + "\n\n" + REFINED_IBTM910017.strip() + "\n", encoding="utf-8")
        print(f"Appended refined IBTM910017 to SOIL.SOL in {bundle.name}")


def update_tmx_fert_depth(tmx_file: Path) -> None:
    if not tmx_file.exists():
        return
    lines = tmx_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    in_fert = False
    new_lines = []
    first_date_per_level = {}
    
    # First pass: find first fertilizer date for each fertilizer level (F)
    for line in lines:
        if line.startswith("*FERTILIZERS"):
            in_fert = True
            continue
        elif in_fert and line.startswith("*"):
            in_fert = False
            continue
        if in_fert and line.strip() and not line.startswith("@"):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    f_level = int(parts[0])
                    f_date = int(parts[1])
                    if f_level not in first_date_per_level or f_date < first_date_per_level[f_level]:
                        first_date_per_level[f_level] = f_date
                except ValueError:
                    pass

    # Second pass: update FDEP
    in_fert = False
    for line in lines:
        if line.startswith("*FERTILIZERS"):
            in_fert = True
            new_lines.append(line)
            continue
        elif in_fert and line.startswith("*"):
            in_fert = False
            new_lines.append(line)
            continue
        if in_fert and line.strip() and not line.startswith("@"):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    f_level = int(parts[0])
                    f_date = int(parts[1])
                    # If this is topdressing (date > first basal date), set FDEP = 5
                    if f_date > first_date_per_level.get(f_level, 0):
                        # Line format: F FDATE FMCD  FACD  FDEP  FAMN  FAMP  FAMK  FAMC  FAMO  FOCD FERNAME
                        # e.g.: " 1 26136 FE018 AP002    25     0     0    10     0     0     0 N3"
                        # We replace the FDEP column (position 4) with 5
                        parts[4] = "5"
                        # Reconstruct line with exact formatting
                        formatted = f" {int(parts[0]):>1} {parts[1]:>5} {parts[2]:>5} {parts[3]:>5} {int(parts[4]):>5} {float(parts[5]):>5.0f} {float(parts[6]):>5.0f} {float(parts[7]):>5.0f} {float(parts[8]):>5.0f} {float(parts[9]):>5.0f} {float(parts[10]):>5.0f} {' '.join(parts[11:])}"
                        new_lines.append(formatted)
                        continue
                except Exception:
                    pass
        new_lines.append(line)

    tmx_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"Updated fertilizer FDEP depths in {tmx_file.name}")


def main() -> int:
    for bundle in BUNDLES:
        update_soil_sol(bundle)
        for tmx in bundle.glob("*.TMX"):
            update_tmx_fert_depth(tmx)
    return 0


if __name__ == "__main__":
    main()
