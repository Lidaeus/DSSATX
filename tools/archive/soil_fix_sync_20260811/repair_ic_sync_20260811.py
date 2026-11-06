"""Repair the misaligned FileX ICBL sync (20260811).

The first sync wrote IC_SNH4_* into the SH2O token and IC_SNO3_* into the
SNH4 token (the ICBL data rows carry 5 tokens: TN ICBL SH2O SNH4 SNO3, while
the header has 4 columns because @C is the treatment).  This script:

  1. Restores every touched token to its pre-sync value recorded in
     sync_report_20260811.json (orig fields).
  2. Re-applies the fixed IC values with the correct column positions.
  3. Verifies the result against the pristine reference copy
     (data/user/experiments/XXQL2501|XXQL2601/XXQL2501|XXQL2601.TMX).

Usage:
    python tools/calibration/repair_ic_sync_20260811.py
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
# pristine reference (pre-sync ICBL): the user experiment copies
REFERENCE = {
    "XXQL2501": ROOT / "data/user/experiments/XXQL2501/XXQL2501.TMX",
    "XXQL2601": ROOT / "data/user/experiments/XXQL2601/XXQL2601.TMX",
}


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


def _icbl_rows(filex: Path):
    """Yield (idx, line, tn, layer, tokens) for every ICBL layer row."""
    lines = filex.read_text(encoding="utf-8", errors="ignore").splitlines()
    in_ic = False
    table_cols = None
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
            table_cols = None
            continue
        if s.lstrip().startswith("@C") and "ICBL" in u and "SH2O" in u and "SNH4" in u and "SNO3" in u:
            table_cols = s.split()[1:]
            continue
        if s.lstrip().startswith("@"):
            table_cols = None
            continue
        parts = s.split()
        if table_cols is None:
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
        yield idx, s, current_tn, layer_by_tn[current_tn], parts
    return


def restore_and_resync(filex: Path, report_changed: dict, fixes: dict) -> dict:
    lines = filex.read_text(encoding="utf-8", errors="ignore").splitlines()
    excode = filex.stem
    restored = []
    for idx, s, tn, layer, parts in _icbl_rows(filex):
        # tokens: [TN, ICBL, SH2O, SNH4, SNO3]
        if len(parts) < 5:
            continue
        keys = {
            2: f"IC_SNH4_{excode}_TN{tn:02d}_L{layer:02d}",   # wrote SH2O wrongly
            3: f"IC_SNO3_{excode}_TN{tn:02d}_L{layer:02d}",   # wrote SNH4 wrongly
        }
        toks = list(re.finditer(r"\S+", s))
        cols = list(s)
        # step 1: restore pre-sync values (from report orig) at the WRONG slots
        for pos, key in keys.items():
            if key in report_changed:
                orig = report_changed[key][0]
                m = toks[pos]
                if cols[m.start() : m.end()] != list(orig):
                    cols[m.start() : m.end()] = list(orig.rjust(m.end() - m.start()))
                    restored.append((key, pos, orig))
        # step 2: apply the fixed value at the CORRECT slot
        snh4_key = f"IC_SNH4_{excode}_TN{tn:02d}_L{layer:02d}"
        sno3_key = f"IC_SNO3_{excode}_TN{tn:02d}_L{layer:02d}"
        for pos, key in ((3, snh4_key), (4, sno3_key)):
            if key in fixes and pos < len(toks):
                orig_tok = toks[pos].group(0)
                new = _fmt_token(fixes[key], orig_tok)
                if new != orig_tok:
                    m = toks[pos]
                    cols[m.start() : m.end()] = list(new)
        lines[idx] = "".join(cols).rstrip() + "\n"
    filex.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"restored": restored}


def verify(filex: Path, ref: Path, fixes: dict) -> dict:
    """Check the repaired file against the pristine reference + fixes."""
    def snapshot(path):
        out = {}
        for idx, s, tn, layer, parts in _icbl_rows(path):
            if len(parts) < 5:
                continue
            out[(tn, layer)] = {"sh2o": parts[2], "snh4": parts[3], "sno3": parts[4]}
        return out
    cur = snapshot(filex)
    refd = snapshot(ref)
    issues = []
    ok = 0
    excode = filex.stem
    for (tn, layer), cv in cur.items():
        rv = refd.get((tn, layer))
        if rv is None:
            continue
        # SH2O must equal reference (never touched by fixes)
        if cv["sh2o"] != rv["sh2o"]:
            issues.append(f"TN{tn} L{layer} SH2O {cv['sh2o']} != ref {rv['sh2o']}")
            continue
        # SNH4/SNO3 must equal the fixed values (formatted)
        snh4_fix = fixes.get(f"IC_SNH4_{excode}_TN{tn:02d}_L{layer:02d}")
        sno3_fix = fixes.get(f"IC_SNO3_{excode}_TN{tn:02d}_L{layer:02d}")
        want_snh4 = _fmt_token(snh4_fix, rv["snh4"]) if snh4_fix is not None else rv["snh4"]
        want_sno3 = _fmt_token(sno3_fix, rv["sno3"]) if sno3_fix is not None else rv["sno3"]
        if cv["snh4"] != want_snh4:
            issues.append(f"TN{tn} L{layer} SNH4 {cv['snh4']} != {want_snh4}")
        if cv["sno3"] != want_sno3:
            issues.append(f"TN{tn} L{layer} SNO3 {cv['sno3']} != {want_sno3}")
        ok += 1
    return {"rows_checked": ok, "issues": issues[:20], "issue_count": len(issues)}


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ic_fix = pd.read_csv(IC_FIX_CSV)
    fixes = dict(zip(ic_fix["param"].astype(str), ic_fix["Fix"].astype(float)))

    out_report = {}
    for excode, bundle in BUNDLES.items():
        tmx = bundle / f"{excode}.TMX"
        ref = REFERENCE[excode]
        # collect report changed entries for this file
        entry = report.get(str(tmx), {})
        changed = entry.get("ic_changed", {})
        res = restore_and_resync(tmx, changed, fixes)
        ver = verify(tmx, ref, fixes)
        print(f"{tmx}")
        print(f"  restored {len(res['restored'])} wrong-slot tokens")
        print(f"  verify: {ver['rows_checked']} rows, {ver['issue_count']} issues")
        for iss in ver["issues"]:
            print(f"    ! {iss}")
        out_report[str(tmx)] = {"restored": res["restored"], "verify": ver}

    (FIX_DIR / "repair_report_20260811.json").write_text(
        json.dumps(out_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nrepair report: figture/soil_param_export_three_20260810/repair_report_20260811.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
