"""Assemble N-observation bundles without overwriting the v2 historical bundles."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.experiments import assemble_v2_bundles_20260726 as base

SUFFIX = "v7_adap34_plantn_slpf_20260729"
for season, info in base.SEASON_INFO.items():
    info["bundle_name"] = f"{info['bundle_name'].split('_v2_')[0]}_{SUFFIX}"

if __name__ == "__main__":
    trial = base.sha256_file(ROOT / "tools/experiments/build_trial_observations_v2_20260726.py")
    soil = base.sha256_file(ROOT / "tools/experiments/build_soil_water_observations.py")
    for season in ("25SP", "25FA", "26SP"):
        out = base.assemble_bundle(season, {"trial": trial, "soil": soil})
        print(f"{season}: {out}")
