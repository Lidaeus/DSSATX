"""Run the official-DSSAT Arm-A/B RRMSE formal calibration and restore the executable."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "workspace/runs/e02_formal_armab_rrmse_official_200x6_20260828"
CASE = "e02_formal_armab_rrmse_200x6_20260828"
OFFICIAL = ROOT / "DSCSM048.EXE"
LIVE = ROOT / "workspace/DSCSM048.EXE"
BACKUP = ROOT / "workspace/DSCSM048.EXE.before_formal_armab_rrmse_20260828"


def main() -> int:
    if not (RUN_DIR / f"{CASE}.pst").is_file():
        raise FileNotFoundError(RUN_DIR / f"{CASE}.pst")
    if BACKUP.exists():
        raise FileExistsError(f"stale executable backup: {BACKUP}")
    LIVE.replace(BACKUP)
    shutil.copy2(OFFICIAL, LIVE)
    try:
        receipt = {
            "case": CASE,
            "run_dir": str(RUN_DIR),
            "dssat_variant": "official DSSAT v4.8",
            "official_exe_sha256": __import__("hashlib").sha256(OFFICIAL.read_bytes()).hexdigest(),
            "realizations": 200,
            "noptmax": 6,
            "agents": 6,
        }
        (RUN_DIR / "formal_launch_receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        cmd = [
            sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
            "--run-dir", str(RUN_DIR), "--case", CASE, "--mode", "ies",
            "--n-agents", "6", "--port", "4068", "--wait",
        ]
        return int(subprocess.run(cmd, cwd=ROOT, check=False).returncode)
    finally:
        if LIVE.exists():
            LIVE.unlink()
        BACKUP.replace(LIVE)


if __name__ == "__main__":
    raise SystemExit(main())
