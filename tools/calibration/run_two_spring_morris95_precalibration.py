"""Prepare/run two-spring genetic pre-calibration from Morris top-95 parameters."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "configs/sa/eggplant_two_spring_nresp_design_20260804.json"
CUSTOM_EXE = ROOT / "windows/windows_nresp_20260803/dscsm048_nresp.exe"
CUSTOM_SPE = ROOT / "windows/windows_nresp_20260803/Genotype/TMGRO048.SPE"
INPUT = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"
SOIL_OVERRIDE = ROOT / "data/user/experiments/xxql2501_sa_controlled_candidate_20260720/SOIL.SOL"
FILEX_OVERRIDES = {
    "XXQL2501.TMX": ROOT / "data/user/experiments/xxql2501_sa_controlled_candidate_20260720/XXQL2501.TMX",
    "XXQL2601.TMX": ROOT / "data/user/experiments/xxql2601_sa_controlled_tn12_w1_candidate_20260721/XXQL2601.TMX",
}

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selected-bounds", type=Path, required=True)
    ap.add_argument("--bounds-id", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--n-reals", type=int, default=150)
    ap.add_argument("--noptmax", type=int, default=4)
    ap.add_argument("--port", type=int, default=4012)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    os.environ["DSSAT_CUSTOM_EXE"] = str(CUSTOM_EXE)
    os.environ["DSSAT_SPE_BASE"] = str(CUSTOM_SPE)
    os.environ["DSSAT_SOIL_BASE"] = str(SOIL_OVERRIDE)
    os.environ["DSSAT_BATCH_FILEX_ROOT"] = r"C:\DSSAT48\TOMATO"
    os.environ["DSSAT_KEEP_RUNS"] = "1"
    import json
    os.environ["DSSAT_FILEX_MAP"] = json.dumps({name: str(path) for name, path in FILEX_OVERRIDES.items()})
    os.environ["DSSAT_DISABLE_SOIL_INJECTION"] = "1"
    if not args.run:
        cmd = [sys.executable, str(ROOT / "src/calibration/build_pest.py"),
               "--mode", "eggplant_stage2", "--multiseason-design", str(DESIGN),
               "--input-dir", str(INPUT), "--bounds-id", args.bounds_id,
               "--bounds-crop", "eggplant", "--prefix", args.out_dir.name,
               "--noptmax", str(args.noptmax), "--ies-num-reals", str(args.n_reals),
               "--random-seed", "20260804", "--bad-phi-sigma", "1e300",
               "--batch", str(INPUT / "DSSBatch.v48"), "--harvest-var", "CHPDT",
               "--include-n-uptake", "--out-dir", str(args.out_dir),
               "--param-review-mode", "off"]
        subprocess.run(cmd, cwd=ROOT, check=True)
        print(f"built pre-calibration case: {args.out_dir}")
        return
    subprocess.run([sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
                    "--run-dir", str(args.out_dir), "--case", args.out_dir.name,
                    "--mode", "ies", "--n-agents", "6", "--port", str(args.port), "--wait"], cwd=ROOT, check=True)

if __name__ == "__main__":
    main()
