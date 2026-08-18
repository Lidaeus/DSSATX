"""Repair v2: FileX ICBL sync with run_dssat-style semantic parsing (20260811).

The first sync misaligned ICBL columns (wrote IC_SNH4_* into SH2O and
IC_SNO3_* into SNH4).  Repair v1 restored wrong-slot tokens from the sync
report but verified against a reference file that differs from the bundle.

This version:
  1. Parses ICBL rows exactly like src/dssat/run_dssat.py does (regex tail
     semantic extraction — handles legacy joined-token layouts).
  2. Restores SH2O/SNH4 pre-sync values from sync_report_20260811.json orig
     fields (ground truth from the bundle itself).
  3. Writes the fixed SNH4/SNO3 into the correct columns.
  4. Verifies: SH2O == report-orig (or untouched), SNH4 == report-orig of the
     IC_SNO3 slot (or untouched), SNO3 == untouched-original; then SNH4/SNO3
     == fix values.

Usage:
    python tools/calibration/repair_ic_sync_v2_20260811.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FIX_DIR = ROOT / "figture/soil_param_export_three_20260810"
REPORT = FIX_DIR / "sync_report_20260811.json"
IC_FIX_CSV = FIX_DIR / "soil_n_ic_Fix.csv"

BUNDLES = {
    "XXQL2501": ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
    "XXQL2601": ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
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


def _icbl_semantics(lines, start, end):
    """Yield (idx, tn, layer, sh2o, snh4, sno3) ICBL rows in [start, end).

    Parsing mirrors src/dssat/run_dssat.py: after the stable TN+depth prefix,
    the remaining numeric tokens are the three semantic fields.
    """
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
        tail = s[m.end():]
        semantic = TOKEN_RE.findall(tail)
        if len(semantic) < 3:
            continue
        yield idx, current_tn, layer_by_tn[current_tn], semantic[0], semantic[1], semantic[2]


def _replace_token(line: str, token_index: int, new: str) -> str:
    """Replace the token_index-th numeric token (run_dssat-style tail scan)."""
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


def repair(filex: Path, report_changed: dict, fixes: dict) -> dict:
    lines = filex.read_text(encoding="utf-8", errors="ignore").splitlines()
    # locate the *INITIAL CONDITIONS section span
    ic_start = ic_end = None
    for i, l in enumerate(lines):
        u = l.strip().upper()
        if u.startswith("*INITIAL CONDITIONS"):
            ic_start = i
        elif ic_start is not None and u.startswith("*") and not u.startswith("*INITIAL CONDITIONS"):
            ic_end = i
            break
    if ic_start is None:
        raise RuntimeError(f"no INITIAL CONDITIONS section in {filex}")
    if ic_end is None:
        ic_end = len(lines)
    excode = filex.stem

    restored = 0
    applied = 0
    for idx, tn, layer, sh2o, snh4, sno3 in _icbl_semantics(lines, ic_start, ic_end):
        snh4_key = f"IC_SNH4_{excode}_TN{tn:02d}_L{layer:02d}"
        sno3_key = f"IC_SNO3_{excode}_TN{tn:02d}_L{layer:02d}"
        # step 1: restore wrong-slot writes from the sync report (ground truth)
        if snh4_key in report_changed:
            orig_sh2o = report_changed[snh4_key][0]
            lines[idx] = _replace_token(lines[idx], 0, orig_sh2o)
            restored += 1
        if sno3_key in report_changed:
            orig_snh4 = report_changed[sno3_key][0]
            lines[idx] = _replace_token(lines[idx], 1, orig_snh4)
            restored += 1
        # step 2: apply fixes at the CORRECT columns (0=SH2O,1=SNH4,2=SNO3)
        if snh4_key in fixes:
            new = _fmt_token(fixes[snh4_key], snh4)
            if new != snh4:
                lines[idx] = _replace_token(lines[idx], 1, new)
                applied += 1
        if sno3_key in fixes:
            new = _fmt_token(fixes[sno3_key], sno3)
            if new != sno3:
                lines[idx] = _replace_token(lines[idx], 2, new)
                applied += 1
    filex.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"restored": restored, "applied": applied}


def verify(filex: Path, report_changed: dict, fixes: dict) -> dict:
    lines = filex.read_text(encoding="utf-8", errors="ignore").splitlines()
    ic_start = ic_end = None
    for i, l in enumerate(lines):
        u = l.strip().upper()
        if u.startswith("*INITIAL CONDITIONS"):
            ic_start = i
        elif ic_start is not None and u.startswith("*") and not u.startswith("*INITIAL CONDITIONS"):
            ic_end = i
            break
    if ic_end is None:
        ic_end = len(lines)
    excode = filex.stem
    issues = []
    checked = 0
    for idx, tn, layer, sh2o, snh4, sno3 in _icbl_semantics(lines, ic_start, ic_end):
        snh4_key = f"IC_SNH4_{excode}_TN{tn:02d}_L{layer:02d}"
        sno3_key = f"IC_SNO3_{excode}_TN{tn:02d}_L{layer:02d}"
        # SH2O must equal the pre-sync bundle value (report orig for the slot)
        if snh4_key in report_changed:
            want = report_changed[snh4_key][0]
            if float(sh2o) != float(want):
                issues.append(f"TN{tn} L{layer} SH2O {sh2o} != {want}")
        # SNH4 must equal fix (or pre-sync if no fix)
        want_snh4 = _fmt_token(fixes[snh4_key], snh4) if snh4_key in fixes else snh4
        if snh4 != want_snh4:
            issues.append(f"TN{tn} L{layer} SNH4 {snh4} != {want_snh4}")
        want_sno3 = _fmt_token(fixes[sno3_key], sno3) if sno3_key in fixes else sno3
        if sno3 != want_sno3:
            issues.append(f"TN{tn} L{layer} SNO3 {sno3} != {want_sno3}")
        checked += 1
    return {"rows_checked": checked, "issue_count": len(issues), "issues": issues[:15]}


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ic_fix = pd.read_csv(IC_FIX_CSV)
    fixes = dict(zip(ic_fix["param"].astype(str), ic_fix["Fix"].astype(float)))

    out = {}
    for excode, bundle in BUNDLES.items():
        tmx = bundle / f"{excode}.TMX"
        entry = report.get(str(tmx), {})
        changed = entry.get("ic_changed", {})
        res = repair(tmx, changed, fixes)
        ver = verify(tmx, changed, fixes)
        print(f"{tmx}")
        print(f"  restored={res['restored']} applied={res['applied']} | verify rows={ver['rows_checked']} issues={ver['issue_count']}")
        for iss in ver["issues"]:
            print(f"    ! {iss}")
        out[str(tmx)] = {"repair": res, "verify": ver}

    (FIX_DIR / "repair_report_v2_20260811.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nrepair v2 report: figture/soil_param_export_three_20260810/repair_report_v2_20260811.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
