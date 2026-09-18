"""Execute E02 S1 then S2 staged pre-calibration for A3 (0805).

The process is deliberately sequential: S2 is built only after the S1 run is
finalized and its stage representative has passed the engineering gate.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "configs/runs/eggplant_e02_s1s2_morris_top95_plus_a3_0805_20260806.json"
MULTI = ROOT / "configs/runs/eggplant_e02_s1s2_a3_0805_multiseason_20260806.json"
BUNDLE = ROOT / "data/user/experiments/xxql2501_corrected_management_layermean_20260806"
POLICY = ROOT / "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260805.csv"
BOUNDS_ID = "eggplant_e02_s1s2_morris_top95_plus_a3_0805_v2_20260806"
EXE = ROOT / "windows/windows_a3_20260805/dscsm048_a3.exe"
SPE = ROOT / "windows/windows_a3_20260805/Genotype/TMGRO048.SPE"
SOIL = BUNDLE / "SOIL.SOL"
CASE1 = "e02_s1_canopy_morris_top95_a3_0805_100x3_20260806"
CASE2 = "e02_s2_harvest_terminal_morris_top95_a3_0805_100x3_20260806"
RUN1 = ROOT / "workspace/runs" / CASE1
RUN2 = ROOT / "workspace/runs" / CASE2
LOG = ROOT / "workspace/runs/e02_s1s2_a3_0805_precal_20260806.log"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def env() -> dict[str, str]:
    out = os.environ.copy()
    out.update({
        "PYTHONPATH": str(ROOT),
        "DSSAT_CUSTOM_EXE": str(EXE.resolve()),
        "DSSAT_SPE_BASE": str(SPE.resolve()),
        "DSSAT_SOIL_BASE": str(SOIL.resolve()),
        "DSSAT_KEEP_RUNS": "1",
    })
    return out


def run(cmd: list[str], log, *, cwd: Path = ROOT) -> None:
    log.write(f"\n$ {' '.join(cmd)}\n")
    log.flush()
    proc = subprocess.run(cmd, cwd=cwd, env=env(), stdout=log, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def build(stage: str, case: str, out_dir: Path, log, fixed_from: Path | None = None) -> None:
    cmd = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--design-config", str(DESIGN), "--stage", stage,
        "--multiseason-design", str(MULTI), "--input-dir", str(BUNDLE),
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant", "--prefix", case,
        "--noptmax", "3", "--ies-num-reals", "100", "--random-seed", "20260806",
        "--initial-ensemble-method", "sobol", "--batch", str(BUNDLE / "DSSBatch.v48"),
        "--harvest-var", "CHPDT", "--include-n-uptake", "--include-soil",
        "--param-review-mode", "off", "--bounds-review-mode", "off",
        "--observation-policy-csv", str(POLICY), "--out-dir", str(out_dir),
        "--weight-scheme", "raw", "--bad-phi-sigma", "1e300",
    ]
    if fixed_from is not None:
        cmd.extend(["--fixed-from", str(fixed_from)])
    run(cmd, log)


def smoke(run_dir: Path, case: str, log) -> None:
    cmd = [
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(MULTI), "--param-csv", str(run_dir / f"{case}_params.csv"),
        "--harvest-var", "CHPDT", "--prefix", f"{case}_smoke", "--keep-nitrogen-outputs",
    ]
    run(cmd, log, cwd=run_dir)
    (run_dir / "smoke_receipt.json").write_text(json.dumps({
        "status": "passed", "case": case, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "custom_executable": str(EXE), "custom_spe": str(SPE), "bundle_manifest_sha256": sha(BUNDLE / "input_manifest.json"),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ies(run_dir: Path, case: str, port: int, log) -> None:
    run([
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir), "--case", case, "--mode", "ies", "--n-agents", "4", "--port", str(port), "--wait",
    ], log)
    run([
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir), "--case", case, "--mode", "ies", "--finalize",
    ], log)


def main() -> int:
    RUN1.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as log:
        receipt = {
            "status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "bounds_id": BOUNDS_ID, "design_config": str(DESIGN), "multiseason_design": str(MULTI),
            "bundle": str(BUNDLE), "bundle_manifest_sha256": sha(BUNDLE / "input_manifest.json"),
            "tmx_sha256": sha(BUNDLE / "XXQL2501.TMX"), "tmt_sha256": sha(BUNDLE / "XXQL2501.TMT"),
            "custom_executable": str(EXE), "custom_executable_sha256": sha(EXE),
            "custom_spe": str(SPE), "custom_spe_sha256": sha(SPE),
            "fl_vs_fixed": 120.0, "stages": {},
        }
        (ROOT / "workspace/runs/e02_s1s2_a3_0805_precal_launch_receipt_20260806.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rep = RUN1 / "calibration_finalize/stage_representative_params.csv"
        finalize_json = RUN1 / "calibration_finalize/calibration_finalize.json"
        existing_stage = ""
        if finalize_json.is_file():
            try:
                existing_stage = str(json.loads(finalize_json.read_text(encoding="utf-8")).get("design_stage") or "")
            except (OSError, json.JSONDecodeError):
                existing_stage = ""
        if not (rep.is_file() and existing_stage.upper() == "S1"):
            build("S1", CASE1, RUN1, log)
            smoke(RUN1, CASE1, log)
            ies(RUN1, CASE1, 4091, log)
        if not rep.is_file():
            raise RuntimeError(f"S1 finalize did not produce {rep}")
        receipt["stages"]["S1"] = {"status": "finalized", "run_dir": str(RUN1), "representative": str(rep), "representative_sha256": sha(rep)}
        RUN2.mkdir(parents=True, exist_ok=True)
        build("S2", CASE2, RUN2, log, fixed_from=rep)
        smoke(RUN2, CASE2, log)
        ies(RUN2, CASE2, 4092, log)
        rep2 = RUN2 / "calibration_finalize/stage_representative_params.csv"
        receipt["stages"]["S2"] = {"status": "finalized", "run_dir": str(RUN2), "representative": str(rep2), "representative_sha256": sha(rep2) if rep2.is_file() else ""}
        receipt["status"] = "completed"
        receipt["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        (ROOT / "workspace/runs/e02_s1s2_a3_0805_precal_launch_receipt_20260806.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
