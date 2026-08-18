"""Prepare the two-spring default-N bounds proposal.

This keeps the current 55-parameter compatible skeleton, restores legacy
stage4_full_v12 ranges where that run had an equivalent parameter, fixes
FL-VS at 120 by user instruction, and keeps SOIL_SLPF active at 0.90-0.96.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_spring_pair_histbest_rtn_relax_20260730.csv"
LEGACY_PST = Path(r"D:\DSSAT48\Tomato_Cal\Workspace\stage4_full_v12.pst")
LEGACY_BEST = Path(r"D:\DSSAT48\Tomato_Cal\Workspace\Calibration_Results\stage4_full_v12_best_parameters_fixed.csv")
PROPOSAL = ROOT / "data/parameter_registry/bounds_proposals/eggplant_e02_spring_pair_defaultn_v1_20260730.csv"
UNSAFE_LEGACY = {
    "RWDTH",
    "TRIFL",
    "JU-R0",
    "TM2",
    "TM3",
    "TO11",
    "TO12",
    "TO13",
    "TO21",
    "TO22",
    "TO23",
}


def legacy_name(name: str) -> str:
    return str(name).strip().lower()


def main() -> int:
    bounds = pd.read_csv(SOURCE, encoding="utf-8-sig")
    legacy = pyemu.Pst(str(LEGACY_PST)).parameter_data[
        ["parval1", "parlbnd", "parubnd", "partrans"]
    ].copy()
    legacy.index = legacy.index.map(legacy_name)
    best = pd.read_csv(LEGACY_BEST, encoding="utf-8-sig")
    best_map = dict(zip(best["name"].map(legacy_name), pd.to_numeric(best["value"], errors="coerce")))

    carried = []
    restored = []
    for idx, row in bounds.iterrows():
        name = str(row["name"])
        key = legacy_name(name)
        if name == "FL-VS":
            bounds.loc[idx, ["init", "lower", "upper", "status"]] = [120.0, 120.0, 120.0, "fixed"]
            bounds.loc[idx, "review_note"] = (
                "两个春季默认硝态氮铵态氮率定v1: user-specified fixed FL-VS=120; "
                "intentional departure from the project default fixed value 100"
            )
            restored.append(name)
            continue
        if name == "SOIL_SLPF":
            init = best_map.get("soil_slpf", 0.95)
            bounds.loc[idx, ["init", "lower", "upper", "status"]] = [float(init), 0.90, 0.96, "active"]
            bounds.loc[idx, "review_note"] = (
                "两个春季默认硝态氮铵态氮率定v1: SLPF active with user-approved range 0.90-0.96"
            )
            restored.append(name)
            continue
        if str(row["status"]).lower() == "fixed":
            carried.append(name)
            bounds.loc[idx, "review_note"] = (
                "两个春季默认硝态氮铵态氮率定v1: retain current fixed-safe skeleton; "
                "legacy stage4_full_v12 counterpart is not used for fixed rows"
            )
            continue
        if name in UNSAFE_LEGACY:
            carried.append(name)
            bounds.loc[idx, "review_note"] = (
                "两个春季默认硝态氮铵态氮率定v1: legacy stage4_full_v12 range conflicts with "
                "current physical/order constraints; retain current compatible spring-pair skeleton"
            )
            continue
        if key in legacy.index:
            legacy_row = legacy.loc[key]
            init = best_map.get(key, legacy_row["parval1"])
            bounds.loc[idx, "init"] = float(init)
            bounds.loc[idx, "lower"] = float(legacy_row["parlbnd"])
            bounds.loc[idx, "upper"] = float(legacy_row["parubnd"])
            bounds.loc[idx, "review_note"] = (
                "两个春季默认硝态氮铵态氮率定v1: range restored from legacy "
                "stage4_full_v12.pst and init anchored to stage4_full_v12_best_parameters_fixed"
            )
            restored.append(name)
        else:
            carried.append(name)
            bounds.loc[idx, "review_note"] = (
                "两个春季默认硝态氮铵态氮率定v1: no direct stage4_full_v12 counterpart; "
                "retain current compatible spring-pair bound skeleton"
            )

    PROPOSAL.parent.mkdir(parents=True, exist_ok=True)
    bounds.to_csv(PROPOSAL, index=False, encoding="utf-8-sig")
    active = int(bounds["status"].astype(str).str.lower().eq("active").sum())
    print(PROPOSAL)
    print(f"active={active}")
    print("restored=" + ",".join(restored))
    if carried:
        print("carried=" + ",".join(carried))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
