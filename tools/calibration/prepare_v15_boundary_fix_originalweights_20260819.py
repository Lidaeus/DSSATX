"""Build the v15 boundary-fix run with the original (lower) W_RESPONSE weights."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/calibration/prepare_v15_boundary_fix_20260819.py"
spec = importlib.util.spec_from_file_location("prepare_v15_boundary_fix", SOURCE)
if spec is None or spec.loader is None:
    raise ImportError(f"cannot load {SOURCE}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

module.CASE = "e02_v15_boundary_fix_origweight_official_200x4_20260819"
module.DESIGN = ROOT / "configs/runs/eggplant_e02_v15_boundary_fix_origweight_20260819.json"
module.SOURCE_CASE = "e02_v15_boundary_fix_official_200x6_20260819"
module.SOURCE_REALIZATION = "38"
module.NOPTMAX = 4
module.WATER_LAMBDA_PER_SEASON = 0.5

if __name__ == "__main__":
    raise SystemExit(module.main())
