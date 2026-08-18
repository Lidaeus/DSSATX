#!/usr/bin/env python3
"""Run a small deterministic factorial around NSTFAC/RTNO3/CMOBMX boundaries.

The starting vector is member 55 of the historical over-response run.  The
experiment is diagnostic only: no PEST objective is evaluated and no formal
calibration files are changed.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BASE_RUN = ROOT / "workspace/runs/e02_joint61_25sp25fa_validic_n012_no_nresponse_formal_200x5_20260801"
DESIGN_SOURCE = ROOT / "configs/runs/eggplant_e02_wnstress_fourcorner_design_v1_20260801.json"
OUT = ROOT / "workspace/runs/wn_response_boundary_combos_20260802_dmfr005"
MAP = {
    "25SP": {2: ("W3", "N3"), 3: ("W3", "N2"), 4: ("W3", "N1"), 5: ("W3", "N0"),
             10: ("W1", "N3"), 11: ("W1", "N2"), 12: ("W1", "N1"), 13: ("W1", "N0")},
    "26SP": {1: ("W3", "N3"), 4: ("W3", "N2"), 7: ("W3", "N1"), 9: ("W3", "N0"),
             3: ("W1", "N3"), 6: ("W1", "N2"), 10: ("W1", "N1"), 12: ("W1", "N0")},
}
COMBOS = [
    ("high_high_high", 1.00, 0.050, 0.046168),
    ("low_low_low", 0.30, 0.005, 0.005),
    ("mid_mid_mid", 0.65, 0.025, 0.025),
    ("low_high_high", 0.30, 0.050, 0.046168),
    ("high_low_low", 1.00, 0.005, 0.005),
    ("low_low_high", 0.30, 0.005, 0.046168),
    ("low_high_low", 0.30, 0.050, 0.005),
    ("high_low_high", 1.00, 0.005, 0.046168),
    ("high_high_low", 1.00, 0.050, 0.005),
    # Local refinement around the only region that lifted N0 without making
    # the N3-N0 slope explode: high NSTFAC with low-to-middle RTNO3.
    ("high_low_quarter", 1.00, 0.005, 0.015),
    ("high_low_mid", 1.00, 0.005, 0.025),
    ("high_mid_low", 1.00, 0.025, 0.005),
    ("high_mid_mid", 1.00, 0.025, 0.025),
    ("mid_low_mid", 0.65, 0.005, 0.025),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def make_design() -> Path:
    design = json.loads(DESIGN_SOURCE.read_text(encoding="utf-8"))
    # Use every N level available in both spring bundles, not only the two
    # corners, so the diagnostic can quantify N1/N2 as well as N3-N0.
    for s in design["seasons"]:
        if s["season_id"] == "25SP":
            s["treatments"] = [2, 3, 4, 5, 10, 11, 12, 13]
        elif s["season_id"] == "26SP":
            s["treatments"] = [1, 3, 4, 6, 7, 9, 10, 12]
        bundle = ROOT / s["bundle_path"]
        manifest = bundle / "input_manifest.json"
        if manifest.exists():
            s["bundle_manifest_sha256"] = sha256(manifest)
        # The scheduler requires at least two calibration seasons; this is a
        # deterministic diagnostic, but the seasons remain structurally
        # calibration rows in the temporary design.
        s["role"] = "calibration"
    design["design_id"] = "e02_wnstress_boundary_combo_diagnostic_20260802"
    design["diagnostic_contract"] = {
        "base_run": str(BASE_RUN),
        "fruit_moisture_truth": "fixed fruit moisture=95%; DMC/DMFR=0.05",
        "no_pest_objective": True,
        "parameters_varied": ["NSTFAC", "RTNO3", "CMOBMX"],
    }
    path = OUT / "diagnostic_design.json"
    path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def base_parameters() -> pd.DataFrame:
    pst = next(BASE_RUN.glob("*.pst"))
    par = pd.read_csv(BASE_RUN / f"{pst.stem}.5.par.csv")
    row = par[par.real_name.astype(str).eq("55")].iloc[0]
    return pd.DataFrame({"name": [c.upper() for c in par.columns if c != "real_name"],
                         "value": [float(row[c]) for c in par.columns if c != "real_name"]})


def harvest(path: Path) -> pd.DataFrame:
    rows = []
    pat = re.compile(r"RUN\s+(\d+)\s+TN\s+(\d+)\s+HNO\s+(\d+)\s+DATE\s+(\d+).*?@CHPDTS@\s+([-+0-9.eE]+)")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = pat.search(line)
        if m:
            rows.append({"global_run": int(m.group(1)), "treatment": int(m.group(2)),
                         "hno": int(m.group(3)), "date": int(m.group(4)), "chpdt": float(m.group(5))})
    return pd.DataFrame(rows)


def observed_terminal() -> pd.DataFrame:
    rows = []
    bundle_map = {
        "25SP": "xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
        "26SP": "xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
    }
    for season, bundle_name in bundle_map.items():
        path = ROOT / "data/user/experiments" / bundle_name / "FileT_values.csv"
        df = pd.read_csv(path)
        df["TRNO"] = pd.to_numeric(df["TRNO"], errors="coerce")
        df["CHPDT"] = pd.to_numeric(df["CHPDT"], errors="coerce")
        df = df[df["CHPDT"].notna()].sort_values("DATE").groupby("TRNO", as_index=False).tail(1)
        for r in df.itertuples(index=False):
            treatment = int(r.TRNO)
            if treatment not in MAP[season]:
                continue
            water, nitrogen = MAP[season][treatment]
            rows.append({"season": season, "water": water, "nitrogen": nitrogen,
                         "treatment": treatment, "observed_CHPDT": float(r.CHPDT)})
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    design = make_design()
    base = base_parameters()
    all_rows = []
    for label, nstfac, rtno3, cmobmx in COMBOS:
        case = OUT / label
        if case.exists():
            shutil.rmtree(case)
        case.mkdir(parents=True)
        params = base.copy()
        params.loc[params.name.eq("NSTFAC"), "value"] = nstfac
        params.loc[params.name.eq("RTNO3"), "value"] = rtno3
        params.loc[params.name.eq("CMOBMX"), "value"] = cmobmx
        param_csv = case / "parameters.csv"
        params.to_csv(param_csv, index=False)
        cmd = [sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
               "--design", str(design), "--param-csv", str(param_csv),
               "--prefix", label, "--harvest-var", "CHPDT"]
        subprocess.run(cmd, cwd=case, check=True)
        h = harvest(case / "PestHarvest.OUT")
        mapping = pd.read_csv(case / f"{label}_run_mapping.csv")
        h = h.merge(mapping[["global_run", "season_id"]], on="global_run", how="left")
        h = h.sort_values("hno").groupby(["season_id", "treatment"], as_index=False).tail(1)
        for season, trmap in MAP.items():
            for water in ("W3", "W1"):
                cells = {(n, nlevel): float(h.loc[(h.season_id.eq(season)) & (h.treatment.eq(tn)), "chpdt"].iloc[0])
                         for tn, (w, nlevel) in trmap.items() if w == water
                         and not h.loc[(h.season_id.eq(season)) & (h.treatment.eq(tn)), "chpdt"].empty
                         for n in [tn]}
                for nlevel in ("N0", "N1", "N2", "N3"):
                    tn = next((t for t, (w, n) in trmap.items() if w == water and n == nlevel), None)
                    val = cells.get((tn, nlevel), np.nan)
                    all_rows.append({"case": label, "NSTFAC": nstfac, "RTNO3": rtno3, "CMOBMX": cmobmx,
                                     "season": season, "water": water, "nitrogen": nlevel,
                                     "treatment": tn, "CHPDT": val})
    out = pd.DataFrame(all_rows)
    out.to_csv(OUT / "chpdt_by_treatment.csv", index=False)
    wide = out.pivot_table(index=["case", "NSTFAC", "RTNO3", "CMOBMX", "season", "water"], columns="nitrogen", values="CHPDT", aggfunc="first").reset_index()
    for a, b in (("N1", "N0"), ("N2", "N0"), ("N3", "N0")):
        wide[f"{a}_minus_{b}"] = wide.get(a, np.nan) - wide.get(b, np.nan)
    wide.to_csv(OUT / "chpdt_response_contrasts.csv", index=False)
    observed = observed_terminal()
    observed.to_csv(OUT / "observed_terminal_chpdt_fixed_dmfr005.csv", index=False)
    (OUT / "manifest.json").write_text(json.dumps({"design": str(design), "base_run": str(BASE_RUN), "combos": COMBOS, "status": "completed"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(wide.to_string(index=False))


if __name__ == "__main__":
    main()
