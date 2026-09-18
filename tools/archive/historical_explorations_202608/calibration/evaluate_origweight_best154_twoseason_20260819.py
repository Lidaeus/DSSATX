"""Replay the best final member of the original-weight v15 run."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/calibration/evaluate_origweight_best154_twoseason_20260819_impl.py"
spec = importlib.util.spec_from_file_location("evaluate_v15", SOURCE)
if spec is None or spec.loader is None:
    raise ImportError(f"cannot load {SOURCE}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

module.CASE = "e02_v15_boundary_fix_origweight_official_200x4_20260819"
module.RUN_DIR = ROOT / "workspace/runs" / module.CASE
module.BEST_MEMBER = "154"
module.BEST_PHI = 558.991
module.SOURCE_ITERATION = 4
module.ARTIFACT_TYPE = "v15_boundary_fix_origweight_best154_two_season_diagnostics_20260819"
module.OUT_ROOT = ROOT / "figture/e02_v15_boundary_fix_origweight_best154_two_season_full_20260819"
module.DET_ROOT = module.RUN_DIR / "deterministic_candidates/best_phi_member154_two_season_20260819"

if __name__ == "__main__":
    raise SystemExit(module.main())
