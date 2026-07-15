"""PEST++ model-command entry point with per-run DSSAT isolation.

Every invocation prepares immutable DSSAT inputs in the current PEST run
directory and executes the real runner there.  No generated model file or
output is shared between calibration workers.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


def _copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Required DSSAT input is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)


def _batch_argument(args: list[str]) -> str:
    for index, value in enumerate(args):
        if value == "--batch" and index + 1 < len(args):
            return args[index + 1]
        if value.startswith("--batch="):
            return value.split("=", 1)[1]
    return "DSSBatch.v48"


def _input_dir_argument(args: list[str]) -> Path | None:
    for index, value in enumerate(args):
        if value == "--input-dir" and index + 1 < len(args):
            return Path(args[index + 1]).expanduser().resolve()
        if value.startswith("--input-dir="):
            return Path(value.split("=", 1)[1]).expanduser().resolve()
    return None


def _local_batch(args: list[str], run_dir: Path, input_dir: Path | None = None) -> Path:
    requested = Path(_batch_argument(args))
    candidates = [
        requested if requested.is_absolute() else run_dir / requested,
        input_dir / requested.name if input_dir else Path("__no_input_dir__"),
        DATA_DIR / "templates" / "batch" / requested.name,
        PROJECT_ROOT / "workspace" / requested.name,
    ]
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise FileNotFoundError(f"DSSAT batch file not found: {requested}")
    destination = run_dir / requested.name
    _copy(source, destination)
    return destination


def _experiment_names(batch_file: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in batch_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("!", "*", "@")):
            continue
        token = line.split()[0]
        if Path(token).suffix.upper() in {".TMX", ".TMA", ".TMT"}:
            names.add(Path(token).stem)
    return names


def prepare_run_directory(run_dir: Path, args: list[str]) -> Path:
    """Populate one run directory with immutable inputs required by DSSAT."""
    run_dir.mkdir(parents=True, exist_ok=True)
    input_dir = _input_dir_argument(args)
    if input_dir is not None and not input_dir.is_dir():
        raise FileNotFoundError(f"User input directory does not exist: {input_dir}")
    genotype = DATA_DIR / "templates" / "genotype"
    for filename in ("TMGRO048.CUL", "TMGRO048.ECO", "TMGRO048.SPE"):
        _copy(genotype / f"{filename}.base", run_dir / f"{filename}.base")
        _copy(genotype / f"{filename}.base", run_dir / filename)

    soil_source = (input_dir / "SOIL.SOL") if input_dir else (DATA_DIR / "raw" / "soil" / "SOIL.SOL")
    _copy(soil_source, run_dir / "SOIL.SOL.base")
    _copy(soil_source, run_dir / "SOIL.SOL")

    templates = DATA_DIR / "templates"
    for filename in ("DSSATPRO.v48", "DSSAT48.INH", "DSSAT48.INP"):
        _copy(templates / filename, run_dir / filename)

    exe_candidates = [
        Path(os.environ.get("DSSAT48_HOME", r"C:\DSSAT48")) / "DSCSM048.EXE",
        PROJECT_ROOT / "workspace" / "DSCSM048.EXE",
    ]
    executable = next((path for path in exe_candidates if path.is_file()), None)
    if executable is None:
        raise FileNotFoundError("DSCSM048.EXE was not found in DSSAT48_HOME or workspace")
    _copy(executable, run_dir / "DSCSM048.EXE")

    batch_file = _local_batch(args, run_dir, input_dir=input_dir)
    experiments = input_dir if input_dir else DATA_DIR / "raw" / "experiments"
    for stem in _experiment_names(batch_file):
        matches = list(experiments.glob(f"{stem}.*"))
        model_files = [path for path in matches if path.suffix.upper() in {".TMX", ".TMA", ".TMT"}]
        if not model_files:
            raise FileNotFoundError(f"Experiment referenced by batch is missing: {stem}")
        for source in model_files:
            _copy(source, run_dir / source.name)

    weather = input_dir if input_dir else DATA_DIR / "raw" / "weather"
    weather_files = list(weather.glob("*.WTH"))
    if not weather_files:
        raise FileNotFoundError(f"No weather files found in {weather}")
    for source in weather_files:
        _copy(source, run_dir / source.name)
    return batch_file


def main() -> int:
    run_dir = Path.cwd().resolve()
    args = list(sys.argv[1:])
    batch_file = prepare_run_directory(run_dir, args)

    # Always point the real runner at the localized batch file.
    localized_args: list[str] = []
    skip = False
    for index, value in enumerate(args):
        if skip:
            skip = False
            continue
        if value == "--batch" and index + 1 < len(args):
            localized_args.extend(["--batch", batch_file.name])
            skip = True
        elif value.startswith("--batch="):
            localized_args.append(f"--batch={batch_file.name}")
        elif value == "--input-dir" and index + 1 < len(args):
            skip = True
        elif value.startswith("--input-dir="):
            continue
        else:
            localized_args.append(value)
    if "--batch" not in localized_args and not any(value.startswith("--batch=") for value in localized_args):
        localized_args.extend(["--batch", batch_file.name])

    env = os.environ.copy()
    env["PEST_OUT_DIR"] = str(run_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    python_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(PROJECT_ROOT) + (os.pathsep + python_path if python_path else "")
    result = subprocess.run(
        [sys.executable, "-m", "src.dssat.run_dssat", *localized_args],
        cwd=run_dir,
        env=env,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
