#!/usr/bin/env python3
"""Export PlantN/PlantGro/SoilNi diagnostics for the G140 extension."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / "tools/analysis/extract_n_process_diagnostics_20260802.py"
spec = importlib.util.spec_from_file_location("n_process_base", source)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {source}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.RUN = ROOT / "workspace/diagnostics/n_min_tissue_g140_extension_20260803"
mod.OUT = mod.RUN / "process_diagnostics"
mod.CASES = ["G140", "G150", "G160", "G180"]

if __name__ == "__main__":
    raise SystemExit(mod.main())
