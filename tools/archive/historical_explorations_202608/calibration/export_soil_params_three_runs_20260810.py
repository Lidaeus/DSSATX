"""Export three-run calibrated soil params + original values to CSVs.

Two deliverables (for manual averaging and fixing):
  1. Soil physical params (SOIL_*): original values from the bundle SOIL.SOL
     (profile IBTM910017: SCOM SLPF row + layer rows) and the posterior
     median of each of the three calibrations (v2 / official / a3).
  2. Soil N IC params (IC_SNH4_* / IC_SNO3_*): original values from the
     bundle FileX initial-conditions rows (per treatment, 5 layers) and the
     posterior median of each run, plus bound-touch flags (fraction of the
     200 realizations within 0.5% of the lower/upper calibration bound).

Usage:
    python tools/calibration/export_soil_params_three_runs_20260810.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "figture/soil_param_export_three_20260810"

RUNS = {
    "v2": "e02_v2_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260808",
    "official": "e02_official_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260809",
    "a3": "e02_a3_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260810",
}
BUNDLE25 = ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"
BUNDLE26 = ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729"

SOIL_LAYER_NAMES = ["SLLL", "SDUL", "SSAT", "SSKS", "SBDM", "SLCL", "SLSI"]
SOIL_PROFILE_ID = "IBTM910017"
REL_TOL = 0.005


# ── original values ─────────────────────────────────────────────────────────
def read_soil_profile(soil_sol: Path) -> dict:
    """Return {SOIL_<NAME>_<layer:02d>: original value} + SOIL_SLPF from SCOM."""
    lines = soil_sol.read_text(encoding="utf-8", errors="ignore").splitlines()
    values = {}
    in_profile = False
    layer_header = None
    layer_idx = 0
    for idx, line in enumerate(lines):
        s = line.rstrip("\n")
        if s.startswith(f"*{SOIL_PROFILE_ID}"):
            in_profile = True
            continue
        if not in_profile:
            continue
        if s.startswith("*") and not s.startswith(f"*{SOIL_PROFILE_ID}"):
            break
        if s.lstrip().startswith("@ SCOM"):
            # SCOM row follows: SCOM SALB SLU1 SLDR SLRO SLNF SLPF ...
            # Only SLPF is a calibration parameter; other SCOM fields are not.
            header = [h for h in s.split() if h != "@"]
            data = lines[idx + 1].split()
            if "SLPF" in header:
                values["SOIL_SLPF"] = float(data[header.index("SLPF")])
            continue
        if s.lstrip().startswith("@  SLB"):
            layer_header = s.split()
            layer_header = [h for h in layer_header if h != "@"]
            layer_idx = 0
            continue
        if layer_header and s.strip() and not s.lstrip().startswith("@"):
            parts = s.split()
            if len(parts) < len(layer_header):
                continue
            layer_idx += 1
            row = dict(zip(layer_header, parts))
            for name in SOIL_LAYER_NAMES:
                if name in row:
                    try:
                        v = float(row[name])
                    except ValueError:
                        continue
                    if v <= -90:  # -99 = no measured value, not a calibrated param
                        continue
                    values[f"SOIL_{name}_{layer_idx:02d}"] = v
    return values


def read_filex_ic(filex: Path) -> dict:
    """Return {(TN, layer_cm, 'SNH4'|'SNO3'): original value} from ICBL rows."""
    lines = filex.read_text(encoding="utf-8", errors="ignore").splitlines()
    values = {}
    in_ic = False
    ic_header = None
    for line in lines:
        s = line.rstrip("\n")
        u = s.strip().upper()
        if u.startswith("*INITIAL CONDITIONS"):
            in_ic = True
            continue
        if not in_ic:
            continue
        if u.startswith("*") and not u.startswith("*INITIAL CONDITIONS"):
            break
        if s.lstrip().startswith("@C  ICBL"):
            # Header "@C ICBL SH2O SNH4 SNO3"; the data row carries the
            # treatment in the @C column, so keep @C in the header mapping.
            ic_header = s.split()
            continue
        if ic_header and s.strip() and not s.lstrip().startswith("@"):
            parts = s.split()
            if len(parts) >= len(ic_header) and parts[0].isdigit():
                row = dict(zip(ic_header, parts))
                tn = int(row["@C"])
                values[(tn, float(row["ICBL"]), "SNH4")] = float(row["SNH4"])
                values[(tn, float(row["ICBL"]), "SNO3")] = float(row["SNO3"])
    return values


# ── calibrated medians + touch flags ────────────────────────────────────────
def load_ensembles(case: str) -> pd.DataFrame:
    path = ROOT / f"workspace/runs/{case}/{case}.5.par.csv"
    frame = pd.read_csv(path)
    real_col = next((c for c in frame.columns if str(c).lower() in {"real_name", "realization"}), None)
    return frame.drop(columns=[real_col])


def touch_flags(name: str, ens: pd.DataFrame, lower: float, upper: float) -> str:
    vals = pd.to_numeric(ens[name], errors="coerce").to_numpy(float)
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return "n/a"
    width = upper - lower
    if width <= 0:
        return "fixed"
    tol = width * REL_TOL
    fl = float((vals <= lower + tol).mean())
    fu = float((vals >= upper - tol).mean())
    parts = []
    if fl >= 0.05:
        parts.append(f"L{fl:.2f}")
    if fu >= 0.05:
        parts.append(f"U{fu:.2f}")
    return ",".join(parts) if parts else "-"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ens = {tag: load_ensembles(case) for tag, case in RUNS.items()}
    # PST bounds for touch flags
    import pyemu
    pst = {tag: pyemu.Pst(str(ROOT / f"workspace/runs/{case}/{case}.pst")) for tag, case in RUNS.items()}

    # ── 1. soil physical ────────────────────────────────────────────────────
    profile = read_soil_profile(BUNDLE25 / "SOIL.SOL")
    rows = []
    for name in sorted(profile):
        original = profile[name]
        key = name.lower()  # PST/ensemble columns are lowercase
        rec = {"param": name, "original": original}
        for tag in ("v2", "official", "a3"):
            if key in ens[tag].columns:
                rec[f"{tag}_median"] = float(ens[tag][key].median())
                lb, ub = float(pst[tag].parameter_data.loc[key, "parlbnd"]), \
                         float(pst[tag].parameter_data.loc[key, "parubnd"])
                rec[f"{tag}_touch"] = touch_flags(key, ens[tag], lb, ub)
            else:
                rec[f"{tag}_median"] = np.nan
                rec[f"{tag}_touch"] = "n/a"
        rows.append(rec)
    df_soil = pd.DataFrame(rows)
    df_soil.to_csv(OUT / "soil_physical_three_runs.csv", index=False, encoding="utf-8-sig")

    # ── 2. soil N IC ───────────────────────────────────────────────────────
    ic25 = read_filex_ic(BUNDLE25 / "XXQL2501.TMX")
    ic26 = read_filex_ic(BUNDLE26 / "XXQL2601.TMX")
    layer_cm = {1: 20, 2: 40, 3: 60, 4: 80, 5: 100}
    rows = []
    for ex, icmap, treatments in (("XXQL2501", ic25, [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]),
                                  ("XXQL2601", ic26, list(range(1, 13)))):
        for tn in treatments:
            for lyr in range(1, 6):
                for var in ("SNH4", "SNO3"):
                    cm = layer_cm[lyr]
                    original = icmap.get((tn, cm, var), np.nan)
                    name = f"IC_{var}_{ex}_TN{tn:02d}_L{lyr:02d}"
                    key = name.lower()
                    rec = {"param": name, "experiment": ex, "treatment": tn,
                           "layer": lyr, "depth_cm": cm, "variable": var,
                           "original": original}
                    for tag in ("v2", "official", "a3"):
                        if key in ens[tag].columns:
                            rec[f"{tag}_median"] = float(ens[tag][key].median())
                            lb, ub = float(pst[tag].parameter_data.loc[key, "parlbnd"]), \
                                     float(pst[tag].parameter_data.loc[key, "parubnd"])
                            rec[f"{tag}_touch"] = touch_flags(key, ens[tag], lb, ub)
                        else:
                            rec[f"{tag}_median"] = np.nan
                            rec[f"{tag}_touch"] = "n/a"
                    rows.append(rec)
    df_ic = pd.DataFrame(rows)
    df_ic.to_csv(OUT / "soil_n_ic_three_runs.csv", index=False, encoding="utf-8-sig")

    manifest = {
        "artifact_type": "soil_param_export_three_runs_20260810",
        "runs": RUNS,
        "soil_profile": SOIL_PROFILE_ID,
        "ic_note": "original values from bundle FileX initial-conditions rows (per treatment, 5 layers)",
        "touch_note": "L<frac>/U<frac> = share of 200 realizations within 0.5% of lower/upper calibration bound",
    }
    (OUT / "diagnostic_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"soil physical rows: {len(df_soil)} | IC rows: {len(df_ic)}")
    print(f"\nWritten to: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
