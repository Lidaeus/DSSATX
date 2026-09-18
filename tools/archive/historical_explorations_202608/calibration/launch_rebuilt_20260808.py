"""Launch IES calibration for one of the rebuilt (DMFR-corrected) cases.

Rebuilt on 2026-08-08 against the DMFR-corrected bundle (TN13/TN5 anomalous
moisture replicates removed).  Swaps the version-specific DSCSM048.EXE + SPE
template, runs parallel PEST++ IES (150 reals x 4 iters, 4 agents, port 4030),
restores the default exe/templates, then finalizes.

Usage:
    python tools/calibration/launch_rebuilt_20260808.py --version <nresp|a3|a3_nr_zp|nni>
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATE = "20260808"

VERSIONS = {
    "nresp": {"exe_dir": "windows_nresp_20260806",
              "title": "批次B重建·原生吸收+连续NR响应 (NREXP+NRMIN)"},
    "a3": {"exe_dir": "windows_a3_20260806",
           "title": "A3 阈值氮吸收 (NUPK50+NUPCMN, 原生NSTRES)"},
    "a3_nr_zp": {"exe_dir": "windows_a3_nr_zp_20260806",
                 "title": "A3+零保持NR响应 (NUPK50+NUPCMN+NREXP+NRMIN)"},
    "nni": {"exe_dir": "windows_nni_20260806",
            "title": "NNI 临界氮稀释验证 (NUPK50+NUPQ)"},
}

DEFAULT_EXE = ROOT / "workspace/DSCSM048.EXE"
GENOTYPE_DIR = ROOT / "data/templates/genotype"


def _active_processes() -> list[str]:
    result = subprocess.run(["tasklist"], capture_output=True, text=True, check=False)
    return [line.strip() for line in result.stdout.splitlines()
            if any(tok in line.upper() for tok in ("DSCSM", "PEST", "PANTHER"))]


def _swap_in(version: str) -> list[tuple[Path, Path]]:
    exe_dir = ROOT / "windows" / VERSIONS[version]["exe_dir"]
    custom_exe = exe_dir / "DSCSM048.EXE"
    custom_spe = exe_dir / "Genotype/TMGRO048.SPE"
    if not custom_exe.is_file():
        raise FileNotFoundError(custom_exe)
    if not custom_spe.is_file():
        raise FileNotFoundError(custom_spe)
    if not DEFAULT_EXE.is_file():
        raise FileNotFoundError(DEFAULT_EXE)

    backup_exe = ROOT / f"workspace/DSCSM048.EXE.default_backup_{DATE}_{version}"
    if backup_exe.exists():
        raise FileExistsError(f"stale executable backup exists: {backup_exe}")

    replacements: list[tuple[Path, Path]] = []
    DEFAULT_EXE.replace(backup_exe)
    shutil.copy2(custom_exe, DEFAULT_EXE)
    replacements.append((DEFAULT_EXE, backup_exe))
    try:
        spe_base = GENOTYPE_DIR / "TMGRO048.SPE.base"
        spe_backup = GENOTYPE_DIR / f"TMGRO048.SPE.base.default_backup_{DATE}_{version}"
        if not spe_base.is_file() or spe_backup.exists():
            raise FileNotFoundError(f"template swap target unavailable: {spe_base}")
        spe_base.replace(spe_backup)
        shutil.copy2(custom_spe, spe_base)
        replacements.append((spe_base, spe_backup))
        plain = GENOTYPE_DIR / "TMGRO048.SPE"
        if plain.is_file():
            plain_backup = GENOTYPE_DIR / f"TMGRO048.SPE.default_backup_{DATE}_{version}"
            if plain_backup.exists():
                raise FileExistsError(f"stale plain template backup exists: {plain_backup}")
            plain.replace(plain_backup)
            shutil.copy2(custom_spe, plain)
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, choices=list(VERSIONS))
    args = parser.parse_args()
    version = args.version

    case = f"e02_v2_rawdiff_terminal_{version}_108par_150x4_{DATE}"
    run_dir = ROOT / "workspace/runs" / case
    if not run_dir.is_dir():
        print(f"ERROR: run dir not found: {run_dir}", file=sys.stderr)
        return 1
    pst = run_dir / f"{case}.pst"
    if not pst.is_file():
        print(f"ERROR: PST not found: {pst}", file=sys.stderr)
        return 1
    rec = run_dir / f"{case}.rec"
    if rec.is_file():
        print(f"WARNING: {rec.name} exists — case may have been run already.", file=sys.stderr)
        resp = input("Continue anyway? [y/N] ").strip().lower()
        if resp != "y":
            print("Aborted.")
            return 1

    if _active_processes():
        print("ERROR: DSSAT/PEST-related processes are active; refusing to swap files", file=sys.stderr)
        return 1

    print(f"[launch] version={version} ({VERSIONS[version]['title']})")
    print(f"[launch] case={case} (DMFR-corrected bundle {DATE})")
    replacements: list[tuple[Path, Path]] = []
    try:
        replacements = _swap_in(version)
        print(f"[run] custom executable active: {ROOT / 'windows' / VERSIONS[version]['exe_dir'] / 'DSCSM048.EXE'}")
        command = [
            sys.executable,
            "tools/parallel/run_parallel.py",
            "--run-dir", str(run_dir),
            "--case", case,
            "--mode", "ies",
            "--n-agents", "4",
            "--port", "4030",
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
            print("[restore] default executable and genotype templates restored")


if __name__ == "__main__":
    sys.exit(main())
