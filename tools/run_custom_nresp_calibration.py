"""Run the six-treatment NREXP/NRMIN IES case with a temporary DSSAT swap."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(r"D:/Tomato_Cal")
RUN_DIR = ROOT / "workspace/runs" / os.environ.get(
    "SIX_TREATMENT_PREFIX",
    "e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260803_retry3",
)
CASE = RUN_DIR.name
CUSTOM_DIR = ROOT / "windows/windows_nresp_20260803"
CUSTOM_EXE = CUSTOM_DIR / "dscsm048_nresp.exe"
CUSTOM_GENOTYPE = CUSTOM_DIR / "Genotype"
DEFAULT_EXE = ROOT / "workspace/DSCSM048.EXE"
BACKUP_EXE = ROOT / "workspace/DSCSM048.EXE.default_backup_20260803_nresp6"
GENOTYPE_DIR = ROOT / "data/templates/genotype"
BACKUP_SUFFIX = ".default_backup_20260803_nresp6"


def _active_processes() -> list[str]:
    result = subprocess.run(["tasklist"], capture_output=True, text=True, check=False)
    names = []
    for line in result.stdout.splitlines():
        upper = line.upper()
        if any(token in upper for token in ("DSCSM", "PEST", "PANTHER")):
            names.append(line.strip())
    return names


def _preflight_xpodf() -> None:
    import csv

    sys.path.insert(0, str(ROOT))
    import src.dssat.run_dssat as runner

    with tempfile.TemporaryDirectory(prefix="nresp_xpodf_preflight_", dir=str(ROOT / "workspace")) as tmp:
        work = Path(tmp)
        shutil.copy2(CUSTOM_GENOTYPE / "TMGRO048.SPE", work / "TMGRO048.SPE.base")
        params = work / "params.csv"
        with params.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["name", "value"])
            writer.writerow(["NSTFAC", "0.73"])
            writer.writerow(["NREXP", "0.61"])
            writer.writerow(["NRMIN", "0.77"])
        old_cwd = Path.cwd()
        try:
            os.chdir(work)
            runner.update_spe_file(str(params))
        finally:
            os.chdir(old_cwd)
        line = next(line for line in (work / "TMGRO048.SPE").read_text(encoding="utf-8").splitlines() if "XPODF" in line)
        if not all(token in line for token in (".73", ".61", ".77")):
            raise RuntimeError(f"XPODF preflight failed; generated line was: {line!r}")
        print(f"[preflight] XPODF injection OK: {line}")


def _swap_in() -> list[tuple[Path, Path]]:
    if not CUSTOM_EXE.is_file():
        raise FileNotFoundError(CUSTOM_EXE)
    if not DEFAULT_EXE.is_file():
        raise FileNotFoundError(DEFAULT_EXE)
    if BACKUP_EXE.exists():
        raise FileExistsError(f"stale executable backup exists: {BACKUP_EXE}")
    for filename in ("TMGRO048.SPE",):
        if not (CUSTOM_GENOTYPE / filename).is_file():
            raise FileNotFoundError(CUSTOM_GENOTYPE / filename)

    replacements: list[tuple[Path, Path]] = []
    DEFAULT_EXE.replace(BACKUP_EXE)
    shutil.copy2(CUSTOM_EXE, DEFAULT_EXE)
    replacements.append((DEFAULT_EXE, BACKUP_EXE))
    try:
        for filename in ("TMGRO048.SPE",):
            source = GENOTYPE_DIR / f"{filename}.base"
            backup = GENOTYPE_DIR / f"{filename}.base{BACKUP_SUFFIX}"
            if not source.is_file() or backup.exists():
                raise FileNotFoundError(f"template swap target unavailable: {source}")
            source.replace(backup)
            shutil.copy2(CUSTOM_GENOTYPE / filename, source)
            replacements.append((source, backup))
            plain = GENOTYPE_DIR / filename
            plain_backup = GENOTYPE_DIR / f"{filename}{BACKUP_SUFFIX}"
            if plain.is_file():
                if plain_backup.exists():
                    raise FileExistsError(f"stale template backup exists: {plain_backup}")
                plain.replace(plain_backup)
                shutil.copy2(CUSTOM_GENOTYPE / filename, plain)
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
        raise FileNotFoundError(RUN_DIR)
    if _active_processes():
        raise RuntimeError("DSSAT/PEST-related processes are active; refusing to swap files")
    _preflight_xpodf()
    replacements: list[tuple[Path, Path]] = []
    try:
        replacements = _swap_in()
        print(f"[run] custom executable active: {CUSTOM_EXE}")
        command = [
            sys.executable,
            "tools/parallel/run_parallel.py",
            "--run-dir", str(RUN_DIR),
            "--case", CASE,
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
            "--run-dir", str(RUN_DIR),
            "--case", CASE,
        ]
        return int(subprocess.run(finalize, cwd=ROOT, check=False).returncode)
    finally:
        if replacements:
            _restore(replacements)
            print("[restore] default executable and genotype templates restored")
        active = _active_processes()
        if active:
            print("[warning] related processes remain active after restore:")
            print("\n".join(active))


if __name__ == "__main__":
    raise SystemExit(main())
