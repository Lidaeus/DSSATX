"""Build, smoke-test, and launch the posterior-edge-adjusted IES rerun."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "configs/runs/eggplant_26sp_w1w2_n012_postprecal_allgenetic_postadj_nrexp065_20260804.json"
POLICY = ROOT / "configs/runs/e02_plantn_chpdtlog_noadap_no_nresponse_v1.csv"
BOUNDS_ID = "eggplant_26sp_w1w2_n012_postprecal_allgenetic_postadj_nrexp065_20260804"
INPUT = ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729"
CUSTOM_EXE = ROOT / "windows/windows_nresp_20260803/dscsm048_nresp.exe"
CUSTOM_SPE = ROOT / "windows/windows_nresp_20260803/Genotype/TMGRO048.SPE"
TOMATO_ROOT = Path(r"C:\DSSAT48\TOMATO")


def _set_env() -> None:
    os.environ["DSSAT_CUSTOM_EXE"] = str(CUSTOM_EXE)
    os.environ["DSSAT_SPE_BASE"] = str(CUSTOM_SPE)
    os.environ["DSSAT_SOIL_BASE"] = str(INPUT / "SOIL.SOL")
    os.environ["DSSAT_BATCH_FILEX_ROOT"] = str(TOMATO_ROOT)
    os.environ["DSSAT_KEEP_RUNS"] = "1"
    os.environ["DSSAT_DISABLE_SOIL_INJECTION"] = "1"
    os.environ["DSSAT_FILEX_MAP"] = json.dumps({"XXQL2601.TMX": str(INPUT / "XXQL2601.TMX")})


def _backup_filex(out_dir: Path) -> Path:
    backup = out_dir / "dssat_tomato_backup"
    backup.mkdir(parents=True, exist_ok=True)
    source = TOMATO_ROOT / "XXQL2601.TMX"
    if source.is_file():
        shutil.copy2(source, backup / source.name)
    return backup


def _restore_filex(backup: Path) -> None:
    for source in backup.glob("*.TMX"):
        shutil.copy2(source, TOMATO_ROOT / source.name)


def _run(command: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def _build(out_dir: Path, case: str, n_reals: int, noptmax: int, seed: int) -> None:
    _run([
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--multiseason-design", str(DESIGN),
        "--input-dir", str(INPUT), "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--prefix", case, "--noptmax", str(noptmax), "--ies-num-reals", str(n_reals),
        "--random-seed", str(seed), "--bad-phi-sigma", "1e300", "--batch", str(INPUT / "DSSBatch.v48"),
        "--harvest-var", "CHPDT", "--include-n-uptake", "--out-dir", str(out_dir),
        "--param-review-mode", "off", "--observation-policy-csv", str(POLICY),
    ])


def _smoke(out_dir: Path, case: str) -> None:
    _run([
        sys.executable, "-m", "src.calibration.run_multiseason",
        "--design", str(DESIGN), "--param-csv", str(out_dir / f"{case}_params.csv"),
        "--harvest-var", "CHPDT", "--prefix", case,
        "--observation-transform-config", str(out_dir / f"{case}.observation_transforms.json"),
        "--keep-nitrogen-outputs",
    ])


def _launch(out_dir: Path, case: str, n_agents: int, port: int) -> None:
    _run([
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(out_dir), "--case", case, "--mode", "ies",
        "--n-agents", str(n_agents), "--port", str(port), "--wait",
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--n-reals", type=int, default=200)
    ap.add_argument("--noptmax", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20260805)
    ap.add_argument("--n-agents", type=int, default=6)
    ap.add_argument("--port", type=int, default=4024)
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--smoke-only", action="store_true")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()
    if args.build_only and (args.smoke_only or args.run):
        raise ValueError("build-only cannot be combined with smoke-only or run")
    if args.smoke_only and args.run:
        raise ValueError("smoke-only cannot be combined with run")
    case = args.run_dir.name
    args.run_dir.mkdir(parents=True, exist_ok=True)
    _set_env()
    backup = _backup_filex(args.run_dir)
    try:
        if not (args.run_dir / f"{case}.pst").is_file():
            _build(args.run_dir, case, args.n_reals, args.noptmax, args.seed)
        if args.build_only:
            return 0
        _smoke(args.run_dir, case)
        if args.smoke_only:
            return 0
        if args.run:
            _launch(args.run_dir, case, args.n_agents, args.port)
            status = json.loads((args.run_dir / "run_status.json").read_text(encoding="utf-8"))
            if status.get("status") != "completed":
                raise RuntimeError(f"IES did not complete: {status.get('status')!r}")
            print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0
    finally:
        _restore_filex(backup)


if __name__ == "__main__":
    raise SystemExit(main())
