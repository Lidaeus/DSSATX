"""Run deterministic six-treatment smoke tests for the four new PST contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VARIANTS = {
    "a3_0805": ("windows/windows_a3_20260805/dscsm048_a3.exe", "windows/windows_a3_20260805/Genotype/TMGRO048.SPE"),
    "a4_0805": ("windows/windows_a4_20260805/dscsm048_a4.exe", "windows/windows_a4_20260805/Genotype/TMGRO048.SPE"),
    "a3_nr_zp_0805": ("windows/windows_a3_nr_zp_20260805/dscsm048_a3_nr_zp.exe", "windows/windows_a3_nr_zp_20260805/Genotype/TMGRO048.SPE"),
    "a4_nr_zp_0805": ("windows/windows_a4_nr_zp_20260805/dscsm048_a4_nr_zp.exe", "windows/windows_a4_nr_zp_20260805/Genotype/TMGRO048.SPE"),
}


def main() -> int:
    results = []
    for variant, (exe, spe) in VARIANTS.items():
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
        cmd = [
            sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
            "--design", str((run_dir / "six_treatment_design.json").resolve()),
            "--param-csv", f"{case}_params.csv", "--harvest-var", "CHPDT",
            "--keep-nitrogen-outputs", "--prefix", case,
        ]
        result = subprocess.run(cmd, cwd=run_dir, env=env, capture_output=True, text=True, check=False)
        outputs = ["PestEval.OUT", "PestJoint.OUT", "PestHarvest.OUT", "PestTmtGrow.OUT", "PestNResponse.OUT", "PestSoilWat.OUT"]
        present = {name: (run_dir / name).is_file() and (run_dir / name).stat().st_size > 0 for name in outputs}
        passed = result.returncode == 0 and all(present.values())
        receipt = {
            "variant": variant, "case": case, "status": "passed" if passed else "failed",
            "returncode": int(result.returncode), "outputs_nonempty": present,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "stderr_tail": (result.stderr or "")[-1500:],
        }
        (run_dir / "smoke_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        results.append(receipt)
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
        if not passed:
            return 1
    (ROOT / "workspace/runs/rawdiff_terminal_nresp01_soil02_smoke_summary_20260805.json").write_text(
        json.dumps({"status": "passed", "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
