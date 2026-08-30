"""Run the selected-eight water-response follow-up with official DSSAT."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_selected8_water_followup_official_100x4_20260818"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4083)
    args = parser.parse_args()
    run_dir = ROOT / "workspace/runs" / CASE
    contract = run_dir / "selected8_water_followup_contract.json"
    if not contract.is_file():
        raise FileNotFoundError("prepare_selected8_water_followup_20260818.py must succeed first")
    env = os.environ.copy()
    env["DSSAT_CUSTOM_EXE"] = str((ROOT / "DSCSM048.EXE").resolve())
    env["DSSAT_SPE_BASE"] = r"C:\DSSAT48\Genotype\TMGRO048.SPE"
    command = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir), "--case", CASE, "--mode", "ies",
        "--n-agents", "6", "--host", "127.0.0.1", "--port", str(args.port), "--wait",
    ]
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False, capture_output=True, text=True)
    receipt = {
        "case": CASE, "port": args.port, "agents": 6, "mode": "ies",
        "return_code": completed.returncode,
        "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip(),
    }
    (run_dir / "background_launch_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
