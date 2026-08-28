"""Run the corrected-bundle formal selected-eight calibration."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_selected8_water_formal_measuredmoisture_official_200x6_20260819"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4090)
    args = parser.parse_args()
    run_dir = ROOT / "workspace/runs" / CASE
    if not (run_dir / "selected8_water_formal_contract.json").is_file():
        raise FileNotFoundError("prepare_selected8_water_formal_20260819.py must succeed first")
    env = os.environ.copy()
    env["DSSAT_CUSTOM_EXE"] = str((ROOT / "DSCSM048.EXE").resolve())
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    command = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir), "--case", CASE, "--mode", "ies",
        "--n-agents", "6", "--host", "127.0.0.1", "--port", str(args.port), "--wait",
    ]
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    receipt = {"case": CASE, "port": args.port, "agents": 6, "return_code": completed.returncode}
    (run_dir / "background_launch_receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
