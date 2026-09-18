"""Run the corrected-26SP-N formal calibration with official DSSAT."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "workspace/runs/e02_formal_armab_rrmse_26spncal_official_200x6_20260828"
CASE = "e02_formal_armab_rrmse_26spncal_200x6_20260828"
OFFICIAL = ROOT / "DSCSM048.EXE"
LIVE = ROOT / "workspace/DSCSM048.EXE"
BACKUP = ROOT / "workspace/DSCSM048.EXE.before_formal_armab_rrmse_26spn_20260828"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    pst = RUN_DIR / f"{CASE}.pst"
    if not pst.is_file():
        raise FileNotFoundError(pst)
    if not OFFICIAL.is_file() or not LIVE.is_file():
        raise FileNotFoundError("Official or workspace DSSAT executable is missing")
    if BACKUP.exists():
        raise FileExistsError(f"Stale executable backup: {BACKUP}")

    LIVE.replace(BACKUP)
    shutil.copy2(OFFICIAL, LIVE)
    try:
        receipt = {
            "schema_version": 1,
            "case": CASE,
            "run_dir": str(RUN_DIR),
            "launched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "dssat_variant": "official DSSAT v4.8",
            "official_exe_sha256": sha256(OFFICIAL),
            "design": "configs/runs/e02_formal_armab_rrmse_26spncal_200x6_20260828.json",
            "source_workbook_sha256": "fa44d25b4a35a8dbfa04324d77faa0b6da15c7dc325ef7ca7bdddce9514addeb",
            "realizations": 200,
            "noptmax": 6,
            "agents": 6,
            "port": 4069,
        }
        (RUN_DIR / "formal_launch_receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        command = [
            sys.executable,
            str(ROOT / "tools/parallel/run_parallel.py"),
            "--run-dir", str(RUN_DIR),
            "--case", CASE,
            "--mode", "ies",
            "--n-agents", "6",
            "--port", "4069",
            "--wait",
        ]
        return int(subprocess.run(command, cwd=ROOT, check=False).returncode)
    finally:
        if LIVE.exists():
            LIVE.unlink()
        BACKUP.replace(LIVE)


if __name__ == "__main__":
    raise SystemExit(main())
