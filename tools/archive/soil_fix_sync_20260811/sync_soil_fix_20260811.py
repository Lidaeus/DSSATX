"""Sync user-fixed soil physical + soil N IC params into bundles (20260811).

Reads the user's two fix files:
  - soil_physical_Fix.csv.xlsx  (48 params: SBDM/SDUL/SLCL/SLLL/SLPF/SLSI/SSAT/SSKS)
  - soil_n_ic_Fix.csv           (220 params: IC_SNH4_*/IC_SNO3_* per treatment/layer)
and writes them into the calibration/plotting bundles (25SP actual_trial v8,
26SP actual_trial v7):

  * SOIL.SOL  — profile IBTM910017: SCOM SLPF row + layer rows
    (SLLL SDUL SSAT SSKS SBDM SLCL SLSI; SSKS/SLCL/SLSI layers 6-8 stay -99)
  * FileX .TMX — initial-conditions ICBL rows: SNH4/SNO3 per treatment/layer

After this sync, soil physical and soil-N IC parameters are NO LONGER
calibrated — the fixed values here are authoritative.

Usage:
    python tools/calibration/sync_soil_fix_20260811.py
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

BUNDLES = {
    "XXQL2501": ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
    "XXQL2601": ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
}
PROFILE = "IBTM910017"
SOIL_LAYER_PARAMS = ["SLLL", "SDUL", "SSAT", "SSKS", "SBDM", "SLCL", "SLSI"]


def _fmt_token(value: float, orig: str) -> str:
    """Format a value to fit the original token's width, DSSAT-style."""
    v = float(value)
    if abs(v) < 1 and (orig.startswith(".") or "." in orig):
        # compact fractional token like .148 / .23
        sign = "-" if v < 0 else ""
        av = abs(v)
        for dec in range(6, 0, -1):
            body = f"{av:.{dec}f}".split(".", 1)[1].rstrip("0")
            if body:
                tok = sign + "." + body
                if len(tok) <= len(orig):
                    return tok.rjust(len(orig))
        return f"{v:.{len(orig)-2}f}".rjust(len(orig))[: len(orig)]
    # general: keep up to the original width
    width = len(orig)
    for dec in range(6, -1, -1):
        tok = f"{v:.{dec}f}"
        if len(tok) <= width:
            return tok.rjust(width)
    return f"{v:.5g}"[:width].rjust(width)


def sync_soil_sol(soil_sol: Path, fixes: dict) -> dict:
    """Rewrite profile IBTM910017 in soil_sol. Returns change summary."""
    lines = soil_sol.read_text(encoding="utf-8", errors="ignore").splitlines()
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
        # SCOM row: SLPF
        if s.lstrip().startswith("@ SCOM"):
            header = [h for h in s.split() if h != "@"]
            data_row = lines[idx + 1]
            parts = data_row.split()
            if "SLPF" in header and "SOIL_SLPF" in fixes:
                pos = header.index("SLPF")
                orig = parts[pos]
                new = _fmt_token(fixes["SOIL_SLPF"], orig)
                if new != orig:
                    cols = list(data_row)
                    # replace token in place at its position
                    start = 0
                    toks = list(re.finditer(r"\S+", data_row))
                    m = toks[pos]
                    cols[m.start() : m.end()] = list(new)
                    lines[idx + 1] = "".join(cols).rstrip() + "\n"
                    changed["SOIL_SLPF"] = (orig.strip(), new.strip())
            continue
        # layer header
        if s.lstrip().startswith("@  SLB"):
            layer_header = [h for h in s.split() if h != "@"]
            layer_idx = 0
            continue
        if layer_header is None:
            continue
        if s.strip() and not s.lstrip().startswith("@"):
            parts = s.split()
            if len(parts) < len(layer_header):
                continue
            layer_idx += 1
            row = dict(zip(layer_header, parts))
            for name in SOIL_LAYER_PARAMS:
                key = f"SOIL_{name}_{layer_idx:02d}"
                if key not in fixes:
                    continue
                if name not in row:
                    continue
                if float(row[name]) <= -90:  # -99 layer: keep missing
                    continue
                orig = row[name]
                new = _fmt_token(fixes[key], orig)
                if new != orig:
                    toks = list(re.finditer(r"\S+", s))
                    pos = layer_header.index(name)
                    cols = list(s)
                    m = toks[pos]
                    cols[m.start() : m.end()] = list(new)
                    lines[idx] = "".join(cols).rstrip() + "\n"
                    changed[key] = (orig.strip(), new.strip())
    soil_sol.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def sync_filex_ic(filex: Path, fixes: dict) -> dict:
    """Rewrite ICBL SNH4/SNO3 rows in FileX. Returns change summary."""
    lines = filex.read_text(encoding="utf-8", errors="ignore").splitlines()
    changed = {}
    in_ic = False
    ic_header = None
    current_tn = None
    layer_by_tn = {}
    for idx, line in enumerate(lines):
        s = line.rstrip("\n")
        u = s.strip().upper()
        if u.startswith("*INITIAL CONDITIONS"):
            in_ic = True
            continue
        if not in_ic:
            continue
        if u.startswith("*") and not u.startswith("*INITIAL CONDITIONS"):
            break
        if s.lstrip().startswith("@C") and "PCR" in u and "ICDAT" in u:
            ic_header = None
            continue
        if s.lstrip().startswith("@C") and "ICBL" in u and "SNH4" in u and "SNO3" in u:
            ic_header = s.split()[1:]
            layer_by_tn[current_tn] = 0 if current_tn is not None else 0
            continue
        if s.lstrip().startswith("@"):
            ic_header = None
            continue
        if ic_header is None or not s.strip():
            # PCR data row: treatment in first column
            parts = s.split()
            if parts:
                try:
                    current_tn = int(float(parts[0]))
                    layer_by_tn[current_tn] = 0
                except ValueError:
                    current_tn = None
            continue
        # ICBL layer row
        parts = s.split()
        if not parts or not parts[0].isdigit():
            continue
        layer_by_tn[current_tn] = layer_by_tn.get(current_tn, 0) + 1
        layer = layer_by_tn[current_tn]
        # locate SNH4/SNO3 columns
        try:
            snh4_pos = ic_header.index("SNH4")
            sno3_pos = ic_header.index("SNO3")
        except ValueError:
            continue
        # find the actual treatment from the row prefix
        m = re.match(r"^\s*(\d+)\s+(\d+)", s)
        if not m:
            continue
        tn = int(m.group(1))
        excode = filex.stem
        keys = {
            snh4_pos: f"IC_SNH4_{excode}_TN{tn:02d}_L{layer:02d}",
            sno3_pos: f"IC_SNO3_{excode}_TN{tn:02d}_L{layer:02d}",
        }
        toks = list(re.finditer(r"\S+", s))
        cols = list(s)
        for pos, key in keys.items():
            if key not in fixes or pos >= len(toks):
                continue
            orig = toks[pos].group(0)
            new = _fmt_token(fixes[key], orig)
            if new != orig:
                m2 = toks[pos]
                cols[m2.start() : m2.end()] = list(new)
                changed[key] = (orig, new)
        if any(k in fixes for k in keys.values()):
            lines[idx] = "".join(cols).rstrip() + "\n"
    filex.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    soil_fix = pd.read_excel(SOIL_FIX_XLSX)
    soil_fixes = dict(zip(soil_fix["param"].astype(str), soil_fix["Fix"].astype(float)))
    ic_fix = pd.read_csv(IC_FIX_CSV)
    ic_fixes = dict(zip(ic_fix["param"].astype(str), ic_fix["Fix"].astype(float)))
    print(f"fix files: soil physical {len(soil_fixes)} params, IC {len(ic_fixes)} params")

    report = {}
    for excode, bundle in BUNDLES.items():
        if not bundle.is_dir():
            print(f"SKIP missing bundle: {bundle}")
            continue
        # SOIL.SOL
        sol = bundle / "SOIL.SOL"
        if sol.is_file():
            ch = sync_soil_sol(sol, soil_fixes)
            report[str(sol)] = {"soil_physical_changed": ch}
            print(f"{sol}  -> {len(ch)} soil params updated")
        # FileX
        tmx = bundle / f"{excode}.TMX"
        if tmx.is_file():
            ch = sync_filex_ic(tmx, ic_fixes)
            report[str(tmx)] = {"ic_changed": ch}
            print(f"{tmx}  -> {len(ch)} IC params updated")

    (ROOT / "figture/soil_param_export_three_20260810/sync_report_20260811.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsync report: figture/soil_param_export_three_20260810/sync_report_20260811.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
