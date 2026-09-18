#!/usr/bin/env python3
"""P0-3/4/5: unified frozen bounds, deterministic acceptance of the three
unified bundles (anchor params WITHOUT season-scoped/xfpht/xfint so the
FileX-approved values are what the model sees), and a PHOSP on/off paired
comparison on 26SP."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.common.param_registry import assert_valid_frozen_bounds

BASE_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v48_del_xfpht_xfint_formal_20260903.csv"
NEW_BOUNDS_ID = "eggplant_e02_unified_baseline_20260914"
NEW_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / f"{NEW_BOUNDS_ID}.csv"
ANCHOR = ROOT / "workspace/reports/e02_formal_v47_free_nscale_20260902_candidates/lowest_phi_params.csv"
WORK = ROOT / "workspace/reports/t0p0_unified_acceptance_20260914b"
DROP_PARAMS = {"xfpht", "xfint", "page_25sp", "penv_25sp", "page_26sp", "penv_26sp",
               "icns_25sp", "icns_26sp", "page_25fa", "penv_25fa"}
FIX_AT = {"PAGE_25SP": 25.0, "PENV_25SP": 20.0, "PAGE_26SP": 24.0, "PENV_26SP": 20.0,
          "ICNS_25SP": 1.0, "ICNS_26SP": 1.0}
SEASONS = {
    "25SP": dict(ex="XXQL2501", bundle=ROOT / "data/user/experiments/xxql2501_unified_20260914",
                 treatments=[2, 3, 4, 5, 9, 10, 11, 12, 13, 14]),
    "26SP": dict(ex="XXQL2601", bundle=ROOT / "data/user/experiments/xxql2601_unified_20260914",
                 treatments=list(range(1, 13))),
    "25FA": dict(ex="XXQL2502", bundle=ROOT / "data/user/experiments/xxql2502_unified_20260914",
                 treatments=list(range(1, 13))),
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def make_bounds() -> str:
    b = pd.read_csv(BASE_BOUNDS, encoding="utf-8-sig")
    names = b["name"].astype(str).str.upper()
    for pname, val in FIX_AT.items():
        m = names.eq(pname)
        assert int(m.sum()) == 1, pname
        b.loc[m, "status"] = "fixed"
        b.loc[m, "init"] = val
        b.loc[m, "lower"] = val
        b.loc[m, "upper"] = val
        b.loc[m, "review_note"] = f"fixed at approved unified-baseline value (T0/P0 D4/D7/D8, 2026-09-14)"
    NEW_BOUNDS.parent.mkdir(parents=True, exist_ok=True)
    b.to_csv(NEW_BOUNDS, index=False, encoding="utf-8-sig")
    assert_valid_frozen_bounds(NEW_BOUNDS)
    n_active = int((b["status"].str.lower() == "active").sum())
    return f"bounds {NEW_BOUNDS_ID}: {n_active} active (was 118)"


def make_design(season: str) -> Path:
    spec = SEASONS[season]
    design = {
        "schema_version": 1, "status": "approved_for_execution",
        "design_id": f"t0p0_unified_acceptance_{season}_20260914",
        "cultivar_identity": "TM0008",
        "purpose": f"T0/P0 P0-4 deterministic acceptance of the unified {season} bundle",
        "observation_policy": "configs/runs/e02_formal_v47_free_nscale_observation_policy_20260901.csv",
        "group_policy": "configs/runs/e02_formal_v48_n_gradient_water2x_group_policy_20260902.csv",
        "bounds_id": NEW_BOUNDS_ID,
        "diagnostic_single_season": True,
        "seasons": [{"season_id": season, "experiment_code": spec["ex"],
                     "bundle_path": str(spec["bundle"].relative_to(ROOT)).replace("\\", "/"),
                     "role": "calibration", "treatments": spec["treatments"]}],
    }
    p = WORK / f"design_{season}.json"
    p.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def run_season(season: str, params_csv: Path, tag: str, bundle_override=None) -> dict:
    spec = dict(SEASONS[season])
    if bundle_override:
        spec["bundle"] = bundle_override
    work = WORK / f"{tag}_{season}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    design = make_design(season)
    if bundle_override:
        d = json.loads(design.read_text(encoding="utf-8"))
        d["seasons"][0]["bundle_path"] = str(bundle_override.relative_to(ROOT)).replace("\\", "/")
        design.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cmd = [sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
           "--design", str(design.resolve()), "--param-csv", str(params_csv.resolve()),
           "--prefix", tag, "--harvest-var", "CHFPW"]
    r = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    ok = r.returncode == 0
    warnings = []
    for f in work.rglob("*.LST"):
        warnings += [l.strip() for l in f.read_text(errors="ignore").splitlines() if "WARN" in l.upper()][:5]
    outs = sorted({f.name for f in work.rglob("Pest*.OUT")})
    return {"season": season, "tag": tag, "ok": ok, "outputs": outs,
            "warnings": warnings[:5], "stdout_tail": (r.stdout.strip().splitlines()[-1] if (ok and r.stdout.strip()) else (r.stderr[-300:] if not ok else ""))}


def main() -> int:
    if WORK.exists():
        raise FileExistsError(WORK)
    WORK.mkdir(parents=True)
    report = {"bounds": make_bounds()}

    # anchor params WITHOUT dropped season-scoped/xfx params: FileX approved
    # values must survive (P0-3 override check)
    params = pd.read_csv(ANCHOR, encoding="utf-8-sig")
    keep = params[~params["name"].astype(str).str.lower().isin(DROP_PARAMS)]
    params_csv = WORK / "anchor_reduced.csv"
    keep.to_csv(params_csv, index=False)
    report["params_dropped"] = sorted(DROP_PARAMS & set(params["name"].astype(str).str.lower()))
    report["params_kept"] = len(keep)

    for season in SEASONS:
        report[f"acceptance_{season}"] = run_season(season, params_csv, "acc")

    # P0-5: PHOSP paired test on 26SP (unified=Y vs temp variant N)
    tmp = WORK / "26sp_phosp_off_variant"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(SEASONS["26SP"]["bundle"], tmp)
    tmx = tmp / "XXQL2601.TMX"
    text = tmx.read_text(encoding="utf-8-sig")
    lines = text.splitlines(keepends=True)
    for j, l in enumerate(lines):
        t = l.split()
        if len(t) >= 6 and t[1] == "OP":
            spans = [(m.start(), m.end()) for m in __import__("re").finditer(r"\S+", l)]
            s, e = spans[4]  # PHOSP switch position (TRNO,OP,W,N,S,PHOSP)
            lines[j] = l[:s] + "N".rjust(e - s) + l[e:]
    tmx.write_text("".join(lines), encoding="utf-8", newline="")
    report["phosp_off_acceptance_26SP"] = run_season("26SP", params_csv, "phosp_off", bundle_override=tmp)
    (WORK / "p0_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
