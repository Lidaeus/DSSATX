"""Per-run isolated execution entry point for DSSAT and PEST++ model calls.

This module provides the concurrency isolation wrapper around the core DSSAT runner
(implemented in :mod:`src.dssat.run_dssat`). Each model call creates an ephemeral
execution directory under ``_iso_runs``, snapshots parameters, executes DSSAT via
subprocess in the sandboxed directory, and atomically publishes PEST interface files
back to the parent directory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

import src.dssat.run_dssat as _dssat_runner
from src.dssat.run_dssat import (
    PROJECT_ROOT,
    PARAM_CSV,
    _to_dssatpro_path,
)

# Export DATA_DIR so monkeypatching it in tests or callers works properly
DATA_DIR = _dssat_runner.DATA_DIR


def prepare_run_directory(run_dir: Path, args: list[str]) -> Path:
    """Delegate to :func:`src.dssat.run_dssat.prepare_run_directory`, keeping DATA_DIR in sync."""
    _dssat_runner.DATA_DIR = DATA_DIR
    return _dssat_runner.prepare_run_directory(run_dir, args)


_DSSAT_MODEL_CODE = "CRGRO048"

_PEST_INTERFACE_FILES = (
    "PestEval.OUT",
    "PestGrow.OUT",
    "PestJoint.OUT",
    "PestHarvest.OUT",
    "PestTmtGrow.OUT",
    "PestHarvest.audit.csv",
    "PestSoilWat.OUT",
    "PestNResponse.OUT",
    "PestWResponse.OUT",
    "PestNDoseGradient.OUT",
    "PestWNContrast.OUT",
)

# Raw DSSAT daily/summary outputs that the SA pipeline (sa_model.py) reads to
# build its response contracts; copied back for SA consumption.
_RAW_DSSAT_OUTPUT_FILES = (
    "Evaluate.OUT",
    "PlantGro.OUT",
    "FreshWt.OUT",
)


def _param_csv_name(args: list) -> str:
    """Return the basename of the parameter CSV referenced by ``--param-csv``."""
    for index, value in enumerate(args):
        if value == "--param-csv" and index + 1 < len(args):
            return os.path.basename(args[index + 1])
        if value.startswith("--param-csv="):
            return os.path.basename(value.split("=", 1)[1])
    return os.path.basename(PARAM_CSV)


def _resolve_param_source(args: list, pest_run_dir: Path) -> Path | None:
    """Resolve parameter CSV source path from arguments and pest run dir."""
    for index, value in enumerate(args):
        raw = None
        if value == "--param-csv" and index + 1 < len(args):
            raw = args[index + 1]
        elif value.startswith("--param-csv="):
            raw = value.split("=", 1)[1]
        if raw:
            p = Path(raw)
            if p.is_absolute() and p.is_file():
                return p
            p_rel = (pest_run_dir / p).resolve()
            if p_rel.is_file():
                return p_rel
            p_base = pest_run_dir / p.name
            if p_base.is_file():
                return p_base
    default_p = pest_run_dir / os.path.basename(PARAM_CSV)
    return default_p if default_p.is_file() else None


def _atomic_copy_back(source_dir: Path, dest_dir: Path, *, keep_nitrogen_outputs: bool = False) -> None:
    """Atomically publish PEST interface files from the run dir to the PEST dir.

    Writes to a per-file ``*.tmp`` and ``os.replace``s it into place so PEST
    (and any concurrent reader) never observes a half-written ``Pest*.OUT``.
    Missing files are skipped: the caller's freshness check decides validity.

    The raw DSSAT outputs (Evaluate/PlantGro/FreshWt.OUT) are also copied back
    (non-atomically - they are read only after the run completes) because the
    SA pipeline derives its response contracts from the daily trajectories
    they carry, which the summary Pest*.OUT do not contain.
    """
    for name in _PEST_INTERFACE_FILES:
        source = source_dir / name
        if not source.is_file():
            continue
        destination = dest_dir / name
        tmp = dest_dir / f"{name}.tmp"
        shutil.copy2(source, tmp)
        os.replace(tmp, destination)
    raw_outputs = list(_RAW_DSSAT_OUTPUT_FILES)
    if keep_nitrogen_outputs:
        raw_outputs.extend(["PlantN.OUT", "SoilNi.OUT", "SoilN.OUT"])
    for name in raw_outputs:
        source = source_dir / name
        if not source.is_file():
            continue
        shutil.copy2(source, dest_dir / name)


def main() -> int:
    # The PEST run directory is the current working directory; PEST reads its
    # interface files (the ``Pest*.OUT``) from here via the .ins instructions.
    pest_run_dir = Path.cwd().resolve()
    args = list(sys.argv[1:])

    # Each model call gets a unique ephemeral directory so that retries,
    # interruptions, and future in-agent concurrency can never reuse a
    # previous call's outputs or injected genotype.
    iso_root = pest_run_dir / "_iso_runs"
    iso_root.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="run_", dir=str(iso_root)))
    keep_failed = os.environ.get("DSSAT_KEEP_FAILED_RUNS", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    result = None

    try:
        batch_file = prepare_run_directory(run_dir, args)

        # Snapshot the PEST-written parameter CSV into the ephemeral dir so
        # later mutation of the agent-root copy cannot affect this call.
        csv_name = _param_csv_name(args)
        param_source = _resolve_param_source(args, pest_run_dir)
        if param_source and param_source.is_file():
            shutil.copy2(param_source, run_dir / csv_name)

        # Localize the batch reference and drop --input-dir (its inputs were
        # already copied into run_dir by prepare_run_directory).
        localized_args = []
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
            elif value == "--param-csv" and index + 1 < len(args):
                localized_args.extend(["--param-csv", csv_name])
                skip = True
            elif value.startswith("--param-csv="):
                localized_args.append(f"--param-csv={csv_name}")
            elif value == "--input-dir" and index + 1 < len(args):
                skip = True
            elif value.startswith("--input-dir="):
                continue
            else:
                localized_args.append(value)
        if "--batch" not in localized_args and not any(v.startswith("--batch=") for v in localized_args):
            localized_args.extend(["--batch", batch_file.name])
        if "--model" not in localized_args and not any(v.startswith("--model=") for v in localized_args):
            localized_args.extend(["--model", _DSSAT_MODEL_CODE])
        if (run_dir / "soil_water_observations.csv").is_file() and "--keep-soil-water" not in localized_args:
            localized_args.append("--keep-soil-water")

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
            capture_output=keep_failed,
            text=keep_failed,
        )
        if result.returncode == 0:
            keep_n = any(
                value == "--keep-nitrogen-outputs"
                or value.startswith("--keep-nitrogen-outputs=")
                for value in localized_args
            )
            _atomic_copy_back(run_dir, pest_run_dir, keep_nitrogen_outputs=keep_n)
        return result.returncode
    finally:
        if keep_failed and result is not None and result.returncode != 0:
            (run_dir / "failure_context.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "returncode": int(result.returncode),
                        "parameter_csv": _param_csv_name(args),
                        "model_command_args": args,
                        "retained_reason": "DSSAT_KEEP_FAILED_RUNS enabled",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "dssat_runner.stdout.log").write_text(
                result.stdout or "", encoding="utf-8", errors="replace"
            )
            (run_dir / "dssat_runner.stderr.log").write_text(
                result.stderr or "", encoding="utf-8", errors="replace"
            )
        else:
            keep_all = os.environ.get("DSSAT_KEEP_RUNS", "").strip().lower() in {"1", "true", "yes", "on"}
            if not keep_all:
                shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
