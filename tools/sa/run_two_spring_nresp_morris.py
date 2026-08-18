"""Build and launch the approved two-spring N-response Morris screen."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_two_spring_organ_n_v1_20260803.csv"
CUSTOM_EXE = ROOT / "windows/windows_nresp_20260803/dscsm048_nresp.exe"
CUSTOM_SPE = ROOT / "windows/windows_nresp_20260803/Genotype/TMGRO048.SPE"
SEASONS = {
    "XXQL2501": (ROOT / "data/user/experiments/xxql2501_sa_controlled_candidate_20260720", ROOT / "configs/sa/eggplant_formal_xxql2501_outputs_20260720.json"),
    "XXQL2601": (ROOT / "data/user/experiments/xxql2601_sa_controlled_tn12_w1_candidate_20260721", ROOT / "configs/sa/eggplant_formal_xxql2601_outputs_20260720.json"),
}
SEEDS = (20260803, 20260804)
OUT = ROOT / "workspace/runs/two_spring_nresp_morris_20260804"

def build() -> None:
    from src.sensitivity.sa_build_sen_case import build_case
    os.environ["DSSAT_CUSTOM_EXE"] = str(CUSTOM_EXE)
    os.environ["DSSAT_SPE_BASE"] = str(CUSTOM_SPE)
    for season, (bundle, profile) in SEASONS.items():
        if not bundle.exists():
            raise FileNotFoundError(bundle)
        for seed in SEEDS:
            case = OUT / season / f"seed_{seed}"
            build_case(BOUNDS, case, ROOT, cultivar="TM0008", morris_r=10,
                       morris_p=6, random_seed=seed, output_profile=profile,
                       input_dir=bundle, run_type="sensitivity_preflight_case")
            print(f"built {season} seed {seed}: {case}")

def run() -> None:
    for season in SEASONS:
        for seed in SEEDS:
            case = OUT / season / f"seed_{seed}"
            subprocess.run([sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
                            "--run-dir", str(case), "--case", "sa_sen_morris",
                            "--mode", "sen", "--n-agents", "2", "--wait"], check=True)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()
    if args.build:
        build()
    if args.run:
        run()
    if not args.build and not args.run:
        ap.error("choose --build or --run")
