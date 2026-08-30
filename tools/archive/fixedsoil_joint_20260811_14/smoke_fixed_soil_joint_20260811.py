"""Smoke test for fixed-soil joint calibration (a3 or official variant, 20260811).

Swaps in the variant exe/SPE, runs one model evaluation at init values,
verifies the six PEST outputs, restores.

Usage:
    python tools/calibration/smoke_fixed_soil_joint_20260811.py --variant a3|official
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import pyemu

ROOT = Path(__file__).resolve().parents[2]

VARIANTS = {
    "a3": {
        "case": "e02_v2_fixedsoil_joint_a3_25sp26sp_200x5_20260811",
        "exe": ROOT / "windows/windows_a3_20260805/dscsm048_a3.exe",
        "spe": ROOT / "windows/windows_a3_20260805/Genotype/TMGRO048.SPE",
    },
    "official": {
        "case": "e02_v2_fixedsoil_joint_official_25sp26sp_200x5_20260811",
        "exe": ROOT / "DSCSM048.EXE",
        "spe": Path(r"C:\DSSAT48\Genotype\TMGRO048.SPE"),
    },
}
DEFAULT_EXE = ROOT / "workspace/DSCSM048.EXE"
GENOTYPE_DIR = ROOT / "data/templates/genotype"
OUTPUTS = ("PestEval.OUT", "PestHarvest.OUT", "PestTmtGrow.OUT",
           "PestNResponse.OUT", "PestSoilWat.OUT", "PestJoint.OUT")


def _swap_in(variant: str) -> list[tuple[Path, Path]]:
    cfg = VARIANTS[variant]
    if not cfg["exe"].is_file():
        raise FileNotFoundError(cfg["exe"])
    if not cfg["spe"].is_file():
        raise FileNotFoundError(cfg["spe"])
    backup_exe = ROOT / f"workspace/DSCSM048.EXE.smoke_fixedsoil_{variant}"
    if backup_exe.exists():
        raise FileExistsError(f"stale backup: {backup_exe}")
    replacements: list[tuple[Path, Path]] = []
    DEFAULT_EXE.replace(backup_exe)
    shutil.copy2(cfg["exe"], DEFAULT_EXE)
    replacements.append((DEFAULT_EXE, backup_exe))
    try:
        spe_base = GENOTYPE_DIR / "TMGRO048.SPE.base"
        spe_backup = GENOTYPE_DIR / f"TMGRO048.SPE.base.smoke_fixedsoil_{variant}"
        if not spe_base.is_file() or spe_backup.exists():
            raise FileNotFoundError(f"template swap target unavailable: {spe_base}")
        spe_base.replace(spe_backup)
        shutil.copy2(cfg["spe"], spe_base)
        replacements.append((spe_base, spe_backup))
        plain = GENOTYPE_DIR / "TMGRO048.SPE"
        if plain.is_file():
            plain_backup = GENOTYPE_DIR / f"TMGRO048.SPE.smoke_fixedsoil_{variant}"
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
    pst_path = run_dir / f"{case}.pst"
    if not pst_path.is_file():
        print(f"ERROR: PST not found: {pst_path}", file=sys.stderr)
        return 1

    replacements: list[tuple[Path, Path]] = []
    try:
        replacements = _swap_in(args.variant)
        print(f"[smoke] {args.variant} exe active: {cfg['exe']}")
        pst = pyemu.Pst(str(pst_path))
        lines = ["name,value"] + [
            f"{n},{v}" for n, v in zip(pst.parameter_data.index, pst.parameter_data.parval1)
        ]
        smoke_param = run_dir / f"{case}_smoke_params.csv"
        smoke_param.write_text("\n".join(lines), encoding="utf-8")
        model_cmd = pst.model_command[0] if isinstance(pst.model_command, list) else pst.model_command
        cmd = model_cmd.replace(f"{case}_params.csv", f"{case}_smoke_params.csv")
        print(f"[smoke] running: {cmd[:130]}...")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                timeout=600, cwd=str(run_dir))
        print(f"[smoke] exit_code={result.returncode}")
        if result.returncode != 0:
            print(f"[smoke] STDERR: {result.stderr[-800:]}")
            return result.returncode
        ok = True
        for outf in OUTPUTS:
            p = run_dir / outf
            sz = p.stat().st_size if p.exists() else 0
            print(f"[smoke] {outf}: {sz} bytes {'OK' if sz > 0 else 'EMPTY!'}")
            if sz == 0:
                ok = False
        print(f"[smoke] {args.variant} PASS" if ok else f"[smoke] {args.variant} FAIL")
        return 0 if ok else 2
    finally:
        _restore(replacements)
        (run_dir / f"{case}_smoke_params.csv").unlink(missing_ok=True)
        for outf in OUTPUTS:
            (run_dir / outf).unlink(missing_ok=True)
        print("[smoke] restored default exe/SPE")


if __name__ == "__main__":
    sys.exit(main())
