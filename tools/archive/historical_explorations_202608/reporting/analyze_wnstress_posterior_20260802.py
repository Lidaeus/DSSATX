#!/usr/bin/env python3
"""Summarise posterior boundaries and four-corner dry-yield responses."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
import numpy as np
import pandas as pd


def bounds_from_pst(path: Path) -> pd.DataFrame:
    rows = []
    active = False
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if s.lower().startswith("* parameter data"):
            active = True
            continue
        if active and s.lower().startswith("* observation"):
            break
        if not active or not s or s.startswith("#"):
            continue
        p = s.split()
        if len(p) < 6 or p[0].lower() in {"parameter", "name"}:
            continue
        try:
            rows.append({"name": p[0].lower(), "status": p[1].lower(),
                         "init": float(p[3]), "lower": float(p[4]), "upper": float(p[5])})
        except ValueError:
            pass
    return pd.DataFrame(rows)


def posterior(run_dir: Path) -> tuple[pd.DataFrame, int, float]:
    pst = next(run_dir.glob("*.pst"))
    prefix = pst.stem
    par = pd.read_csv(run_dir / f"{prefix}.5.par.csv")
    par.columns = [str(c).lower() for c in par.columns]
    phi = pd.read_csv(run_dir / f"{prefix}.phi.actual.csv")
    members = [c for c in phi.columns if str(c).isdigit()]
    best = int(phi.iloc[-1][members].astype(float).idxmin())
    best_phi = float(phi.iloc[-1][str(best)])
    b = bounds_from_pst(pst)
    b = b[b.status != "fixed"].copy()
    values = par.drop(columns=["real_name"], errors="ignore")
    values.columns = [str(c).lower() for c in values.columns]
    rows = []
    for r in b.itertuples(index=False):
        if r.name not in values:
            continue
        x = pd.to_numeric(values[r.name], errors="coerce")
        width = r.upper - r.lower
        rows.append({"name": r.name, "init": r.init, "lower": r.lower, "upper": r.upper,
                     "median": x.median(), "mean": x.mean(), "p05": x.quantile(.05),
                     "p95": x.quantile(.95),
                     "near_lower_pct": float((x <= r.lower + .05 * width).mean() * 100),
                     "near_upper_pct": float((x >= r.upper - .05 * width).mean() * 100),
                     "mean_shift_pct_of_range": float((x.mean() - r.init) / width * 100)})
    return pd.DataFrame(rows), best, best_phi


def four_corner(run_dir: Path, mapping: Path) -> pd.DataFrame:
    pst = next(run_dir.glob("*.pst")); prefix = pst.stem
    phi = pd.read_csv(run_dir / f"{prefix}.phi.actual.csv")
    members = [c for c in phi.columns if str(c).isdigit()]
    best = int(phi.iloc[-1][members].astype(float).idxmin())
    obs = pd.read_csv(run_dir / f"{prefix}.5.obs.csv")
    row = obs[obs.real_name.astype(str).eq(str(best))].iloc[0]
    sim = row.drop("real_name"); sim.index = sim.index.str.lower()
    reg = pd.read_csv(run_dir / f"{prefix}_observation_registry.csv")
    reg["key"] = reg.obsnme.str.lower()
    reg["sim_transformed"] = reg.key.map(sim)
    reg = reg[reg.obsnme.str.contains("CHPDTS", case=False, na=False)].copy()
    reg["harvest_number"] = reg.obsnme.str.extract(r"_H(\d+)", flags=re.I)[0].astype(int)
    reg["simulated"] = np.exp(pd.to_numeric(reg.sim_transformed, errors="coerce")) - 1.0
    reg["observed"] = pd.to_numeric(reg.raw_obsval, errors="coerce")
    final = reg.sort_values("harvest_number").groupby(["season_id", "treatment"], as_index=False).tail(1)
    m = pd.read_csv(mapping)
    final = final.merge(m, on=["season_id", "treatment"], how="left")
    return final[["season_id", "treatment", "water_level", "nitrogen_level", "observed", "simulated", "harvest_number"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--mapping", type=Path, default=Path("configs/runs/e02_three_season_water_n_mapping_20260730.csv"))
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    p, best, phi = posterior(args.run_dir)
    p.to_csv(args.out_dir / "posterior_summary.csv", index=False)
    r = four_corner(args.run_dir, args.mapping)
    r.to_csv(args.out_dir / "best_member_four_corner_chpdt.csv", index=False)
    (args.out_dir / "summary.txt").write_text(f"best_member={best}\nactual_phi={phi}\nactive_parameters={len(p)}\n", encoding="utf-8")
    print(f"best_member={best} actual_phi={phi:.6g} active_parameters={len(p)}")


if __name__ == "__main__":
    main()
