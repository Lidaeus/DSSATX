"""Prepare the reviewed E02 bounds proposal for stronger nitrogen response."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "data/parameter_registry/bounds_frozen/eggplant"
    / "eggplant_e02_joint62_v6_touchrelax_slpf096_20260729.csv"
)
PROPOSAL = (
    ROOT
    / "data/parameter_registry/bounds_proposals"
    / "eggplant_e02_joint62_v7_nstfac050_rhght035_20260730.csv"
)


def main() -> int:
    bounds = pd.read_csv(SOURCE, encoding="utf-8-sig")
    changes = {
        "NSTFAC": {
            "lower": 0.50,
            "review_note": (
                "E02 N-response experiment: raise lower bound from 0.10 to "
                "0.50 to exclude the weak-response posterior region"
            ),
        },
        "RHGHT": {
            "lower": 0.35,
            "review_note": (
                "User-authorized continuation below the former 0.50 physical "
                "floor after persistent lower-edge accumulation"
            ),
        },
    }
    for name, updates in changes.items():
        mask = bounds["name"].astype(str).str.upper().eq(name)
        if int(mask.sum()) != 1:
            raise RuntimeError(f"Expected exactly one {name} row")
        for column, value in updates.items():
            bounds.loc[mask, column] = value

    proposal = PROPOSAL
    proposal.parent.mkdir(parents=True, exist_ok=True)
    bounds.to_csv(proposal, index=False, encoding="utf-8-sig")
    print(proposal)
    print(
        bounds.loc[
            bounds["name"].isin(changes),
            ["name", "init", "lower", "upper", "status", "review_note"],
        ].to_string(index=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
