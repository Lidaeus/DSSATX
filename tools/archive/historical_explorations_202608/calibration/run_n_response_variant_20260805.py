"""Run one corrected 25SP six-treatment N-response variant in isolation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VARIANTS = {
    "a3_0805": ("windows/windows_a3_20260805/dscsm048_a3.exe", "windows/windows_a3_20260805/Genotype/TMGRO048.SPE"),
    "a4_0805": ("windows/windows_a4_20260805/dscsm048_a4.exe", "windows/windows_a4_20260805/Genotype/TMGRO048.SPE"),
    "a3_nr_zp_0805": ("windows/windows_a3_nr_zp_20260805/dscsm048_a3_nr_zp.exe", "windows/windows_a3_nr_zp_20260805/Genotype/TMGRO048.SPE"),
    "a4_nr_zp_0805": ("windows/windows_a4_nr_zp_20260805/dscsm048_a4_nr_zp.exe", "windows/windows_a4_nr_zp_20260805/Genotype/TMGRO048.SPE"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--n-agents", type=int, default=4)
    args = ap.parse_args()

    case = f"e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260805_{args.variant}"
    run_dir = ROOT / "workspace/runs" / case
    if not (run_dir / f"{case}.pst").is_file():
        raise FileNotFoundError(run_dir / f"{case}.pst")
    exe, spe = VARIANTS[args.variant]
    env = os.environ.copy()
    env.update(
        {
            "DSSAT_CUSTOM_EXE": str((ROOT / exe).resolve()),
            "DSSAT_SPE_BASE": str((ROOT / spe).resolve()),
            "DSSAT_SOIL_BASE": str((ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801/SOIL.SOL").resolve()),
            "DSSAT_KEEP_RUNS": "1",
        }
    )
    parallel = [
        sys.executable,
        "tools/parallel/run_parallel.py",
        "--run-dir", str(run_dir),
        "--case", case,
        "--mode", "ies",
        "--n-agents", str(args.n_agents),
        "--port", str(args.port),
        "--wait",
    ]
    print(json.dumps({"variant": args.variant, "case": case, "port": args.port, "exe": env["DSSAT_CUSTOM_EXE"]}, ensure_ascii=False), flush=True)
    result = subprocess.run(parallel, cwd=ROOT, env=env, check=False)
    if result.returncode != 0:
        return int(result.returncode)
    finalize = [
        sys.executable,
        "-m", "src.calibration.finalize_calibration",
        "--run-dir", str(run_dir),
        "--case", case,
    ]
    return int(subprocess.run(finalize, cwd=ROOT, env=env, check=False).returncode)


if __name__ == "__main__":
    raise SystemExit(main())
