#!/usr/bin/env python3
"""Build dual-plot soil profiles (XXSL2501 for Plot 9/25SP, XXSL2601 for Plot 2/26SP & 25FA).

Complies with docs/reports/2025春_2026春数据重构与双地块土壤方案执行方案_20260917.md:
  - D1=B: 10L-B mass-conserving micro-grid scheme (2, 4, 15, 30, 40, 60, 80, 100, 140, 180 cm)
  - D10=A: Bulk density from 2号棚容重测定.xlsx Sheet2 authoritative 6-point mean
  - Shared physical basis: SBDM, SDUL, SSAT, SLLL, SSKS, SLCL=15.0, SLSI=20.0, SLCF=0 (no -99)
  - Differentiated seasonal chemical properties:
      XXSL2501: 2025春 9号棚实测 SLNI, SLHW, SLOC (via C:N=11:1 from TN per D4=A)
      XXSL2601: 2026春 2号棚实测 SLNI, SLHW, SLOC (from 有机质/1.724)
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_SOL = ROOT / "data/raw/soil/SOIL.SOL"

# 10L-B scheme layer bottoms (cm)
LAYER_BOTTOMS = [2, 4, 15, 30, 40, 60, 80, 100, 140, 180]

# Shared physical parameters across both profiles (10 layers)
PHYSICAL_LAYERS = [
    # SLB, SLLL,  SDUL,  SSAT,  SRGF,  SSKS, SBDM, SLCL, SLSI, SLCF
    (  2, 0.142, 0.296, 0.492, 1.000, 2.03, 1.36, 15.0, 20.0, 0),
    (  4, 0.142, 0.296, 0.492, 1.000, 2.03, 1.36, 15.0, 20.0, 0),
    ( 15, 0.142, 0.296, 0.492, 1.000, 2.03, 1.36, 15.0, 20.0, 0),
    ( 30, 0.149, 0.303, 0.448, 0.900, 1.96, 1.49, 15.0, 20.0, 0),
    ( 40, 0.152, 0.306, 0.426, 0.800, 1.81, 1.55, 15.0, 20.0, 0),
    ( 60, 0.171, 0.330, 0.443, 0.650, 0.33, 1.56, 15.0, 20.0, 0),
    ( 80, 0.157, 0.315, 0.463, 0.200, 2.03, 1.51, 15.0, 20.0, 0),
    ( 100, 0.167, 0.331, 0.498, 0.200, 1.43, 1.47, 15.0, 20.0, 0),
    ( 140, 0.165, 0.300, 0.420, 0.000, 0.16, 1.55, 15.0, 20.0, 0),
    ( 180, 0.160, 0.280, 0.380, 0.000, 0.59, 1.60, 15.0, 20.0, 0),
]

# Chemical parameters for XXSL2501 (9号棚 / 25SP)
CHEM_25SP = [
    # SLNI, SLHW, SLOC
    (0.081, 8.13, 0.90),  # 0-2 cm
    (0.081, 8.13, 0.90),  # 2-4 cm
    (0.081, 8.13, 0.90),  # 4-15 cm
    (0.064, 8.05, 0.71),  # 15-30 cm
    (0.055, 8.01, 0.61),  # 30-40 cm
    (0.030, 7.98, 0.31),  # 40-60 cm
    (0.020, 8.00, 0.20),  # 60-80 cm
    (0.015, 8.00, 0.15),  # 80-100 cm
    (0.010, 8.00, 0.10),  # 100-140 cm
    (0.010, 8.00, 0.08),  # 140-180 cm
]

# Chemical parameters for XXSL2601 (2号棚 / 26SP & 25FA)
CHEM_26SP = [
    # SLNI, SLHW, SLOC
    (0.113, 7.91, 0.92),  # 0-2 cm
    (0.113, 7.91, 0.92),  # 2-4 cm
    (0.113, 7.91, 0.92),  # 4-15 cm
    (0.097, 8.03, 0.77),  # 15-30 cm
    (0.089, 8.09, 0.69),  # 30-40 cm
    (0.046, 8.25, 0.31),  # 40-60 cm
    (0.025, 8.30, 0.20),  # 60-80 cm
    (0.020, 8.30, 0.15),  # 80-100 cm
    (0.010, 8.30, 0.10),  # 100-140 cm
    (0.010, 8.30, 0.08),  # 140-180 cm
]


def format_profile(soil_id: str, desc: str, chem_layers: list[tuple[float, float, float]]) -> list[str]:
    lines = [
        f"*{soil_id:10s}  SCS         -99     180 {desc}",
        "@SITE        COUNTRY          LAT     LONG SCS FAMILY",
        " Xinxiang    China         35.160  113.800 Sandy Loam",
        "@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE",
        "   -99  0.13   5.5  0.65  75.0  1.00  .933 IB001 IB001 IB001",
        "@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC",
    ]
    for (slb, slll, sdul, ssat, srgf, ssks, sbdm, slcl, slsi, slcf), (slni, slhw, sloc) in zip(PHYSICAL_LAYERS, chem_layers):
        line = (
            f"{slb:6d}"
            f"   -99"
            f"{slll:6.3f}"
            f"{sdul:6.3f}"
            f"{ssat:6.3f}"
            f"{srgf:6.3f}"
            f"{ssks:6.2f}"
            f"{sbdm:6.2f}"
            f"{sloc:6.2f}"
            f"{slcl:6.1f}"
            f"{slsi:6.1f}"
            f"{slcf:6d}"
            f"{slni:6.3f}"
            f"{slhw:6.2f}"
            f"   -99"
            f"   -99"
            f"   -99"
        )
        lines.append(line)
    return lines


def build_soil_sol(
    dst_path: Path,
    src_sol_path: Path = RAW_SOL,
    *,
    chem_25sp: list[tuple[float, float, float]] | None = None,
    chem_26sp: list[tuple[float, float, float]] | None = None,
    chem_25fa: list[tuple[float, float, float]] | None = None,
) -> None:
    text = src_sol_path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()

    p25_lines = format_profile("XXSL2501", "Plot 9 Fields (2025 Spring 10L-B Scheme)", chem_25sp or CHEM_25SP)
    p26_lines = format_profile("XXSL2601", "Plot 2 Fields (2026 Spring & 2025 Autumn 10L-B Scheme)", chem_26sp or CHEM_26SP)
    pfa_lines = format_profile("XXSL2502", "Plot 2 Fields (2025 Autumn 10L-B Scheme)", chem_25fa) if chem_25fa else []

    both_profiles = p25_lines + p26_lines + pfa_lines

    # 1. If XXSL2501 is already present, replace the existing XXSL2501 and XXSL2601 profiles
    xxsl25_idx = None
    for i, l in enumerate(lines):
        if l.startswith("*XXSL2501"):
            xxsl25_idx = i
            break

    if xxsl25_idx is not None:
        target_end = len(lines)
        for j in range(xxsl25_idx + 1, len(lines)):
            if lines[j].startswith("*") and not lines[j].startswith(("*XXSL2501", "*XXSL2601", "*XXSL2502")):
                target_end = j
                break
        new_lines = lines[:xxsl25_idx] + both_profiles + lines[target_end:]
    else:
        # 2. Check for legacy profiles to replace
        legacy_idx = None
        legacy_end = None
        for target_key in ["*XXSL1800S1", "*IBTM910017"]:
            for i, l in enumerate(lines):
                if l.startswith(target_key):
                    legacy_idx = i
                    for j in range(i + 1, len(lines)):
                        if lines[j].startswith("*"):
                            legacy_end = j
                            break
                    break
            if legacy_idx is not None:
                break

        if legacy_idx is not None and legacy_end is not None:
            new_lines = lines[:legacy_idx] + both_profiles + lines[legacy_end:]
        else:
            # 3. Insert before first real profile (skip header *SOILS:)
            first_profile_idx = next(
                i for i, l in enumerate(lines)
                if l.startswith("*") and not l.startswith("*SOILS")
            )
            new_lines = lines[:first_profile_idx] + both_profiles + lines[first_profile_idx:]

    dst_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build dual-plot soil profiles into SOIL.SOL")
    parser.add_argument("--out", type=Path, default=ROOT / "data/raw/soil/SOIL.SOL")
    args = parser.parse_args()
    build_soil_sol(args.out)
    print(f"Updated {args.out} with XXSL2501 and XXSL2601.")
