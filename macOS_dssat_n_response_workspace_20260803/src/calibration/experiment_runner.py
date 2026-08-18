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
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.calibration.experiment_spec import ExperimentSpec
from src.common.project import PROJECT_ROOT, sha256_file, git_metadata


# IES numerical-stability profile (mirrors the proven T10 dry-only runner).
# Without these options, 25SP members crash at a high rate (DSSAT numerical
# instability in certain parameter combinations).  ies_use_approx=False forces
# the exact (non-approximate) objective; the multi-lambda search and bound
# enforcement prevent the ensemble from drifting into unstable regions.
IES_STABILITY_PROFILE = {
    "ies_use_approx": False,
    "ies_lambda_mults": "0.5,1.0,10.0",
    "lambda_scale_fac": "0.9,1.0",
    "ies_enforce_bounds": True,
}

# Enhanced IES profile with covariance reinflation to prevent ensemble collapse
# in early iterations. Recommended for high-dimensional parameter spaces.
# See PEST++ manual section 9.1.15 for reinflation details.
IES_REINFLATION_PROFILE = {
    "ies_use_approx": False,
    "ies_lambda_mults": "0.5,1.0,10.0",
    "lambda_scale_fac": "0.9,1.0",
    "ies_enforce_bounds": True,
    # Reinflation after iteration 1 and 2 (early collapse prevention)
    "ies_reinflate": 1,
    # Dampen reinflation to 80% of prior variance to avoid over-dispersion
    "ies_reinflate_factor": 0.8,
}


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
    ies_num_reals: int | None = None,
    noptmax: int | None = None,
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

    # Explicit run-size overrides are used for short, auditable pre-calibration
    # trials.  They never alter the source spec on disk.
    if smoke:
        spec = _override_execution(spec, ies_num_reals=20, noptmax=1)
    elif ies_num_reals is not None or noptmax is not None:
        spec = _override_execution(
            spec,
            ies_num_reals=ies_num_reals or spec.execution.ies_num_reals,
            noptmax=noptmax if noptmax is not None else spec.execution.noptmax,
        )

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


def run_build(
    spec: ExperimentSpec,
    run_dir: Path,
    *,
    prefix: str | None = None,
    check: bool = True,
) -> Path:
    """Invoke the existing ``build_pest.py`` to generate the PST for this spec.

    This is the real bridge from spec -> PST.  It shells out to the existing,
    audited multiseason builder with explicit, spec-derived arguments (no global
    state, no implicit fallback).  The invocation mirrors the proven T10
    dry-only runner contract: ``--mode eggplant_stage2 --multiseason-design
    <spec.design> --observation-policy-csv <profile> --harvest-var CHPDT``.

    Returns the path to the run directory (which now contains ``<prefix>.pst``).
    Raises :class:`subprocess.CalledProcessError` if the builder fails and
    ``check=True``.
    """
    if spec.multiseason_design_path is None:
        raise ValueError(
            f"Experiment '{spec.experiment_id}' has no multiseason_design; "
            f"run_build requires a multiseason design."
        )
    pfx = prefix or spec.experiment_id
    # The observation policy CSV is read from the spec's observation profile
    # directory convention: the multiseason design JSON points at it, but the
    # article contract requires it be passed explicitly on the CLI too.
    obs_policy = _resolve_observation_policy_csv(spec)
    batch_parent = _resolve_batch_parent(spec)

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "src" / "calibration" / "build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(spec.multiseason_design_path),
        "--input-dir", str(batch_parent),
        "--bounds-id", spec.bounds_id,
        "--bounds-crop", "eggplant",
        "--prefix", pfx,
        "--noptmax", str(spec.execution.noptmax),
        "--ies-num-reals", str(spec.execution.ies_num_reals),
        "--random-seed", str(spec.execution.seed),
        "--bad-phi-sigma", "1e300",
        "--batch", str(batch_parent / "DSSBatch.v48"),
        "--harvest-var", "CHPDT",
        "--include-n-uptake",
        "--out-dir", str(run_dir),
        "--param-review-mode", "off",
        "--observation-policy-csv", str(obs_policy),
    ]
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=check)
    # Apply the IES stability profile to the generated PST (same mitigation as
    # the T10 dry-only runner).  This must happen after build_pest writes the
    # PST and before run_execute launches PEST++.
    _apply_stability_profile(run_dir, pfx)
    return run_dir


def _apply_stability_profile(run_dir: Path, case: str) -> None:
    """Write the IES stability options into the PST (in place).

    Mirrors ``run_t10_dryonly._apply_stability_profile``: loads the PST, updates
    ``pestpp_options`` with :data:`IES_STABILITY_PROFILE`, and rewrites it.
    """
    import pyemu

    pst_path = run_dir / f"{case}.pst"
    if not pst_path.is_file():
        return
    pst = pyemu.Pst(str(pst_path))
    pst.pestpp_options.update(IES_STABILITY_PROFILE)
    pst.write(str(pst_path))


def run_execute(
    spec: ExperimentSpec,
    run_dir: Path,
    *,
    prefix: str | None = None,
    n_agents: int = 0,
    wait: bool = True,
    check: bool = True,
) -> int:
    """Launch PEST++ (IES) execution for a built experiment.

    Shells out to ``tools/parallel/run_parallel.py`` with the prepared run
    directory.  P0-C unlocked this path by eliminating the cross-season
    ``USER_INPUT_DIR`` global mutation that previously made the multiseason
    builder non-reentrant.

    Returns the subprocess exit code (0 = success).
    """
    pfx = prefix or spec.experiment_id
    pst_path = run_dir / f"{pfx}.pst"
    if not pst_path.is_file():
        raise FileNotFoundError(
            f"PST not found: {pst_path}.  Run with --build-only first."
        )

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "parallel" / "run_parallel.py"),
        "--run-dir", str(run_dir),
        "--case", pfx,
        "--mode", "ies",
        "--n-agents", str(n_agents),
    ]
    if wait:
        cmd.append("--wait")
    else:
        cmd.append("--no-wait")
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=check)
    return result.returncode


def _resolve_observation_policy_csv(spec: ExperimentSpec) -> Path:
    """Resolve the observation-policy CSV the builder must consume.

    The policy CSV is sourced from the spec's multiseason design JSON
    (``observation_policy`` field).  This is the authoritative path: each
    design pins the exact sigma/transform/phi_role table the builder must
    consume, so E01-P / E01-O / E01-Y-strict sub-trials can activate
    different observation domains without modifying the builder.

    Falls back to the dry-only sigma CSV only when the design omits the
    field (backward compatibility for legacy designs).
    """
    # Read the observation_policy path from the multiseason design JSON.
    if spec.multiseason_design_path is not None:
        try:
            with spec.multiseason_design_path.open("r", encoding="utf-8") as fh:
                design_raw = json.load(fh)
            policy_ref = str(design_raw.get("observation_policy", "")).strip()
            if policy_ref:
                candidate = Path(policy_ref)
                if not candidate.is_absolute():
                    candidate = PROJECT_ROOT / candidate
                candidate = candidate.resolve()
                if candidate.is_file():
                    return candidate
                raise FileNotFoundError(
                    f"multiseason design '{spec.multiseason_design_path.name}' "
                    f"observation_policy path does not exist: {candidate}"
                )
        except (OSError, json.JSONDecodeError) as exc:
            raise FileNotFoundError(
                f"Failed to read multiseason design '{spec.multiseason_design_path}': {exc}"
            ) from exc

    # Backward-compatible fallback: the article dry-only sigma CSV.
    candidate = PROJECT_ROOT / "configs" / "runs" / "assumption_based_sigma_v5_dryonly.csv"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(
        f"observation policy CSV not found for profile "
        f"'{spec.observation_profile.profile_id}': expected {candidate}"
    )


def _resolve_batch_parent(spec: ExperimentSpec) -> Path:
    """Resolve the input-dir (batch parent) for the first calibration season.

    The multiseason builder takes one ``--input-dir`` (the first season's
    bundle); the scheduler copies per-season bundles from the design JSON.
    """
    for season in spec.season_inputs:
        if season.role in ("calibration", "development_calibration", "diagnostic"):
            return season.input_manifest_path.parent
    # fall back to the first season of any role
    return spec.season_inputs[0].input_manifest_path.parent


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
