"""Create the reviewed 26SP W1/W2 N0-N2 bounds proposal.

The proposal is derived mechanically from the completed two-spring genetic
pre-calibration bounds.  Parameters that accumulated on a bound are given a
small, physical-bound-aware escape margin; parameters with a concentrated
conditional ensemble are narrowed only where the pre-calibration provides
positive evidence.  The script never mutates an existing frozen bounds file.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_two_spring_morris_top95_genetic_precal_20260804.csv"
DEFAULT_OUT = ROOT / "data/parameter_registry/bounds_proposals/eggplant/eggplant_26sp_w1w2_n012_postprecal_20260804.csv"

# Explicit, auditable decisions from the pre-calibration posterior.  Values
# are intentionally modest and remain inside PHYSICAL_BOUNDS.
UPDATES: dict[str, tuple[float, float, str]] = {
    "CMOBMX": (0.005, 0.080, "upper-bound accumulation; modest upper release"),
    "EM-FL": (22.5, 25.0, "conditional mass concentrated near lower end"),
    "EM-V1": (38.0, 40.0, "retain physical/phenology range"),
    "FL-SD": (5.0, 15.0, "lower-bound accumulation; narrow upper tail"),
    "FRLFF": (0.24, 0.40, "posterior concentrated near lower end; retain baseline inside proposal"),
    "LFMAX": (1.20, 1.40, "lower-bound accumulation; modest release"),
    "NMOBMX": (0.04, 0.30, "lower-bound accumulation; modest release"),
    "NVSMOB": (0.10, 0.40, "lower-bound accumulation; modest release"),
    "PM06": (0.25, 0.55, "lower-bound accumulation; modest release"),
    "PROLFF": (0.10, 0.15, "posterior concentrated near upper end; retain baseline inside proposal"),
    "PROLFG": (0.15, 0.30, "upper-bound accumulation; modest release"),
    "PROLFI": (0.27, 0.34, "posterior-supported narrowing"),
    "PRORTF": (0.045, 0.070, "retain root partition support"),
    "PRORTG": (0.115, 0.140, "upper-bound accumulation; modest release"),
    "PRORTI": (0.140, 0.180, "upper-tail release for root partition"),
    "PROSHF": (0.080, 0.140, "lower-bound accumulation; narrow shell evidence remains uncertain"),
    "PROSHI": (0.180, 0.260, "upper-bound accumulation; modest release"),
    "PROSTF": (0.045, 0.090, "retain stem partition support"),
    "PROSTG": (0.080, 0.180, "upper-bound accumulation; modest release"),
    "PROSTI": (0.130, 0.250, "upper-bound accumulation; modest release"),
    "RTNH4": (0.010, 0.045, "posterior-supported nitrogen uptake range; retain baseline inside proposal"),
    "RTNO3": (0.012, 0.025, "posterior-supported nitrogen uptake range"),
    "RWUMX": (0.015, 0.045, "lower-bound accumulation; modest release"),
    "SENDAY": (0.000, 0.120, "upper-bound accumulation; modest release"),
    "TB1": (7.5, 10.0, "posterior-supported thermal range"),
    "TB2": (6.0, 10.0, "lower-bound accumulation; modest release"),
    "TO11": (24.0, 27.5, "upper-bound accumulation; DSSAT TO11<TO21 order constrains release"),
    "TO12": (19.5, 27.5, "posterior-supported lower range; retain baseline inside proposal"),
    "TRIFL": (0.50, 0.68, "posterior-supported flowering rate range"),
    "XFINT": (0.10, 0.45, "upper-bound accumulation; modest release"),
    "XFRT": (0.65, 1.00, "upper-bound accumulation; physical upper limit"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    source = pd.read_csv(SOURCE, encoding="utf-8-sig")
    if set(source.loc[source["status"].eq("active"), "name"]) != set(UPDATES):
        raise RuntimeError("active parameter set changed; refusing to create an implicit proposal")
    proposal = source.copy()
    notes = []
    for idx, row in proposal.iterrows():
        name = str(row["name"])
        if name not in UPDATES:
            continue
        lower, upper, note = UPDATES[name]
        proposal.loc[idx, "lower"] = lower
        proposal.loc[idx, "upper"] = upper
        proposal.loc[idx, "review_note"] = note
        proposal.loc[idx, "decision_role"] = "postprecal_boundary_review"
        proposal.loc[idx, "evidence_basis"] = "two_spring_morris95_precal_genetic_20260804 final ensemble"
        notes.append(f"{name}: {lower:g}-{upper:g} ({note})")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    proposal.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"proposal={args.out}")
    print(f"active={len(UPDATES)} fixed_or_disabled={len(proposal) - len(UPDATES)}")
    for item in notes:
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
