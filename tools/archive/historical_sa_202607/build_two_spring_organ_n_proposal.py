"""Build the review-only two-spring organ-N sensitivity proposal.

The script deliberately writes a *proposal* (never a frozen bounds file).  It
starts from the old broad formal domain, keeps all existing active rows, fixes
FL-VS at 120, and adds the newly requested SPE parameters with narrow ranges.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_formal_multiseason_candidate_v4_20260721.csv"
CURRENT = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v2_formal25sp_nosoilwater_20260802.csv"

NARROW = {
    "FRCNOD": (0.05, 0.04, 0.06),
    "SD-PM": (400.0, 360.0, 440.0),
    "FL-LF": (400.0, 360.0, 440.0),
    "FL-VS": (120.0, 120.0, 120.0),
    "NREXP": (1.0, 0.05, 2.0),
    "NRMIN": (0.5, 0.05, 0.8),
}
ORG = {
    "PROLFI": (0.31, 0.26, 0.36), "PROLFG": (0.21, 0.17, 0.25), "PROLFF": (0.11, 0.08, 0.14),
    "PROSTI": (0.18, 0.145, 0.22), "PROSTG": (0.115, 0.09, 0.14), "PROSTF": (0.06, 0.04, 0.08),
    "PRORTI": (0.144, 0.13, 0.16), "PRORTG": (0.119, 0.107, 0.131), "PRORTF": (0.06, 0.05, 0.07),
    "PROSHI": (0.21, 0.19, 0.23), "PROSHG": (0.15, 0.14, 0.16), "PROSHF": (0.11, 0.10, 0.12),
}

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "data/parameter_registry/bounds_proposals/eggplant/eggplant_two_spring_organ_n_v1_20260803.csv")
    args = ap.parse_args()
    old = pd.read_csv(OLD)
    cur = pd.read_csv(CURRENT)
    # Old broad domain is authoritative for existing names; current rows fill
    # parameters added during the refactor.
    old = old[old["name"].notna()].copy()
    merged = pd.concat([old, cur[~cur.name.isin(old.name)]], ignore_index=True)
    merged = merged.drop_duplicates("name", keep="first")
    for name, (init, lo, hi) in {**ORG, **NARROW}.items():
        row = {c: "" for c in merged.columns}
        row.update(name=name, init=init, lower=lo, upper=hi, status="fixed" if lo == hi else "active", pargp="organ_n" if name.startswith(("PRO", "FRC", "NREXP", "NRMIN")) else "structure", location="SPE" if name not in {"SD-PM", "FL-LF", "FL-VS"} else "CUL", file="TMGRO048.SPE" if name not in {"SD-PM", "FL-LF", "FL-VS"} else "TMGRO048.CUL", mode="two_spring_organ_n")
        merged = merged[merged.name != name]
        merged = pd.concat([merged, pd.DataFrame([row])], ignore_index=True)
    merged = merged.sort_values("name").reset_index(drop=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.out, index=False)
    print(f"wrote proposal {args.out} ({len(merged)} rows; active={sum(merged.status=='active')})")

if __name__ == "__main__":
    main()
