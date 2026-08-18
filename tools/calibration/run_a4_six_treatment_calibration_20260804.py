"""Smoke-test and launch the A4 six-treatment 25SP IES calibration."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CASE = "a4_v1_formal25sp_nreleased_nrexp_nrmin_nup_6treat_150x4_20260804"
RUN_DIR = ROOT / "workspace/runs" / CASE
DESIGN = RUN_DIR / "six_treatment_design.json"
INPUT = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"
CUSTOM_EXE = ROOT / "windows/windows_a4_20260804/dscsm048_a4.exe"
CUSTOM_SPE = ROOT / "windows/windows_a4_20260804/Genotype/TMGRO048.SPE"
TOMATO_ROOT = Path(r"C:\DSSAT48\TOMATO")


def _set_env() -> None:
    os.environ["DSSAT_CUSTOM_EXE"] = str(CUSTOM_EXE)
    os.environ["DSSAT_SPE_BASE"] = str(CUSTOM_SPE)
    os.environ["DSSAT_SOIL_BASE"] = str(INPUT / "SOIL.SOL")
    os.environ["DSSAT_BATCH_FILEX_ROOT"] = str(TOMATO_ROOT)
    os.environ["DSSAT_KEEP_RUNS"] = "1"
    os.environ["DSSAT_FILEX_MAP"] = json.dumps({"XXQL2501.TMX": str(INPUT / "XXQL2501.TMX")})


def _backup_filex(out_dir: Path) -> Path:
    backup = out_dir / "dssat_tomato_backup"
    backup.mkdir(parents=True, exist_ok=True)
    source = TOMATO_ROOT / "XXQL2501.TMX"
    if source.is_file():
        shutil.copy2(source, backup / source.name)
    return backup


def _restore_filex(backup: Path) -> None:
    TOMATO_ROOT.mkdir(parents=True, exist_ok=True)
    for source in backup.glob("*.TMX"):
        shutil.copy2(source, TOMATO_ROOT / source.name)


def _preflight_injection() -> None:
    """Verify all three A4 SPE slots survive exact read/write formatting."""
    sys.path.insert(0, str(ROOT))
    from src.dssat.run_dssat import update_spe_file

    with tempfile.TemporaryDirectory(prefix="a4_nup_preflight_", dir=str(ROOT / "workspace")) as tmp:
        work = Path(tmp)
        shutil.copy2(CUSTOM_SPE, work / "TMGRO048.SPE.base")
        params = work / "params.csv"
        with params.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["name", "value"])
            writer.writerow(["NUPK50", "17.25"])
            writer.writerow(["NUPQ", "1.00"])
            writer.writerow(["NUPAV", "0.73"])
        old = Path.cwd()
        try:
            os.chdir(work)
            update_spe_file(str(params))
        finally:
            os.chdir(old)
        line = next(x for x in (work / "TMGRO048.SPE").read_text(encoding="utf-8").splitlines() if "NUPK50" in x)
        if not all(token in line for token in ("17.25", "1.00", ".73")):
            raise RuntimeError(f"A4 NUP injection failed: {line!r}")
        print(f"[preflight] A4 NUP injection OK: {line}", flush=True)


def _run(command: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def _smoke() -> None:
    _run(
        [
            sys.executable,
            "-m",
            "src.calibration.run_multiseason",
            "--design",
            str(DESIGN),
            "--param-csv",
            str(RUN_DIR / f"{CASE}_params.csv"),
            "--harvest-var",
            "CHPDT",
            "--prefix",
            CASE,
            "--observation-transform-config",
            str(RUN_DIR / f"{CASE}.observation_transforms.json"),
            "--keep-nitrogen-outputs",
        ]
    )


def _launch(n_agents: int, port: int) -> None:
    _run(
        [
            sys.executable,
            "tools/parallel/run_parallel.py",
            "--run-dir",
            str(RUN_DIR),
            "--case",
            CASE,
            "--mode",
            "ies",
            "--n-agents",
            str(n_agents),
            "--port",
            str(port),
            "--wait",
        ]
    )


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke-only", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--n-agents", type=int, default=4)
    ap.add_argument("--port", type=int, default=4032)
    args = ap.parse_args()
    if args.smoke_only and args.run:
        raise ValueError("--smoke-only and --run are mutually exclusive")
    if not (RUN_DIR / f"{CASE}.pst").is_file():
        raise FileNotFoundError(RUN_DIR / f"{CASE}.pst")
    _set_env()
    _preflight_injection()
    backup = _backup_filex(RUN_DIR)
    try:
        _smoke()
        if args.smoke_only:
            return 0
        if args.run:
            _launch(args.n_agents, args.port)
            status = json.loads((RUN_DIR / "run_status.json").read_text(encoding="utf-8"))
            if status.get("status") != "completed":
                raise RuntimeError(f"A4 IES did not complete: {status.get('status')!r}")
            print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0
    finally:
        _restore_filex(backup)


if __name__ == "__main__":
    raise SystemExit(main())
