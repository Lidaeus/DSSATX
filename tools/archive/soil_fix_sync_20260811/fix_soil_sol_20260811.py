"""Fix SOIL.SOL sync: apply all per-layer replacements atomically (20260811).

The first sync wrote SLPF and per-layer soil params into the bundle SOIL.SOL
but overwrote `lines[idx]` inside the per-name loop, so only the LAST writable
parameter of each layer survived (e.g. SBDM_01=1.38) while earlier ones
(SLLL_01/SDUL_01/...) were silently lost.  This script re-applies the full fix
set to the IBTM910017 profile using a single replacements pass per row
(right-to-left, same as src/dssat/run_dssat.py::update_soil_file), so every
fixed value lands correctly regardless of current file state.

Usage:
    python tools/calibration/fix_soil_sol_20260811.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FIX_DIR = ROOT / "figture/soil_param_export_three_20260810"
SOIL_FIX_XLSX = FIX_DIR / "soil_physical_Fix.csv.xlsx"

BUNDLES = [
    ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
    ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
]
PROFILE = "IBTM910017"
LAYER_NAMES = ["SLLL", "SDUL", "SSAT", "SSKS", "SBDM", "SLCL", "SLSI"]
TOKEN_RE = re.compile(r"\S+")


def _fmt(value: float, orig: str, col_width: int | None = None) -> str:
    """Format value into a SOIL.SOL token.  ``col_width`` is the fixed-width
    column span (next-token start - token start); when the original token is
    too narrow for the value's precision, expand within the column width —
    DSSAT reads SOIL.SOL by fixed column positions, not token width."""
    v = float(value)
    width = max(len(orig), col_width or 0)
    if abs(v) < 1 and (orig.startswith(".") or "." in orig):
        sign = "-" if v < 0 else ""
        av = abs(v)
        for dec in range(6, 0, -1):
            body = f"{av:.{dec}f}".split(".", 1)[1].rstrip("0")
            if body:
                tok = sign + "." + body
                if len(tok) <= width:
                    return tok.rjust(width)
        return f"{v:.{width-2}f}".rjust(width)[:width]
    for dec in range(6, -1, -1):
        tok = f"{v:.{dec}f}"
        if len(tok) <= width:
            return tok.rjust(width)
    return f"{v:.5g}"[:width].rjust(width)


def fix_soil_sol(sol: Path, fixes: dict) -> dict:
    lines = sol.read_text(encoding="utf-8", errors="ignore").splitlines()
    changed = {}
    in_profile = False
    layer_header = None
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
        # SCOM row: SLPF (next line)
        if s.lstrip().startswith("@ SCOM"):
            header = [h for h in s.split() if h != "@"]
            data_line = lines[idx + 1]
            if "SLPF" in header and "SOIL_SLPF" in fixes:
                pos = header.index("SLPF")
                toks = list(TOKEN_RE.finditer(data_line))
                if pos < len(toks):
                    m = toks[pos]
                    orig = m.group(0)
                    col_w = (toks[pos + 1].start() - m.start()) if pos + 1 < len(toks) else (len(data_line) - m.start())
                    new = _fmt(fixes["SOIL_SLPF"], orig, col_w)
                    if new != orig:
                        cols = list(data_line)
                        cols[m.start() : m.end()] = list(new)
                        lines[idx + 1] = "".join(cols).rstrip() + "\n"
                        changed["SOIL_SLPF"] = (orig, new)
            continue
        if s.lstrip().startswith("@  SLB"):
            layer_header = [h for h in s.split() if h != "@"]
            layer_idx = 0
            continue
        if layer_header is None:
            continue
        if not s.strip() or s.lstrip().startswith("@"):
            continue
        parts = s.split()
        if len(parts) < len(layer_header):
            continue
        layer_idx += 1
        # collect all replacements for this row, apply right-to-left once
        replacements = []
        for name in LAYER_NAMES:
            key = f"SOIL_{name}_{layer_idx:02d}"
            if key not in fixes or name not in layer_header:
                continue
            pos = layer_header.index(name)
            toks = list(TOKEN_RE.finditer(s))
            if pos >= len(toks):
                continue
            m = toks[pos]
            orig = m.group(0)
            try:
                if float(orig) <= -90:  # -99 layer stays missing
                    continue
            except ValueError:
                continue
            col_w = (toks[pos + 1].start() - m.start()) if pos + 1 < len(toks) else (len(s) - m.start())
            new = _fmt(fixes[key], orig, col_w)
            if new != orig:
                replacements.append((m.start(), m.end(), new))
                changed[key] = (orig, new)
        if replacements:
            cols = list(s)
            for start, end, new in sorted(replacements, key=lambda x: x[0], reverse=True):
                cols[start:end] = list(new)
            lines[idx] = "".join(cols).rstrip() + "\n"
    sol.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def verify(sol: Path, fixes: dict) -> dict:
    lines = sol.read_text(encoding="utf-8", errors="ignore").splitlines()
    issues = []
    checked = 0
    in_profile = False
    layer_header = None
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
            header = [h for h in s.split() if h != "@"]
            data = lines[idx + 1].split()
            if "SLPF" in header:
                got = float(data[header.index("SLPF")])
                if abs(got - fixes["SOIL_SLPF"]) > 1e-9:
                    issues.append(f"SLPF got {got} want {fixes['SOIL_SLPF']}")
            continue
        if s.lstrip().startswith("@  SLB"):
            layer_header = [h for h in s.split() if h != "@"]
            layer_idx = 0
            continue
        if layer_header is None or not s.strip() or s.lstrip().startswith("@"):
            continue
        parts = s.split()
        if len(parts) < len(layer_header):
            continue
        layer_idx += 1
        row = dict(zip(layer_header, parts))
        for name in LAYER_NAMES:
            key = f"SOIL_{name}_{layer_idx:02d}"
            if key in fixes and name in row and float(row[name]) > -90:
                checked += 1
                if abs(float(row[name]) - fixes[key]) > 1e-9:
                    issues.append(f"{key} got {row[name]} want {fixes[key]}")
    return {"checked": checked, "issue_count": len(issues), "issues": issues[:15]}


def main() -> int:
    soil_fix = pd.read_excel(SOIL_FIX_XLSX)
    fixes = dict(zip(soil_fix["param"].astype(str), soil_fix["Fix"].astype(float)))
    out = {}
    for bundle in BUNDLES:
        sol = bundle / "SOIL.SOL"
        print(f"=== {sol}")
        ch = fix_soil_sol(sol, fixes)
        print(f"  changed {len(ch)} values")
        ver = verify(sol, fixes)
        print(f"  verify: checked={ver['checked']} issues={ver['issue_count']}")
        for iss in ver["issues"]:
            print(f"    ! {iss}")
        out[str(sol)] = {"changed": len(ch), "verify": ver}
    (FIX_DIR / "soil_sol_fix_report_20260811.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nreport: figture/soil_param_export_three_20260810/soil_sol_fix_report_20260811.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
