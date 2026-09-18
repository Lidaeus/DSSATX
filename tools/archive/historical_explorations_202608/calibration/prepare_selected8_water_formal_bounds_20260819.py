"""Freeze the formal bounds using selected-eight member 94 as initialization."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ID = "eggplant_e02_selected8_water_followup_20260818"
SOURCE_CASE = "e02_selected8_water_followup_official_100x4_20260818"
BOUNDS_ID = "eggplant_e02_selected8_water_formal_measuredmoisture_20260819"
PROPOSAL = ROOT / f"data/parameter_registry/bounds_proposals/{BOUNDS_ID}.csv"


def main() -> int:
    frozen = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv"
    if frozen.exists():
        print(f"already frozen: {frozen}")
        return 0
    source_bounds = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{SOURCE_ID}.csv"
    source_par = ROOT / "workspace/runs" / SOURCE_CASE / f"{SOURCE_CASE}.4.par.csv"
    bounds = pd.read_csv(source_bounds, encoding="utf-8-sig")
    posterior = pd.read_csv(source_par)
    real_col = posterior.columns[0]
    row = posterior.loc[
        posterior[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq("94")
    ]
    if len(row) != 1:
        raise ValueError(f"expected member 94 exactly once, found {len(row)}")
    values = {str(k).lower(): v for k, v in row.iloc[0].items() if k != real_col}
    for index, item in bounds.iterrows():
        name = str(item["name"]).lower()
        if name in values and pd.notna(values[name]):
            bounds.loc[index, "init"] = min(
                max(float(values[name]), float(item["lower"])), float(item["upper"])
            )
    PROPOSAL.parent.mkdir(parents=True, exist_ok=True)
    bounds.to_csv(PROPOSAL, index=False, encoding="utf-8-sig")
    subprocess.run(
        [
            sys.executable, str(ROOT / "tools/freeze_bounds.py"),
            "--proposal", str(PROPOSAL), "--crop", "eggplant",
            "--bounds-id", BOUNDS_ID,
            "--notes", "Formal corrected-bundle calibration; ranges unchanged from 20260818 follow-up; member 94 initialization",
        ],
        cwd=ROOT, check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
