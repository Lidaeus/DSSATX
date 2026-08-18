#!/usr/bin/env python3
"""Prepare a small G180-fixed yield-recovery calibration contract.

G-class organ-protein coefficients are supplied through ``--fixed-from``;
other selected yield/N/water parameters remain active.  The selected active
initial values are taken from the G180 deterministic member.  Only the few
active bounds that did not contain that member are minimally extended so the
Sobol ensemble can start from the actual G180 state.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_wnstress_fourcorner_layermeanic_v1_20260801.csv"
G180 = ROOT / "workspace/diagnostics/n_min_tissue_g140_extension_20260803/G180/parameters.csv"
PROPOSAL = ROOT / "data/parameter_registry/bounds_proposals/eggplant/eggplant_e02_g180_yield_recovery_20260803.csv"
FIXED = ROOT / "workspace/diagnostics/g180_fixed_yield_recovery_20260803/g180_fixed.csv"

ACTIVE = {
    "LFMAX", "SIZLF", "SLAVR", "XFRT", "RHGHT", "RWDTH", "TRIFL",
    "KCAN", "PARMAX", "PHTMAX", "FRLFF", "FRSTMF", "FINREF", "SIZREF",
    "SLAREF", "VSSINK", "RTNO3", "RTNH4", "RTEXF", "NSTFAC", "NMOBMX",
    "NVSMOB", "NRCVR", "SOIL_SLPF", "LNREF", "CMOBMX", "DSWBAR", "XFRMAX",
    "RWUMX",
}
G_NAMES = ["PROLFG", "PROSTG", "PRORTG", "PROSHG"]


def main() -> int:
    bounds = pd.read_csv(SOURCE, encoding="utf-8-sig")
    values = pd.read_csv(G180).set_index("name")["value"].astype(float)
    bounds["status"] = bounds["name"].astype(str).str.upper().map(
        lambda n: "active" if n in ACTIVE else "fixed"
    )
    for i, row in bounds.iterrows():
        name = str(row["name"]).upper()
        if name in values.index:
            v = float(values[name])
            if name in ACTIVE:
                # Keep the published bounds unless the G180 state lies just
                # outside; in that case extend only the affected side.
                bounds.at[i, "init"] = v
                bounds.at[i, "lower"] = min(float(row["lower"]), v)
                bounds.at[i, "upper"] = max(float(row["upper"]), v)
            else:
                bounds.at[i, "init"] = v
                bounds.at[i, "lower"] = v
                bounds.at[i, "upper"] = v
        if bounds.at[i, "status"] == "fixed":
            bounds.at[i, "lower"] = bounds.at[i, "init"]
            bounds.at[i, "upper"] = bounds.at[i, "init"]
    PROPOSAL.parent.mkdir(parents=True, exist_ok=True)
    bounds.to_csv(PROPOSAL, index=False, encoding="utf-8-sig")

    FIXED.parent.mkdir(parents=True, exist_ok=True)
    fixed = pd.DataFrame({"name": G_NAMES, "value": [float(values[n]) for n in G_NAMES]})
    fixed.to_csv(FIXED, index=False)
    receipt = {
        "source_bounds": str(SOURCE),
        "proposal": str(PROPOSAL),
        "fixed_from": str(FIXED),
        "active_parameters": sorted(ACTIVE),
        "active_count": len(ACTIVE),
        "fixed_g_parameters": {n: float(values[n]) for n in G_NAMES},
        "initial_member": str(G180),
        "design": "25SP+26SP layer-mean FileX; existing no-soil-water/no-NRESP observation policy; Sobol 100x4",
    }
    (FIXED.parent / "preparation_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
