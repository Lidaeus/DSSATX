#!/usr/bin/env python3
"""Report raw-scale metrics for the best member of the corrected E02 run."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.metrics import compute_metrics


KEEP = {"CHPDT", "HPODW", "LAID", "LAIX", "LWAD", "SWAD", "CHTD", "SNAM", "LNAM", "SOIL_WATER"}


def root_variable(obgnme: str) -> str:
    s = str(obgnme).upper()
    m = re.search(r"(?:^|_)(PDAP|ADAP|MDAP|LAIX|CHFPW|CHPDT|HPODW|LAID|LWAD|SWAD|CHTD|SNAM|LNAM|NRESP|SW\d+)(?:M|S)?(?:_|$)", s)
    if not m:
        return "OTHER"
    token = m.group(1)
    return "SOIL_WATER" if token.startswith("SW") and token[2:].isdigit() else token


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    run = args.run_dir.resolve()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    pst = next(run.glob("*.pst"))
    case = pst.stem
    phi = pd.read_csv(run / f"{case}.phi.actual.csv")
    members = [c for c in phi.columns if str(c).isdigit()]
    best = int(phi.iloc[-1][members].astype(float).idxmin())
    best_phi = float(phi.iloc[-1][str(best)])
    # Use the actual final iteration; formal runs may use noptmax=4 rather
    # than the historical five-iteration E02 baseline.
    obs_files = sorted(
        run.glob(f"{case}.*.obs.csv"),
        key=lambda p: int(p.name[len(case) + 1 :].split(".", 1)[0]),
    )
    if not obs_files:
        raise FileNotFoundError(f"No iteration observation ensemble found in {run}")
    final_iter = int(obs_files[-1].name[len(case) + 1 :].split(".", 1)[0])
    obs = pd.read_csv(obs_files[-1])
    row = obs.loc[obs["real_name"].astype(str).eq(str(best))].iloc[0]
    reg = pd.read_csv(run / f"{case}_observation_registry.csv")
    reg["variable"] = reg["obgnme"].map(root_variable)
    reg = reg[(pd.to_numeric(reg["weight"], errors="coerce") > 0) & reg["variable"].isin(KEEP)].copy()
    sim = pd.to_numeric(reg["obsnme"].str.lower().map(row), errors="coerce")
    offset = pd.to_numeric(reg.get("transform_offset", 0), errors="coerce").fillna(0.0)
    transform = reg.get("transform", pd.Series("raw", index=reg.index)).astype(str).str.lower()
    reg["simulated"] = np.where(transform.eq("log"), np.exp(sim) - offset, sim)
    reg["observed"] = pd.to_numeric(reg["raw_obsval"], errors="coerce")
    reg = reg[np.isfinite(reg["observed"]) & np.isfinite(reg["simulated"])].copy()
    reg[["season_id", "treatment", "variable", "observed", "simulated"]].to_csv(out / "best_member_observation_pairs_rawscale.csv", index=False)

    rows = []
    for variable, sub in reg.groupby("variable", sort=True):
        rows.append({"scope": "overall", "season_id": "ALL", "variable": variable, **compute_metrics(sub.observed, sub.simulated)})
    for (season, variable), sub in reg.groupby(["season_id", "variable"], sort=True):
        rows.append({"scope": "season", "season_id": season, "variable": variable, **compute_metrics(sub.observed, sub.simulated)})
    metrics = pd.DataFrame(rows)
    metrics.to_csv(out / "best_member_metrics_rawscale.csv", index=False)

    par = pd.read_csv(run / f"{case}.{final_iter}.par.csv")
    par.loc[par["real_name"].astype(str).eq(str(best))].to_csv(out / "best_member_parameters.csv", index=False)
    summary = out / "summary.txt"
    summary.write_text(f"best_member={best}\nactual_phi={best_phi:.10g}\nactive_metric_variables={','.join(sorted(KEEP))}\n", encoding="utf-8")
    print(f"best_member={best} actual_phi={best_phi:.10g} rows={len(reg)}")
    print(metrics.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
