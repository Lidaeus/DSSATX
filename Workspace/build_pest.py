"""Compatibility stub for :mod:`src.calibration.build_pest`."""

from pathlib import Path
import runpy
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

runpy.run_module("src.calibration.build_pest", run_name="__main__")
