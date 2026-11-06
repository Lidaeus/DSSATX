"""Smoke test for official-DSSAT joint calibration (20260809).

Swaps in the OFFICIAL DSSAT v4.8 exe + SPE, runs one model evaluation at init
values, verifies all six PEST observation outputs are non-empty, restores.

Usage:
    python tools/calibration/smoke_official_v2_20260809.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pyemu

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_official_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260809"
RUN_DIR = ROOT / "workspace/runs" / CASE

OFFICIAL_EXE = ROOT / "DSCSM048.EXE"
OFFICIAL_SPE = Path(r"C:\DSSAT48\Genotype\TMGRO048.SPE")
DEFAULT_EXE = ROOT / "workspace/DSCSM048.EXE"
GENOTYPE_DIR = ROOT / "data/templates/genotype"

OUTPUTS = ("PestEval.OUT", "PestHarvest.OUT", "PestTmtGrow.OUT",
           "PestNResponse.OUT", "PestSoilWat.OUT", "PestJoint.OUT")


def _swap_in() -> list[tuple[Path, Path]]:
    if not OFFICIAL_EXE.is_file():
        raise FileNotFoundError(OFFICIAL_EXE)
    if not OFFICIAL_SPE.is_file():
        raise FileNotFoundError(OFFICIAL_SPE)
    backup_exe = ROOT / "workspace/DSCSM048.EXE.smoke_official_20260809"
    if backup_exe.exists():
        raise FileExistsError(f"stale backup: {backup_exe}")
    replacements: list[tuple[Path, Path]] = []
    DEFAULT_EXE.replace(backup_exe)
    shutil.copy2(OFFICIAL_EXE, DEFAULT_EXE)
    replacements.append((DEFAULT_EXE, backup_exe))
    try:
        spe_base = GENOTYPE_DIR / "TMGRO048.SPE.base"
        spe_backup = GENOTYPE_DIR / f"TMGRO048.SPE.base.smoke_official_20260809"
        if not spe_base.is_file() or spe_backup.exists():
            raise FileNotFoundError(f"template swap target unavailable: {spe_base}")
        spe_base.replace(spe_backup)
        shutil.copy2(OFFICIAL_SPE, spe_base)
        replacements.append((spe_base, spe_backup))
        plain = GENOTYPE_DIR / "TMGRO048.SPE"
        if plain.is_file():
            plain_backup = GENOTYPE_DIR / f"TMGRO048.SPE.smoke_official_20260809"
            if plain_backup.exists():
                raise FileExistsError(f"stale plain backup: {plain_backup}")
            plain.replace(plain_backup)
            shutil.copy2(OFFICIAL_SPE, plain)
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
    pst_path = RUN_DIR / f"{CASE}.pst"
    if not pst_path.is_file():
        print(f"ERROR: PST not found: {pst_path}", file=sys.stderr)
        return 1

    replacements: list[tuple[Path, Path]] = []
    try:
        replacements = _swap_in()
        print(f"[smoke] OFFICIAL exe active: {OFFICIAL_EXE}")

        pst = pyemu.Pst(str(pst_path))
        lines = ["name,value"] + [
            f"{n},{v}" for n, v in zip(pst.parameter_data.index, pst.parameter_data.parval1)
        ]
        smoke_param = RUN_DIR / f"{CASE}_smoke_params.csv"
        smoke_param.write_text("\n".join(lines), encoding="utf-8")

        model_cmd = pst.model_command[0] if isinstance(pst.model_command, list) else pst.model_command
        cmd = model_cmd.replace(f"{CASE}_params.csv", f"{CASE}_smoke_params.csv")
        print(f"[smoke] running: {cmd[:130]}...")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                timeout=600, cwd=str(RUN_DIR))
        print(f"[smoke] exit_code={result.returncode}")
        if result.returncode != 0:
            print(f"[smoke] STDERR: {result.stderr[-800:]}")
            return result.returncode

        ok = True
        for outf in OUTPUTS:
            p = RUN_DIR / outf
            sz = p.stat().st_size if p.exists() else 0
            print(f"[smoke] {outf}: {sz} bytes {'OK' if sz > 0 else 'EMPTY!'}")
            if sz == 0:
                ok = False
        print("[smoke] PASS" if ok else "[smoke] FAIL")
        return 0 if ok else 2
    finally:
        _restore(replacements)
        (RUN_DIR / f"{CASE}_smoke_params.csv").unlink(missing_ok=True)
        for outf in OUTPUTS:
            (RUN_DIR / outf).unlink(missing_ok=True)
        print("[smoke] restored default exe/SPE")


if __name__ == "__main__":
    sys.exit(main())
