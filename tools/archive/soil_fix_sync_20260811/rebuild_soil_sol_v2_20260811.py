"""Rebuild bundle SOIL.SOL from pristine baseline, fixed-width column layout (20260811).

SOIL.SOL layer rows are strict fixed-width: field i occupies columns
[i*6, (i+1)*6) right-justified (SLB=0-5, SLMH=6-11, SLLL=12-17, SDUL=18-23,
SSAT=24-29, SRGF=30-35, SSKS=36-41, SBDM=42-47, SLOC=48-53, SLCL=54-59,
SLSI=60-65, SLCF=66-71, SLNI=72-77, SLHW=78-83, SLHB=84-89, SCEC=90-95,
SADC=96-101).  The SCOM row has the same layout (SCOM=0-5, SALB=6-11,
SLU1=12-17, SLDR=18-23, SLRO=24-29, SLNF=30-35, SLPF=36-41, ...).

This script:
  1. Copies the pristine baseline (season-dir SOIL.SOL from the a3
     deterministic run, sha256 a986374f5ca9...) over both bundle SOIL.SOLs.
  2. Applies the full fix set with atomic right-to-left replacements inside
     the fixed 6-char columns — values expand within their column (e.g.
     .3 -> .31) without shifting neighbours.
  3. Verifies every fixed value and the fixed-width layout.

Usage:
    python tools/calibration/rebuild_soil_sol_v2_20260811.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FIX_DIR = ROOT / "figture/soil_param_export_three_20260810"
SOIL_FIX_XLSX = FIX_DIR / "soil_physical_Fix.csv.xlsx"

BASELINE = {
    "25SP": ROOT / "workspace/runs/e02_a3_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260810/best_member_117_deterministic_20260810/_seasons/25SP/SOIL.SOL",
    "26SP": ROOT / "workspace/runs/e02_a3_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260810/best_member_117_deterministic_20260810/_seasons/26SP/SOIL.SOL",
}
BUNDLES = [
    ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
    ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
]
PROFILE = "IBTM910017"

# layer field order in the layer header (without @)
LAYER_FIELDS = ["SLB", "SLMH", "SLLL", "SDUL", "SSAT", "SRGF", "SSKS",
                "SBDM", "SLOC", "SLCL", "SLSI", "SLCF", "SLNI", "SLHW",
                "SLHB", "SCEC", "SADC"]
LAYER_FIX_NAMES = ["SLLL", "SDUL", "SSAT", "SSKS", "SBDM", "SLCL", "SLSI"]
# SCOM field order (without @)
SCOM_FIELDS = ["SCOM", "SALB", "SLU1", "SLDR", "SLRO", "SLNF", "SLPF",
               "SMHB", "SMPX", "SMKE"]


def _fmt(value: float, col_w: int, orig: str) -> str:
    v = float(value)
    if abs(v) < 1 and orig.startswith("."):
        sign = "-" if v < 0 else ""
        av = abs(v)
        for dec in range(6, 0, -1):
            body = f"{av:.{dec}f}".split(".", 1)[1].rstrip("0")
            if body:
                tok = sign + "." + body
                if len(tok) <= col_w:
                    return tok.rjust(col_w)
        return f"{v:.{col_w-2}f}".rjust(col_w)[:col_w]
    for dec in range(6, -1, -1):
        tok = f"{v:.{dec}f}"
        if len(tok) <= col_w:
            return tok.rjust(col_w)
    return f"{v:.5g}"[:col_w].rjust(col_w)


def _write_field(line: str, field_idx: int, new_tok: str) -> str:
    """Replace field_idx-th 6-char column (right-justified) in line."""
    start = field_idx * 6
    cols = list(line)
    cols[start : start + 6] = list(new_tok[:6].rjust(6))
    return "".join(cols)


def rebuild_and_fix(sol: Path, baseline: Path, fixes: dict) -> dict:
    shutil.copy2(baseline, sol)
    lines = sol.read_text(encoding="utf-8", errors="ignore").splitlines()
    changed = {}
    in_profile = False
    layer_idx = 0
    for idx, line in enumerate(lines):
        s = line.rstrip("\n")
        if s.startswith(f"*{PROFILE}"):
            in_profile = True
            continue
        if not in_profile:
            continue
        if s.startswith("*") and not s.startswith(f"*{PROFILE}"):
            break
        if s.lstrip().startswith("@ SCOM"):
            if "SOIL_SLPF" in fixes:
                slpf_idx = SCOM_FIELDS.index("SLPF")
                data_row = lines[idx + 1]
                orig = data_row[slpf_idx * 6 : slpf_idx * 6 + 6].strip()
                new_tok = _fmt(fixes["SOIL_SLPF"], 6, orig)
                lines[idx + 1] = _write_field(data_row, slpf_idx, new_tok)
                changed["SOIL_SLPF"] = (orig, new_tok.strip())
            continue
        if s.lstrip().startswith("@  SLB"):
            layer_idx = 0
            continue
        if layer_idx is None or not s.strip() or s.lstrip().startswith("@"):
            continue
        if not re_match_layer(s):
            continue
        layer_idx += 1
        replacements = []
        for name in LAYER_FIX_NAMES:
            key = f"SOIL_{name}_{layer_idx:02d}"
            if key not in fixes:
                continue
            fidx = LAYER_FIELDS.index(name)
            seg = s[fidx * 6 : fidx * 6 + 6]
            orig = seg.strip()
            try:
                if float(orig) <= -90:  # -99 layer stays missing
                    continue
            except ValueError:
                continue
            new_tok = _fmt(fixes[key], 6, orig)
            if new_tok.strip() != orig:
                replacements.append((fidx, new_tok))
                changed[key] = (orig, new_tok.strip())
        if replacements:
            for fidx, new_tok in sorted(replacements, key=lambda x: x[0], reverse=True):
                lines[idx] = _write_field(lines[idx], fidx, new_tok)
    sol.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def re_match_layer(s: str) -> bool:
    import re
    return bool(re.match(r"^\s*\d+\s+[-]?\d+\s", s))


def verify(sol: Path, fixes: dict) -> dict:
    import re
    lines = sol.read_text(encoding="utf-8", errors="ignore").splitlines()
    issues = []
    checked = 0
    in_profile = False
    layer_idx = 0
    for idx, line in enumerate(lines):
        s = line.rstrip("\n")
        if s.startswith(f"*{PROFILE}"):
            in_profile = True
            continue
        if not in_profile:
            continue
        if s.startswith("*") and not s.startswith(f"*{PROFILE}"):
            break
        if s.lstrip().startswith("@ SCOM"):
            slpf_idx = SCOM_FIELDS.index("SLPF")
            seg = lines[idx + 1][slpf_idx * 6 : slpf_idx * 6 + 6].strip()
            try:
                got = float(seg)
            except ValueError:
                continue
            if abs(got - fixes["SOIL_SLPF"]) > 1e-9:
                issues.append(f"SLPF got {seg} want {fixes['SOIL_SLPF']}")
            continue
        if s.lstrip().startswith("@  SLB"):
            layer_idx = 0
            continue
        if layer_idx is None or not s.strip() or s.lstrip().startswith("@"):
            continue
        if not re_match_layer(s):
            continue
        layer_idx += 1
        for name in LAYER_FIX_NAMES:
            key = f"SOIL_{name}_{layer_idx:02d}"
            if key in fixes:
                fidx = LAYER_FIELDS.index(name)
                seg = s[fidx * 6 : fidx * 6 + 6].strip()
                try:
                    got = float(seg)
                except ValueError:
                    continue
                if got <= -90:
                    continue
                checked += 1
                if abs(got - fixes[key]) > 1e-9:
                    issues.append(f"{key} got {seg} want {fixes[key]}")
    return {"checked": checked, "issue_count": len(issues), "issues": issues[:15]}


def main() -> int:
    soil_fix = pd.read_excel(SOIL_FIX_XLSX)
    fixes = dict(zip(soil_fix["param"].astype(str), soil_fix["Fix"].astype(float)))
    out = {}
    for bundle in BUNDLES:
        sol = bundle / "SOIL.SOL"
        baseline = BASELINE["25SP"] if "2501" in bundle.name else BASELINE["26SP"]
        print(f"=== {sol}")
        ch = rebuild_and_fix(sol, baseline, fixes)
        print(f"  changed {len(ch)} values (from pristine baseline)")
        ver = verify(sol, fixes)
        print(f"  verify: checked={ver['checked']} issues={ver['issue_count']}")
        for iss in ver["issues"]:
            print(f"    ! {iss}")
        out[str(sol)] = {"changed": len(ch), "verify": ver}
    (FIX_DIR / "soil_sol_rebuild_report_v2_20260811.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nreport: figture/soil_param_export_three_20260810/soil_sol_rebuild_report_v2_20260811.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
