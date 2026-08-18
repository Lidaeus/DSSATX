"""Apply fixed soil params to ALL active bundles (20260811).

After the initial sync (which covered only the two actual_trial calibration
bundles), this script propagates the fixed soil physical params (SLPF + layer
SLLL/SDUL/SSAT/SSKS/SBDM/SLCL/SLSI) to every active experiment bundle that
shares the IBTM910017 profile, and the fixed IC soil-N values to every
25SP/26SP FileX:

  * SOIL.SOL — all active bundles under data/user/experiments (excluding
    _archive_*), plus data/raw/soil/SOIL.SOL.  Values are written into the
    fixed 6-char columns (SLB=0-5, SLMH=6-11, ...) exactly like
    src/dssat/run_dssat.py reads them.  Only the first IBTM910017 profile in
    each file is modified; other profiles (IBPP910015 etc.) are left alone.
  * FileX ICBL — every XXQL2501/XXQL2601.TMX in active bundles gets the fixed
    SNH4/SNO3 values rewritten in the run_dssat fixed-width layout
    (f"{tn:3d}{depth:6d}{sh2o:>6}{snh4:>6}{sno3:>6}").  XXQL2502 (25FA) has
    no IC fixes and is untouched.

Historical run directories (workspace/runs/.../_seasons) are NOT modified:
they are snapshots copied from the bundles at run time and are regenerated on
every new run.

Usage:
    python tools/calibration/sync_soil_fix_all_bundles_20260811.py
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
IC_FIX_CSV = FIX_DIR / "soil_n_ic_Fix.csv"

PROFILE = "IBTM910017"
# fixed-width field order (6 chars per field, right-justified)
LAYER_FIELDS = ["SLB", "SLMH", "SLLL", "SDUL", "SSAT", "SRGF", "SSKS",
                "SBDM", "SLOC", "SLCL", "SLSI", "SLCF", "SLNI", "SLHW",
                "SLHB", "SCEC", "SADC"]
LAYER_FIX_NAMES = ["SLLL", "SDUL", "SSAT", "SSKS", "SBDM", "SLCL", "SLSI"]
SCOM_FIELDS = ["SCOM", "SALB", "SLU1", "SLDR", "SLRO", "SLNF", "SLPF",
               "SMHB", "SMPX", "SMKE"]
TOKEN_RE = re.compile(r"[-+]?\d*\.?\d+")


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
    start = field_idx * 6
    cols = list(line)
    cols[start : start + 6] = list(new_tok[:6].rjust(6))
    return "".join(cols)


def _is_layer_row(s: str) -> bool:
    return bool(re.match(r"^\s*\d+\s+[-]?\d+\s", s))


def sync_soil_sol(sol: Path, fixes: dict) -> dict:
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
                fidx = SCOM_FIELDS.index("SLPF")
                data_row = lines[idx + 1]
                orig = data_row[fidx * 6 : fidx * 6 + 6].strip()
                new_tok = _fmt(fixes["SOIL_SLPF"], 6, orig)
                lines[idx + 1] = _write_field(data_row, fidx, new_tok)
                changed["SOIL_SLPF"] = (orig, new_tok.strip())
            continue
        if s.lstrip().startswith("@  SLB"):
            layer_idx = 0
            continue
        if layer_idx is None or not s.strip() or s.lstrip().startswith("@"):
            continue
        if not _is_layer_row(s):
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


def sync_filex_ic(tmx: Path, fixes: dict) -> dict:
    lines = tmx.read_text(encoding="utf-8", errors="ignore").splitlines()
    start = end = None
    for i, l in enumerate(lines):
        u = l.strip().upper()
        if u.startswith("*INITIAL CONDITIONS"):
            start = i
        elif start is not None and u.startswith("*") and not u.startswith("*INITIAL CONDITIONS"):
            end = i
            break
    if end is None:
        end = len(lines)
    if start is None:
        return {}
    excode = tmx.stem
    changed = {}
    in_layer = False
    current_tn = None
    layer_by_tn = {}
    for idx in range(start, end):
        s = lines[idx].rstrip("\n")
        u = s.strip().upper()
        if not u:
            continue
        if s.lstrip().startswith("@C") and "PCR" in u and "ICDAT" in u:
            in_layer = False
            continue
        if s.lstrip().startswith("@C") and "ICBL" in u and "SNH4" in u and "SNO3" in u:
            in_layer = True
            continue
        if s.lstrip().startswith("@"):
            in_layer = False
            continue
        parts = s.split()
        if not in_layer:
            if parts:
                try:
                    current_tn = int(float(parts[0]))
                    layer_by_tn[current_tn] = 0
                except ValueError:
                    current_tn = None
            continue
        if current_tn is None or not parts or not parts[0].isdigit():
            continue
        layer_by_tn[current_tn] = layer_by_tn.get(current_tn, 0) + 1
        layer = layer_by_tn[current_tn]
        m = re.match(r"^\s*(\d+)\s+(\d+)", s)
        if not m:
            continue
        depth = int(m.group(2))
        sem = TOKEN_RE.findall(s[m.end():])
        if len(sem) < 3:
            continue
        sh2o, snh4, sno3 = sem[0], sem[1], sem[2]
        snh4_key = f"IC_SNH4_{excode}_TN{current_tn:02d}_L{layer:02d}"
        sno3_key = f"IC_SNO3_{excode}_TN{current_tn:02d}_L{layer:02d}"
        new_snh4 = f"{fixes[snh4_key]:.6g}" if snh4_key in fixes else snh4
        new_sno3 = f"{fixes[sno3_key]:.6g}" if sno3_key in fixes else sno3
        if snh4_key in fixes:
            changed[snh4_key] = (snh4, new_snh4)
        if sno3_key in fixes:
            changed[sno3_key] = (sno3, new_sno3)
        lines[idx] = (
            f"{current_tn:3d}{depth:6d}"
            f"{str(sh2o).rjust(6)}"
            f"{str(new_snh4).rjust(6)}"
            f"{str(new_sno3).rjust(6)}\n"
        )
    tmx.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    soil_fix = pd.read_excel(SOIL_FIX_XLSX)
    soil_fixes = dict(zip(soil_fix["param"].astype(str), soil_fix["Fix"].astype(float)))
    ic_fix = pd.read_csv(IC_FIX_CSV)
    ic_fixes = dict(zip(ic_fix["param"].astype(str), ic_fix["Fix"].astype(float)))

    report = {"soil_sol": {}, "filex_ic": {}}

    # ---- SOIL.SOL: every active bundle + raw ----
    exp_root = ROOT / "data/user/experiments"
    sol_paths = sorted(exp_root.glob("*/SOIL.SOL"))
    sol_paths = [p for p in sol_paths if "_archive" not in str(p)]
    raw_sol = ROOT / "data/raw/soil/SOIL.SOL"
    if raw_sol.is_file():
        sol_paths.append(raw_sol)
    for sol in sol_paths:
        ch = sync_soil_sol(sol, soil_fixes)
        report["soil_sol"][str(sol)] = {"changed": len(ch)}
        print(f"{sol.relative_to(ROOT)}: {len(ch)} values")

    # ---- FileX IC: XXQL2501/XXQL2601 only ----
    tmx_paths = sorted(exp_root.glob("*/XXQL2501.TMX")) + sorted(exp_root.glob("*/XXQL2601.TMX"))
    tmx_paths = [p for p in tmx_paths if "_archive" not in str(p)]
    for tmx in tmx_paths:
        ch = sync_filex_ic(tmx, ic_fixes)
        report["filex_ic"][str(tmx)] = {"changed": len(ch)}
        print(f"{tmx.relative_to(ROOT)}: {len(ch)} IC values")

    (FIX_DIR / "sync_all_bundles_report_20260811.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nreport: figture/soil_param_export_three_20260810/sync_all_bundles_report_20260811.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
