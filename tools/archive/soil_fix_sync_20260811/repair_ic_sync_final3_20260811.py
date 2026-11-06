"""Final repair v3: rebuild bundle FileX IC section with fixed-width rewrite (20260811).

Rebuilds the *INITIAL CONDITIONS ICBL rows of each bundle FileX from the
pristine reference copy, then rewrites each row in DSSAT fixed-width layout
exactly like src/dssat/run_dssat.py does:

    f"{tn:3d}{depth:6d}{sh2o.rjust(6)}{snh4.rjust(6)}{sno3.rjust(6)}"

with numeric tokens rendered at 6g precision (never truncated by the old
token's width, which lost precision for values like 1.6 in a 1-char slot).

Rows for treatments NOT in the fix file keep the reference values.

Usage:
    python tools/calibration/repair_ic_sync_final3_20260811.py
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


def _fixed_n_token(value, fallback):
    """Render a numeric token at 6g precision; matches run_dssat behavior."""
    if value is None:
        return fallback
    v = float(value)
    rendered = f"{v:.6g}"
    if len(rendered) > 6:
        rendered = f"{v:.5g}"
    if len(rendered) > 6:
        rendered = f"{v:.4g}"
    if len(rendered) > 6:
        raise ValueError(f"value {value} does not fit FileX 6-char field")
    return rendered


def _ic_section(lines: list[str]):
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
    """Yield (idx, tn, layer, sh2o, snh4, sno3) with raw row string."""
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
        depth = int(m.group(2))
        sem = TOKEN_RE.findall(s[m.end():])
        if len(sem) >= 3:
            yield idx, current_tn, layer_by_tn[current_tn], depth, sem[0], sem[1], sem[2], s


def repair(bundle: Path, ref: Path, fixes: dict) -> dict:
    blines = bundle.read_text(encoding="utf-8", errors="ignore").splitlines()
    rlines = ref.read_text(encoding="utf-8", errors="ignore").splitlines()
    bstart, bend = _ic_section(blines)
    rstart, rend = _ic_section(rlines)
    if bstart is None or rstart is None:
        raise RuntimeError("INITIAL CONDITIONS section missing")

    # 1) rebuild IC section from reference
    new_section = rlines[rstart:rend]
    blines[bstart:bend] = new_section
    excode = bundle.stem

    # 2) rewrite each ICBL row in fixed-width layout with fix values
    applied = 0
    for idx, tn, layer, depth, sh2o, snh4, sno3, _ in _icbl_rows(blines, bstart, bstart + len(new_section)):
        snh4_key = f"IC_SNH4_{excode}_TN{tn:02d}_L{layer:02d}"
        sno3_key = f"IC_SNO3_{excode}_TN{tn:02d}_L{layer:02d}"
        new_sh2o = sh2o
        new_snh4 = _fixed_n_token(fixes[snh4_key], snh4) if snh4_key in fixes else snh4
        new_sno3 = _fixed_n_token(fixes[sno3_key], sno3) if sno3_key in fixes else sno3
        if snh4_key in fixes or sno3_key in fixes:
            applied += 1
        blines[idx] = (
            f"{tn:3d}{depth:6d}"
            f"{str(new_sh2o).rjust(6)}"
            f"{str(new_snh4).rjust(6)}"
            f"{str(new_sno3).rjust(6)}\n"
        )
    bundle.write_text("\n".join(blines) + "\n", encoding="utf-8")
    return {"rows_rewritten": applied}


def verify(bundle: Path, ref: Path, fixes: dict) -> dict:
    blines = bundle.read_text(encoding="utf-8", errors="ignore").splitlines()
    rlines = ref.read_text(encoding="utf-8", errors="ignore").splitlines()
    bstart, bend = _ic_section(blines)
    rstart, rend = _ic_section(rlines)
    excode = bundle.stem
    bmap = {(tn, lyr): (s0, s1, s2) for _, tn, lyr, _, s0, s1, s2, _ in _icbl_rows(blines, bstart, bend)}
    rmap = {(tn, lyr): (s0, s1, s2) for _, tn, lyr, _, s0, s1, s2, _ in _icbl_rows(rlines, rstart, rend)}
    issues = []
    checked = 0
    for (tn, lyr), (s0, s1, s2) in sorted(rmap.items()):
        if (tn, lyr) not in bmap:
            issues.append(f"TN{tn} L{lyr} missing")
            continue
        b0, b1, b2 = bmap[(tn, lyr)]
        if float(b0) != float(s0):
            issues.append(f"TN{tn} L{lyr} SH2O {b0} != ref {s0}")
        snh4_key = f"IC_SNH4_{excode}_TN{tn:02d}_L{lyr:02d}"
        sno3_key = f"IC_SNO3_{excode}_TN{tn:02d}_L{lyr:02d}"
        want1 = _fixed_n_token(fixes[snh4_key], s1) if snh4_key in fixes else s1
        want2 = _fixed_n_token(fixes[sno3_key], s2) if sno3_key in fixes else s2
        if float(b1) != float(want1):
            issues.append(f"TN{tn} L{lyr} SNH4 {b1} != {want1}")
        if float(b2) != float(want2):
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

    (FIX_DIR / "repair_report_final3_20260811.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nfinal3 repair report: figture/soil_param_export_three_20260810/repair_report_final3_20260811.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
