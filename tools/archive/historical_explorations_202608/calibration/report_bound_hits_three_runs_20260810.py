"""Report parameter bound-hitting (触边) across the three calibrations.

For each run (v2 / official / a3), load the PST bounds and the final IES
posterior (.5.par.csv, 200 realizations) and flag active parameters whose
posterior sits against the lower or upper calibration bound:

  * hit_lower_frac / hit_upper_frac — fraction of the 200 realizations within
    0.5% of the bound (relative to bound width)
  * median relative position (0=lower, 1=upper)
  * classification: hard_pin (>=90% at bound), partial (5-90%), none

Groups: genetic / soil physical / IC.  Fixed params (trans=fixed) are excluded
from the hit analysis (they are pinned by design).

Usage:
    python tools/calibration/report_bound_hits_three_runs_20260810.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]

RUNS = {
    "v2": "e02_v2_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260808",
    "official": "e02_official_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260809",
    "a3": "e02_a3_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260810",
}
OUT = ROOT / "figture/param_bound_hits_three_20260810"

REL_TOL = 0.005  # 0.5% of bound width counts as touching


def analyze(case: str) -> pd.DataFrame:
    pst = pyemu.Pst(str(ROOT / f"workspace/runs/{case}/{case}.pst"))
    ens = pd.read_csv(ROOT / f"workspace/runs/{case}/{case}.5.par.csv")
    real_col = next((c for c in ens.columns if str(c).lower() in {"real_name", "realization"}), None)
    ens = ens.drop(columns=[real_col])

    rows = []
    for name, r in pst.parameter_data.iterrows():
        if str(r.partrans) == "fixed":
            continue
        lb, ub = float(r.parlbnd), float(r.parubnd)
        width = ub - lb
        if width <= 0:
            continue
        vals = pd.to_numeric(ens[name], errors="coerce").to_numpy(float)
        vals = vals[np.isfinite(vals)]
        if len(vals) == 0:
            continue
        tol = width * REL_TOL
        frac_low = float((vals <= lb + tol).mean())
        frac_high = float((vals >= ub - tol).mean())
        rel = (np.median(vals) - lb) / width
        rows.append({
            "param": name,
            "lower": lb, "upper": ub,
            "median": float(np.median(vals)),
            "rel_pos": rel,               # 0 = on lower, 1 = on upper
            "hit_lower_frac": frac_low,
            "hit_upper_frac": frac_high,
        })
    return pd.DataFrame(rows).set_index("param")


def classify(r: pd.Series, tag: str) -> str:
    low = r[f"{tag}_hit_lower_frac"]
    high = r[f"{tag}_hit_upper_frac"]
    if low >= 0.90:
        return "LOWER_PIN"
    if high >= 0.90:
        return "UPPER_PIN"
    if low >= 0.05 or high >= 0.05:
        return "partial"
    return "none"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tables = {tag: analyze(case) for tag, case in RUNS.items()}

    # Merge into one table with per-run columns
    merged = pd.DataFrame(index=sorted(set().union(*[set(t.index) for t in tables.values()])))
    for tag, t in tables.items():
        for col in ("rel_pos", "hit_lower_frac", "hit_upper_frac"):
            merged[f"{tag}_{col}"] = t[col]
    merged["group"] = np.where(merged.index.str.lower().str.startswith("ic_"), "IC",
                      np.where(merged.index.str.lower().str.startswith("soil_"), "soil_physical", "genetic"))
    merged["class_v2"] = merged.apply(lambda r: classify(r, "v2") if not np.isnan(r["v2_rel_pos"]) else "n/a", axis=1)
    merged["class_official"] = merged.apply(lambda r: classify(r, "official") if not np.isnan(r["official_rel_pos"]) else "n/a", axis=1)
    merged["class_a3"] = merged.apply(lambda r: classify(r, "a3") if not np.isnan(r["a3_rel_pos"]) else "n/a", axis=1)
    merged.to_csv(OUT / "bound_hits_all.csv", encoding="utf-8-sig")

    # Summary counts by group and class
    summary = []
    for tag in ("v2", "official", "a3"):
        cls = merged[f"class_{tag}"]
        for group in ("genetic", "soil_physical", "IC"):
            sub = cls[merged["group"] == group]
            summary.append({
                "run": tag, "group": group,
                "n_active": int(sub.notna().sum()),
                "lower_pin": int((sub == "LOWER_PIN").sum()),
                "upper_pin": int((sub == "UPPER_PIN").sum()),
                "partial": int((sub == "partial").sum()),
                "clean": int((sub == "none").sum()),
            })
    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(OUT / "bound_hits_summary.csv", index=False, encoding="utf-8-sig")
    print(summary_df.to_string(index=False))

    # Detail: hard pins per run
    for tag in ("v2", "official", "a3"):
        cls = merged[f"class_{tag}"]
        pins = merged[(cls == "LOWER_PIN") | (cls == "UPPER_PIN")]
        print(f"\n{tag} hard pins ({len(pins)}):")
        for p, r in pins.sort_values(f"{tag}_rel_pos").iterrows():
            side = "lower" if r[f"{tag}_hit_lower_frac"] >= 0.9 else "upper"
            t = tables[tag].loc[p]
            print(f"  [{r['group']:>14}] {p:<36} {side:>6}  (frac={max(r[f'{tag}_hit_lower_frac'], r[f'{tag}_hit_upper_frac']):.2f}, "
                  f"median={t['median']:.4g}, bound={t[side == 'lower' and 'lower' or 'upper']:.4g})")

    manifest = {
        "artifact_type": "bound_hits_report_three_runs_20260810",
        "runs": RUNS,
        "rel_tolerance": REL_TOL,
        "note": "hit fraction = share of 200 realizations within 0.5% of bound width; hard pin = >=90%",
    }
    (OUT / "diagnostic_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nWritten to: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
