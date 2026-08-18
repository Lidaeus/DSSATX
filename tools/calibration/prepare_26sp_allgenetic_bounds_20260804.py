"""Create the all-genetic-parameter bounds proposal for the 26SP run.

The 31-parameter post-precalibration ranges are kept byte-for-byte from the
current frozen bounds.  Remaining genetic/structure parameters are activated
using the reviewed ``eggplant_two_spring_organ_n_v1_20260803`` proposal.  Soil
and measured initial-condition parameters stay fixed/disabled so this remains
an all-genetic comparison rather than a mixed genetic-soil experiment.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CURRENT = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_26sp_w1w2_n012_postprecal_20260804.csv"
REMAINING = ROOT / "data/parameter_registry/bounds_proposals/eggplant/eggplant_two_spring_organ_n_v1_20260803.csv"
OUT = ROOT / "data/parameter_registry/bounds_proposals/eggplant/eggplant_26sp_w1w2_n012_postprecal_allgenetic_20260804.csv"


def main() -> int:
    current = pd.read_csv(CURRENT)
    reviewed = pd.read_csv(REMAINING)
    if current["name"].duplicated().any() or reviewed["name"].duplicated().any():
        raise ValueError("bounds input contains duplicate parameter names")

    current_by_name = current.set_index("name")
    reviewed_by_name = reviewed.set_index("name")
    current_active = set(current.loc[current["status"].eq("active"), "name"])

    # Only reviewed active non-soil candidates are added.  SOIL_SLPF is kept
    # fixed because the comparison is intended to release genetic parameters,
    # while all IC_* rows remain disabled by the current design contract.
    additions = reviewed.loc[
        reviewed["status"].eq("active")
        & reviewed["location"].astype(str).str.upper().ne("SOIL")
        & ~reviewed["name"].isin(current_active)
    ].copy()

    update_columns = [
        "init", "lower", "upper", "status", "pargp", "location", "file",
        "cultivar", "ecotype", "mode", "review_note", "decision_role",
        "evidence_basis", "notes",
    ]
    for _, row in additions.iterrows():
        name = str(row["name"])
        if name not in current_by_name.index:
            raise ValueError(f"reviewed candidate absent from current registry: {name}")
        for column in update_columns:
            if column in additions.columns and column in current.columns:
                current_by_name.loc[name, column] = row[column]

    out = current_by_name.reset_index()
    out = out[current.columns]

    # Explicit contractual guards for this comparison.
    active = out.loc[out["status"].eq("active")]
    expected = len(current_active) + len(additions)
    if len(active) != expected:
        raise ValueError(f"expected {expected} active parameters, got {len(active)}")
    if active["location"].astype(str).str.upper().eq("SOIL").any():
        raise ValueError("soil parameter was accidentally activated")
    fl_vs = out.loc[out["name"].eq("FL-VS")].iloc[0]
    if str(fl_vs["status"]) != "fixed" or float(fl_vs["lower"]) != 120.0 or float(fl_vs["upper"]) != 120.0:
        raise ValueError("FL-VS must remain fixed at 120")
    for name, lower, upper in [("NREXP", 0.05, 2.0), ("NRMIN", 0.05, 0.8)]:
        row = out.loc[out["name"].eq(name)].iloc[0]
        if str(row["status"]) != "active" or float(row["lower"]) != lower or float(row["upper"]) != upper:
            raise ValueError(f"{name} range/status contract failed")
    numeric = active[["init", "lower", "upper"]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or (numeric["lower"] > numeric["upper"]).any():
        raise ValueError("active bounds contain non-finite or inverted ranges")
    if ((numeric["init"] < numeric["lower"]) | (numeric["init"] > numeric["upper"])).any():
        bad = active.loc[(numeric["init"] < numeric["lower"]) | (numeric["init"] > numeric["upper"]), "name"].tolist()
        raise ValueError(f"active init outside bounds: {bad}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"proposal={OUT}")
    print(f"current_active={len(current_active)} additions={len(additions)} all_genetic_active={len(active)}")
    print("added=" + ",".join(additions["name"].tolist()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
