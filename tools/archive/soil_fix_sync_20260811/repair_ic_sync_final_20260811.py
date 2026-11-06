"""Final repair: rebuild bundle FileX IC section from pristine reference (20260811).

The earlier sync wrote IC_SNH4_* into the SH2O token and IC_SNO3_* into the
SNH4 token (ICBL data rows carry 5 tokens — TN ICBL SH2O SNH4 SNO3 — while the
header lists 4 columns because @C is the treatment), and two repair attempts
further corrupted the file.  This script:

  1. Rebuilds the whole *INITIAL CONDITIONS section of each bundle FileX from
     the pristine reference copy (data/user/experiments/XXQL2501|XXQL2601/
     XXQL2501|XXQL2601.TMX), which matches the pre-sync bundle values 100%
     (verified against the sync report's recorded originals).
  2. Applies the fixed SNH4/SNO3 values with run_dssat-style semantic parsing
     (stable TN+depth prefix, remaining numeric tokens = SH2O SNH4 SNO3).
  3. Verifies every ICBL row: SH2O equals the reference, SNH4/SNO3 equal the
     fixed values (formatted to the reference token width).

Usage:
    python tools/calibration/repair_ic_sync_final_20260811.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FIX_DIR = ROOT / "figture/soil_param_export_three_20260810"
IC_FIX_CSV = FIX_DIR / "soil_n_ic_Fix.csv"

BUNDLES = {
    "XXQL2501": ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
    "XXQL2601": ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
}
REFERENCES = {
    "XXQL2501": ROOT / "data/user/experiments/XXQL2501/XXQL2501.TMX",
    "XXQL2601": ROOT / "data/user/experiments/XXQL2601/XXQL2601.TMX",
}
TOKEN_RE = re.compile(r"[-+]?\d*\.?\d+")


def _fmt_token(value: float, orig: str) -> str:
    v = float(value)
    if abs(v) < 1 and (orig.startswith(".") or "." in orig):
        sign = "-" if v < 0 else ""
        av = abs(v)
        for dec in range(6, 0, -1):
            body = f"{av:.{dec}f}".split(".", 1)[1].rstrip("0")
            if body:
                tok = sign + "." + body
                if len(tok) <= len(orig):
                    return tok.rjust(len(orig))
        return f"{v:.{len(orig)-2}f}".rjust(len(orig))[: len(orig)]
    width = len(orig)
    for dec in range(6, -1, -1):
        tok = f"{v:.{dec}f}"
        if len(tok) <= width:
            return tok.rjust(width)
    return f"{v:.5g}"[:width].rjust(width)


def _ic_section(lines: list[str]):
    """Return (start_idx, end_idx) of *INITIAL CONDITIONS section."""
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
    return start, end


def _icbl_rows(lines: list[str], start: int, end: int):
    """Yield (idx, tn, layer, sh2o, snh4, sno3) for ICBL rows in section."""
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
        m = re.match(r"^\s*(\d+)\s+(\d+)", s)
        if not m:
            continue
        sem = TOKEN_RE.findall(s[m.end():])
        if len(sem) >= 3:
            yield idx, current_tn, layer_by_tn[current_tn], sem[0], sem[1], sem[2]


def _replace_semantic(line: str, token_index: int, new: str) -> str:
    """Replace token_index-th semantic token (0=SH2O, 1=SNH4, 2=SNO3)."""
    m = re.match(r"^\s*(\d+)\s+(\d+)", line)
    if not m:
        return line
    tail_start = m.end()
    toks = list(TOKEN_RE.finditer(line[tail_start:]))
    if token_index >= len(toks):
        return line
    t = toks[token_index]
    start, end = tail_start + t.start(), tail_start + t.end()
    return line[:start] + new + line[end:]


def repair(bundle: Path, ref: Path, fixes: dict) -> dict:
    blines = bundle.read_text(encoding="utf-8", errors="ignore").splitlines()
    rlines = ref.read_text(encoding="utf-8", errors="ignore").splitlines()
    bstart, bend = _ic_section(blines)
    rstart, rend = _ic_section(rlines)
    if bstart is None or rstart is None:
        raise RuntimeError("INITIAL CONDITIONS section missing")

    # 1) sanity: reference rows == expected count
    ref_rows = list(_icbl_rows(rlines, rstart, rend))
    print(f"  reference ICBL rows: {len(ref_rows)}")

    # 2) rebuild bundle IC section from reference (preserve section headers)
    new_section = rlines[rstart:rend]
    blines[bstart:bend] = new_section

    # 3) apply fixes with correct semantics
    applied = 0
    excode = bundle.stem
    for idx, tn, layer, sh2o, snh4, sno3 in _icbl_rows(blines, bstart, bstart + len(new_section)):
        snh4_key = f"IC_SNH4_{excode}_TN{tn:02d}_L{layer:02d}"
        sno3_key = f"IC_SNO3_{excode}_TN{tn:02d}_L{layer:02d}"
        if snh4_key in fixes:
            new = _fmt_token(fixes[snh4_key], snh4)
            if new != snh4:
                blines[idx] = _replace_semantic(blines[idx], 1, new)
                applied += 1
        if sno3_key in fixes:
            new = _fmt_token(fixes[sno3_key], sno3)
            if new != sno3:
                blines[idx] = _replace_semantic(blines[idx], 2, new)
                applied += 1
    bundle.write_text("\n".join(blines) + "\n", encoding="utf-8")
    return {"reference_rows": len(ref_rows), "applied": applied}


def verify(bundle: Path, ref: Path, fixes: dict) -> dict:
    blines = bundle.read_text(encoding="utf-8", errors="ignore").splitlines()
    rlines = ref.read_text(encoding="utf-8", errors="ignore").splitlines()
    bstart, bend = _ic_section(blines)
    rstart, rend = _ic_section(rlines)
    excode = bundle.stem
    issues = []
    checked = 0
    bmap = {(tn, lyr): (s0, s1, s2) for _, tn, lyr, s0, s1, s2 in _icbl_rows(blines, bstart, bend)}
    rmap = {(tn, lyr): (s0, s1, s2) for _, tn, lyr, s0, s1, s2 in _icbl_rows(rlines, rstart, rend)}
    for (tn, lyr), (s0, s1, s2) in sorted(rmap.items()):
        if (tn, lyr) not in bmap:
            issues.append(f"TN{tn} L{lyr} missing")
            continue
        b0, b1, b2 = bmap[(tn, lyr)]
        if b0 != s0:
            issues.append(f"TN{tn} L{lyr} SH2O {b0} != ref {s0}")
        snh4_key = f"IC_SNH4_{excode}_TN{tn:02d}_L{lyr:02d}"
        sno3_key = f"IC_SNO3_{excode}_TN{tn:02d}_L{lyr:02d}"
        want1 = _fmt_token(fixes[snh4_key], s1) if snh4_key in fixes else s1
        want2 = _fmt_token(fixes[sno3_key], s2) if sno3_key in fixes else s2
        if b1 != want1:
            issues.append(f"TN{tn} L{lyr} SNH4 {b1} != {want1}")
        if b2 != want2:
            issues.append(f"TN{tn} L{lyr} SNO3 {b2} != {want2}")
        checked += 1
    return {"rows_checked": checked, "issue_count": len(issues), "issues": issues[:15]}


def main() -> int:
    ic_fix = pd.read_csv(IC_FIX_CSV)
    fixes = dict(zip(ic_fix["param"].astype(str), ic_fix["Fix"].astype(float)))

    out = {}
    for excode, bundle in BUNDLES.items():
        tmx = bundle / f"{excode}.TMX"
        ref = REFERENCES[excode]
        print(f"=== {tmx}")
        res = repair(tmx, ref, fixes)
        print(f"  repair: {res}")
        ver = verify(tmx, ref, fixes)
        print(f"  verify: rows={ver['rows_checked']} issues={ver['issue_count']}")
        for iss in ver["issues"]:
            print(f"    ! {iss}")
        out[str(tmx)] = {"repair": res, "verify": ver}

    (FIX_DIR / "repair_report_final_20260811.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nfinal repair report: figture/soil_param_export_three_20260810/repair_report_final_20260811.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
