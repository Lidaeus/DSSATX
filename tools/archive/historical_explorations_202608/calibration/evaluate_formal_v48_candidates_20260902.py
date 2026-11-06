"""Reuse the established deterministic candidate audit for v48 r2."""
from pathlib import Path

import evaluate_formal_v47_free_nscale_candidates_20260902 as audit


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    audit.RUN = root / "workspace/runs/e02_formal_v48_n_gradient_water2x_200x4_20260902_r2"
    audit.CASE = "e02_formal_v48_n_gradient_water2x_200x4_20260902"
    audit.DESIGN = root / "configs/runs/e02_formal_v48_n_gradient_water2x_20260902.json"
    audit.OUT = root / "workspace/reports/e02_formal_v48_20260902_candidates"
    audit.FINAL_ITERATION = 4
    if audit.OUT.exists():
        raise FileExistsError(f"Preserve previous audit: {audit.OUT}")
    raise SystemExit(audit.main())
