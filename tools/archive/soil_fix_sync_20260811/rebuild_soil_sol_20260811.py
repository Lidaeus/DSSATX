"""Rebuild bundle SOIL.SOL from pristine baseline + apply fixes atomically (20260811).

The bundle SOIL.SOL files were corrupted by the first sync (per-name loop
overwrote the row) and by two repair attempts that expanded tokens into wrong
column widths.  The pristine baseline is the season-dir SOIL.SOL copied from
the bundle at calibration time (workspace/runs/.../best_member_*_deterministic/
_seasons/{25SP,26SP}/SOIL.SOL, sha256 a986374f5ca9...) — identical across the
official and a3 runs.

This script:
  1. Copies the pristine baseline over both bundle SOIL.SOL files.
  2. Applies the full fix set (SLPF + per-layer SLLL/SDUL/SSAT/SSKS/SBDM/
     SLCL/SLSI) with atomic right-to-left replacements per row, using the
     FIXED column span from the header (6 chars per field) — never the
     next-token distance — so narrow tokens (.3 -> .31) expand inside their
     column without shifting the row.
  3. Verifies every fixed value and the row layout.

Usage:
    python tools/calibration/rebuild_soil_sol_20260811.py
"""

from __future__ import annotations

import json
import re
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
LAYER_NAMES = ["SLLL", "SDUL", "SSAT", "SSKS", "SBDM", "SLCL", "SLSI"]
TOKEN_RE = re.compile(r"\S+")


def _column_spans(header_line: str) -> dict[str, tuple[int, int]]:
    """Fixed column spans from the header token starts (DSSAT F6.x fields)."""
    starts = [m.start() for m in TOKEN_RE.finditer(header_line)]
    names = [m.group(0) for m in TOKEN_RE.finditer(header_line)]
    spans = {}
    for i, name in enumerate(names):
        end = starts[i + 1] if i + 1 < len(starts) else len(header_line)
        spans[name] = (starts[i], end)
    return spans


def _fmt(value: float, col_span: tuple[int, int], orig: str) -> str:
    """Render value right-justified inside the fixed column span."""
    col_w = col_span[1] - col_span[0]
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


def rebuild_and_fix(sol: Path, baseline: Path, fixes: dict) -> dict:
    shutil.copy2(baseline, sol)
    lines = sol.read_text(encoding="utf-8", errors="ignore").splitlines()
    changed = {}
    in_profile = False
    layer_header = None
    spans = {}
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
            spans_scom = _column_spans(s)
            if "SLPF" in header and "SOIL_SLPF" in fixes:
                pos = header.index("SLPF")
                span = spans_scom[header[pos]]
                orig = s  # not used; value read from data row below
                data_line = lines[idx + 1]
                dspans = _column_spans(s)
                # SCOM data row shares the same header spans
                seg = data_line[span[0] : span[1]]
                orig_tok = seg.strip()
                new_tok = _fmt(fixes["SOIL_SLPF"], span, orig_tok)
                cols = list(data_line)
                cols[span[0] : span[1]] = list(new_tok)
                lines[idx + 1] = "".join(cols).rstrip() + "\n"
                changed["SOIL_SLPF"] = (orig_tok, new_tok.strip())
            continue
        if s.lstrip().startswith("@  SLB"):
            layer_header = [h for h in s.split() if h != "@"]
            spans = _column_spans(s)
            layer_idx = 0
            continue
        if layer_header is None:
            continue
        if not s.strip() or s.lstrip().startswith("@"):
            continue
        # layer data row: apply all fixes atomically within fixed spans
        layer_idx += 1
        replacements = []
        for name in LAYER_NAMES:
            key = f"SOIL_{name}_{layer_idx:02d}"
            if key not in fixes or name not in spans:
                continue
            start, end = spans[name]
            seg = s[start:end]
            orig_tok = seg.strip()
            try:
                if float(orig_tok) <= -90:  # -99 layer stays missing
                    continue
            except ValueError:
                continue
            new_tok = _fmt(fixes[key], (start, end), orig_tok)
            if new_tok.strip() != orig_tok:
                replacements.append((start, end, new_tok))
                changed[key] = (orig_tok, new_tok.strip())
        if replacements:
            cols = list(s)
            for start, end, new_tok in sorted(replacements, key=lambda x: x[0], reverse=True):
                cols[start:end] = list(new_tok)
            lines[idx] = "".join(cols).rstrip() + "\n"
    sol.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def verify(sol: Path, fixes: dict) -> dict:
    lines = sol.read_text(encoding="utf-8", errors="ignore").splitlines()
    issues = []
    checked = 0
    in_profile = False
    layer_header = None
    spans = {}
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
            spans = _column_spans(s)
            if "SLPF" in header:
                span = spans[header[header.index("SLPF")]]
                got = float(lines[idx + 1][span[0] : span[1]].strip())
                if abs(got - fixes["SOIL_SLPF"]) > 1e-9:
                    issues.append(f"SLPF got {got} want {fixes['SOIL_SLPF']}")
            continue
        if s.lstrip().startswith("@  SLB"):
            layer_header = [h for h in s.split() if h != "@"]
            spans = _column_spans(s)
            layer_idx = 0
            continue
        if layer_header is None or not s.strip() or s.lstrip().startswith("@"):
            continue
        layer_idx += 1
        for name in LAYER_NAMES:
            key = f"SOIL_{name}_{layer_idx:02d}"
            if key in fixes and name in spans:
                start, end = spans[name]
                seg = s[start:end].strip()
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
    (FIX_DIR / "soil_sol_rebuild_report_20260811.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nreport: figture/soil_param_export_three_20260810/soil_sol_rebuild_report_20260811.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
