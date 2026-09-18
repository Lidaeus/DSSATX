"""Launch a3-DSSAT joint calibration (20260810).

Swaps in the OFFICIAL DSSAT v4.8 exe (D:\\Tomato_Cal\\DSCSM048.EXE) + official
SPE (C:\\DSSAT48\\Genotype\\TMGRO048.SPE), runs PEST++ IES (200 reals x 5
iters), restores, then finalizes.

Config base: v2 joint calibration with the SAME parameter set
(NREXP/NRMIN/NUPK50/NUPCMN all kept — the a3 SPE contains all four).

Usage:
    python tools/calibration/launch_a3_20260810.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_a3_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260810"
RUN_DIR = ROOT / "workspace/runs" / CASE

A3_EXE = ROOT / "windows/windows_a3_20260805/dscsm048_a3.exe"
A3_SPE = ROOT / "windows/windows_a3_20260805/Genotype/TMGRO048.SPE"
DEFAULT_EXE = ROOT / "workspace/DSCSM048.EXE"
GENOTYPE_DIR = ROOT / "data/templates/genotype"


def _active_processes() -> list[str]:
    result = subprocess.run(["tasklist"], capture_output=True, text=True, check=False)
    return [line.strip() for line in result.stdout.splitlines()
            if any(tok in line.upper() for tok in ("DSCSM", "PEST", "PANTHER"))]


def _swap_in() -> list[tuple[Path, Path]]:
    if not A3_EXE.is_file():
        raise FileNotFoundError(A3_EXE)
    if not A3_SPE.is_file():
        raise FileNotFoundError(A3_SPE)
    backup_exe = ROOT / "workspace/DSCSM048.EXE.default_backup_20260810_a3"
    if backup_exe.exists():
        raise FileExistsError(f"stale backup: {backup_exe}")
    replacements: list[tuple[Path, Path]] = []
    DEFAULT_EXE.replace(backup_exe)
    shutil.copy2(A3_EXE, DEFAULT_EXE)
    replacements.append((DEFAULT_EXE, backup_exe))
    try:
        spe_base = GENOTYPE_DIR / "TMGRO048.SPE.base"
        spe_backup = GENOTYPE_DIR / f"TMGRO048.SPE.base.default_backup_20260810_a3"
        if not spe_base.is_file() or spe_backup.exists():
            raise FileNotFoundError(f"template swap target unavailable: {spe_base}")
        spe_base.replace(spe_backup)
        shutil.copy2(A3_SPE, spe_base)
        replacements.append((spe_base, spe_backup))
        plain = GENOTYPE_DIR / "TMGRO048.SPE"
        if plain.is_file():
            plain_backup = GENOTYPE_DIR / f"TMGRO048.SPE.default_backup_20260810_a3"
            if plain_backup.exists():
                raise FileExistsError(f"stale plain backup: {plain_backup}")
            plain.replace(plain_backup)
            shutil.copy2(A3_SPE, plain)
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
    if not RUN_DIR.is_dir():
        print(f"ERROR: run dir not found: {RUN_DIR}", file=sys.stderr)
        return 1
    pst = RUN_DIR / f"{CASE}.pst"
    if not pst.is_file():
        print(f"ERROR: PST not found: {pst}", file=sys.stderr)
        return 1
    rec = RUN_DIR / f"{CASE}.rec"
    if rec.is_file():
        print(f"WARNING: {rec.name} exists — case may have been run.", file=sys.stderr)
        resp = input("Continue anyway? [y/N] ").strip().lower()
        if resp != "y":
            print("Aborted.")
            return 1

    if _active_processes():
        print("ERROR: DSSAT/PEST processes active; refusing to swap", file=sys.stderr)
        return 1

    print(f"[launch] case={CASE}")
    print(f"[launch] 250 adjustable (103 genetic + 132 IC + 15 soil physical), 200 reals x 5 iters")
    print(f"[launch] 22 treatments dual-season (25SP+26SP)")
    print(f"[launch] A3 exe (thresholded N uptake; NREXP/NRMIN inert in SPE)")
    print(f"[launch] a3 SPE: {A3_SPE}")
    replacements: list[tuple[Path, Path]] = []
    try:
        replacements = _swap_in()
        print(f"[run] official exe active: {A3_EXE}")
        command = [
            sys.executable,
            "tools/parallel/run_parallel.py",
            "--run-dir", str(RUN_DIR),
            "--case", CASE,
            "--mode", "ies",
            "--n-agents", "4",
            "--port", "4032",
            "--wait",
        ]
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode != 0:
            return int(result.returncode)
        finalize = [
            sys.executable,
            "-m", "src.calibration.finalize_calibration",
            "--run-dir", str(RUN_DIR),
            "--case", CASE,
        ]
        return int(subprocess.run(finalize, cwd=ROOT, check=False).returncode)
    finally:
        if replacements:
            _restore(replacements)
            print("[restore] default exe and SPE restored")


if __name__ == "__main__":
    sys.exit(main())
