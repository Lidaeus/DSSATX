#!/usr/bin/env python3
"""Small mechanism experiment for the low-N yield collapse.

This is a deterministic diagnostic, not a PEST++ calibration.  It starts
from the minimum-Phi member of the completed E02 water/N run and varies the
minimum tissue-N (G-class) composition coefficients.  A combined G/I-class
case is included to separate low-N maintenance from high-N demand saturation.
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
BASE_RUN = ROOT / "workspace/runs/e02_joint62_posterior_soil_wnresponse_200x5_20260802"
DESIGN_SOURCE = ROOT / "configs/runs/eggplant_e02_wnstress_fourcorner_design_v1_20260801.json"
OUT = ROOT / "workspace/diagnostics/n_min_tissue_response_20260802"

SEASONS = {
    # Full W3/W1 × N3/N2/N1/N0 factorial available in the authoritative
    # layer-mean bundles; this avoids averaging unlike water levels.
    "25SP": ("data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801", [2, 3, 4, 5, 10, 11, 12, 13]),
    "26SP": ("data/user/experiments/xxql2601_layermean_ic_valid_n012_v1_20260801", [1, 4, 7, 9, 3, 6, 10, 12]),
}

# G-class coefficients are the minimum N concentrations used by VEGGR's
# low-N growth gate; I-class coefficients affect potential demand.
DEFAULT_COMPOSITION = {
    "PROLFI": 0.270, "PROLFG": 0.220, "PROLFF": 0.110,
    "PROSTI": 0.188, "PROSTG": 0.136, "PROSTF": 0.065,
    "PRORTI": 0.144, "PRORTG": 0.119, "PRORTF": 0.060,
    "PROSHI": 0.210, "PROSHG": 0.150, "PROSHF": 0.110,
    "FNPGN1": 2.00, "FNPGN2": 4.50,
}

CASES = [
    ("G075", 0.75, 1.00, 2.00, 4.50),
    ("G085", 0.85, 1.00, 2.00, 4.50),
    ("G100", 1.00, 1.00, 2.00, 4.50),
    ("G115", 1.15, 1.00, 2.00, 4.50),
    ("G120", 1.20, 1.00, 2.00, 4.50),
    ("G130", 1.30, 1.00, 2.00, 4.50),
    ("G140", 1.40, 1.00, 2.00, 4.50),
    # Component tests around G115: identify whether the response is driven
    # mainly by leaf, stem, root, or shoot composition.
    ("G115_leaf", 1.00, 1.00, 2.00, 4.50),
    ("G115_stem", 1.00, 1.00, 2.00, 4.50),
    ("G115_root", 1.00, 1.00, 2.00, 4.50),
    # Diagnostic separation: lower the maintenance threshold while raising
    # I-class demand, which should lift N0 without making N1/N2 saturate.
    ("G075_I110", 0.75, 1.10, 2.00, 4.50),
    # Optional leaf-N response control; it is not interpreted as evidence
    # about the tissue-N gate unless it changes the response after G is fixed.
    ("G085_FNPGNwide", 0.85, 1.00, 1.50, 5.00),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def make_design() -> Path:
    design = json.loads(DESIGN_SOURCE.read_text(encoding="utf-8"))
    for season in design["seasons"]:
        sid = season["season_id"]
        bundle, treatments = SEASONS[sid]
        season["bundle_path"] = bundle
        season["treatments"] = treatments
        season["role"] = "calibration"
        manifest = ROOT / bundle / "input_manifest.json"
        if manifest.exists():
            season["bundle_manifest_sha256"] = sha256(manifest)
    design["design_id"] = "e02_n_min_tissue_fourcorner_diagnostic_20260802"
    design["diagnostic_contract"] = {
        "base_run": str(BASE_RUN),
        "purpose": "identify whether low-N collapse is caused by minimum tissue-N gate",
        "parameters_varied": ["PROLFG", "PROSTG", "PRORTG", "PROLFI", "PROSTI", "PRORTI", "FNPGN1", "FNPGN2"],
        "not_a_calibration": True,
    }
    path = OUT / "diagnostic_design.json"
    path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def base_parameters() -> tuple[pd.DataFrame, int, float]:
    par_path = BASE_RUN / "e02_joint62_posterior_soil_wnresponse_200x5_20260802.5.par.csv"
    phi_path = BASE_RUN / "e02_joint62_posterior_soil_wnresponse_200x5_20260802.phi.actual.csv"
    par = pd.read_csv(par_path)
    phi = pd.read_csv(phi_path)
    row = phi[phi["iteration"].eq(5)].iloc[0]
    phi_cols = [c for c in row.index if str(c).isdigit()]
    best_name = min(phi_cols, key=lambda c: float(row[c]))
    best_phi = float(row[best_name])
    p = par[par["real_name"].astype(str).eq(str(best_name))]
    if p.empty:
        raise RuntimeError(f"best realisation {best_name} not present in {par_path}")
    rowp = p.iloc[0]
    names = [c.upper() for c in par.columns if c != "real_name"]
    values = [float(rowp[c]) for c in par.columns if c != "real_name"]
    result = pd.DataFrame({"name": names, "value": values})
    for name, value in DEFAULT_COMPOSITION.items():
        if name not in result["name"].values:
            result.loc[len(result)] = [name, value]
    return result, int(best_name), best_phi


def harvest(path: Path) -> pd.DataFrame:
    rows = []
    pat = re.compile(r"RUN\s+(\d+)\s+TN\s+(\d+)\s+HNO\s+(\d+)\s+DATE\s+(\d+).*?@CHPDTS@\s+([-+0-9.eE]+)")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = pat.search(line)
        if m:
            rows.append({"global_run": int(m.group(1)), "treatment": int(m.group(2)),
                         "hno": int(m.group(3)), "date": int(m.group(4)), "CHPDT": float(m.group(5))})
    if not rows:
        raise RuntimeError(f"no harvest rows parsed from {path}")
    return pd.DataFrame(rows)


def extract_case(case_dir: Path, label: str, nst: float, design: Path) -> pd.DataFrame:
    h = harvest(case_dir / "PestHarvest.OUT")
    mapping = pd.read_csv(case_dir / f"{label}_run_mapping.csv")
    h = h.merge(mapping[["global_run", "season_id"]], on="global_run", how="left")
    h = h.sort_values(["season_id", "treatment", "hno"]).groupby(["season_id", "treatment"], as_index=False).tail(1)
    rows = []
    for sid, (_, treatments) in SEASONS.items():
        for tn in treatments:
            rec = h[(h["season_id"] == sid) & (h["treatment"] == tn)]
            if rec.empty:
                raise RuntimeError(f"missing terminal CHPDT for {sid} treatment {tn}")
            if sid == "25SP":
                level = {2: "N3", 3: "N2", 4: "N1", 5: "N0", 10: "N3", 11: "N2", 12: "N1", 13: "N0"}[tn]
                water = "W3" if tn in (2, 3, 4, 5) else "W1"
            else:
                level = {1: "N3", 4: "N2", 7: "N1", 9: "N0", 3: "N3", 6: "N2", 10: "N1", 12: "N0"}[tn]
                water = "W3" if tn in (1, 4, 7, 9) else "W1"
            rows.append({"case": label, "NSTFAC_base": nst, "season": sid, "water": water,
                         "treatment": tn, "nitrogen": level, "CHPDT": float(rec.iloc[0]["CHPDT"])})
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    design = make_design()
    base, best_real, best_phi = base_parameters()
    all_rows = []
    for label, g_scale, i_scale, fn1, fn2 in CASES:
        case = OUT / label
        if case.exists():
            shutil.rmtree(case)
        case.mkdir(parents=True)
        params = base.copy()
        g_names = ["PROLFG", "PROSTG", "PRORTG", "PROSHG"]
        i_names = ["PROLFI", "PROSTI", "PRORTI", "PROSHI"]
        for name in g_names:
            params.loc[params.name.eq(name), "value"] = DEFAULT_COMPOSITION[name] * g_scale
        for name in i_names:
            params.loc[params.name.eq(name), "value"] = DEFAULT_COMPOSITION[name] * i_scale
        if label == "G115_leaf":
            params.loc[params.name.eq("PROLFG"), "value"] = DEFAULT_COMPOSITION["PROLFG"] * 1.15
        elif label == "G115_stem":
            params.loc[params.name.eq("PROSTG"), "value"] = DEFAULT_COMPOSITION["PROSTG"] * 1.15
        elif label == "G115_root":
            params.loc[params.name.eq("PRORTG"), "value"] = DEFAULT_COMPOSITION["PRORTG"] * 1.15
        params.loc[params.name.eq("FNPGN1"), "value"] = fn1
        params.loc[params.name.eq("FNPGN2"), "value"] = fn2
        param_csv = case / "parameters.csv"
        params.to_csv(param_csv, index=False)
        cmd = [sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
               "--design", str(design), "--param-csv", str(param_csv),
               "--prefix", label, "--harvest-var", "CHPDT",
               "--keep-nitrogen-outputs"]
        subprocess.run(cmd, cwd=case, check=True)
        all_rows.append(extract_case(case, label, g_scale, design))
    out = pd.concat(all_rows, ignore_index=True)
    out.to_csv(OUT / "chpdt_by_treatment.csv", index=False)
    wide = out.pivot_table(index=["case", "NSTFAC_base", "season", "water"], columns="nitrogen", values="CHPDT", aggfunc="first").reset_index()
    for a, b in (("N1", "N0"), ("N2", "N0"), ("N3", "N0"), ("N2", "N1"), ("N3", "N1")):
        if a in wide and b in wide:
            wide[f"{a}_minus_{b}"] = wide[a] - wide[b]
    wide.to_csv(OUT / "chpdt_response_contrasts.csv", index=False)
    manifest = {"status": "completed", "base_run": str(BASE_RUN), "best_real": best_real,
                "best_phi": best_phi, "cases": CASES, "design": str(design)}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(wide.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
