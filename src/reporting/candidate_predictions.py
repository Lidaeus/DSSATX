"""Candidate-solution prediction comparison for a finalized staged calibration.

Given a frozen posterior contract (candidate pairs over the S4 final ensemble),
this entry point exports each candidate realization's parameters, runs one
isolated deterministic DSSAT rerun per unique realization, builds a canonical
comparison table for each, and computes a frozen prediction distance between
the two realizations of every candidate pair. Outputs are bound by SHA-256
manifests and, under a ``tooling_demo`` upstream, can only be labelled as demo
predictions — never as functional equifinality or science validation.

The module is deliberately small and contract-driven: it reuses
``validation_metrics.build_comparison_from_rerun`` so the representative and
candidate comparisons share one parsing/alignment definition, and it never
re-runs IES/Morris/Sobol or modifies calibration artifacts.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.calibration.design_config import load_design_config
from src.calibration.finalize_calibration import verify_calibration_artifact_manifest
from src.calibration.observation_policy import load_observation_policy
from src.common.input_manifest import (
    USE_VALIDATION_AGAINST_OBSERVED_IC,
    assert_use_allowed,
    verify_manifest_integrity,
)
from src.common.project import git_metadata, sha256_file
from src.common.quality import read_flat_run_manifest_field
from src.reporting.analyze_results import _infer_excode_from_filex, _parse_batch_entries
from src.reporting.validation_metrics import build_comparison_from_rerun

# Frozen variable -> observation-policy group mapping (T4.2 handoff §7.2).
# Prediction distance uses these groups' raw-scale sigma; it does NOT apply
# group_multiplier (distance measures prediction differences, not Phi).
_VARIABLE_TO_POLICY_GROUP: dict[str, str] = {
    "ADAP": "ADAPM",
    "LAIX": "LAIXM",
    "CNAM": "CNAMM",
    "LAID": "LAIDM",
    "LWAD": "LWADM",
    "SWAD": "SWADM",
    "DRY_INC": "PWAIM",
    "DRY_CUM": "PWADM",
}

# Roles consumed by prediction distance (T4.2 handoff §6): validation and
# diagnostic treatments only — calibration rows never enter the distance.
_DISTANCE_ROLES: tuple[str, ...] = ("validation", "diagnostic")

# Pre-declared classification threshold in sigma_eff units (§7.4).
_DISTANCE_THRESHOLD = 1.0

# Scientific keys for one-to-one A/B row alignment (§7.1).
_ALIGNMENT_KEYS: tuple[str, ...] = (
    "dataset_role", "variable", "treatment", "date_code", "harvest_number",
)


# ---------------------------------------------------------------------------
# Manifest / upstream verification
# ---------------------------------------------------------------------------

def _manifest_field(path: Path, key: str) -> str:
    return read_flat_run_manifest_field(path, key) or ""


def _require_hash(path: Path, expected: str, label: str) -> None:
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"{label} hash mismatch for {path}: expected {expected}, got {actual}")


def _verify_posterior_manifest(posterior_manifest_path: Path, case: str) -> dict[str, Any]:
    if not posterior_manifest_path.is_file():
        raise FileNotFoundError(f"posterior manifest not found: {posterior_manifest_path}")
    payload = json.loads(posterior_manifest_path.read_text(encoding="utf-8"))
    if str(payload.get("run_id") or "") != case:
        raise ValueError(
            f"posterior manifest run_id {payload.get('run_id')!r} does not match case {case!r}"
        )
    status = str(payload.get("candidate_pair_status") or "")
    if status == "prediction_distance_complete":
        raise ValueError(
            "posterior manifest already reports prediction_distance_complete; "
            "refusing to overwrite a frozen prediction result"
        )
    if status and status != "prediction_distance_pending":
        raise ValueError(f"unexpected posterior candidate_pair_status: {status!r}")
    # Verify every artifact the posterior manifest binds.
    base = posterior_manifest_path.parent
    for entry in payload.get("artifacts", []):
        rel = str(entry.get("path") or "").strip().replace("\\", "/")
        expected = str(entry.get("sha256") or "").strip().lower()
        if not rel or len(expected) != 64:
            raise ValueError(f"invalid posterior manifest artifact entry: {entry!r}")
        _require_hash(base / rel, expected, f"posterior artifact {rel}")
    return payload


def _load_frozen_context(run_dir: Path, case: str) -> dict[str, Any]:
    """Load and hash-verify the S4 frozen inputs shared by all candidates."""
    verify_calibration_artifact_manifest(
        run_dir, case,
        required_rerun_outputs={"Evaluate.OUT", "PlantGro.OUT", "FreshWt.OUT"},
    )
    run_manifest = run_dir / "run_manifest.yaml"
    finalize_path = run_dir / "calibration_finalize" / "calibration_finalize.json"
    finalize = json.loads(finalize_path.read_text(encoding="utf-8"))
    if finalize.get("engineering_status") != "engineering_validated":
        raise ValueError("candidate predictions require an engineering_validated calibration finalize")
    science_validated = (
        finalize.get("science_status") == "science_validated"
        and finalize.get("scientific_status") == "validated"
    )
    input_dir = Path(_manifest_field(run_manifest, "input_dir")).resolve()
    input_manifest = verify_manifest_integrity(input_dir)
    assert_use_allowed(input_manifest, use=USE_VALIDATION_AGAINST_OBSERVED_IC)
    _require_hash(
        input_dir / "input_manifest.json",
        _manifest_field(run_manifest, "input_manifest_sha256"),
        "input manifest",
    )
    design_path = Path(_manifest_field(run_manifest, "design_config")).resolve()
    _require_hash(
        design_path,
        _manifest_field(run_manifest, "design_config_sha256"),
        "design config",
    )
    stage = _manifest_field(run_manifest, "design_stage")
    design = load_design_config(design_path, stage)
    split_path = Path(design.observation["split_path"]).resolve()
    _require_hash(
        split_path,
        _manifest_field(run_manifest, "validation_split_sha256"),
        "validation split",
    )
    batch_path = run_dir / "DSSBatch.v48"
    _require_hash(batch_path, _manifest_field(run_manifest, "batch_sha256"), "batch file")
    entries = _parse_batch_entries(str(batch_path))
    if not entries:
        raise ValueError(f"no batch entries found in {batch_path}")
    excode = _infer_excode_from_filex(str(input_dir / entries[0]["filex"]))
    tmt_path = input_dir / f"{excode}.TMT"
    if not tmt_path.is_file():
        raise FileNotFoundError(f"frozen observed TMT file not found: {tmt_path}")
    # Frozen observation policy + harvest var are bound by the S4 run_manifest.
    # Downstream tools must use these exact bytes, not an arbitrary CLI path,
    # so that another sigma file cannot silently regenerate a well-formed
    # prediction-distance manifest.
    frozen_policy_csv = _manifest_field(run_manifest, "observation_policy_csv")
    frozen_policy_sha = _manifest_field(run_manifest, "observation_policy_sha256")
    if not frozen_policy_csv or not frozen_policy_sha:
        raise ValueError(
            "S4 run_manifest must record observation_policy_csv and "
            "observation_policy_sha256 for candidate predictions"
        )
    frozen_policy_path = Path(frozen_policy_csv).resolve()
    if not frozen_policy_path.is_file():
        raise FileNotFoundError(f"frozen observation policy not found: {frozen_policy_path}")
    _require_hash(frozen_policy_path, frozen_policy_sha, "frozen observation policy")
    frozen_harvest_var = _manifest_field(run_manifest, "harvest_var")
    if not frozen_harvest_var:
        raise ValueError("S4 run_manifest must record harvest_var for candidate predictions")
    return {
        "run_manifest": run_manifest,
        "finalize": finalize,
        "finalize_path": finalize_path,
        "finalize_sha256": sha256_file(finalize_path),
        "artifact_manifest_sha256": sha256_file(
            run_dir / "calibration_finalize" / "calibration_artifacts_manifest.json"
        ),
        "science_validated": science_validated,
        "input_dir": input_dir,
        "input_manifest": input_manifest,
        "design": design,
        "split_path": split_path,
        "batch_path": batch_path,
        "entries": entries,
        "tmt_path": tmt_path,
        "frozen_policy_path": frozen_policy_path,
        "frozen_policy_sha256": frozen_policy_sha,
        "frozen_harvest_var": frozen_harvest_var,
    }


# ---------------------------------------------------------------------------
# Candidate realization extraction and parameter export
# ---------------------------------------------------------------------------

def _final_ensemble_path(run_dir: Path, case: str) -> Path:
    """Locate the final parameter ensemble from the artifact manifest role.

    Reads the role rather than guessing the iteration number from a filename,
    so the contract holds even if a future finalize writes a different suffix.
    """
    manifest_path = run_dir / "calibration_finalize" / "calibration_artifacts_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in payload.get("artifacts", []):
        if entry.get("role") == "final_parameter_ensemble":
            return (run_dir / str(entry["path"]).replace("\\", "/")).resolve()
    raise ValueError("calibration artifact manifest has no final_parameter_ensemble entry")


def _strict_nonneg_int(value: Any, *, context: str) -> int:
    """Parse a realization/pair id as a non-negative integer, rejecting floats
    like 4.5 (which int(float(...)) would silently truncate), negatives, and
    non-finite values."""
    if isinstance(value, bool):
        raise ValueError(f"{context} must be an integer, got bool {value!r}")
    if isinstance(value, int):
        n = value
    elif isinstance(value, float):
        if not math.isfinite(value) or value < 0 or value != int(value):
            raise ValueError(f"{context} must be a non-negative integer, got {value!r}")
        n = int(value)
    else:
        text = str(value).strip()
        try:
            f = float(text)
        except (TypeError, ValueError):
            raise ValueError(f"{context} must be an integer, got {value!r}")
        if not math.isfinite(f) or f < 0 or f != int(f):
            raise ValueError(f"{context} must be a non-negative integer, got {value!r}")
        n = int(f)
    if n < 0:
        raise ValueError(f"{context} must be non-negative, got {n}")
    return n


def _validate_candidate_pairs_schema(pairs_df: pd.DataFrame) -> pd.DataFrame:
    """Strict T4.2 candidate-pair schema gate.

    Enforces: 1-3 pairs, each with a unique pair_id, real_a != real_b, both
    non-negative integers, and at most 6 unique realizations total. This is a
    consumer-side guard so a hash-self-consistent but oversized pairs CSV
    cannot trigger more than the approved <=6 DSSAT reruns.
    """
    for col in ("pair_id", "real_a", "real_b"):
        if col not in pairs_df.columns:
            raise ValueError(f"candidate_pairs.csv missing required column {col!r}")
    n_pairs = len(pairs_df)
    if n_pairs < 1 or n_pairs > 3:
        raise ValueError(f"candidate_pairs.csv must have 1-3 pairs, got {n_pairs}")

    pair_ids: list[int] = []
    uniq: list[int] = []
    for idx, row in pairs_df.iterrows():
        pid = _strict_nonneg_int(row["pair_id"], context=f"row {idx} pair_id")
        if pid in pair_ids:
            raise ValueError(f"duplicate pair_id {pid} in candidate_pairs.csv")
        pair_ids.append(pid)
        ra = _strict_nonneg_int(row["real_a"], context=f"pair {pid} real_a")
        rb = _strict_nonneg_int(row["real_b"], context=f"pair {pid} real_b")
        if ra == rb:
            raise ValueError(f"pair {pid} has real_a == real_b ({ra}); self-pairing is not allowed")
        for rid in (ra, rb):
            if rid not in uniq:
                uniq.append(rid)
    if len(uniq) > 6:
        raise ValueError(
            f"candidate_pairs.csv yields {len(uniq)} unique realizations; "
            "T4.2 allows at most 6"
        )
    # Return a normalized copy with int dtypes so downstream code is type-stable.
    out = pairs_df.copy()
    out["pair_id"] = pair_ids
    return out


def _unique_realizations(pairs_df: pd.DataFrame) -> list[int]:
    seen: list[int] = []
    for col in ("real_a", "real_b"):
        for value in pairs_df[col].tolist():
            rid = _strict_nonneg_int(value, context=f"column {col!r}")
            if rid not in seen:
                seen.append(rid)
    return seen


def _export_candidate_params(
    ensemble_df: pd.DataFrame,
    realization: int,
    out_path: Path,
) -> str:
    """Write ``name,value`` rows for one realization; return its SHA-256.

    Exports every parameter column present in the ensemble (including S4-fixed
    XFRT/XFINT). The representative median must never be substituted in.
    """
    real_col = next((c for c in ensemble_df.columns if str(c).lower() in {"real_name", "realization"}), None)
    if real_col is None:
        raise ValueError("final parameter ensemble lacks a real_name/realization column")

    def _row_realization(value: Any) -> int | None:
        # Lenient match for ensemble row lookup (real_name may be "0"/0/0.0).
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(f) or f != int(f):
            return None
        return int(f)

    mask = ensemble_df[real_col].apply(_row_realization) == realization
    if not mask.any():
        raise ValueError(f"candidate realization {realization} is absent from the final ensemble")
    if mask.sum() > 1:
        raise ValueError(f"candidate realization {realization} appears {int(mask.sum())} times in the ensemble")
    row = ensemble_df.loc[mask].iloc[0]
    param_cols = [c for c in ensemble_df.columns if c != real_col]
    seen_upper: set[str] = set()
    out_rows: list[dict[str, Any]] = []
    for col in param_cols:
        name = str(col).strip()
        key = name.upper()
        if key in seen_upper:
            raise ValueError(f"duplicate parameter (case-insensitive) in ensemble: {name}")
        seen_upper.add(key)
        try:
            value = float(row[col])
        except (TypeError, ValueError):
            raise ValueError(f"candidate realization {realization} parameter {name!r} is non-numeric: {row[col]!r}")
        if not math.isfinite(value):
            raise ValueError(f"candidate realization {realization} parameter {name!r} is non-finite: {value}")
        out_rows.append({"name": name, "value": value})
    if not out_rows:
        raise ValueError("final parameter ensemble has no parameter columns")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out_rows).to_csv(out_path, index=False, encoding="utf-8")
    return sha256_file(out_path)


# ---------------------------------------------------------------------------
# Deterministic DSSAT rerun (isolated; one per unique realization)
# ---------------------------------------------------------------------------

REQUIRED_RERUN_OUTPUTS: tuple[str, ...] = (
    "Evaluate.OUT", "PlantGro.OUT", "FreshWt.OUT",
    "PestEval.OUT", "PestTmtGrow.OUT", "PestHarvest.OUT", "PestJoint.OUT", "PestGrow.OUT",
)


def _build_runner_argv(
    *,
    param_csv: Path,
    batch_name: str,
    harvest_var: str,
    input_dir: Path,
) -> list[str]:
    """Reproducible argv for the isolated DSSAT rerun (no cwd-relative tokens).

    Mirrors the S4 model command: no --cultivar (the cultivar is fixed by the
    frozen FileX/DSSBatch, and run_dssat.py infers the rest). Paths are
    absolute so the recorded command reproduces from any cwd.
    """
    return [
        "--param-csv", str(param_csv.resolve()),
        "--batch", batch_name,
        "--harvest-var", harvest_var,
        "--input-dir", str(input_dir.resolve()),
    ]


def _run_candidate_dssat(
    realization: int,
    param_csv: Path,
    run_dir_for_candidate: Path,
    *,
    input_dir: Path,
    batch_path: Path,
    harvest_var: str,
    runner: Callable[..., int] | None,
) -> dict[str, Any]:
    """Run one isolated deterministic DSSAT rerun for a candidate realization.

    The candidate directory must be freshly created and empty: a non-zero
    returncode that leaves pre-existing OUT files must never be mistaken for a
    successful run. ``runner`` is injectable so tests substitute a synthetic
    OUT writer without spawning DSSAT.
    """
    if run_dir_for_candidate.exists():
        leftover = [p for p in run_dir_for_candidate.iterdir()]
        if leftover:
            raise ValueError(
                f"candidate run dir {run_dir_for_candidate} is not empty "
                f"({len(leftover)} entries); refuse to reuse stale outputs"
            )
    run_dir_for_candidate.mkdir(parents=True, exist_ok=True)
    # Copy the batch file into the isolated candidate dir so DSSAT runs there.
    batch_dst = run_dir_for_candidate / batch_path.name
    if batch_path.resolve() != batch_dst.resolve():
        batch_dst.write_bytes(batch_path.read_bytes())
    argv = _build_runner_argv(
        param_csv=param_csv, batch_name=batch_path.name,
        harvest_var=harvest_var, input_dir=input_dir,
    )
    started_at = datetime.now(timezone.utc)
    if runner is None:
        runner = _default_dssat_runner
    returncode: int
    diagnostics: str = ""
    try:
        returncode = int(runner(
            param_csv=param_csv,
            work_dir=run_dir_for_candidate,
            input_dir=input_dir,
            batch_name=batch_path.name,
            harvest_var=harvest_var,
        ))
    except Exception as exc:  # noqa: BLE001 — preserve diagnostics, mark incomplete
        returncode = 1
        diagnostics = f"{type(exc).__name__}: {exc}"
    ended_at = datetime.now(timezone.utc)
    out_hashes: dict[str, str] = {}
    missing: list[str] = []
    for name in REQUIRED_RERUN_OUTPUTS:
        p = run_dir_for_candidate / name
        if p.is_file():
            out_hashes[name] = sha256_file(p)
        else:
            missing.append(name)
    return {
        "realization": realization,
        "returncode": int(returncode),
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ended_at": ended_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "missing_outputs": missing,
        "output_hashes": out_hashes,
        "argv": argv,
        "diagnostics": diagnostics,
    }


def _default_dssat_runner(
    *,
    param_csv: Path,
    work_dir: Path,
    input_dir: Path,
    batch_name: str,
    harvest_var: str,
) -> int:
    """Production DSSAT runner via the calibration isolation layer.

    Calls ``src/calibration/run_dssat.py`` by absolute script path (the same
    pattern ``sa_model.py`` uses) rather than ``-m src.calibration.run_dssat``,
    because the subprocess runs with ``cwd=work_dir`` (an isolated candidate
    directory) where the ``src`` package is not importable. ``run_dssat.py``
    locates PROJECT_ROOT from ``__file__`` and imports no ``src.*`` modules, so
    a direct script invocation works from any cwd. No --cultivar flag: the
    cultivar is fixed by the frozen FileX/DSSBatch, matching the S4 model
    command. On non-zero exit the runner returns that code (does NOT raise) so
    the caller can record the failure and mark the pair prediction_incomplete
    rather than aborting the whole bundle; stderr is parked beside the outputs.
    """
    runner_path = Path(__file__).resolve().parents[1] / "calibration" / "run_dssat.py"
    if not runner_path.is_file():
        raise FileNotFoundError(f"DSSAT calibration entry point not found: {runner_path}")
    cmd = [
        sys.executable, str(runner_path),
        "--param-csv", str(param_csv.resolve()),
        "--batch", batch_name,
        "--harvest-var", harvest_var,
        "--input-dir", str(input_dir.resolve()),
    ]
    result = subprocess.run(cmd, cwd=str(work_dir), capture_output=True, text=True)
    if result.returncode != 0:
        # Preserve diagnostics in the run dir; the caller records this run as
        # incomplete and never builds a comparison from these outputs.
        (work_dir / "_runner_stderr.txt").write_text(
            result.stderr[-4000:] or "(empty stderr)", encoding="utf-8"
        )
    return int(result.returncode)


# ---------------------------------------------------------------------------
# Prediction distance (frozen definition, §7)
# ---------------------------------------------------------------------------

def _sigma_eff_map(policy_path: Path) -> dict[str, float]:
    """``{variable: sigma_eff}`` for every variable in the frozen mapping.

    sigma_eff = sqrt(sigma^2 + model_sigma^2 + sigma_floor^2) on the raw scale.
    group_multiplier is intentionally NOT applied (distance, not Phi).
    """
    policies = load_observation_policy(policy_path)
    out: dict[str, float] = {}
    for variable, group in _VARIABLE_TO_POLICY_GROUP.items():
        entry = policies.get(group)
        if entry is None:
            raise ValueError(f"observation policy {policy_path.name} lacks group {group!r} for variable {variable!r}")
        transform = str(entry.get("transform") or "").strip().lower()
        if transform != "raw":
            raise ValueError(
                f"prediction distance requires raw transform for {group!r}, got {transform!r}"
            )
        try:
            sigma = float(entry["sigma"])
            model_sigma = float(entry["model_sigma"])
            sigma_floor = float(entry["sigma_floor"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"observation policy {group!r} is missing finite sigma/model_sigma/sigma_floor")
        # Shared observation-policy semantics: the base sigma must be strictly
        # positive; model_sigma and sigma_floor are additive components that may
        # legitimately be zero. The combined sigma_eff must end up finite and
        # positive so the distance normalization is well-defined.
        for name, value, allow_zero in (
            ("sigma", sigma, False),
            ("model_sigma", model_sigma, True),
            ("sigma_floor", sigma_floor, True),
        ):
            if not math.isfinite(value) or value < 0.0 or (value == 0.0 and not allow_zero):
                raise ValueError(
                    f"observation policy {group!r} has invalid {name}={value} "
                    f"(must be finite, >= 0{'' if allow_zero else ', > 0'})"
                )
        sigma_eff = math.sqrt(sigma * sigma + model_sigma * model_sigma + sigma_floor * sigma_floor)
        if not math.isfinite(sigma_eff) or sigma_eff <= 0.0:
            raise ValueError(f"observation policy {group!r} yields non-positive/non-finite sigma_eff")
        out[variable] = sigma_eff
    return out


def _align_pair(comparison_a: pd.DataFrame, comparison_b: pd.DataFrame) -> pd.DataFrame:
    """One-to-one merge of two candidate comparisons on the scientific keys.

    Any missing/extra/duplicate key combination, or a mismatched variable set,
    is a hard failure (§7.1). Returns a frame with aligned sim_a/sim_b per row.
    """
    for label, frame in (("A", comparison_a), ("B", comparison_b)):
        for col in ("dataset_role", "variable", "treatment", "simulated"):
            if col not in frame.columns:
                raise ValueError(f"comparison {label} lacks required column {col!r}")

    def _key_frame(frame: pd.DataFrame) -> pd.DataFrame:
        df = frame.copy()
        for col in ("date_code", "harvest_number"):
            if col not in df.columns:
                df[col] = -1.0
        df["_key"] = (
            df["dataset_role"].astype(str) + "|"
            + df["variable"].astype(str) + "|"
            + df["treatment"].astype(str) + "|"
            + df["date_code"].astype(str) + "|"
            + df["harvest_number"].astype(str)
        )
        return df

    ka = _key_frame(comparison_a)
    kb = _key_frame(comparison_b)
    if ka["_key"].duplicated().any():
        raise ValueError("comparison A has duplicate alignment keys")
    if kb["_key"].duplicated().any():
        raise ValueError("comparison B has duplicate alignment keys")
    keys_a = set(ka["_key"])
    keys_b = set(kb["_key"])
    if keys_a != keys_b:
        only_a = keys_a - keys_b
        only_b = keys_b - keys_a
        raise ValueError(
            f"comparison A/B rows do not align one-to-one: only_in_A={sorted(only_a)[:3]} "
            f"only_in_B={sorted(only_b)[:3]}"
        )
    merged = ka[["dataset_role", "variable", "treatment", "date_code", "harvest_number", "simulated"]].merge(
        kb[["dataset_role", "variable", "treatment", "date_code", "harvest_number", "simulated"]],
        on=["dataset_role", "variable", "treatment", "date_code", "harvest_number"],
        suffixes=("_a", "_b"),
        validate="one_to_one",
    )
    return merged


def _distance_components(aligned: pd.DataFrame, sigma_eff_map: dict[str, float]) -> pd.DataFrame:
    """Per (role, variable) RMS normalized difference. Calibration rows excluded."""
    rows = aligned[aligned["dataset_role"].isin(_DISTANCE_ROLES)].copy()
    if rows.empty:
        raise ValueError("no validation/diagnostic rows available for prediction distance")
    out_records: list[dict[str, Any]] = []
    for (role, variable), group in rows.groupby(["dataset_role", "variable"], sort=True):
        if variable not in sigma_eff_map:
            raise ValueError(f"variable {variable!r} (role {role!r}) has no sigma_eff mapping")
        sigma_eff = sigma_eff_map[variable]
        diff = (group["simulated_a"] - group["simulated_b"]).to_numpy(dtype=float)
        normalized = diff / sigma_eff
        rms = float(math.sqrt(float((normalized ** 2).mean())))
        out_records.append({
            "dataset_role": role,
            "variable": variable,
            "n_rows": int(len(group)),
            "sigma_eff": sigma_eff,
            "rms_normalized": rms,
        })
    return pd.DataFrame(out_records)


def _aggregate_distance(components: pd.DataFrame) -> tuple[float | None, float | None, float | None]:
    """Return (d_validation, d_diagnostic, prediction_distance) per §7.3.

    Equal weight per variable within each role, then equal weight across the
    two roles. None if a role has no variables.
    """
    d_val: float | None = None
    d_diag: float | None = None
    for role in ("validation", "diagnostic"):
        sub = components[components["dataset_role"] == role]
        if sub.empty:
            continue
        value = float(sub["rms_normalized"].mean())
        if role == "validation":
            d_val = value
        else:
            d_diag = value
    if d_val is not None and d_diag is not None:
        prediction_distance = float((d_val + d_diag) / 2.0)
    else:
        prediction_distance = d_val if d_val is not None else d_diag
    return d_val, d_diag, prediction_distance


def _classify(d_val: float | None, d_diag: float | None, *, demo: bool) -> str:
    if d_val is None or d_diag is None:
        return "prediction_incomplete"
    max_d = max(d_val, d_diag)
    prefix = "demo_" if demo else ""
    if max_d <= _DISTANCE_THRESHOLD:
        return f"{prefix}prediction_similar"
    return f"{prefix}prediction_divergent"


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def build_candidate_prediction_bundle(
    run_dir: str | Path,
    case: str,
    posterior_manifest: str | Path,
    out_dir: str | Path,
    *,
    observation_policy_csv: str | Path | None = None,
    allow_unvalidated_demo: bool = False,
    harvest_var: str | None = None,
    dssat_runner: Callable[..., int] | None = None,
) -> Path:
    """Build the candidate-prediction bundle for a frozen posterior contract.

    Returns the path to the written ``candidate_prediction_manifest.json``.

    ``observation_policy_csv`` and ``harvest_var`` default to the values frozen
    in the S4 run_manifest. If supplied explicitly they must hash/equal the
    frozen values, so a different sigma file or harvest variable cannot
    silently regenerate a well-formed manifest.
    """
    run_dir = Path(run_dir).resolve()
    out_dir = Path(out_dir).resolve()
    posterior_manifest_path = Path(posterior_manifest).resolve()

    # Refuse to reuse a non-empty output directory: a candidate run must not
    # inherit stale OUT files from a previous attempt. No --force escape hatch.
    if out_dir.exists():
        existing = [p for p in out_dir.iterdir() if p.name != ".gitkeep"]
        if existing:
            raise ValueError(
                f"out_dir {out_dir} is not empty ({len(existing)} entries); "
                "candidate predictions require a fresh directory to avoid reusing "
                "stale DSSAT outputs. Remove or rename the existing directory."
            )
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

    ctx = _load_frozen_context(run_dir, case)
    posterior = _verify_posterior_manifest(posterior_manifest_path, case)

    science_validated = bool(ctx["science_validated"])
    if not science_validated and not allow_unvalidated_demo:
        raise ValueError(
            "calibration is not science_validated; pass --allow-unvalidated-demo "
            "only for tooling/interface QA. Zero DSSAT runs were attempted."
        )
    data_status = "science_validated" if science_validated else "tooling_demo"
    demo = data_status == "tooling_demo"

    # Cross-check the posterior's recorded upstream hashes against the current
    # S4 finalize/artifact manifest. A posterior from a different S4 run must
    # not feed candidates into this one.
    posterior_upstream = posterior.get("upstream") or {}
    for key, actual in (
        ("calibration_finalize_sha256", ctx["finalize_sha256"]),
        ("calibration_artifacts_manifest_sha256", ctx["artifact_manifest_sha256"]),
    ):
        expected = str(posterior_upstream.get(key) or "").strip().lower()
        if expected and expected != actual:
            raise ValueError(
                f"posterior upstream {key} {expected!r} does not match current S4 "
                f"value {actual!r}; the posterior belongs to a different calibration"
            )

    # Resolve the observation policy: default to the S4-frozen file, and require
    # any CLI override to have the exact frozen bytes.
    frozen_policy_path: Path = ctx["frozen_policy_path"]
    if observation_policy_csv is not None:
        cli_policy_path = Path(observation_policy_csv).resolve()
        if sha256_file(cli_policy_path) != ctx["frozen_policy_sha256"]:
            raise ValueError(
                f"--observation-policy-csv {cli_policy_path} does not match the "
                f"S4-frozen observation policy hash {ctx['frozen_policy_sha256']}"
            )
        policy_path = cli_policy_path
    else:
        policy_path = frozen_policy_path

    # Resolve harvest_var: default to the S4-frozen value, reject mismatches.
    if harvest_var is not None and harvest_var != ctx["frozen_harvest_var"]:
        raise ValueError(
            f"--harvest-var {harvest_var!r} does not match the S4-frozen "
            f"value {ctx['frozen_harvest_var']!r}"
        )
    resolved_harvest_var = ctx["frozen_harvest_var"]

    posterior_base = posterior_manifest_path.parent
    pairs_path = posterior_base / "candidate_pairs.csv"
    pairs_entry = next(
        (a for a in posterior.get("artifacts", []) if a.get("role") == "candidate_pairs"), None
    )
    if pairs_entry is None:
        raise ValueError("posterior manifest has no candidate_pairs artifact")
    _require_hash(pairs_path, pairs_entry["sha256"], "candidate_pairs")
    pairs_df = _validate_candidate_pairs_schema(pd.read_csv(pairs_path))

    ensemble_path = _final_ensemble_path(run_dir, case)
    ensemble_df = pd.read_csv(ensemble_path)
    unique_reals = _unique_realizations(pairs_df)

    sigma_eff_map = _sigma_eff_map(policy_path)
    design = ctx["design"]
    roles = _role_lookup(design)
    entries = ctx["entries"]
    tmt_path = ctx["tmt_path"]
    input_dir = ctx["input_dir"]
    batch_path = ctx["batch_path"]

    param_dir = out_dir / "candidate_parameters"
    runs_dir = out_dir / "runs"

    # Export parameters + run each unique realization once.
    candidate_parameters_rows: list[dict[str, Any]] = []
    candidate_runs_rows: list[dict[str, Any]] = []
    comparison_by_real: dict[int, pd.DataFrame] = {}
    for realization in unique_reals:
        param_csv = param_dir / f"real_{realization}.csv"
        param_sha = _export_candidate_params(ensemble_df, realization, param_csv)
        candidate_parameters_rows.append({
            "realization": realization, "name": "(all)", "parameter_csv": str(param_csv.relative_to(out_dir)),
            "parameter_csv_sha256": param_sha,
        })
        real_run_dir = runs_dir / f"real_{realization}"
        run_record = _run_candidate_dssat(
            realization, param_csv, real_run_dir,
            input_dir=input_dir, batch_path=batch_path,
            harvest_var=resolved_harvest_var, runner=dssat_runner,
        )
        run_record["parameter_csv"] = _relative_posix(param_csv, out_dir)
        run_record["parameter_csv_sha256"] = param_sha
        run_record["final_parameter_ensemble"] = _relative_posix(ensemble_path, run_dir)
        run_record["final_parameter_ensemble_sha256"] = sha256_file(ensemble_path)
        run_record["input_dir"] = str(input_dir)
        run_record["input_manifest_sha256"] = sha256_file(input_dir / "input_manifest.json")
        run_record["batch"] = batch_path.name
        run_record["batch_sha256"] = sha256_file(batch_path)
        run_record["harvest_var"] = resolved_harvest_var
        run_record["upstream_run_id"] = case
        run_record["analysis_git"] = git_metadata()
        candidate_run_manifest_path = real_run_dir / "candidate_run_manifest.json"
        candidate_run_manifest_path.write_text(
            json.dumps(run_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        candidate_runs_rows.append({
            "realization": realization,
            "returncode": run_record["returncode"],
            "missing_outputs": ",".join(run_record["missing_outputs"]),
            "run_dir": _relative_posix(real_run_dir, out_dir),
            "run_manifest": _relative_posix(candidate_run_manifest_path, out_dir),
        })
        # A candidate is usable only if the run succeeded (returncode == 0) AND
        # every required output is present from this run. A non-zero returncode
        # with pre-existing OUT files must never be accepted (review P1: such a
        # case was previously treated as a complete run).
        if run_record["returncode"] != 0 or run_record["missing_outputs"]:
            continue
        comparison = build_comparison_from_rerun(
            real_run_dir, case=case, data_status=data_status, roles=roles,
            tmt_path=tmt_path, entries=entries,
        )
        comparison_by_real[realization] = comparison

    # Per-pair prediction distance.
    pair_prediction_rows: list[dict[str, Any]] = []
    distance_component_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    for _, pair in pairs_df.iterrows():
        pair_id = int(pair["pair_id"])
        real_a = int(pair["real_a"])
        real_b = int(pair["real_b"])
        comp_a = comparison_by_real.get(real_a)
        comp_b = comparison_by_real.get(real_b)
        d_val: float | None = None
        d_diag: float | None = None
        prediction_distance: float | None = None
        classification = "prediction_incomplete"
        if comp_a is not None and comp_b is not None:
            aligned = _align_pair(comp_a, comp_b)
            components = _distance_components(aligned, sigma_eff_map)
            if not components.empty:
                components.insert(0, "pair_id", pair_id)
                distance_component_rows.extend(components.to_dict("records"))
                d_val, d_diag, prediction_distance = _aggregate_distance(components)
                classification = _classify(d_val, d_diag, demo=demo)
            # Record BOTH sides of the pair so the frozen comparison table can
            # support re-drawing either candidate's predictions. Previously only
            # the A side was written, dropping realizations 16/20/32.
            for side, comp, real in (("A", comp_a, real_a), ("B", comp_b, real_b)):
                comp_records = comp.copy()
                comp_records["pair_id"] = pair_id
                comp_records["realization"] = real
                comp_records["candidate_side"] = side
                comparison_rows.extend(comp_records.to_dict("records"))
        pair_prediction_rows.append({
            "run_id": case,
            "data_status": data_status,
            "pair_id": pair_id,
            "real_a": real_a,
            "real_b": real_b,
            "phi_a": pair.get("phi_a"),
            "phi_b": pair.get("phi_b"),
            "parameter_distance": pair.get("parameter_distance"),
            "d_validation": d_val,
            "d_diagnostic": d_diag,
            "prediction_distance": prediction_distance,
            "classification": classification,
        })

    # Write outputs.
    candidate_parameters_path = out_dir / "candidate_parameters.csv"
    candidate_runs_path = out_dir / "candidate_runs.csv"
    candidate_comparison_path = out_dir / "candidate_comparison.csv"
    distance_components_path = out_dir / "prediction_distance_components.csv"
    pair_predictions_path = out_dir / "candidate_pair_predictions.csv"

    # Long-form parameter table (one row per realization×parameter).
    long_param_rows: list[dict[str, Any]] = []
    for realization in unique_reals:
        param_csv = param_dir / f"real_{realization}.csv"
        df = pd.read_csv(param_csv)
        for _, r in df.iterrows():
            long_param_rows.append({"realization": realization, "name": r["name"], "value": r["value"]})
    pd.DataFrame(long_param_rows).to_csv(candidate_parameters_path, index=False, encoding="utf-8")
    pd.DataFrame(candidate_runs_rows).to_csv(candidate_runs_path, index=False, encoding="utf-8")
    if comparison_rows:
        pd.DataFrame(comparison_rows).to_csv(candidate_comparison_path, index=False, encoding="utf-8")
    else:
        # Keep a header-only file so the manifest can still hash it.
        candidate_comparison_path.write_text(
            "pair_id,realization,dataset_role,variable,treatment,observed,simulated\n",
            encoding="utf-8",
        )
    if distance_component_rows:
        pd.DataFrame(distance_component_rows).to_csv(distance_components_path, index=False, encoding="utf-8")
    else:
        distance_components_path.write_text(
            "pair_id,dataset_role,variable,n_rows,sigma_eff,rms_normalized\n",
            encoding="utf-8",
        )
    pd.DataFrame(pair_prediction_rows).to_csv(pair_predictions_path, index=False, encoding="utf-8")

    manifest = _build_manifest(
        out_dir=out_dir,
        run_dir=run_dir,
        case=case,
        data_status=data_status,
        posterior_manifest_path=posterior_manifest_path,
        posterior_payload=posterior,
        ensemble_path=ensemble_path,
        ctx=ctx,
        observation_policy_csv=policy_path,
        split_path=ctx["split_path"],
        unique_reals=unique_reals,
        output_files={
            "candidate_parameters": candidate_parameters_path,
            "candidate_runs": candidate_runs_path,
            "candidate_comparison": candidate_comparison_path,
            "prediction_distance_components": distance_components_path,
            "candidate_pair_predictions": pair_predictions_path,
        },
        param_dir=param_dir,
        runs_dir=runs_dir,
    )
    manifest_path = out_dir / "candidate_prediction_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def _role_lookup(spec: Any) -> dict[int, str]:
    """Map treatment id -> role string from a DesignSpec."""
    out: dict[int, str] = {}
    for role in ("calibration", "validation", "diagnostic"):
        for tn in getattr(spec, f"{role}_treatments"):
            out[int(tn)] = role
    return out


def _relative_posix(path: Path, base: Path) -> str:
    return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")


def _build_manifest(
    *,
    out_dir: Path,
    run_dir: Path,
    case: str,
    data_status: str,
    posterior_manifest_path: Path,
    posterior_payload: dict[str, Any],
    ensemble_path: Path,
    ctx: dict[str, Any],
    observation_policy_csv: Path,
    split_path: Path,
    unique_reals: list[int],
    output_files: dict[str, Path],
    param_dir: Path,
    runs_dir: Path,
) -> dict[str, Any]:
    artifacts: list[dict[str, str]] = []
    for role, path in output_files.items():
        artifacts.append({"role": role, "path": _relative_posix(path, out_dir), "sha256": sha256_file(path)})
    # Per-realization parameter CSVs and candidate OUT hashes.
    for realization in unique_reals:
        param_csv = param_dir / f"real_{realization}.csv"
        artifacts.append({
            "role": "candidate_parameter_csv",
            "realization": str(realization),
            "path": _relative_posix(param_csv, out_dir),
            "sha256": sha256_file(param_csv),
        })
        run_manifest_json = runs_dir / f"real_{realization}" / "candidate_run_manifest.json"
        if run_manifest_json.is_file():
            artifacts.append({
                "role": "candidate_run_manifest",
                "realization": str(realization),
                "path": _relative_posix(run_manifest_json, out_dir),
                "sha256": sha256_file(run_manifest_json),
            })
    run_manifest = ctx["run_manifest"]
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": case,
        "data_status": data_status,
        "analysis_scope": "candidate_prediction_distance",
        "analysis_git": git_metadata(),
        "unique_realizations": [int(r) for r in unique_reals],
        "limitations": (
            "Prediction distance between two conditional-ensemble realizations on the "
            "frozen validation/diagnostic treatments. Tooling-demo outputs are for "
            "interface QA only; they do not establish functional equifinality or any "
            "scientific claim."
        ),
        "upstream": {
            "run_manifest_sha256": sha256_file(run_manifest),
            "calibration_finalize_sha256": sha256_file(
                run_dir / "calibration_finalize" / "calibration_finalize.json"
            ),
            "calibration_artifacts_manifest_sha256": sha256_file(
                run_dir / "calibration_finalize" / "calibration_artifacts_manifest.json"
            ),
            "posterior_results_manifest_sha256": sha256_file(posterior_manifest_path),
            "final_parameter_ensemble_sha256": sha256_file(ensemble_path),
            "input_manifest_sha256": sha256_file(ctx["input_dir"] / "input_manifest.json"),
            "batch_sha256": sha256_file(ctx["batch_path"]),
            "observation_policy_sha256": sha256_file(observation_policy_csv),
            "validation_split_sha256": sha256_file(split_path),
        },
        "artifacts": artifacts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Candidate-solution prediction comparison for a finalized staged calibration",
    )
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--posterior-manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--observation-policy-csv", default=None,
                        help="Defaults to the S4-frozen policy; if given, must hash-match it")
    parser.add_argument("--harvest-var", default=None,
                        help="Defaults to the S4-frozen value; if given, must equal it")
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    args = parser.parse_args(argv)
    manifest_path = build_candidate_prediction_bundle(
        run_dir=args.run_dir,
        case=args.case,
        posterior_manifest=args.posterior_manifest,
        out_dir=args.out_dir,
        observation_policy_csv=args.observation_policy_csv,
        allow_unvalidated_demo=bool(args.allow_unvalidated_demo),
        harvest_var=args.harvest_var,
    )
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
