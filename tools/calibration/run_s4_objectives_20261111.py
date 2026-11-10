#!/usr/bin/env python3
"""run_s4_objectives_20261111.py -- S4 forward entry for the base85
calibration (chain-equivalent patches + trial.forward)."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.calibration.run_dual_morris98_trial_20261105 as trial
import src.calibration.sa98_joint40 as s98


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--forward", type=Path)
    args = parser.parse_args()
    trial.MEMBERS, trial.UPDATES, trial.WORKERS = 40, 3, 8
    s98.SIGNED.add("N2_N0_FRESH_CONTRAST")
    s98.SIGNED.add("W_FRESH_CONTRAST")
    if args.forward is None:
        raise SystemExit("use --forward <run-dir>")
    design = trial.read(args.forward / "design.json")
    trial.DATES = dict(design["anthesis_dates"])
    trial.forward(args.forward)
