"""Launch fixed-soil joint calibration (a3 or official variant, 20260813).

Swaps in the variant DSSAT exe + SPE, runs PEST++ IES (200 reals x 5 iters),
restores, then finalizes.

Usage:
    python tools/calibration/launch_fixed_soil_joint_20260813.py --variant a3|official
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

VARIANTS = {
    "a3": {
        "case": "e02_v2_fixedsoil_joint_a3_25sp26sp_200x5_20260813",
        "exe": ROOT / "windows/windows_a3_20260805/dscsm048_a3.exe",
        "spe": ROOT / "windows/windows_a3_20260805/Genotype/TMGRO048.SPE",
        "port": "4036",
        "desc": "a3 (thresholded N uptake)",
    },
    "official": {
        "case": "e02_v2_fixedsoil_joint_official_25sp26sp_200x5_20260813",
        "exe": ROOT / "DSCSM048.EXE",
        "spe": Path(r"C:\DSSAT48\Genotype\TMGRO048.SPE"),
        "port": "4040",
        "desc": "official DSSAT v4.8",
    },
}
DEFAULT_EXE = ROOT / "workspace/DSCSM048.EXE"
GENOTYPE_DIR = ROOT / "data/templates/genotype"


def _completed_run_status(run_dir: Path) -> dict[str, object] | None:
    """Return validated completion metadata, if this case already finished."""
    status_path = run_dir / "run_status.json"
    if not status_path.is_file():
        return None
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        status.get("status") == "completed"
        and status.get("manager_exit_code") == 0
        and status.get("engineering_status") == "engineering_validated"
    ):
        return status
    return None


def _active_processes() -> list[str]:
    result = subprocess.run(["tasklist"], capture_output=True, text=True, check=False)
    return [line.strip() for line in result.stdout.splitlines()
            if any(tok in line.upper() for tok in ("DSCSM", "PEST", "PANTHER"))]


def _swap_in(variant: str) -> list[tuple[Path, Path]]:
    cfg = VARIANTS[variant]
    if not cfg["exe"].is_file():
        raise FileNotFoundError(cfg["exe"])
    if not cfg["spe"].is_file():
        raise FileNotFoundError(cfg["spe"])
    backup_exe = ROOT / f"workspace/DSCSM048.EXE.default_backup_20260813v2_{variant}"
    if backup_exe.exists():
        raise FileExistsError(f"stale backup: {backup_exe}")
    replacements: list[tuple[Path, Path]] = []
    DEFAULT_EXE.replace(backup_exe)
    shutil.copy2(cfg["exe"], DEFAULT_EXE)
    replacements.append((DEFAULT_EXE, backup_exe))
    try:
        spe_base = GENOTYPE_DIR / "TMGRO048.SPE.base"
        spe_backup = GENOTYPE_DIR / f"TMGRO048.SPE.base.default_backup_20260813v2_{variant}"
        if not spe_base.is_file() or spe_backup.exists():
            raise FileNotFoundError(f"template swap target unavailable: {spe_base}")
        spe_base.replace(spe_backup)
        shutil.copy2(cfg["spe"], spe_base)
        replacements.append((spe_base, spe_backup))
        plain = GENOTYPE_DIR / "TMGRO048.SPE"
        if plain.is_file():
            plain_backup = GENOTYPE_DIR / f"TMGRO048.SPE.default_backup_20260813v2_{variant}"
            if plain_backup.exists():
                raise FileExistsError(f"stale plain backup: {plain_backup}")
            plain.replace(plain_backup)
            shutil.copy2(cfg["spe"], plain)
            replacements.append((plain, plain_backup))
    except Exception:
        _restore(replacements)
        raise
    return replacements


def _restore(replacements: list[tuple[Path, Path]]) -> None:
    for live, backup in reversed(replacements):
        if live.exists():
            live.unlink()
        if backup.exists():
            backup.replace(live)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=list(VARIANTS), required=True)
    args = ap.parse_args()
    cfg = VARIANTS[args.variant]
    case = cfg["case"]
    run_dir = ROOT / "workspace/runs" / case

    if not run_dir.is_dir():
        print(f"ERROR: run dir not found: {run_dir}", file=sys.stderr)
        return 1
    pst = run_dir / f"{case}.pst"
    if not pst.is_file():
        print(f"ERROR: PST not found: {pst}", file=sys.stderr)
        return 1
    completed = _completed_run_status(run_dir)
    if completed is not None:
        print(f"[already-completed] case={case}")
        print(
            "[already-completed] engineering_status=engineering_validated "
            f"finished_at={completed.get('finished_at', 'unknown')}"
        )
        print(
            "[science-gate] science_pending is expected: scientific promotion "
            "requires separate machine evidence; it is not a calibration error."
        )
        return 0

    rec = run_dir / f"{case}.rec"
    if rec.is_file():
        print(
            f"ERROR: {rec.name} exists but the run is not engineering-validated. "
            "Refusing to overwrite partial calibration artifacts; diagnose or "
            "resume the run explicitly.",
            file=sys.stderr,
        )
        return 2

    if _active_processes():
        print("ERROR: DSSAT/PEST processes active; refusing to swap", file=sys.stderr)
        return 1

    print(f"[launch] case={case}")
    print(f"[launch] variant: {cfg['desc']} | exe: {cfg['exe']}")
    print(f"[launch] IC/soil params FIXED; adjustable = genetic only")
    print(f"[launch] Phi budgets: SOIL_WATER x1/4, N_RESPONSE x1/4, DRY_TOTAL x3")
    replacements: list[tuple[Path, Path]] = []
    try:
        replacements = _swap_in(args.variant)
        print(f"[run] {cfg['desc']} exe active")
        command = [
            sys.executable,
            "tools/parallel/run_parallel.py",
            "--run-dir", str(run_dir),
            "--case", case,
            "--mode", "ies",
            "--n-agents", "2",
            "--port", cfg["port"],
            "--wait",
        ]
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode != 0:
            return int(result.returncode)
        finalize = [
            sys.executable,
            "-m", "src.calibration.finalize_calibration",
            "--run-dir", str(run_dir),
            "--case", case,
        ]
        return int(subprocess.run(finalize, cwd=ROOT, check=False).returncode)
    finally:
        if replacements:
            _restore(replacements)
            print("[restore] default exe and SPE restored")


if __name__ == "__main__":
    sys.exit(main())
