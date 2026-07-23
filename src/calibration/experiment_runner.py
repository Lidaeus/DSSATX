"""Thin adapter: drive the existing multiseason builder from an ExperimentSpec.

This module bridges :class:`~src.calibration.experiment_spec.ExperimentSpec`
to the existing ``build_pest.py`` / ``build_pest_multiseason.py`` pipeline.
It does **not** re-implement PST building, DSSAT running, or PEST++ execution;
it translates the spec's declared contract into the CLI arguments and ctx
dictionary that the existing builder expects.

The adapter is intentionally minimal: it validates the spec, writes the
experiment receipt, delegates to the builder, and records the run directory.
Actual PEST++ execution is handled by the existing ``run_parallel.py`` or
``run_multiseason.py`` infrastructure.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.calibration.experiment_spec import ExperimentSpec
from src.common.project import PROJECT_ROOT, sha256_file, git_metadata


@dataclass(frozen=True)
class ExperimentRunResult:
    """Outcome of running (or building) an experiment."""

    experiment_id: str
    run_dir: Path
    receipt_path: Path
    spec: ExperimentSpec


def prepare_experiment_run(
    spec_path: str | Path,
    run_dir: str | Path,
    *,
    smoke: bool = False,
) -> ExperimentRunResult:
    """Load and validate a spec, write the receipt, and prepare the run directory.

    This is the build-only entry point.  It:

    1. Loads and fully validates the :class:`ExperimentSpec`.
    2. Creates the run directory.
    3. Writes ``experiment_receipt.json`` with all SHA-256 hashes.
    4. Returns the result for the caller to proceed with builder/PEST++.

    Parameters
    ----------
    spec_path
        Path to the experiment spec JSON.
    run_dir
        Target run directory (will be created if absent).
    smoke
        If True, override execution to 20 realisations / 1 update for
        interface smoke testing.

    Raises
    ------
    ExperimentSpecError
        If the spec fails contract validation.
    """
    spec = ExperimentSpec.load(spec_path)

    run_dir_path = Path(run_dir).expanduser().resolve()
    run_dir_path.mkdir(parents=True, exist_ok=True)

    # Override execution for smoke runs
    if smoke:
        spec = _override_execution(spec, ies_num_reals=20, noptmax=1)

    # Write the receipt
    receipt = spec.receipt()
    receipt["run_dir"] = str(run_dir_path)
    receipt["smoke_mode"] = smoke
    receipt["git"] = git_metadata()

    receipt_path = run_dir_path / "experiment_receipt.json"
    with receipt_path.open("w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2, ensure_ascii=False, sort_keys=True)

    return ExperimentRunResult(
        experiment_id=spec.experiment_id,
        run_dir=run_dir_path,
        receipt_path=receipt_path,
        spec=spec,
    )


def build_args_from_spec(
    spec: ExperimentSpec,
    run_dir: Path,
    *,
    prefix: str | None = None,
) -> SimpleNamespace:
    """Translate an ExperimentSpec into the argparse namespace that
    ``build_pest.py`` expects for the multiseason path.

    This is the explicit-argument bridge: no global state mutation, no
    implicit fallbacks.  Every value comes from the spec or the run_dir.
    """
    if spec.multiseason_design_path is None:
        raise ValueError(
            f"Experiment '{spec.experiment_id}' has no multiseason_design path. "
            f"Single-season specs must reference a diagnostic multiseason design."
        )

    pfx = prefix or spec.experiment_id

    return SimpleNamespace(
        mode="eggplant_stage2",
        prefix=pfx,
        bounds_id=spec.bounds_id,
        bounds_crop="eggplant",
        multiseason_design=str(spec.multiseason_design_path),
        out_dir=str(run_dir),
        noptmax=spec.execution.noptmax,
        ies_num_reals=spec.execution.ies_num_reals,
        seed=str(spec.execution.seed),
        # Retired flags — always off for article experiments
        weight_scheme="raw",
        apply_normalization=False,
        apply_log_transform=False,
        apply_pwtadj1=False,
        cv_based_sigma=None,
        noptmax0_sims=0,
        # Harvest contract
        batch="DSSBatch.v48",
        harvest_var="CHPDT",
        # Observation policy — from spec's observation profile
        observation_policy_csv=None,  # Let multiseason design supply it
        # Design config (staged design)
        design_config=None,
        stage=None,
        fixed_from=None,
        input_dir=None,
        # Extra params
        extra_params=None,
        bounds_review_csv=None,
        # Model command
        model_cmd_extra=f"--batch DSSBatch.v48 --harvest-var CHPDT",
    )


def _override_execution(
    spec: ExperimentSpec,
    *,
    ies_num_reals: int,
    noptmax: int,
) -> ExperimentSpec:
    """Return a copy of *spec* with overridden execution settings."""
    from dataclasses import replace
    from src.calibration.experiment_spec import ExecutionConfig

    new_exec = ExecutionConfig(
        ies_num_reals=ies_num_reals,
        noptmax=noptmax,
        seed=spec.execution.seed,
        min_retention_rate=spec.execution.min_retention_rate,
    )
    return replace(spec, execution=new_exec)
