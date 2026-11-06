"""Freeze batch-1 bounds + group policy + design for the water/yield-boundary fix round.

Absorbs the external analysis report (2026-08-18/19,
analysis_26sp_yield_and_boundary.md) recommendations, batch 1 only:

Priority-1 range releases (report section 2.2) + PPSEN fixed at 0 (section 3.2-3):
    PODUR   lower 12 -> 8            (physical [5, 80])
    SFDUR   upper 27 -> 35           (physical [5, 50])
    SENRTE  [0.3, 3.0] -> [0.1, 5.0] (physical [0, 10])
    CMOBMX  [0.005, 0.05] -> [0.001, 0.10] (physical [0, 1])
    FINREF  upper 275 -> 350         (physical [0, 1000])
    PPSEN   status active -> fixed, init 0.0

Weight budget (report section 3.2-2):
    W_RESPONSE phi budget 0.025 -> 0.10 per season
    (realized share was 0.6x budget -> ~6% realized, above the 5% floor)

Deferred to batch 2 (only after batch-1 improves LAI/yield; report section 3.2-5):
    temperature TO11/TO21/TO22/TM1/TM2 (+ ladder-order constraints),
    allocation FRLFF/FRSTMF/XFINT-upper/XFPHT/XMAGE/LNGSH, NSTFAC, KCAN/SIZREF/PARMAX.

Usage:
    python tools/calibration/prepare_water_batch1_bounds_20260819.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE_BOUNDS_ID = "eggplant_e02_selected8_water_formal_measuredmoisture_20260819"
BOUNDS_ID = "eggplant_e02_water_batch1_20260819"
SOURCE_DESIGN = ROOT / "configs/runs/eggplant_e02_selected8_water_formal_measuredmoisture_20260819.json"
DESIGN = ROOT / "configs/runs/eggplant_e02_water_batch1_20260819.json"
SOURCE_POLICY = ROOT / "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv"
POLICY = ROOT / "configs/runs/t10_water_batch1_group_policy_20260819.csv"

# (name, expected (lower, upper), new (lower, upper)) — refuses to edit a file
# whose current ranges drift from the report's evidence base.
RANGE_CHANGES = {
    "podur":  ((12.0, 58.0), (8.0, 58.0)),
    "sfdur":  ((10.0, 27.0), (10.0, 35.0)),
    "senrte": ((0.3, 3.0), (0.1, 5.0)),
    "cmobmx": ((0.005, 0.05), (0.001, 0.10)),
    "finref": ((165.0, 275.0), (165.0, 350.0)),
}
PPSEN_INIT = 0.0
W_RESPONSE_BUDGET = 0.10


def main() -> int:
    frozen = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv"
    if frozen.exists():
        raise FileExistsError(f"already frozen: {frozen}")

    source = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{SOURCE_BOUNDS_ID}.csv"
    bounds = pd.read_csv(source, encoding="utf-8-sig")
    bounds["name"] = bounds["name"].astype(str).str.lower()

    changes: list[dict] = []
    for name, (expected, new) in RANGE_CHANGES.items():
        rows = bounds[bounds["name"] == name]
        if len(rows) != 1:
            raise ValueError(f"expected exactly one row for {name}, got {len(rows)}")
        idx = rows.index[0]
        current = (float(bounds.at[idx, "lower"]), float(bounds.at[idx, "upper"]))
        if not (abs(current[0] - expected[0]) < 1e-9 and abs(current[1] - expected[1]) < 1e-9):
            raise ValueError(
                f"{name}: current bounds {current} differ from report evidence {expected}; "
                "refusing to apply stale adjustments")
        bounds.at[idx, "lower"], bounds.at[idx, "upper"] = new
        init = float(bounds.at[idx, "init"])
        bounds.at[idx, "init"] = min(max(init, new[0]), new[1])
        changes.append({"name": name, "old": current, "new": new,
                        "init": float(bounds.at[idx, "init"])})

    ppsen = bounds[bounds["name"] == "ppsen"]
    if len(ppsen) != 1:
        raise ValueError("expected exactly one ppsen row")
    idx = ppsen.index[0]
    bounds.at[idx, "status"] = "fixed"
    bounds.at[idx, "init"] = PPSEN_INIT
    # Registry rule: fixed requires lower == init == upper.
    bounds.at[idx, "lower"] = PPSEN_INIT
    bounds.at[idx, "upper"] = PPSEN_INIT
    changes.append({"name": "ppsen", "old": "active", "new": "fixed@0.0",
                    "init": PPSEN_INIT})

    proposal = ROOT / f"data/parameter_registry/bounds_proposals/{BOUNDS_ID}.csv"
    proposal.parent.mkdir(parents=True, exist_ok=True)
    bounds.to_csv(proposal, index=False, encoding="utf-8-sig")
    subprocess.run(
        [sys.executable, str(ROOT / "tools/freeze_bounds.py"),
         "--proposal", str(proposal), "--crop", "eggplant",
         "--bounds-id", BOUNDS_ID,
         "--notes",
         "Batch-1 report-driven release: PODUR lo 8, SFDUR hi 35, SENRTE [0.1,5], "
         "CMOBMX [0.001,0.10], FINREF hi 350; PPSEN fixed 0; W_RESPONSE budget 0.10/season"],
        cwd=ROOT, check=True,
    )

    # ── group policy: raise W_RESPONSE budget ──
    policy = pd.read_csv(SOURCE_POLICY, encoding="utf-8-sig")
    mask = policy["group"].astype(str).str.strip() == "W_RESPONSE"
    if int(mask.sum()) != 1:
        raise ValueError(f"expected one W_RESPONSE row, got {int(mask.sum())}")
    old_budget = float(policy.loc[mask, "phi_budget"].iloc[0])
    policy.loc[mask, "phi_budget"] = W_RESPONSE_BUDGET
    policy.loc[mask, "note"] = (
        "Within-nitrogen water-yield contrast; x4 vs 20260813 (0.025) per "
        "26SP yield/boundary report 20260819 to reach >=5% realized Phi share")
    policy.to_csv(POLICY, index=False, encoding="utf-8-sig")

    # ── design: copy with new refs + scope notes ──
    design = json.loads(SOURCE_DESIGN.read_text(encoding="utf-8"))
    design["design_id"] = "eggplant_e02_water_batch1_20260819"
    design["bounds_id"] = BOUNDS_ID
    design["group_policy"] = str(POLICY.relative_to(ROOT)).replace("\\", "/")
    design["batch1_scope"] = {
        "report": "analysis_26sp_yield_and_boundary.md (20260819)",
        "range_releases": {c["name"]: {"old": list(c["old"]) if isinstance(c["old"], tuple) else c["old"],
                                       "new": list(c["new"]) if isinstance(c["new"], tuple) else c["new"]}
                            for c in changes},
        "ppsen": "fixed at 0 (91.5% lower-bound pile-up; eggplant day-length insensitive)",
        "w_response_budget_per_season": W_RESPONSE_BUDGET,
        "deferred_batch2": [
            "temperature TO11/TO21/TO22/TM1/TM2 releases WITH ladder-order constraints "
            "(TO11<TO12, TO21<TO22, TO1x<TO2x<TMx)",
            "allocation FRLFF/FRSTMF/XFINT-upper/XFPHT/XMAGE/LNGSH",
            "NSTFAC lower 0.3 (only if N-response rounds resume)",
            "KCAN/SIZREF/PARMAX",
        ],
        "gate_to_batch2": "batch-1 must first improve 26SP DRY_CUM bias/plateau and LAI overestimate",
    }
    DESIGN.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "bounds_id": BOUNDS_ID,
        "changes": changes,
        "policy": str(POLICY),
        "w_response_budget": {"old": old_budget, "new": W_RESPONSE_BUDGET},
        "design": str(DESIGN),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
