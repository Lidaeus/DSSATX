"""Materialize the approved PAGE/PENV + 26SP-N=0.34 formal design.

This preparation step only creates the frozen bounds/config artifacts.  It
does not launch PEST++.  The four FileX terms are direct season-scoped
parameters; the runner chooses PAGE_25SP/PENV_25SP for XXQL2501 and
PAGE_26SP/PENV_26SP for XXQL2601.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.common.param_registry import assert_valid_frozen_bounds
BASE_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v37_formal_source_sink_balanced_bounds.csv"
FROZEN_ID = "eggplant_e02_v46_page_penv_n034_formal_20260901"
FROZEN_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / f"{FROZEN_ID}.csv"
PROPOSAL_DESIGN = ROOT / "configs/runs/e02_formal_v46_page_penv_n034_20260901_proposal.json"
DESIGN = ROOT / "configs/runs/e02_formal_v46_page_penv_n034_20260901.json"

SEEDLING_ROWS = [
    {
        "name": "PAGE_25SP", "init": 60.0, "lower": 24.0, "upper": 60.0,
        "status": "active", "pargp": "initial_conditions", "location": "IC",
        "file": "XXQL2501.TMX", "cultivar": "TM0008", "ecotype": "TM0001",
        "mode": "25SP", "review_note": "Direct 25SP PAGE FileX term; approved range 24-60 d",
    },
    {
        "name": "PENV_25SP", "init": 20.0, "lower": 8.0, "upper": 20.0,
        "status": "active", "pargp": "initial_conditions", "location": "IC",
        "file": "XXQL2501.TMX", "cultivar": "TM0008", "ecotype": "TM0001",
        "mode": "25SP", "review_note": "Direct 25SP PENV FileX term; approved range 8-20 degC",
    },
    {
        "name": "PAGE_26SP", "init": 34.0, "lower": 24.0, "upper": 60.0,
        "status": "active", "pargp": "initial_conditions", "location": "IC",
        "file": "XXQL2601.TMX", "cultivar": "TM0008", "ecotype": "TM0001",
        "mode": "26SP", "review_note": "Direct 26SP PAGE FileX term; initialized from approved sweep reference",
    },
    {
        "name": "PENV_26SP", "init": 19.0, "lower": 8.0, "upper": 20.0,
        "status": "active", "pargp": "initial_conditions", "location": "IC",
        "file": "XXQL2601.TMX", "cultivar": "TM0008", "ecotype": "TM0001",
        "mode": "26SP", "review_note": "Direct 26SP PENV FileX term; initialized from approved sweep reference",
    },
]


def main() -> None:
    base = pd.read_csv(BASE_BOUNDS)
    names = {str(v).strip().upper() for v in base["name"]}
    if names.intersection({row["name"] for row in SEEDLING_ROWS}):
        raise RuntimeError("base frozen bounds already contain one of the PAGE/PENV names")
    out = pd.concat([base, pd.DataFrame(SEEDLING_ROWS)], ignore_index=True)
    out.to_csv(FROZEN_BOUNDS, index=False, encoding="utf-8-sig")
    issues = assert_valid_frozen_bounds(FROZEN_BOUNDS)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise RuntimeError("new frozen bounds failed validation: " + "; ".join(map(str, errors)))

    design = json.loads(PROPOSAL_DESIGN.read_text(encoding="utf-8"))
    design["status"] = "approved_for_execution"
    design["executable"] = True
    design["bounds_id"] = FROZEN_ID
    design["prepared_from_proposal"] = str(PROPOSAL_DESIGN.relative_to(ROOT))
    design["bounds_sha256"] = __import__("hashlib").sha256(FROZEN_BOUNDS.read_bytes()).hexdigest()
    DESIGN.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"frozen_bounds={FROZEN_BOUNDS}")
    print(f"design={DESIGN}")
    print(f"rows={len(out)} active={(out['status'].str.lower() == 'active').sum()}")


if __name__ == "__main__":
    main()
