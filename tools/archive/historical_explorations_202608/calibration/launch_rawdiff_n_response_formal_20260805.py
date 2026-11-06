"""Launch the four 150x4 IES runs under the 2026-08-05 objective contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VARIANTS = {
    "a3_0805": ("windows/windows_a3_20260805/dscsm048_a3.exe", "windows/windows_a3_20260805/Genotype/TMGRO048.SPE", 4061),
    "a4_0805": ("windows/windows_a4_20260805/dscsm048_a4.exe", "windows/windows_a4_20260805/Genotype/TMGRO048.SPE", 4062),
    "a3_nr_zp_0805": ("windows/windows_a3_nr_zp_20260805/dscsm048_a3_nr_zp.exe", "windows/windows_a3_nr_zp_20260805/Genotype/TMGRO048.SPE", 4063),
    "a4_nr_zp_0805": ("windows/windows_a4_nr_zp_20260805/dscsm048_a4_nr_zp.exe", "windows/windows_a4_nr_zp_20260805/Genotype/TMGRO048.SPE", 4064),
}


def main() -> int:
    launched = []
    for variant, (exe, spe, port) in VARIANTS.items():
        case = f"e02_v2_rawdiff_terminal_nresp01_soil02_6treat_150x4_20260805_{variant}"
        run_dir = ROOT / "workspace/runs" / case
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(ROOT),
            "DSSAT_CUSTOM_EXE": str((ROOT / exe).resolve()),
            "DSSAT_SPE_BASE": str((ROOT / spe).resolve()),
            "DSSAT_SOIL_BASE": str((ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801/SOIL.SOL").resolve()),
            "DSSAT_KEEP_RUNS": "1",
        })
        log = (run_dir / "formal_console.log").open("w", encoding="utf-8")
        cmd = [
            sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
            "--run-dir", str(run_dir), "--case", case, "--mode", "ies",
            "--n-agents", "4", "--port", str(port), "--wait",
        ]
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        launched.append({"variant": variant, "case": case, "pid": proc.pid, "port": port, "log": str(run_dir / "formal_console.log")})
        print(json.dumps(launched[-1], ensure_ascii=False), flush=True)
    receipt = {"status": "launched", "objective_contract": "raw_scale_difference_plus_terminal_20260805", "launched_at_utc": datetime.now(timezone.utc).isoformat(), "runs": launched}
    (ROOT / "workspace/runs/rawdiff_terminal_nresp01_soil02_formal_launch_receipt_20260805.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
