"""Create the reviewed/frozen bounds for the selected-eight water follow-up."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_fixedsoil_formal_nse_20260817.csv"
SOURCE_CASE = "e02_selected8_water_B_wresp_nse_lam0p5_80x4_20260818_retry1"
SOURCE_RUN = ROOT / "workspace/runs" / SOURCE_CASE
PROPOSAL = ROOT / "data/parameter_registry/bounds_proposals/eggplant_e02_selected8_water_followup_20260818.csv"
BOUNDS_ID = "eggplant_e02_selected8_water_followup_20260818"


def main() -> int:
    frozen = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv"
    if frozen.exists():
        print(f"already frozen: {frozen}")
        return 0
    bounds = pd.read_csv(SOURCE_BOUNDS, encoding="utf-8-sig")
    bounds["name"] = bounds["name"].astype(str).str.lower()
    posterior = pd.read_csv(SOURCE_RUN / f"{SOURCE_CASE}.4.par.csv")
    real_col = posterior.columns[0]
    row = posterior.loc[
        posterior[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq("39")
    ]
    if len(row) != 1:
        raise ValueError(f"expected B realization 39 exactly once, found {len(row)}")
    values = row.iloc[0].to_dict()
    for index, item in bounds.iterrows():
        name = str(item["name"])
        if name in values:
            value = float(values[name])
            bounds.loc[index, "init"] = min(max(value, float(item["lower"])), float(item["upper"]))

    pormin = bounds["name"].eq("pormin")
    if pormin.sum() != 1:
        raise ValueError("source bounds must contain PORMIN exactly once")
    bounds.loc[pormin, ["lower", "upper", "status"]] = [0.001, 0.010, "active"]
    bounds.loc[pormin, "init"] = bounds.loc[pormin, "init"].clip(0.001, 0.010)
    bounds.loc[pormin, "review_note"] = (
        "OAT: PORMIN=0.001 improved mean W-response NSE and 26SP dry NSE; "
        "values >=0.02 broke the dry/scale gate"
    )

    additions = pd.DataFrame(
        [
            {
                "name": "swbar_rec", "init": 0.72, "lower": 0.25, "upper": 0.75,
                "status": "active", "pargp": "SPE_WaterResponse", "location": "SPE",
                "file": "TMGRO048.SPE.base", "cultivar": "", "ecotype": "", "mode": "both",
                "review_note": "OAT gate-qualified: mean W-response NSE -10.685 to -7.918 at 0.72",
                "notes": "Anchor reconstructs XSWBAR ordered nodes",
            },
            {
                "name": "yswbar_mid", "init": 0.55, "lower": 0.40, "upper": 1.00,
                "status": "active", "pargp": "SPE_WaterResponse", "location": "SPE",
                "file": "TMGRO048.SPE.base", "cultivar": "", "ecotype": "", "mode": "both",
                "review_note": "OAT gate-qualified: mean W-response NSE -10.685 to -8.399 at 0.55; 0.15 failed gate",
                "notes": "Anchor reconstructs YSWBAR bounded nodes",
            },
        ]
    )
    for column in bounds.columns:
        if column not in additions.columns:
            additions[column] = ""
    additions = additions[bounds.columns]
    proposal = pd.concat([bounds, additions], ignore_index=True)
    if proposal["name"].duplicated().any():
        raise ValueError("follow-up proposal contains duplicate parameters")
    PROPOSAL.parent.mkdir(parents=True, exist_ok=True)
    proposal.to_csv(PROPOSAL, index=False, encoding="utf-8-sig")
    subprocess.run(
        [
            sys.executable, str(ROOT / "tools/freeze_bounds.py"),
            "--proposal", str(PROPOSAL), "--crop", "eggplant",
            "--bounds-id", BOUNDS_ID,
            "--notes", "Selected-eight B objective; member39 anchor; OAT-approved PORMIN and SWBAR curve anchors",
        ],
        cwd=ROOT, check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
