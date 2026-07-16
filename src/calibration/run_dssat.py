"""PEST++ model-command entry point with per-run DSSAT isolation.

Implements the three-layer isolation prescribed by
``docs/DSSAT并行隔离与输入路径规范.md`` §2.2/§5.3 for PEST++-IES calibration:
each model call runs DSSAT inside a unique ephemeral directory under the
agent's ``_iso_runs/``, using a snapshot of the PEST-written parameter CSV,
while the PEST-facing ``Pest*.OUT`` files are written atomically back to the
PEST run directory (the current working directory) where the ``.ins`` files
read them.  The ephemeral directory is removed in ``finally`` so that retries,
manual interruptions, and future in-agent concurrency can never reuse a stale
``Evaluate.OUT``/``PlantGro.OUT``/genotype from a previous call.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

# Files the real runner writes into PEST_OUT_DIR and that PEST reads via .ins.
_PEST_INTERFACE_FILES = (
    "PestEval.OUT",
    "PestGrow.OUT",
    "PestJoint.OUT",
    "PestHarvest.OUT",
    "PestTmtGrow.OUT",
)


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


def _param_csv_name(args: list[str]) -> str:
    """Return the basename of the parameter CSV referenced by ``--param-csv``."""
    for index, value in enumerate(args):
        if value == "--param-csv" and index + 1 < len(args):
            return os.path.basename(args[index + 1])
        if value.startswith("--param-csv="):
            return os.path.basename(value.split("=", 1)[1])
    return "pest_params.csv"


def _atomic_copy_back(source_dir: Path, dest_dir: Path) -> None:
    """Atomically publish PEST interface files from the run dir to the PEST dir.

    Writes to a per-file ``*.tmp`` and ``os.replace``s it into place so PEST
    (and any concurrent reader) never observes a half-written ``Pest*.OUT``.
    Missing files are skipped: the caller's freshness check decides validity.
    """
    for name in _PEST_INTERFACE_FILES:
        source = source_dir / name
        if not source.is_file():
            continue
        destination = dest_dir / name
        tmp = dest_dir / f"{name}.tmp"
        shutil.copy2(source, tmp)
        os.replace(tmp, destination)


def main() -> int:
    # The PEST run directory is the current working directory; PEST reads its
    # interface files (the ``Pest*.OUT``) from here via the .ins instructions.
    pest_run_dir = Path.cwd().resolve()
    args = list(sys.argv[1:])

    # Spec §2.2/§5.3: each model call gets a unique ephemeral directory so that
    # retries, interruptions, and future in-agent concurrency can never reuse a
    # previous call's Evaluate.OUT / PlantGro.OUT / injected genotype.
    iso_root = pest_run_dir / "_iso_runs"
    iso_root.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="run_", dir=str(iso_root)))

    try:
        batch_file = prepare_run_directory(run_dir, args)

        # Spec §2.2 step 2: snapshot the PEST-written parameter CSV into the
        # ephemeral dir so later mutation of the agent-root copy cannot affect
        # this call, and the real runner finds it in its own working directory.
        csv_name = _param_csv_name(args)
        param_source = pest_run_dir / csv_name
        if param_source.is_file():
            shutil.copy2(param_source, run_dir / csv_name)

        # Localize the batch reference and drop --input-dir (its inputs were
        # already copied into run_dir by prepare_run_directory).
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
        # All outputs stay inside the ephemeral run_dir; only the PEST interface
        # files are published back to pest_run_dir after a successful run.
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
        # Spec §5.6: only on success, atomically write the PEST interface files
        # back to the directory PEST reads from.  On failure the Pest*.OUT are
        # left untouched (PEST treats a missing/stale run as failed via its own
        # max_run_fail logic rather than receiving recycled outputs).
        if result.returncode == 0:
            _atomic_copy_back(run_dir, pest_run_dir)
        return result.returncode
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
