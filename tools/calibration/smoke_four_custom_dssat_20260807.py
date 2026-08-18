"""Smoke-test the four custom DSSAT versions (20260806).

For each of the four custom DSSAT builds, swap in its exe + SPE template,
run ONE DSSAT evaluation with the base parameter set, verify the six output
files are produced, then restore the default exe/templates.

Usage:
    python tools/calibration/smoke_four_custom_dssat_20260807.py [--version VERSION]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import pyemu

ROOT = Path(__file__).resolve().parents[2]

VERSIONS = {
    "a3": {"exe_dir": "windows_a3_20260806"},
    "a3_nr_zp": {"exe_dir": "windows_a3_nr_zp_20260806"},
    "nni": {"exe_dir": "windows_nni_20260806"},
    "nresp": {"exe_dir": "windows_nresp_20260806"},
}

DEFAULT_EXE = ROOT / "workspace/DSCSM048.EXE"
GENOTYPE_DIR = ROOT / "data/templates/genotype"


def _swap(version: str) -> list[tuple[Path, Path]]:
    """Swap the version's exe + SPE template in; returns restore list."""
    exe_dir = ROOT / "windows" / VERSIONS[version]["exe_dir"]
    custom_exe = exe_dir / "DSCSM048.EXE"
    custom_spe = exe_dir / "Genotype/TMGRO048.SPE"
    if not custom_exe.is_file() or not custom_spe.is_file():
        raise FileNotFoundError(f"{version}: missing exe/SPE in {exe_dir}")

    replacements: list[tuple[Path, Path]] = []
    # Exe swap: default -> backup, custom -> default
    backup_exe = ROOT / f"workspace/DSCSM048.EXE.smoke_{version}"
    if backup_exe.exists():
        raise FileExistsError(f"stale backup: {backup_exe}")
    shutil.copy2(DEFAULT_EXE, backup_exe)
    shutil.copy2(custom_exe, DEFAULT_EXE)
    replacements.append((DEFAULT_EXE, backup_exe))

    # SPE base swap: .base -> backup, custom -> .base
    spe_base = GENOTYPE_DIR / "TMGRO048.SPE.base"
    spe_backup = GENOTYPE_DIR / f"TMGRO048.SPE.base.smoke_{version}"
    if spe_backup.exists():
        raise FileExistsError(f"stale SPE backup: {spe_backup}")
    shutil.copy2(spe_base, spe_backup)
    shutil.copy2(custom_spe, spe_base)
    replacements.append((spe_base, spe_backup))

    # Plain SPE (if present, e.g. run-time instantiated)
    plain = GENOTYPE_DIR / "TMGRO048.SPE"
    if plain.is_file():
        plain_backup = GENOTYPE_DIR / f"TMGRO048.SPE.smoke_{version}"
        if plain_backup.exists():
            raise FileExistsError(f"stale plain SPE backup: {plain_backup}")
        shutil.copy2(plain, plain_backup)
        shutil.copy2(custom_spe, plain)
        replacements.append((plain, plain_backup))
    return replacements


def _restore(replacements: list[tuple[Path, Path]]) -> None:
    for live, backup in reversed(replacements):
        if live.exists():
            live.unlink()
        if backup.exists():
            backup.replace(live)


def smoke_version(version: str) -> bool:
    case = f"e02_v2_rawdiff_terminal_{version}_108par_150x4_20260807"
    run_dir = ROOT / "workspace/runs" / case
    pst_path = run_dir / f"{case}.pst"
    if not pst_path.is_file():
        print(f"[{version}] SKIP: PST not found: {pst_path}")
        return False

    print(f"\n[{version}] smoke test (exe={VERSIONS[version]['exe_dir']})")
    replacements = _swap(version)
    try:
        pst = pyemu.Pst(str(pst_path))
        lines = ["name,value"] + [
            f"{n},{v}" for n, v in zip(pst.parameter_data.index, pst.parameter_data.parval1)
        ]
        smoke_param = run_dir / f"{case}_smoke_params.csv"
        smoke_param.write_text("\n".join(lines), encoding="utf-8")

        model_cmd = pst.model_command[0] if isinstance(pst.model_command, list) else pst.model_command
        cmd = model_cmd.replace(f"{case}_params.csv", f"{case}_smoke_params.csv")
        print(f"  running: {cmd[:120]}...")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180, cwd=str(run_dir))
        print(f"  exit_code={result.returncode}")
        if result.returncode != 0:
            print(f"  STDERR: {result.stderr[-500:]}")
            return False

        ok = True
        for outf in ("PestEval.OUT", "PestHarvest.OUT", "PestTmtGrow.OUT",
                     "PestNResponse.OUT", "PestSoilWat.OUT", "PestJoint.OUT"):
            p = run_dir / outf
            sz = p.stat().st_size if p.exists() else 0
            print(f"  {outf}: {sz} bytes {'OK' if sz > 0 else 'EMPTY!'}")
            if sz == 0:
                ok = False
        return ok
    finally:
        _restore(replacements)
        smoke_param = run_dir / f"{case}_smoke_params.csv"
        smoke_param.unlink(missing_ok=True)
        for outf in ("PestEval.OUT", "PestHarvest.OUT", "PestTmtGrow.OUT",
                     "PestNResponse.OUT", "PestSoilWat.OUT", "PestJoint.OUT"):
            (run_dir / outf).unlink(missing_ok=True)
        print(f"[{version}] restored default exe/SPE")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=list(VERSIONS), default=None)
    args = parser.parse_args()
    to_test = [args.version] if args.version else list(VERSIONS)
    all_ok = True
    for v in to_test:
        ok = smoke_version(v)
        all_ok = all_ok and ok
        print(f"[{v}] SMOKE {'PASSED' if ok else 'FAILED'}")
    print(f"\n{'='*50}")
    print(f"OVERALL: {'ALL PASSED' if all_ok else 'SOME FAILED'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
