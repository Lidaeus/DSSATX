#!/usr/bin/env python3
"""Extend the G-class minimum-tissue-N diagnostic beyond G140.

This reuses the validated deterministic experiment runner but writes to a new
directory so the original G075--G140/component results remain unchanged.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / "tools/calibration/run_n_min_tissue_experiment_20260802.py"
spec = importlib.util.spec_from_file_location("n_min_tissue_base", source)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {source}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

mod.OUT = ROOT / "workspace/diagnostics/n_min_tissue_g140_extension_20260803"
mod.CASES = [
    ("G140", 1.40, 1.00, 2.00, 4.50),
    ("G150", 1.50, 1.00, 2.00, 4.50),
    ("G160", 1.60, 1.00, 2.00, 4.50),
    ("G180", 1.80, 1.00, 2.00, 4.50),
]

if __name__ == "__main__":
    raise SystemExit(mod.main())
