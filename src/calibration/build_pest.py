import argparse
import sys
import os
import re
import csv
import shutil
import json
import math
from pathlib import Path
from typing import Dict, Optional, Set

# Support both ``python -m src.calibration.build_pest`` and direct execution.
_BOOTSTRAP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BOOTSTRAP_ROOT not in sys.path:
    sys.path.insert(0, _BOOTSTRAP_ROOT)

import pandas as pd
import numpy as np
import pyemu

import subprocess
from datetime import datetime, timezone

from src.calibration.weight_scheme import (
    WEIGHT_POLICY_ID,
    normalize_and_weight,
    compute_cv_based_sigma,
    compute_balanced_weights,
    build_observation_weights,
    weight_from_sigma,
    VARIABLE_TREATMENT,
)
from src.calibration.observation_policy import (
    POLICY_VERSION,
    apply_observation_policy,
    load_observation_policy,
    write_transform_config,
)
from src.calibration.build_pest_multiseason import build_multiseason_stage2
from src.calibration.multiseason_design import MultiSeasonDesign
from src.calibration.design_config import (
    apply_observation_stage,
    apply_parameter_stage,
    load_design_config,
    load_frozen_bounds_lookup,
    write_design_audit,
)
from src.common.input_manifest import (
    InputManifestError,
    verify_calibrated_input_bundle,
)
from src.common.param_registry import DEFAULT_BOUNDS, assert_valid_frozen_bounds
from src.common.project import PROJECT_ROOT, WORKSPACE_DIR, git_metadata, resolve_path, sha256_file
from src.common.quality import read_flat_run_manifest_field, serialize_manifest_scalar

WORKSPACE = str(WORKSPACE_DIR)
CUL_BASE_FILE = str(PROJECT_ROOT / "data" / "templates" / "genotype" / "TMGRO048.CUL.base")
ECO_FILE = str(PROJECT_ROOT / "data" / "templates" / "genotype" / "TMGRO048.ECO.base")
SPE_FILE = str(PROJECT_ROOT / "data" / "templates" / "genotype" / "TMGRO048.SPE.base")
SOIL_FILE = str(PROJECT_ROOT / "data" / "raw" / "soil" / "SOIL.SOL")
SOIL_BASE_FILE = SOIL_FILE
USER_INPUT_DIR = None
SENSITIVITY_PARAM_REVIEW_CSV = os.path.join(
    WORKSPACE,
    "Sensitivity_Analyze",
    "SA_Project_Output",
    "sensitivity_param_review.csv",
)
OUT_FILE = os.path.join(WORKSPACE, "Evaluate.OUT")
PEST_EVAL_FILE = os.path.join(WORKSPACE, "PestEval.OUT")
PEST_GROW_FILE = os.path.join(WORKSPACE, "PestGrow.OUT")
PEST_JOINT_FILE = os.path.join(WORKSPACE, "PestJoint.OUT")
PEST_HARVEST_FILE = os.path.join(WORKSPACE, "PestHarvest.OUT")
PEST_TMTGROW_FILE = os.path.join(WORKSPACE, "PestTmtGrow.OUT")


def _project_root():
    """Return the repository root independently of the current directory."""
    return str(PROJECT_ROOT)


def _resolve_bounds_id(bounds_id, crop=None):
    """Resolve a bounds_id to a frozen bounds CSV path."""
    root = _project_root()
    if crop:
        candidate = os.path.join(root, "data", "parameter_registry",
                                 "bounds_frozen", crop, bounds_id + ".csv")
        if os.path.exists(candidate):
            return candidate
    candidate = os.path.join(root, "data", "parameter_registry",
                             "bounds_frozen", bounds_id + ".csv")
    if os.path.exists(candidate):
        return candidate
    if os.path.exists(bounds_id):
        return os.path.abspath(bounds_id)
    return None


def _get_git_commit():
    """Get current git commit hash."""
    return str(git_metadata().get("git_commit", ""))


def _write_run_manifest(out_dir, **kwargs):
    """Write run_manifest.yaml to out_dir using simple YAML-like format.

    Scalars are serialized with ``serialize_manifest_scalar`` so that Windows
    paths (with backslashes) render as YAML single-quoted scalars and stay
    valid under both the project reader and a standard YAML parser. List
    values keep their historical ``repr()`` rendering for backward
    compatibility with existing readers.
    """
    path = os.path.join(out_dir, "run_manifest.yaml")
    with open(path, "w", encoding="utf-8") as f:
        for key, val in kwargs.items():
            if isinstance(val, (list, tuple)):
                f.write(key + ':\n')
                for item in val:
                    f.write('  - ' + repr(str(item)) + '\n')
            else:
                f.write(f"{key}: {serialize_manifest_scalar(val)}\n")
    return path


def _resolve_upstream_run_dir(source: Path) -> tuple[Path, Path, Path, Path]:
    """Locate the run directory, manifest, finalize and representative metadata.

    The stage representative CSV is produced by ``write_stage_representative``
    at ``<run_dir>/calibration_finalize/stage_representative_params.csv``.
    Older layouts placed the CSV directly in the run root. Both are accepted so
    long as ``run_manifest.yaml`` and ``calibration_finalize/calibration_finalize.json``
    are found relative to the same run directory; any other layout is rejected
    with an explicit message listing the two supported placements.

    Returns ``(run_dir, manifest_path, finalize_json_path, representative_metadata_json_path)``.
    The metadata path may not exist on disk for legacy runs; callers must handle
    ``None``/missing when enforcing the three-way hash contract.
    """
    parent = source.parent
    candidate_run_dir: Path | None = None
    # Preferred: finalize subdir layout produced by write_stage_representative.
    if parent.name == "calibration_finalize":
        grand = parent.parent
        if (grand / "run_manifest.yaml").is_file() and (parent / "calibration_finalize.json").is_file():
            candidate_run_dir = grand
    # Legacy: CSV sitting directly in the run root.
    if candidate_run_dir is None and (parent / "run_manifest.yaml").is_file():
        finalize_candidate = parent / "calibration_finalize" / "calibration_finalize.json"
        if finalize_candidate.is_file():
            candidate_run_dir = parent
    if candidate_run_dir is None:
        raise ValueError(
            f"--fixed-from {source} must come from a run with run_manifest.yaml and "
            "calibration_finalize/calibration_finalize.json. Expected the CSV either at "
            "<run_dir>/calibration_finalize/stage_representative_params.csv (finalize output) "
            "or directly under <run_dir>/ with the manifest and finalize subdir beside it."
        )
    run_dir = candidate_run_dir
    manifest = run_dir / "run_manifest.yaml"
    finalize_dir = run_dir / "calibration_finalize"
    finalize = finalize_dir / "calibration_finalize.json"
    representative_metadata = finalize_dir / "stage_representative_params.json"
    return run_dir, manifest, finalize, representative_metadata


def _fixed_from_provenance(
    paths: list[str] | None,
    *,
    current_stage: str | None = None,
    design_table_id: str | None = None,
    approval_scope: str | None = None,
) -> list[dict[str, str]]:
    """Bind inherited parameters to an upstream run and its finalize state."""
    records: list[dict[str, str]] = []
    if current_stage and len(paths or []) != 1:
        raise ValueError(f"{current_stage} requires exactly one --fixed-from from its immediate predecessor")
    expected_stage = {
        "S2": "S1",
        "S3": "S2",
        "S4": "S3",
    }.get(str(current_stage or "").upper())
    for raw in paths or []:
        source = Path(raw).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"--fixed-from file not found: {source}")
        run_dir, manifest, finalize, representative_metadata = _resolve_upstream_run_dir(source)
        try:
            finalize_payload = json.loads(finalize.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid upstream finalize artifact: {finalize}") from exc
        manifest_run_id = read_flat_run_manifest_field(manifest, "run_id")
        run_id = manifest_run_id or run_dir.name
        upstream_stage = str(read_flat_run_manifest_field(manifest, "design_stage") or "").upper()
        upstream_scope = str(read_flat_run_manifest_field(manifest, "approval_scope") or "").lower()
        finalize_case = str(finalize_payload.get("case") or "")
        if current_stage and not manifest_run_id:
            raise ValueError(f"upstream manifest {manifest} lacks run_id")
        if current_stage and not finalize_case:
            raise ValueError(f"upstream finalize {finalize} lacks case")
        if finalize_case and finalize_case != str(run_id):
            raise ValueError(
                f"upstream manifest run_id {run_id!r} != finalize case {finalize_case!r}"
            )
        if expected_stage and upstream_stage != expected_stage:
            raise ValueError(
                f"{current_stage} must inherit {expected_stage}; upstream is {upstream_stage or 'unknown'}"
            )
        if approval_scope and upstream_scope != str(approval_scope).lower():
            raise ValueError(
                f"upstream approval_scope {upstream_scope or 'missing'} does not match {approval_scope}"
            )
        expected_representative_hash = str(finalize_payload.get("stage_representative", {}).get("sha256") or "")
        if current_stage and not expected_representative_hash:
            raise ValueError(
                f"upstream run {run_id} lacks generated stage representative provenance"
            )
        actual_file_hash = sha256_file(source)
        if current_stage and expected_representative_hash != actual_file_hash:
            raise ValueError(
                f"--fixed-from representative file hash {actual_file_hash} does not match "
                f"finalize stage_representative.sha256 {expected_representative_hash} for upstream run {run_id}"
            )
        # Three-way consistency: the manifest-upserted hash, the finalize
        # stage_representative.sha256 and the representative metadata json
        # output_sha256 must all describe the same bytes. A divergence means
        # the finalize artifacts were edited independently after generation.
        metadata_output_hash = ""
        if representative_metadata.is_file():
            try:
                metadata_payload = json.loads(representative_metadata.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"invalid upstream representative metadata {representative_metadata}"
                ) from exc
            metadata_output_hash = str(metadata_payload.get("output_sha256") or "")
        if current_stage and metadata_output_hash and metadata_output_hash != actual_file_hash:
            raise ValueError(
                f"upstream run {run_id} representative hash disagreement: file="
                f"{actual_file_hash} finalize={expected_representative_hash} "
                f"metadata={metadata_output_hash}"
            )
        upstream_design_id = str(read_flat_run_manifest_field(manifest, "design_table_id") or "")
        if current_stage and not upstream_design_id:
            raise ValueError(f"upstream manifest {manifest} lacks design_table_id")
        if design_table_id and upstream_design_id != design_table_id:
            raise ValueError(
                f"upstream design_table_id {upstream_design_id!r} does not match {design_table_id!r}"
            )
        finalize_stage = str(finalize_payload.get("design_stage") or "").upper()
        finalize_design_id = str(finalize_payload.get("design_table_id") or "")
        finalize_scope = str(finalize_payload.get("approval_scope") or "").lower()
        if current_stage and not finalize_stage:
            raise ValueError(f"upstream finalize {finalize} lacks design_stage")
        if current_stage and not finalize_design_id:
            raise ValueError(f"upstream finalize {finalize} lacks design_table_id")
        if current_stage and finalize_stage != upstream_stage:
            raise ValueError(
                f"upstream finalize design_stage {finalize_stage!r} does not match manifest {upstream_stage!r}"
            )
        if current_stage and finalize_design_id != upstream_design_id:
            raise ValueError(
                "upstream finalize design_table_id does not match manifest design_table_id"
            )
        if current_stage and finalize_scope != upstream_scope:
            raise ValueError(
                "upstream finalize approval_scope does not match manifest approval_scope"
            )
        engineering_status = str(finalize_payload.get("engineering_status") or "")
        science_status = str(finalize_payload.get("science_status") or "")
        if engineering_status != "engineering_validated":
            raise ValueError(
                f"--fixed-from upstream run {run_id} is not engineering_validated: {engineering_status or 'missing'}"
            )
        records.append({
            "path": str(source),
            "sha256": sha256_file(source),
            "run_id": str(run_id),
            "design_stage": upstream_stage,
            "design_table_id": upstream_design_id,
            "engineering_status": engineering_status,
            "science_status": science_status,
            "run_manifest": str(manifest),
            "run_manifest_sha256": sha256_file(manifest),
            "finalize": str(finalize),
            "finalize_sha256": sha256_file(finalize),
        })
    return records


def _resolve_sigma(group_sigmas, obgnme, obs_col):
    """Resolve a declared observation sigma without a silent numeric fallback."""
    if group_sigmas is None:
        return None
    for key in (obgnme, obs_col):
        if key in group_sigmas:
            sigma = float(group_sigmas[key])
            weight_from_sigma(sigma)  # validates positive and finite
            return sigma
    raise KeyError(
        f"No sigma configured for observation group {obgnme!r} "
        f"(base variable {obs_col!r})"
    )


def _write_weight_audit(obs_df, out_dir, prefix):
    """Write the exact statistical and final weights used in the PST."""
    if obs_df.empty:
        return None
    audit = obs_df.copy()
    if "sigma" not in audit:
        audit["sigma"] = audit["weight"].map(
            lambda value: (1.0 / float(value)) if float(value) > 0 else None
        )
    if "base_weight" not in audit:
        audit["base_weight"] = audit["weight"]
    if "group_multiplier" not in audit:
        audit["group_multiplier"] = 1.0
    if "transform" not in audit:
        audit["transform"] = "raw"
    if "weight_policy_id" not in audit:
        audit["weight_policy_id"] = WEIGHT_POLICY_ID
    columns = [
        "obsnme", "obgnme", "raw_obsval", "obsval", "raw_sigma", "sigma",
        "sigma_source", "base_weight", "group_multiplier", "weight",
        "transform", "transform_offset", "transform_reference",
        "sim_token", "model_output_file", "weight_policy_id", "phi_role",
    ]
    # PEST++ writes its own realization-level ``case.weights.csv`` at runtime;
    # keep the policy audit under a distinct name so it cannot be overwritten.
    path = os.path.join(out_dir, f"{prefix}.weights.audit.csv")
    audit[[column for column in columns if column in audit]].to_csv(
        path, index=False, encoding="utf-8-sig"
    )
    return path


def _apply_policy_and_prepare_runner(obs_df, policies, out_dir, prefix, model_cmd_extra):
    """Apply the approved observation policy and configure the model command."""
    if obs_df.empty or not policies:
        return obs_df, model_cmd_extra
    obs_df, token_map = apply_observation_policy(obs_df, policies)
    if not token_map:
        return obs_df, model_cmd_extra
    config_name = f"{prefix}.observation_transforms.json"
    write_transform_config(os.path.join(out_dir, config_name), token_map)
    extra = str(model_cmd_extra or "").strip()
    transform_arg = f"--observation-transform-config {config_name}"
    return obs_df, f"{extra} {transform_arg}".strip()


def _write_observation_noise_ensemble(
    pst_path,
    weights_audit_path,
    out_dir,
    prefix,
    n_reals,
    seed,
):
    """Freeze an observation-plus-noise ensemble from the audited sigma values.

    PEST++ otherwise silently falls back to ``no-noise`` when a PST contains
    only ordinary observation weights.  The project uses ``1/sigma`` weights
    for the objective, so this explicit file keeps the same ``sigma_eff``
    available to the IES observation ensemble without conflating it with any
    group multiplier used for Phi balancing.
    """
    pst = pyemu.Pst(str(pst_path))
    obs = pst.observation_data.copy()
    obs = obs[pd.to_numeric(obs["weight"], errors="coerce") > 0].copy()
    if obs.empty:
        raise ValueError("cannot create observation-noise ensemble without non-zero observations")
    audit = pd.read_csv(weights_audit_path, encoding="utf-8-sig")
    if "obsnme" not in audit:
        raise ValueError("weights audit lacks obsnme; cannot freeze observation noise")
    audit = audit.drop_duplicates("obsnme").copy()
    audit["_obs_key"] = audit["obsnme"].astype(str).str.upper()
    audit = audit.set_index("_obs_key")
    obs_keys = pd.Index([str(name).upper() for name in obs.index])
    missing = [name for name, key in zip(obs.index, obs_keys) if key not in audit.index]
    if missing:
        raise ValueError(f"weights audit lacks sigma for {len(missing)} observations")
    sigma = pd.to_numeric(audit.loc[obs_keys, "raw_sigma"], errors="coerce")
    if sigma.isna().any() or (sigma <= 0).any() or not np.isfinite(sigma.to_numpy()).all():
        raise ValueError("observation-noise contract requires finite positive raw_sigma for every active observation")
    observed = pd.to_numeric(obs.loc[:, "obsval"], errors="coerce")
    if observed.isna().any() or not np.isfinite(observed.to_numpy()).all():
        raise ValueError("observation-noise contract requires finite obsval for every active observation")

    rng = np.random.default_rng(int(seed))
    values = observed.to_numpy(dtype=float)[None, :] + rng.normal(
        loc=0.0,
        scale=sigma.to_numpy(dtype=float)[None, :],
        size=(int(n_reals), len(obs)),
    )
    frame = pd.DataFrame(values, columns=list(obs.index))
    frame.insert(0, "real_name", [str(i) for i in range(int(n_reals))])
    path = Path(out_dir) / f"{prefix}.observation_ensemble.csv"
    frame.to_csv(path, index=False, float_format="%.12g", encoding="utf-8")
    metadata = {
        "schema_version": 1,
        "run_id": prefix,
        "n_reals": int(n_reals),
        "seed": int(seed),
        "noise_distribution": "independent_normal",
        "sigma_source": "weights_audit.raw_sigma",
        "weight_definition": "objective weight remains group_multiplier/raw_sigma; noise uses raw_sigma",
        "observation_count": int(len(obs)),
        "observation_names_sha256": sha256_file(path),
    }
    metadata_path = Path(out_dir) / f"{prefix}.observation_ensemble.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return str(path), str(metadata_path), metadata


def _finalize_ies_contract(
    pst_path,
    out_dir,
    prefix,
    ies_num_reals,
    random_seed,
    bad_phi_sigma,
    observation_noise=True,
):
    """Apply explicit IES filtering/noise policy after PST construction."""
    pst = pyemu.Pst(str(pst_path))
    # 1e300 is PEST++'s effectively-disabled relative filter.  A finite value
    # is reserved for an explicitly requested D0 diagnostic comparison.
    sigma_value = float(bad_phi_sigma)
    if not math.isfinite(sigma_value) or sigma_value <= 0:
        raise ValueError("bad_phi_sigma must be a positive finite value; use 1e300 to disable relative screening")
    pst.pestpp_options["ies_bad_phi_sigma"] = sigma_value
    noise_path = noise_meta_path = None
    noise_meta = None
    if observation_noise:
        audit_path = Path(out_dir) / f"{prefix}.weights.audit.csv"
        if not audit_path.exists():
            # Backward compatibility for pre-contract builds whose policy
            # audit used the runtime-facing ``.weights.csv`` name.
            audit_path = Path(out_dir) / f"{prefix}.weights.csv"
        noise_path, noise_meta_path, noise_meta = _write_observation_noise_ensemble(
            pst_path,
            audit_path,
            out_dir,
            prefix,
            ies_num_reals,
            int(random_seed) + 1000003,
        )
        pst.pestpp_options["ies_observation_ensemble"] = os.path.basename(noise_path)
        pst.pestpp_options["ies_no_noise"] = False
    pst.write(str(pst_path))
    return {
        "bad_phi_sigma": sigma_value,
        "relative_phi_screening": sigma_value < 1.0e299,
        "observation_noise": bool(observation_noise),
        "observation_ensemble": os.path.basename(noise_path) if noise_path else "",
        "observation_noise_metadata": os.path.basename(noise_meta_path) if noise_meta_path else "",
        "observation_noise_seed": noise_meta.get("seed") if noise_meta else None,
        "observation_ensemble_sha256": (
            sha256_file(noise_path) if noise_path and os.path.isfile(noise_path) else ""
        ),
    }

ECO_BOUNDS_EGGPLANT = {
    name: DEFAULT_BOUNDS[name]
    for name in (
        "PL-EM", "EM-V1", "V1-JU", "JU-R0", "FL-VS", "TRIFL",
        "RWDTH", "RHGHT", "OPTBI", "SLOBI", "XMAGE", "XFPHT", "XFINT",
    )
}

SPE_TEMP_BOUNDS_EGGPLANT = {
    name: DEFAULT_BOUNDS[name]
    for name in (
        "TB", "TO1", "TO2", "TM",
        "TB1", "TO11", "TO21", "TM1",
        "TB2", "TO12", "TO22", "TM2",
        "TB3", "TO13", "TO23", "TM3",
    )
}


SPE_DIRECT_BOUNDS_EGGPLANT = {
    "KC_SLOPE": (0.0, 0.40),
    "VSSINK": (2.05, 8.20),
    "RTNO3": (0.010, 0.050),
    "RTNH4": (0.010, 0.050),
    "RTEXF": (0.05, 0.25),
    "NSTFAC": (0.40, 0.85),
    "NMOBMX": (0.15, 0.40),
    "NVSMOB": (0.20, 0.50),
    "NRCVR": (0.05, 0.30),
}


def _param_location_from_group(pargp):
    g = (pargp or "").strip().lower()
    if g == "cultivar":
        return "CUL"
    if g == "ecotype":
        return "ECO"
    if g == "species":
        return "SPE"
    return ""


def _param_file_from_location(location):
    loc = (location or "").strip().upper()
    if loc == "CUL":
        return os.path.basename(CUL_BASE_FILE)
    if loc == "ECO":
        return os.path.basename(ECO_FILE)
    if loc == "SPE":
        return os.path.basename(SPE_FILE)
    return ""


def write_param_review_csv(params, csv_path, cultivar=None, ecotype=None, mode=None):
    rows = []
    for p in params:
        pargp = p.get("pargp", "")
        location = _param_location_from_group(pargp)
        rows.append(
            {
                "name": p.get("name"),
                "init": p.get("init"),
                "lower": p.get("lower"),
                "upper": p.get("upper"),
                "status": p.get("status"),
                "pargp": pargp,
                "location": location,
                "file": _param_file_from_location(location),
                "cultivar": cultivar or "",
                "ecotype": ecotype or "",
                "mode": mode or "",
            }
        )

    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")


def _coerce_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if pd.isna(v):
            return None
        return float(v)
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _coerce_str(v):
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    if pd.isna(v):
        return None
    s = str(v).strip()
    return s if s else None


def apply_param_review_csv(params, csv_path):
    if not csv_path or not os.path.exists(csv_path):
        return params

    df = pd.read_csv(csv_path)
    if df.empty:
        return params

    cols_lower = {str(c).strip().lower(): c for c in df.columns}

    def _col(*names):
        for n in names:
            key = str(n).strip().lower()
            if key in cols_lower:
                return cols_lower[key]
        return None

    name_col = _col("name", "parnme", "parameter")
    if name_col is None:
        return params

    init_col = _col("init", "initial", "value", "parval1")
    lb_col = _col("lower", "lb", "parlbnd")
    ub_col = _col("upper", "ub", "parubnd")
    status_col = _col("status", "partrans")
    pargp_col = _col("pargp", "group")

    by_name = {}
    for _, r in df.iterrows():
        k = _coerce_str(r.get(name_col))
        if not k:
            continue
        by_name[k.strip().lower()] = r

    for p in params:
        k = str(p.get("name", "")).strip().lower()
        if not k or k not in by_name:
            continue
        r = by_name[k]

        init_v = _coerce_float(r.get(init_col)) if init_col else None
        lb_v = _coerce_float(r.get(lb_col)) if lb_col else None
        ub_v = _coerce_float(r.get(ub_col)) if ub_col else None
        status_v = _coerce_str(r.get(status_col)) if status_col else None
        pargp_v = _coerce_str(r.get(pargp_col)) if pargp_col else None

        if lb_v is not None:
            p["lower"] = float(lb_v)
        if ub_v is not None:
            p["upper"] = float(ub_v)
        if init_v is not None:
            p["init"] = float(init_v)
        if status_v is not None:
            status_key = str(status_v).strip().lower()
            p["status"] = {"active": "none", "disabled": "fixed"}.get(status_key, status_key)
        if pargp_v is not None:
            p["pargp"] = str(pargp_v)

        try:
            lb = float(p.get("lower"))
            ub = float(p.get("upper"))
            init = float(p.get("init"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Parameter review contains non-numeric bounds for {p.get('name')}") from exc
        if not lb <= init <= ub:
            raise ValueError(
                f"Parameter review requires lower <= init <= upper for {p.get('name')}: "
                f"{lb:g} <= {init:g} <= {ub:g}"
            )

        if float(p.get("lower", 0.0)) == float(p.get("upper", 0.0)):
            p["status"] = "fixed"

    return params


def apply_bounds_review_csv(params, csv_path, cultivar=None, ecotype=None, mode=None):
    if not csv_path or not os.path.exists(csv_path):
        return params, {"applied": 0, "missing": 0, "missing_names": []}

    df = pd.read_csv(csv_path)
    if df.empty:
        return params, {"applied": 0, "missing": 0, "missing_names": []}

    cols_lower = {str(c).strip().lower(): c for c in df.columns}

    def _col(*names):
        for n in names:
            key = str(n).strip().lower()
            if key in cols_lower:
                return cols_lower[key]
        return None

    name_col = _col("name", "parnme", "parameter")
    init_col = _col("init", "parval1", "initial")
    lb_col = _col("lower", "lb", "parlbnd")
    ub_col = _col("upper", "ub", "parubnd")
    status_col = _col("status")
    cul_col = _col("cultivar")
    eco_col = _col("ecotype")
    loc_col = _col("location")
    mode_col = _col("mode")
    if name_col is None or lb_col is None or ub_col is None:
        return params, {"applied": 0, "missing": 0, "missing_names": []}

    by_name = {}
    for _, r in df.iterrows():
        name_raw = _coerce_str(r.get(name_col))
        if not name_raw:
            continue
        k = name_raw.strip().lower()
        by_name.setdefault(k, []).append(r)

    def _pick_row(rows, location=None, mode=None):
        if not rows:
            return None
        if loc_col and location:
            rows2 = []
            for rr in rows:
                if str(rr.get(loc_col, "")).strip().upper() == str(location).strip().upper():
                    rows2.append(rr)
            if rows2:
                rows = rows2
        if cul_col and cultivar:
            rows2 = []
            for rr in rows:
                if str(rr.get(cul_col, "")).strip().upper() == str(cultivar).strip().upper():
                    rows2.append(rr)
            if rows2:
                rows = rows2
        if eco_col and ecotype:
            rows2 = []
            for rr in rows:
                if str(rr.get(eco_col, "")).strip().upper() == str(ecotype).strip().upper():
                    rows2.append(rr)
            if rows2:
                rows = rows2
        if mode_col and mode:
            rows2 = []
            for rr in rows:
                mv = str(rr.get(mode_col, "")).strip().lower()
                if not mv or mv == str(mode).strip().lower() or mv == "both":
                    rows2.append(rr)
            if rows2:
                rows = rows2
        return rows[0]

    applied = 0
    missing_names = []
    for p in params:
        if str(p.get("pargp", "")).strip().lower() in {"soil", "initial_conditions"}:
            continue
        k = str(p.get("name", "")).strip().lower()
        if not k:
            continue
        rows = by_name.get(k)
        if not rows:
            missing_names.append(p.get("name"))
            continue
        location = _param_location_from_group(p.get("pargp"))
        r = _pick_row(rows, location=location, mode=mode)
        if r is None:
            missing_names.append(p.get("name"))
            continue

        lb_v = _coerce_float(r.get(lb_col))
        ub_v = _coerce_float(r.get(ub_col))
        if lb_v is None or ub_v is None:
            continue
        init_v = _coerce_float(r.get(init_col)) if init_col else None
        candidate_init = float(init_v) if init_v is not None else float(p.get("init"))
        candidate_lower = float(lb_v)
        candidate_upper = float(ub_v)
        if not candidate_lower <= candidate_init <= candidate_upper:
            raise ValueError(
                f"Bounds review requires lower <= init <= upper for {p.get('name')}: "
                f"{candidate_lower:g} <= {candidate_init:g} <= {candidate_upper:g}"
            )
        p["lower"] = candidate_lower
        p["upper"] = candidate_upper
        p["init"] = candidate_init
        source_status = ""
        if status_col:
            status_v = _coerce_str(r.get(status_col)).lower()
            if status_v in {"active", "fixed", "disabled"}:
                source_status = status_v
                p["status"] = {"active": "none", "fixed": "fixed", "disabled": "fixed"}[status_v]
                p["disabled"] = status_v == "disabled"
        if source_status == "fixed" and not candidate_lower == candidate_init == candidate_upper:
            raise ValueError(
                f"Fixed bounds review row requires lower == init == upper for {p.get('name')}"
            )
        if source_status == "active" and candidate_lower == candidate_upper:
            raise ValueError(f"Active bounds review row has zero width for {p.get('name')}")
        applied += 1

        if float(p.get("lower", 0.0)) == float(p.get("upper", 0.0)):
            p["status"] = "fixed"

    params = [parameter for parameter in params if not parameter.get("disabled", False)]
    return params, {"applied": applied, "missing": len(missing_names), "missing_names": missing_names}


def validate_sensitivity_param_review_csv(csv_path):
    issues = []
    if not csv_path or not os.path.exists(csv_path):
        return [f"missing_file: {csv_path}"]
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        return [f"read_error: {e}"]
    if df.empty:
        return ["empty_csv"]

    cols = {str(c).strip().lower(): c for c in df.columns}
    name_c = cols.get("name")
    init_c = cols.get("init")
    lb_c = cols.get("lower")
    ub_c = cols.get("upper")
    status_c = cols.get("status")
    loc_c = cols.get("location")
    cul_c = cols.get("cultivar")
    eco_c = cols.get("ecotype")

    required = [name_c, init_c, lb_c, ub_c]
    if any(c is None for c in required):
        missing = [k for k in ("name", "init", "lower", "upper") if k not in cols]
        issues.append(f"missing_required_columns: {','.join(missing)}")
        return issues

    def _norm_name(v):
        s = _coerce_str(v)
        return s.strip().upper() if s else None

    def _norm_loc(v):
        s = _coerce_str(v)
        return s.strip().upper() if s else ""

    seen = {}
    for i, r in df.iterrows():
        name = _norm_name(r.get(name_c))
        if not name:
            issues.append(f"row_{i+2}: missing_name")
            continue

        init = _coerce_float(r.get(init_c))
        lb = _coerce_float(r.get(lb_c))
        ub = _coerce_float(r.get(ub_c))
        status = (_coerce_str(r.get(status_c)) or "").strip().lower() if status_c else ""
        loc = _norm_loc(r.get(loc_c)) if loc_c else ""
        cul = _coerce_str(r.get(cul_c)) if cul_c else ""
        eco = _coerce_str(r.get(eco_c)) if eco_c else ""

        if init is None or lb is None or ub is None:
            issues.append(f"{name}: missing_numeric (row {i+2})")
            continue
        if lb > ub:
            issues.append(f"{name}: lower_gt_upper ({lb}>{ub})")
        if init < min(lb, ub) or init > max(lb, ub):
            issues.append(f"{name}: init_outside_bounds (init={init}, lb={lb}, ub={ub})")
        if status == "fixed" and float(lb) != float(ub):
            issues.append(f"{name}: status_fixed_but_bounds_not_equal (lb={lb}, ub={ub})")
        if status == "active" and float(lb) == float(ub):
            issues.append(f"{name}: status_active_but_bounds_equal (v={lb})")

        key = (name, loc, (cul or "").strip().upper(), (eco or "").strip().upper())
        prev = seen.get(key)
        if prev is not None:
            issues.append(
                f"{name}: duplicate_key (rows {prev},{i+2}, loc={loc or 'NA'}, cul={cul or 'NA'}, eco={eco or 'NA'})"
            )
        else:
            seen[key] = i + 2

    def _extract_layer(n):
        m = re.search(r"_(\d{2})$", str(n))
        if not m:
            return None
        try:
            return int(m.group(1))
        except Exception:
            return None

    soil = {}
    for _, r in df.iterrows():
        name = _norm_name(r.get(name_c))
        if not name:
            continue
        if not name.startswith("SOIL_") and not name.startswith("IC_SH2O_"):
            continue
        soil[name] = {
            "init": _coerce_float(r.get(init_c)),
            "lb": _coerce_float(r.get(lb_c)),
            "ub": _coerce_float(r.get(ub_c)),
        }

    layers = set()
    for k in soil.keys():
        layer = _extract_layer(k)
        if layer is not None:
            layers.add(layer)

    for layer in sorted(layers):
        slll = soil.get(f"SOIL_SLLL_{layer:02d}")
        sdul = soil.get(f"SOIL_SDUL_{layer:02d}")
        ssat = soil.get(f"SOIL_SSAT_{layer:02d}")
        sh2o = soil.get(f"IC_SH2O_{layer:02d}")
        if slll and sdul and ssat:
            a, b, c = slll.get("init"), sdul.get("init"), ssat.get("init")
            if a is not None and b is not None and a > b:
                issues.append(f"SOIL layer {layer:02d}: SLLL_gt_SDUL (SLLL={a}, SDUL={b})")
            if b is not None and c is not None and b > c:
                issues.append(f"SOIL layer {layer:02d}: SDUL_gt_SSAT (SDUL={b}, SSAT={c})")
            if a is not None and c is not None and a > c:
                issues.append(f"SOIL layer {layer:02d}: SLLL_gt_SSAT (SLLL={a}, SSAT={c})")
        if sh2o and slll and ssat:
            w = sh2o.get("init")
            a = slll.get("init")
            c = ssat.get("init")
            if w is not None and a is not None and w < a:
                issues.append(f"SOIL layer {layer:02d}: SH2O_below_SLLL (SH2O={w}, SLLL={a})")
            if w is not None and c is not None and w > c:
                issues.append(f"SOIL layer {layer:02d}: SH2O_above_SSAT (SH2O={w}, SSAT={c})")

    return issues


def _parse_batch_entries(batch_file):
    entries = []
    if not batch_file or not os.path.exists(batch_file):
        return entries

    with open(batch_file, "r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("$") or s.startswith("@") or s.startswith("!"):  # header/comment
                continue
            parts = s.split()
            if not parts:
                continue
            filex = parts[0]
            tn = -99
            if len(parts) >= 2:
                try:
                    tn = int(float(parts[1]))
                except Exception:
                    tn = -99
            entries.append({"filex": filex, "tn": tn})

    for i, e in enumerate(entries, start=1):
        e["run"] = i
    return entries


def _infer_excode_from_filex(filex_path):
    if not filex_path:
        return None
    base = os.path.basename(filex_path)
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base or None


def _collect_tmt_events_per_run(entries):
    """Return ``(events_by_run, points_by_run)`` keyed by ``@RUN``."""
    events_by_run = {}
    points_by_run = {}
    tmt_cache = {}
    for entry in entries:
        run_no = int(entry["run"])
        tn = int(entry.get("tn", -99))
        filex = entry.get("filex")
        filex_path = (
            _resolve_filex_path(filex)
            or (filex if filex and os.path.isabs(filex) else None)
        )
        if not filex_path:
            raise FileNotFoundError(f"cannot resolve FileX for batch entry run={run_no}: {filex!r}")
        if filex_path not in tmt_cache:
            excode = _infer_excode_from_filex(filex_path)
            tmt_path = os.path.join(os.path.dirname(os.path.abspath(filex_path)), f"{excode}.TMT") if excode else None
            tmt_cache[filex_path] = (_read_tmt_harvest_events(tmt_path), _read_tmt_process_points(tmt_path))
        events_by_tn, points_by_tn = tmt_cache[filex_path]
        events_by_run[run_no] = list(events_by_tn.get(tn, []))
        points_by_run[run_no] = list(points_by_tn.get(tn, []))
    return events_by_run, points_by_run


def _infer_ecotype_from_cul_base(target_cultivar):
    if not target_cultivar or not os.path.exists(CUL_BASE_FILE):
        return None
    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")
    with open(CUL_BASE_FILE, "r") as f:
        for line in f:
            if not line.startswith(target_cultivar):
                continue
            m = number_re.search(line)
            if not m:
                return None
            prefix = line[: m.start()]
            parts = prefix.split()
            if not parts:
                return None
            return parts[-1].strip() or None
    return None


def _read_eco_init_values(target_ecotype):
    if not target_ecotype or not os.path.exists(ECO_FILE):
        return {}

    header_idx = -1
    eco_idx = -1
    with open(ECO_FILE, "r") as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        if line.startswith("@ECO#"):
            header_idx = i
        elif line.startswith(target_ecotype):
            eco_idx = i

    if header_idx == -1 or eco_idx == -1:
        return {}

    headers = lines[header_idx].split()
    if len(headers) < 3:
        return {}
    param_names = headers[2:]

    eco_line = lines[eco_idx]
    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")
    matches = [m.group(0) for m in number_re.finditer(eco_line)]
    if len(matches) < len(param_names):
        return {}

    vals = matches[-len(param_names) :]
    out = {}
    for name, v in zip(param_names, vals):
        try:
            out[str(name).strip().upper()] = float(v)
        except Exception:
            continue
    return out


def _read_spe_temp_init_values():
    if not os.path.exists(SPE_FILE):
        return {}

    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")
    with open(SPE_FILE, "r") as f:
        lines = f.readlines()

    pheno_idx = -1
    for i, line in enumerate(lines):
        if line.strip().upper().startswith("!*PHENOLOGY PARAMETERS") or line.strip().upper().startswith("*PHENOLOGY PARAMETERS"):
            pheno_idx = i
            break
    if pheno_idx == -1:
        return {}

    def _stage_for_line(line):
        u = (line or "").upper()
        if "VEGETATIVE DEVELOPMENT" in u:
            return 1
        if "EARLY REPRODUCTIVE DEVELOPMENT" in u:
            return 2
        if "LATE REPRODUCTIVE DEVELOPMENT" in u:
            return 3
        return None

    out = {}
    for i in range(pheno_idx + 1, min(pheno_idx + 60, len(lines))):
        s = lines[i]
        if "DEVELOPMENT" not in s.upper():
            continue
        stage = _stage_for_line(s)
        if stage is None:
            continue
        matches = [m.group(0) for m in number_re.finditer(s)]
        if len(matches) < 4:
            continue
        try:
            tb, to1, to2, tm = (float(matches[0]), float(matches[1]), float(matches[2]), float(matches[3]))
        except Exception:
            continue

        out[f"TB{stage}"] = tb
        out[f"TO1{stage}"] = to1
        out[f"TO2{stage}"] = to2
        out[f"TM{stage}"] = tm

        if stage == 1:
            out["TB"] = tb
            out["TO1"] = to1
            out["TO2"] = to2
            out["TM"] = tm

    return out


def _read_spe_direct_init_values():
    if not os.path.exists(SPE_FILE):
        return {}

    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")
    with open(SPE_FILE, "r") as f:
        lines = f.readlines()

    out = {}
    for line in lines:
        u = line.upper()
        if "PARMAX,PHTMAX" in u and "KC_SLOPE" in u:
            nums = [m.group(0) for m in number_re.finditer(line)]
            if len(nums) >= 4:
                try:
                    out["KC_SLOPE"] = float(nums[3])
                except Exception:
                    pass
        if "CMOBMX,CADSTF" in u and "NMOBMX" in u:
            nums = [m.group(0) for m in number_re.finditer(line)]
            if len(nums) >= 6:
                try:
                    out["NMOBMX"] = float(nums[3])
                    out["NVSMOB"] = float(nums[4])
                    out["NRCVR"] = float(nums[5])
                except Exception:
                    pass
        if "XPODF" in u and "NSTFAC" in u:
            nums = [m.group(0) for m in number_re.finditer(line)]
            if len(nums) >= 1:
                try:
                    out["NSTFAC"] = float(nums[-1])
                except Exception:
                    pass
        if "FINREF,SLAREF" in u and "VSSINK" in u:
            nums = [m.group(0) for m in number_re.finditer(line)]
            if len(nums) >= 4:
                try:
                    out["VSSINK"] = float(nums[3])
                except Exception:
                    pass
        if "RTNO3,RTNH4" in u and "RTEXF" in u:
            nums = [m.group(0) for m in number_re.finditer(line)]
            if len(nums) >= 4:
                try:
                    out["RTNO3"] = float(nums[0])
                    out["RTNH4"] = float(nums[1])
                    out["PORMIN"] = float(nums[2])
                    out["RTEXF"] = float(nums[3])
                except Exception:
                    pass
    return out


def parse_extra_params(init_map, bounds_map, allowed_params=None, pargp="ecotype"):
    params = []
    for name_raw, (lb, ub) in (bounds_map or {}).items():
        name = str(name_raw).strip().upper()
        if allowed_params is not None and name not in {str(a).strip().upper() for a in allowed_params}:
            continue
        init = init_map.get(name)
        if init is None:
            init = (float(lb) + float(ub)) / 2.0
        status = "none" if float(lb) != float(ub) else "fixed"
        params.append(
            {
                "name": name_raw,
                "init": float(init),
                "lower": float(lb),
                "upper": float(ub),
                "idx": None,
                "status": status,
                "pargp": str(pargp),
            }
        )
    return params


def _read_tmt_harvest_events(tmt_path):
    if not tmt_path or not os.path.exists(tmt_path):
        return {}

    header = None
    rows = []
    with open(tmt_path, "r") as f:
        for line in f:
            s = line.rstrip("\n")
            if not s.strip():
                continue
            if s.lstrip().startswith("@TRNO"):
                header = s.split()
                continue
            if header is None:
                continue
            if s.startswith("*") or s.lstrip().startswith("@"):  
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            if len(parts) < len(header):
                parts += ["-99"] * (len(header) - len(parts))
            row = dict(zip(header, parts[: len(header)]))
            rows.append(row)

    def _as_int(v, default=-99):
        try:
            return int(float(v))
        except Exception:
            return default

    def _as_float(v, default=-99.0):
        try:
            return float(v)
        except Exception:
            return default

    events_by_tn = {}
    for r in rows:
        tn = _as_int(r.get("@TRNO"), default=-99)
        date = _as_int(r.get("DATE"), default=-99)
        if tn <= 0 or date <= 0:
            continue

        chpdt = _as_float(r.get("CHPDT"), default=-99.0)
        hpodw = _as_float(r.get("HPODW"), default=-99.0)
        pwad = _as_float(r.get("PWAD"), default=-99.0)
        chfpw = _as_float(r.get("CHFPW"), default=-99.0)
        hfpow = _as_float(r.get("HFPOW"), default=-99.0)
        if all(v == -99.0 for v in [chpdt, hpodw, pwad, chfpw, hfpow]):
            continue

        events_by_tn.setdefault(tn, []).append(
            {
                "date": date,
                "chpdt": chpdt,
                "hpodw": hpodw,
                "pwad": pwad,
                "chfpw": chfpw,
                "hfpow": hfpow,
            }
        )

    out = {}
    for tn, evs in events_by_tn.items():
        evs_sorted = sorted(evs, key=lambda x: x["date"])
        dry_cum = 0.0
        fresh_cum = 0.0
        out_list = []
        prev_dry_cum = None
        prev_fresh_cum = None
        for idx, e in enumerate(evs_sorted, start=1):
            dry_inc = -99.0
            if e["chpdt"] != -99.0:
                prev = float(dry_cum)
                dry_cum = float(e["chpdt"])
                dry_inc = float(dry_cum - prev)
            else:
                if e.get("hpodw", -99.0) != -99.0:
                    inc = float(e["hpodw"])
                elif e.get("pwad", -99.0) != -99.0:
                    inc = float(e["pwad"])
                else:
                    inc = 0.0
                dry_cum += inc
                dry_inc = float(inc)

            fresh_inc = -99.0
            if e["chfpw"] != -99.0:
                prev = float(fresh_cum)
                fresh_cum = float(e["chfpw"])
                fresh_inc = float(fresh_cum - prev)
            else:
                inc = 0.0 if e["hfpow"] == -99.0 else float(e["hfpow"])
                fresh_cum += inc
                fresh_inc = float(inc) if e["hfpow"] != -99.0 else -99.0

            if prev_dry_cum is None and dry_inc != -99.0 and dry_inc < 0:
                dry_inc = float(dry_cum)
            if prev_fresh_cum is None and fresh_inc != -99.0 and fresh_inc < 0:
                fresh_inc = float(fresh_cum)
            prev_dry_cum = float(dry_cum)
            prev_fresh_cum = float(fresh_cum)

            out_list.append(
                {
                    "hno": idx,
                    "date": int(e["date"]),
                    "dry_cum": float(dry_cum)
                    if e["chpdt"] != -99.0 or e.get("hpodw", -99.0) != -99.0 or e.get("pwad", -99.0) != -99.0
                    else -99.0,
                    "dry_inc": float(dry_inc)
                    if e["chpdt"] != -99.0 or e.get("hpodw", -99.0) != -99.0 or e.get("pwad", -99.0) != -99.0
                    else -99.0,
                    "fresh_cum": float(fresh_cum) if e["chfpw"] != -99.0 or e["hfpow"] != -99.0 else -99.0,
                    "fresh_inc": float(fresh_inc) if e["chfpw"] != -99.0 or e["hfpow"] != -99.0 else -99.0,
                }
            )
        out[tn] = out_list

    return out


def _read_tmt_process_points(tmt_path):
    if not tmt_path or not os.path.exists(tmt_path):
        return {}

    header = None
    rows = []
    with open(tmt_path, "r") as f:
        for line in f:
            s = line.rstrip("\n")
            if not s.strip():
                continue
            if s.lstrip().startswith("@TRNO"):
                header = s.split()
                continue
            if header is None:
                continue
            if s.startswith("*") or s.lstrip().startswith("@"):
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            if len(parts) < len(header):
                parts += ["-99"] * (len(header) - len(parts))
            row = dict(zip(header, parts[: len(header)]))
            rows.append(row)

    def _as_int(v, default=-99):
        try:
            return int(float(v))
        except Exception:
            return default

    def _as_float(v, default=-99.0):
        try:
            return float(v)
        except Exception:
            return default

    points_by_tn = {}
    for r in rows:
        tn = _as_int(r.get("@TRNO"), default=-99)
        date = _as_int(r.get("DATE"), default=-99)
        if tn <= 0 or date <= 0:
            continue

        lnsd = _as_float(r.get("L#SD"), default=-99.0)
        laid = _as_float(r.get("LAID"), default=-99.0)
        lwad = _as_float(r.get("LWAD"), default=-99.0)
        swad = _as_float(r.get("SWAD"), default=-99.0)

        if lnsd == -99.0 and laid == -99.0 and lwad == -99.0 and swad == -99.0:
            continue

        points_by_tn.setdefault(tn, []).append(
            {
                "date": int(date),
                "lnsd": float(lnsd),
                "laid": float(laid),
                "lwad": float(lwad),
                "swad": float(swad),
            }
        )

    out = {}
    for tn, pts in points_by_tn.items():
        out[tn] = sorted(pts, key=lambda x: x["date"])
    return out


def _read_evaluate_out(path):
    rows = []
    header = None

    with open(path, "r") as f:
        for line in f:
            s = line.rstrip("\n")
            if not s.strip():
                continue

            stripped = s.lstrip()
            if stripped.startswith("@RUN"):
                header = stripped.split()
                continue

            if header is None:
                continue
            if stripped.startswith("*") or stripped.startswith("@"): 
                continue
            if not stripped[:1].isdigit():
                continue

            parts = stripped.split()
            if len(parts) < len(header):
                parts += ["-99"] * (len(header) - len(parts))
            rows.append(dict(zip(header, parts[: len(header)])))

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    for c in df.columns:
        if c in {"EXCODE", "CR"}:
            continue
        as_num = pd.to_numeric(df[c], errors="coerce")
        if as_num.notna().sum() >= max(1, int(0.8 * len(df))):
            df[c] = as_num.fillna(-99)

    return df

def _first_batch_filex_path(batch_file):
    if not os.path.exists(batch_file):
        return None
    with open(batch_file, "r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("$") or s.startswith("@") or s.startswith("!"):
                continue
            return s.split()[0]
    return None


def _evaluate_out_path_from_batch(batch_file, fallback=OUT_FILE):
    filex = _first_batch_filex_path(batch_file)
    if not filex:
        return fallback
    candidates = []
    if os.path.isabs(filex):
        candidates.append(filex)
    if batch_file:
        batch_dir = os.path.dirname(os.path.abspath(batch_file))
        candidates.append(os.path.join(batch_dir, filex))
    resolved = _resolve_filex_path(filex)
    if resolved:
        candidates.append(resolved)
    candidates.append(os.path.join(WORKSPACE, filex))
    for p in candidates:
        if not p:
            continue
        if not os.path.exists(p):
            continue
        eval_path = os.path.join(os.path.dirname(os.path.abspath(p)), "Evaluate.OUT")
        if os.path.exists(eval_path):
            return eval_path
    return fallback


def _dssat_root_from_workspace():
    return os.path.abspath(os.path.join(WORKSPACE, os.pardir, os.pardir))


def _try_read_evaluate_out(evaluate_out_path):
    candidates = [
        evaluate_out_path,
        os.path.join(_dssat_root_from_workspace(), "Evaluate.OUT"),
        os.path.join(WORKSPACE, "Evaluate.OUT"),
    ]
    tried = []
    seen = set()
    for p in candidates:
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        tried.append(ap)
        if not os.path.exists(ap):
            continue
        try:
            return _read_evaluate_out(ap)
        except Exception:
            continue
    raise FileNotFoundError(f"Evaluate.OUT not found/readable. Tried: {tried}")


_FILEA_DATE_TO_EVALUATE = {
    "EDAT": "EDAPM",
    "ADAT": "ADAPM",
    "PD1T": "PD1PM",
    "PDFT": "PDFPM",
    "MDAT": "MDAPM",
    "R8AT": "R8APM",
}

_FILEA_VALUE_TO_EVALUATE = {
    "HWAM": "HWAMM",
    "PWAM": "PWAMM",
    "CWAAM": "CWAAM",
    "CWAM": "CWAMM",
    "BWAM": "BWAMM",
    "H#AM": "H#AMM",
    "HWUM": "HWUMM",
    "H#UM": "H#UMM",
    "HIAM": "HIAMM",
    "THAM": "THAMM",
    "LAIX": "LAIXM",
    "L#SM": "L#SMM",
    "CHTA": "CHTAM",
    "CNAA": "CNAAM",
    "CNAM": "CNAMM",
    "SNAM": "SNAMM",
    "GNAM": "GNAMM",
    "GN%M": "GN%MM",
    "GL%M": "GL%MM",
}


def _read_filea_rows(filea_path):
    """Read the treatment-level measured values from a DSSAT FileA."""
    header = None
    rows = {}
    with open(filea_path, "r") as handle:
        for raw in handle:
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.upper().startswith("@TRNO"):
                header = [token.lstrip("@").upper() for token in stripped.split()]
                continue
            if header is None or stripped.startswith(("*", "!", "@")):
                continue
            parts = stripped.split()
            if len(parts) < len(header):
                parts += ["-99"] * (len(header) - len(parts))
            record = dict(zip(header, parts[:len(header)]))
            try:
                treatment = int(float(record["TRNO"]))
            except (KeyError, TypeError, ValueError):
                continue
            rows[treatment] = record
    if header is None:
        raise ValueError(f"FileA is missing an @TRNO header: {filea_path}")
    return rows


def _yyddd_day_difference(start_code, end_code):
    """Return elapsed days for DSSAT YYDDD/YYYYDDD date codes."""
    try:
        start = str(int(float(start_code)))
        end = str(int(float(end_code)))
    except (TypeError, ValueError):
        return -99.0
    if start.startswith("-") or end.startswith("-"):
        return -99.0
    try:
        start_fmt = "%Y%j" if len(start) == 7 else "%y%j"
        end_fmt = "%Y%j" if len(end) == 7 else "%y%j"
        start_dt = datetime.strptime(start.zfill(7 if len(start) == 7 else 5), start_fmt)
        end_dt = datetime.strptime(end.zfill(7 if len(end) == 7 else 5), end_fmt)
    except ValueError:
        return -99.0
    return float((end_dt - start_dt).days)


def _build_evaluate_observations_from_filea(batch_entries):
    """Build Evaluate-style measured columns solely from versioned FileA files.

    The returned frame contains no simulated evidence from a previous model
    run.  Candidate simulations are still read later from newly generated
    tagged ``PestEval.OUT``/``PestJoint.OUT`` files.
    """
    filea_cache = {}
    output_rows = []
    for entry in batch_entries:
        filex = entry.get("filex")
        filex_path = _resolve_filex_path(filex) or (
            filex if filex and os.path.isabs(filex) else None
        )
        if not filex_path or not os.path.isfile(filex_path):
            raise FileNotFoundError(f"cannot resolve FileX for batch entry: {filex!r}")
        suffix = Path(filex_path).suffix
        filea_suffix = f"{suffix[:-1]}A" if suffix else ".TMA"
        filea_path = str(Path(filex_path).with_suffix(filea_suffix))
        if not os.path.isfile(filea_path):
            raise FileNotFoundError(f"versioned FileA not found for {filex_path}: {filea_path}")
        if filea_path not in filea_cache:
            filea_cache[filea_path] = _read_filea_rows(filea_path)

        treatment = int(entry.get("tn", -99))
        measured = filea_cache[filea_path].get(treatment)
        if measured is None:
            raise ValueError(f"FileA {filea_path} has no row for treatment {treatment}")

        row = {"@RUN": int(entry["run"]), "TN": treatment}
        planting_date = measured.get("PDAT", -99)
        for source, target in _FILEA_DATE_TO_EVALUATE.items():
            row[target] = _yyddd_day_difference(planting_date, measured.get(source, -99))
        for source, target in _FILEA_VALUE_TO_EVALUATE.items():
            try:
                row[target] = float(measured.get(source, -99))
            except (TypeError, ValueError):
                row[target] = -99.0
        output_rows.append(row)
    return pd.DataFrame(output_rows)

def _infer_cultivar_from_filex(filex_path):
    if not filex_path or not os.path.exists(filex_path):
        return None
    with open(filex_path, "r") as f:
        lines = f.readlines()

    def _section_idx(tag):
        for i, line in enumerate(lines):
            if line.strip().upper().startswith(tag):
                return i
        return -1

    trt_idx = _section_idx("*TREATMENTS")
    cul_idx = _section_idx("*CULTIVARS")
    if trt_idx == -1 or cul_idx == -1:
        return None

    cu_level = None
    for i in range(trt_idx + 1, len(lines)):
        s = lines[i].rstrip("\n")
        if not s.strip():
            continue
        if s.startswith("*"):
            break
        if s.startswith("@"):
            continue

        parts = s.split()
        if len(parts) < 4 + 13:
            continue

        factor_tokens = parts[-13:]
        try:
            factors = [int(t) for t in factor_tokens]
        except Exception:
            continue

        cu_level = factors[0]
        break

    if cu_level is None:
        return None

    for i in range(cul_idx + 1, len(lines)):
        s = lines[i].strip("\n")
        if not s.strip():
            continue
        if s.startswith("*"):
            break
        if s.startswith("@"):
            continue
        parts = s.split()
        if len(parts) < 4:
            continue
        try:
            c = int(parts[0])
        except Exception:
            continue
        if c == cu_level:
            return parts[2]

    return None


def _resolve_filex_path(filex):
    if not filex:
        return None
    p = str(filex).strip()
    if not p:
        return None
    if os.path.exists(p):
        return os.path.abspath(p)
    if os.path.isabs(p):
        return None
    candidates = [
        Path(USER_INPUT_DIR) / p if USER_INPUT_DIR else Path("__no_user_input__"),
        PROJECT_ROOT / "data" / "raw" / "experiments" / p,
        Path(WORKSPACE) / p,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())
    return None


def _infer_soil_id_from_filex(filex_path):
    if not filex_path or not os.path.exists(filex_path):
        return None
    header = None
    soil_idx = None
    in_fields = False
    with open(filex_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.rstrip("\n")
            u = s.strip().upper()
            if not u:
                continue
            if u.startswith("*FIELDS"):
                in_fields = True
                header = None
                soil_idx = None
                continue
            if in_fields and u.startswith("*") and (not u.startswith("*FIELDS")):
                break
            if not in_fields:
                continue
            if s.lstrip().startswith("@"):
                header = s.split()
                try:
                    soil_idx = header.index("ID_SOIL")
                except ValueError:
                    soil_idx = None
                continue
            if s.lstrip().startswith("!"):
                continue
            if header is None or soil_idx is None:
                continue
            parts = s.split()
            if len(parts) <= soil_idx:
                continue
            sid = str(parts[soil_idx]).strip()
            return sid or None
    return None


def _soil_source_path():
    if USER_INPUT_DIR:
        user_soil = Path(USER_INPUT_DIR) / "SOIL.SOL"
        if user_soil.is_file():
            return str(user_soil)
    return SOIL_BASE_FILE if os.path.exists(SOIL_BASE_FILE) else SOIL_FILE


def _read_soil_layers(soil_path, soil_id):
    if not soil_path or not os.path.exists(soil_path) or not soil_id:
        return []

    sec_start = None
    with open(soil_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    for i, s in enumerate(lines):
        if s.startswith("*"):
            sid = s[1:].strip().split()[0] if s[1:].strip() else ""
            if sid.upper() == str(soil_id).strip().upper():
                sec_start = i
                break
    if sec_start is None:
        return []

    sec_end = len(lines)
    for j in range(sec_start + 1, len(lines)):
        if lines[j].startswith("*"):
            sec_end = j
            break

    header = None
    col_idx = {}
    layer_lines = []
    for j in range(sec_start, sec_end):
        s = lines[j].rstrip("\n")
        u = s.strip().upper()
        if not u:
            continue
        if u.startswith("@") and ("SLLL" in u and "SDUL" in u and "SSAT" in u):
            header = s.split()
            if header and header[0].startswith("@"):  # DSSAT header has a leading '@'
                header = header[1:]
            col_idx = {k: header.index(k) for k in ["SLLL", "SDUL", "SSAT", "SBDM"] if k in header}
            continue
        if header is None:
            continue
        if u.startswith("@") or u.startswith("*"):
            break
        if s.lstrip().startswith("!"):
            continue
        parts = s.split()
        if not parts:
            continue
        layer_lines.append(parts)

    layers = []
    for parts in layer_lines:
        rec = {}
        for k, idx in col_idx.items():
            if idx < len(parts):
                try:
                    rec[k] = float(parts[idx])
                except Exception:
                    rec[k] = None
        layers.append(rec)
    return layers


def _read_initial_sh2o(filex_path):
    if not filex_path or not os.path.exists(filex_path):
        return []

    with open(filex_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    ic_start = None
    ic_end = None
    for i, line in enumerate(lines):
        u = line.strip().upper()
        if u.startswith("*INITIAL CONDITIONS"):
            ic_start = i
            continue
        if ic_start is not None and u.startswith("*") and (not u.startswith("*INITIAL CONDITIONS")):
            ic_end = i
            break
    if ic_start is None:
        return []
    if ic_end is None:
        ic_end = len(lines)

    sh2o_vals = []
    header = None
    sh2o_idx = None
    for j in range(ic_start + 1, ic_end):
        s = lines[j].rstrip("\n")
        u = s.strip().upper()
        if not u:
            continue
        if s.lstrip().startswith("@C") and ("ICBL" in u) and ("SH2O" in u):
            header = s.split()
            try:
                sh2o_idx = header.index("SH2O")
            except ValueError:
                sh2o_idx = None
            continue
        if header is None or sh2o_idx is None:
            continue
        if u.startswith("@") or u.startswith("*"):
            break
        parts = s.split()
        if len(parts) <= sh2o_idx:
            continue
        try:
            v = float(parts[sh2o_idx])
        except Exception:
            continue
        if v == -99.0:
            continue
        sh2o_vals.append(max(0.01, min(0.80, float(v))))
    return sh2o_vals


def _build_soil_sbdm_params(soil_layers, delta=None, frac=None):
    params = []
    d = abs(float(delta)) if delta is not None else None
    f = abs(float(frac)) if frac is not None else None
    for i, layer in enumerate(soil_layers, start=1):
        init = layer.get("SBDM")
        if init is None:
            continue
        init_v = float(init)
        if f is not None:
            lo0 = init_v * (1.0 - f)
            hi0 = init_v * (1.0 + f)
        else:
            dd = float(d) if d is not None else 0.0
            lo0 = init_v - dd
            hi0 = init_v + dd
        lb = max(0.5, lo0)
        ub = min(2.2, hi0)
        if lb == ub:
            ub = min(2.2, lb + 1e-6)
        params.append(
            {
                "name": f"SOIL_SBDM_{i:02d}",
                "init": max(lb, min(ub, init_v)),
                "lower": lb,
                "upper": ub,
                "idx": None,
                "status": "none",
                "pargp": "soil",
            }
        )
    return params


def _build_ic_sh2o_params(sh2o_vals, soil_layers, delta=None, frac=None):
    params = []
    d = abs(float(delta)) if delta is not None else None
    f = abs(float(frac)) if frac is not None else None
    for i, sh2o in enumerate(sh2o_vals, start=1):
        lo = 0.01
        hi = 0.80
        if soil_layers and (i - 1) < len(soil_layers):
            slll = soil_layers[i - 1].get("SLLL")
            ssat = soil_layers[i - 1].get("SSAT")
            if slll is not None:
                lo = max(lo, float(slll))
            if ssat is not None:
                hi = min(hi, float(ssat))
        init = max(lo, min(hi, float(sh2o)))
        if f is not None:
            lo0 = init * (1.0 - f)
            hi0 = init * (1.0 + f)
        else:
            dd = float(d) if d is not None else 0.0
            lo0 = init - dd
            hi0 = init + dd
        lb = max(lo, lo0)
        ub = min(hi, hi0)
        if lb == ub:
            ub = min(hi, lb + 1e-6)
        params.append(
            {
                "name": f"IC_SH2O_{i:02d}",
                "init": max(lb, min(ub, init)),
                "lower": lb,
                "upper": ub,
                "idx": None,
                "status": "none",
                "pargp": "initial_conditions",
            }
        )
    return params

def parse_cul_params(target_cultivar, allowed_params=None):
    with open(CUL_BASE_FILE, 'r') as f:
        lines = f.readlines()

    header_idx = -1
    calib_idx = -1
    min_idx = -1
    max_idx = -1
    cultivar_idx = -1

    for i, line in enumerate(lines):
        if line.startswith("@VAR#"):
            header_idx = i
        elif line.startswith("!Calibration"):
            calib_idx = i
        elif "MINIMA" in line:
            min_idx = i
        elif "MAXIMA" in line:
            max_idx = i
        elif target_cultivar and line.startswith(target_cultivar):
            cultivar_idx = i

    if any(idx == -1 for idx in [header_idx, calib_idx, min_idx, max_idx, cultivar_idx]):
        raise ValueError("Could not find all required sections in TMGRO048.CUL.base")

    headers = lines[header_idx].split()
    param_names = headers[4:]

    calib_flags = lines[calib_idx].split()[1:]

    number_re = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")

    def _last_n_numbers(line, n):
        matches = [m.group(0) for m in number_re.finditer(line)]
        if len(matches) < n:
            raise ValueError(f"Not enough numeric tokens in line for {n} params")
        return matches[-n:]

    n_params = len(param_names)
    min_vals = _last_n_numbers(lines[min_idx], n_params)
    max_vals = _last_n_numbers(lines[max_idx], n_params)
    init_vals = _last_n_numbers(lines[cultivar_idx], n_params)

    params = []
    for i, name in enumerate(param_names):
        if i >= len(calib_flags):
            continue
        if allowed_params is not None and name not in allowed_params:
            continue
        flag = calib_flags[i]
        if flag not in ['P', 'G']:
            continue
        p_min = float(min_vals[i])
        p_max = float(max_vals[i])
        p_init = float(init_vals[i])
        status = "none"
        if p_min == p_max:
            status = "fixed"
        params.append({
            "name": name,
            "init": p_init,
            "lower": p_min,
            "upper": p_max,
            "idx": i,
            "status": status,
            "pargp": "cultivar",
        })

    return params

def create_param_csv_tpl(params, param_csv_tpl_path):
    with open(param_csv_tpl_path, 'w') as f:
        f.write("ptf ~\n")
        f.write("name,value\n")
        for p in params:
            f.write(f"{p['name']},~ {p['name']} ~\n")

def create_param_csv(params, param_csv_path):
    with open(param_csv_path, "w") as f:
        f.write("name,value\n")
        for p in params:
            f.write(f"{p['name']},{p['init']}\n")

def create_ins_and_pst(
    params,
    prefix,
    noptmax,
    ies_num_reals,
    random_seed=20260715,
    obs_bases=None,
    critical_obs=None,
    model_out_path=OUT_FILE,
    group_sigmas=None,
    evaluate_out_path=OUT_FILE,
    df_override=None,
    model_cmd_extra=None,
    out_dir=None,
    weight_scheme="legacy",
    apply_normalization=False,
    apply_log_transform=False,
    apply_pwtadj1=False,
    cv_based_sigma=False,
    noptmax0_sims=None,
    observation_policies=None,
):
    out_dir = out_dir or WORKSPACE
    os.makedirs(out_dir, exist_ok=True)
    if df_override is not None:
        df = df_override.copy()
    else:
        try:
            df = _try_read_evaluate_out(evaluate_out_path)
        except Exception as e:
            print(f"Warning: Could not read model output file: {e}.")
            return

    param_csv_tpl_path = os.path.join(out_dir, f"{prefix}_params.csv.tpl")
    param_csv_path = os.path.join(out_dir, f"{prefix}_params.csv")
    ins_path = os.path.join(out_dir, f"{prefix}_{os.path.basename(model_out_path)}.ins")
    pst_path = os.path.join(out_dir, f"{prefix}.pst")

    obs_cols = [c for c in df.columns if isinstance(c, str) and c.endswith('M')]
    sim_cols = [c[:-1] + 'S' for c in obs_cols]

    if obs_bases is not None:
        filtered = []
        for o, s in zip(obs_cols, sim_cols):
            if o[:-1] in obs_bases:
                filtered.append((o, s))
        obs_cols = [o for o, _ in filtered]
        sim_cols = [s for _, s in filtered]

    critical_obs = set(critical_obs or [])

    def get_pest_offset(col_idx):
        return 0

    obs_data = []
    model_out_norm = os.path.normcase(os.path.abspath(model_out_path))
    is_tagged_output = model_out_norm in {
        os.path.normcase(os.path.abspath(PEST_EVAL_FILE)),
        os.path.normcase(os.path.abspath(PEST_GROW_FILE)),
        os.path.normcase(os.path.abspath(PEST_JOINT_FILE)),
        os.path.normcase(os.path.abspath(PEST_HARVEST_FILE)),
        os.path.normcase(os.path.abspath(PEST_TMTGROW_FILE)),
    }
    if is_tagged_output:
        ins_lines = ["pif @"]
    else:
        ins_lines = ["pif @", "l3"]

    col_names = df.columns.tolist()
    for _, row in df.iterrows():
        if "@RUN" in row.index:
            run_no = int(row['@RUN'])
        else:
            run_no = int(row["RUN"])

        season_prefix = ""
        if "season" in row.index and pd.notna(row.get("season")):
            season_prefix = re.sub(r"[^A-Za-z0-9]", "", str(row["season"])).upper()

        suffix = ""
        if "HNO" in row.index:
            try:
                suffix = f"_H{int(row['HNO'])}"
            except Exception:
                suffix = ""
        elif "DATE" in row.index:
            try:
                suffix = f"_D{int(row['DATE'])}"
            except Exception:
                suffix = ""

        current_ins_line = "l1 "

        valid_obs = []
        for obs_col, sim_col in zip(obs_cols, sim_cols):
            val = row[obs_col]
            if val != -99 or obs_col in critical_obs:
                valid_obs.append((obs_col, sim_col, val))

        if not valid_obs:
            ins_lines.append(current_ins_line)
            continue

        if not is_tagged_output:
            valid_obs.sort(key=lambda x: col_names.index(x[1]))

        last_idx = -1
        for obs_col, sim_col, val in valid_obs:
            name_prefix = f"{season_prefix}_" if season_prefix else ""
            obs_name = f"{name_prefix}{sim_col}_R{run_no}{suffix}"
            if is_tagged_output:
                current_ins_line += f"@{sim_col}@ w !{obs_name}! "
            else:
                col_idx = col_names.index(sim_col)
                target_idx = col_idx + get_pest_offset(col_idx)
                skips = target_idx - last_idx - 1
                if skips < 0:
                    skips = 0
                current_ins_line += "w " * skips
                current_ins_line += f"!{obs_name}! "

            base_group = f"{obs_col}{suffix}" if suffix else obs_col
            obgnme = f"{name_prefix}{base_group}"
            sigma = _resolve_sigma(group_sigmas, base_group, obs_col)
            if val == -99:
                weight = 0.0
            else:
                weight = 1.0 if sigma is None else weight_from_sigma(sigma)

            obs_data.append({
                "obsnme": obs_name,
                "obsval": val if val != -99 else 0,
                "raw_obsval": val,
                "weight": weight,
                "obgnme": obgnme,
                "sigma": sigma,
                "base_weight": weight,
                "group_multiplier": 1.0,
                "transform": "raw",
                "sim_token": sim_col,
                "model_output_file": os.path.basename(model_out_path),
                "weight_policy_id": WEIGHT_POLICY_ID,
            })
            if not is_tagged_output:
                last_idx = target_idx

        ins_lines.append(current_ins_line)

    with open(ins_path, 'w') as f:
        f.write("\n".join(ins_lines))

    create_param_csv_tpl(params, param_csv_tpl_path)
    create_param_csv(params, param_csv_path)

    par_df = pd.DataFrame([{
        "parnme": p['name'],
        "parval1": p['init'],
        "parlbnd": p['lower'],
        "parubnd": p['upper'],
        "pargp": p.get('pargp', 'cultivar'),
        "scale": 1.0,
        "offset": 0.0,
        "partrans": p['status']
    } for p in params])

    obs_df = pd.DataFrame(obs_data)

    if weight_scheme == "improved" and not obs_df.empty:
        noptmax0_df = None
        if noptmax0_sims is not None and os.path.exists(noptmax0_sims):
            try:
                noptmax0_df = pd.read_csv(noptmax0_sims)
            except Exception:
                pass
        sim_baseline_df = noptmax0_df

        obs_df = pd.DataFrame(build_observation_weights(
            obs_data,
            df_override=df_override,
            sim_baseline=sim_baseline_df,
            apply_normalization=apply_normalization,
            apply_log_transform=apply_log_transform,
            apply_pwtadj1=apply_pwtadj1,
            cv_based_sigma=cv_based_sigma,
        ))

    obs_df, model_cmd_extra = _apply_policy_and_prepare_runner(
        obs_df, observation_policies, out_dir, prefix, model_cmd_extra
    )

    _write_weight_audit(obs_df, out_dir, prefix)

    pst = pyemu.Pst.from_par_obs_names(par_df.parnme, obs_df.obsnme if not obs_df.empty else [])

    par_df_indexed = par_df.set_index('parnme')
    for col in ['parval1', 'parlbnd', 'parubnd', 'pargp', 'partrans']:
        pst.parameter_data.loc[par_df.parnme, col] = par_df_indexed[col].values

    fixed_pars = par_df[par_df['parlbnd'] == par_df['parubnd']]['parnme']
    if not fixed_pars.empty:
        pst.parameter_data.loc[fixed_pars, 'partrans'] = 'fixed'

    zero_pars = par_df[(par_df['parval1'] == 0) & (par_df['parlbnd'] != par_df['parubnd'])]['parnme']
    if not zero_pars.empty:
        pst.parameter_data.loc[zero_pars, 'partrans'] = 'none'

    if not obs_df.empty:
        pst.observation_data.loc[obs_df.obsnme, 'obsval'] = obs_df.set_index('obsnme')['obsval']
        pst.observation_data.loc[obs_df.obsnme, 'obgnme'] = obs_df.set_index('obsnme')['obgnme']
        pst.observation_data.loc[obs_df.obsnme, 'weight'] = obs_df.set_index('obsnme')['weight']

    pst.control_data.noptmax = noptmax
    pst.pestpp_options["ies_num_reals"] = ies_num_reals
    pst.pestpp_options["rand_seed"] = int(random_seed)
    pst.pestpp_options["ies_bad_phi_sigma"] = 2.0
    pst.pestpp_options["overdue_giveup_fac"] = 4.0
    pst.pestpp_options["max_run_fail"] = 3
    pst.pestpp_options["par_sigma_range"] = 6

    run_dssat_path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_dssat.py"))
    cmd = f"python \"{run_dssat_path}\" --param-csv {os.path.basename(param_csv_path)}"
    if model_cmd_extra:
        cmd = f"{cmd} {str(model_cmd_extra).strip()}"
    pst.model_command = [cmd]
    pst.model_input_data = pd.DataFrame({"pest_file": [os.path.basename(param_csv_tpl_path)], "model_file": [os.path.basename(param_csv_path)]})
    pst.model_output_data = pd.DataFrame({"pest_file": [os.path.basename(ins_path)], "model_file": [os.path.basename(model_out_path)]})

    pst.write(pst_path)
    print(f"PST file written to {pst_path}")


def _is_tagged_output(model_out_path):
    model_out_norm = os.path.normcase(os.path.abspath(model_out_path))
    return model_out_norm in {
        os.path.normcase(os.path.abspath(PEST_EVAL_FILE)),
        os.path.normcase(os.path.abspath(PEST_GROW_FILE)),
        os.path.normcase(os.path.abspath(PEST_JOINT_FILE)),
        os.path.normcase(os.path.abspath(PEST_HARVEST_FILE)),
        os.path.normcase(os.path.abspath(PEST_TMTGROW_FILE)),
    }


def _build_ins_and_obs(df, obs_bases, critical_obs, model_out_path, group_sigmas):
    obs_cols = [c for c in df.columns if isinstance(c, str) and c.endswith('M')]
    sim_cols = [c[:-1] + 'S' for c in obs_cols]

    if obs_bases is not None:
        filtered = []
        for o, s in zip(obs_cols, sim_cols):
            if o[:-1] in obs_bases:
                filtered.append((o, s))
        obs_cols = [o for o, _ in filtered]
        sim_cols = [s for _, s in filtered]

    critical_obs = set(critical_obs or [])

    def get_pest_offset(col_idx):
        return 0

    obs_data = []
    is_tagged_output = _is_tagged_output(model_out_path)
    ins_lines = ["pif @"] if is_tagged_output else ["pif @", "l3"]

    col_names = df.columns.tolist()
    for _, row in df.iterrows():
        if "@RUN" in row.index:
            run_no = int(row['@RUN'])
        else:
            run_no = int(row["RUN"])

        season_prefix = ""
        if "season" in row.index and pd.notna(row.get("season")):
            season_prefix = re.sub(r"[^A-Za-z0-9]", "", str(row["season"])).upper()

        suffix = ""
        if "HNO" in row.index:
            try:
                suffix = f"_H{int(row['HNO'])}"
            except Exception:
                suffix = ""
        elif "DATE" in row.index:
            try:
                suffix = f"_D{int(row['DATE'])}"
            except Exception:
                suffix = ""

        current_ins_line = "l1 "

        valid_obs = []
        for obs_col, sim_col in zip(obs_cols, sim_cols):
            val = row[obs_col]
            if val != -99 or obs_col in critical_obs:
                valid_obs.append((obs_col, sim_col, val))

        if not valid_obs:
            ins_lines.append(current_ins_line)
            continue

        if not is_tagged_output:
            valid_obs.sort(key=lambda x: col_names.index(x[1]))

        last_idx = -1
        for obs_col, sim_col, val in valid_obs:
            name_prefix = f"{season_prefix}_" if season_prefix else ""
            obs_name = f"{name_prefix}{sim_col}_R{run_no}{suffix}"
            if is_tagged_output:
                current_ins_line += f"@{sim_col}@ w !{obs_name}! "
            else:
                col_idx = col_names.index(sim_col)
                target_idx = col_idx + get_pest_offset(col_idx)
                skips = target_idx - last_idx - 1
                if skips < 0:
                    skips = 0
                current_ins_line += "w " * skips
                current_ins_line += f"!{obs_name}! "

            base_group = f"{obs_col}{suffix}" if suffix else obs_col
            obgnme = f"{name_prefix}{base_group}"
            sigma = _resolve_sigma(group_sigmas, base_group, obs_col)
            if val == -99:
                weight = 0.0
            else:
                weight = 1.0 if sigma is None else weight_from_sigma(sigma)

            obs_data.append(
                {
                    "obsnme": obs_name,
                    "obsval": val if val != -99 else 0,
                    "raw_obsval": val,
                    "weight": weight,
                    "obgnme": obgnme,
                    "sigma": sigma,
                    "base_weight": weight,
                    "group_multiplier": 1.0,
                    "transform": "raw",
                    "sim_token": sim_col,
                    "model_output_file": os.path.basename(model_out_path),
                    "weight_policy_id": WEIGHT_POLICY_ID,
                }
            )
            if not is_tagged_output:
                last_idx = target_idx

        ins_lines.append(current_ins_line)

    return obs_data, ins_lines


def _populate_pst_from_par_obs(pst, par_df, obs_df):
    par_df_indexed = par_df.set_index('parnme')
    for col in ['parval1', 'parlbnd', 'parubnd', 'pargp', 'partrans']:
        pst.parameter_data.loc[par_df.parnme, col] = par_df_indexed[col].values

    fixed_pars = par_df[par_df['parlbnd'] == par_df['parubnd']]['parnme']
    if not fixed_pars.empty:
        pst.parameter_data.loc[fixed_pars, 'partrans'] = 'fixed'

    zero_pars = par_df[(par_df['parval1'] == 0) & (par_df['parlbnd'] != par_df['parubnd'])]['parnme']
    if not zero_pars.empty:
        pst.parameter_data.loc[zero_pars, 'partrans'] = 'none'

    if not obs_df.empty:
        pst.observation_data.loc[obs_df.obsnme, 'obsval'] = obs_df.set_index('obsnme')['obsval']
        pst.observation_data.loc[obs_df.obsnme, 'obgnme'] = obs_df.set_index('obsnme')['obgnme']
        pst.observation_data.loc[obs_df.obsnme, 'weight'] = obs_df.set_index('obsnme')['weight']


def create_ins_and_pst_multi(
    params,
    prefix,
    noptmax,
    ies_num_reals,
    outputs,
    random_seed=20260715,
    evaluate_out_path=OUT_FILE,
    model_cmd_extra=None,
    out_dir=None,
    weight_scheme="legacy",
    apply_normalization=False,
    apply_log_transform=False,
    apply_pwtadj1=False,
    cv_based_sigma=False,
    noptmax0_sims=None,
    observation_policies=None,
):
    out_dir = out_dir or WORKSPACE
    os.makedirs(out_dir, exist_ok=True)
    eval_df = None
    if any(out.get("df") is None for out in outputs):
        try:
            eval_df = _try_read_evaluate_out(evaluate_out_path)
        except Exception as e:
            raise FileNotFoundError(
                "an output definition lacks an observation dataframe and no "
                f"Evaluate.OUT is available: {e}"
            ) from e

    param_csv_tpl_path = os.path.join(out_dir, f"{prefix}_params.csv.tpl")
    param_csv_path = os.path.join(out_dir, f"{prefix}_params.csv")
    pst_path = os.path.join(out_dir, f"{prefix}.pst")

    create_param_csv_tpl(params, param_csv_tpl_path)
    create_param_csv(params, param_csv_path)

    par_df = pd.DataFrame([
        {
            "parnme": p['name'],
            "parval1": p['init'],
            "parlbnd": p['lower'],
            "parubnd": p['upper'],
            "pargp": p.get('pargp', 'cultivar'),
            "scale": 1.0,
            "offset": 0.0,
            "partrans": p['status'],
        }
        for p in params
    ])

    obs_data_all = []
    model_output_rows = []

    for out in outputs:
        model_out_path = out["model_out_path"]
        df = out.get("df")
        if df is None:
            df = eval_df

        obs_data, ins_lines = _build_ins_and_obs(
            df=df,
            obs_bases=out.get("obs_bases"),
            critical_obs=out.get("critical_obs"),
            model_out_path=model_out_path,
            group_sigmas=out.get("group_sigmas"),
        )
        obs_data_all.extend(obs_data)

        ins_path = os.path.join(out_dir, f"{prefix}_{os.path.basename(model_out_path)}.ins")
        with open(ins_path, 'w') as f:
            f.write("\n".join(ins_lines))

        model_output_rows.append(
            {"pest_file": os.path.basename(ins_path), "model_file": os.path.basename(model_out_path)}
        )

    obs_df = pd.DataFrame(obs_data_all)

    if weight_scheme == "improved" and not obs_df.empty:
        noptmax0_df = None
        if noptmax0_sims is not None and os.path.exists(noptmax0_sims):
            try:
                noptmax0_df = pd.read_csv(noptmax0_sims)
            except Exception:
                pass
        sim_baseline_df = noptmax0_df

        obs_df = pd.DataFrame(build_observation_weights(
            obs_data_all,
            df_override=None,
            sim_baseline=sim_baseline_df,
            apply_normalization=apply_normalization,
            apply_log_transform=apply_log_transform,
            apply_pwtadj1=apply_pwtadj1,
            cv_based_sigma=cv_based_sigma,
        ))

    obs_df, model_cmd_extra = _apply_policy_and_prepare_runner(
        obs_df, observation_policies, out_dir, prefix, model_cmd_extra
    )

    _write_weight_audit(obs_df, out_dir, prefix)

    pst = pyemu.Pst.from_par_obs_names(par_df.parnme, obs_df.obsnme if not obs_df.empty else [])
    _populate_pst_from_par_obs(pst, par_df, obs_df)

    pst.control_data.noptmax = noptmax
    pst.pestpp_options["ies_num_reals"] = ies_num_reals
    pst.pestpp_options["rand_seed"] = int(random_seed)
    pst.pestpp_options["ies_bad_phi_sigma"] = 2.0
    pst.pestpp_options["overdue_giveup_fac"] = 4.0
    pst.pestpp_options["max_run_fail"] = 3
    pst.pestpp_options["par_sigma_range"] = 6

    run_dssat_path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_dssat.py"))
    cmd = f"python \"{run_dssat_path}\" --param-csv {os.path.basename(param_csv_path)}"
    if model_cmd_extra:
        cmd = f"{cmd} {str(model_cmd_extra).strip()}"
    pst.model_command = [cmd]
    pst.model_input_data = pd.DataFrame(
        {"pest_file": [os.path.basename(param_csv_tpl_path)], "model_file": [os.path.basename(param_csv_path)]}
    )
    pst.model_output_data = pd.DataFrame(model_output_rows)

    pst.write(pst_path)
    print(f"PST file written to {pst_path}")


def _infer_pargp_for_name(name, cul_params=None, eco_params=None):
    n = str(name or "").strip().upper()
    if not n:
        return "fixed"
    if n.startswith("SOIL_"):
        return "soil"
    if n.startswith("IC_SH2O_"):
        return "initial_conditions"
    if cul_params and n in cul_params:
        return "cultivar"
    if eco_params and n in eco_params:
        return "ecotype"
    return "fixed"


def _read_cul_param_names():
    if not os.path.exists(CUL_BASE_FILE):
        return set()
    with open(CUL_BASE_FILE, "r") as f:
        for line in f:
            if line.startswith("@VAR#"):
                headers = line.split()
                return {str(h).strip().upper() for h in headers[4:]}
    return set()


def _read_eco_param_names():
    if not os.path.exists(ECO_FILE):
        return set()
    with open(ECO_FILE, "r") as f:
        for line in f:
            if line.startswith("@ECO#"):
                headers = line.split()
                return {str(h).strip().upper() for h in headers[2:]}
    return set()


def apply_fixed_params_csv(params, fixed_csv_paths):
    fixed_csv_paths = [p for p in (fixed_csv_paths or []) if p]
    if not fixed_csv_paths:
        return params

    cul_params = _read_cul_param_names()
    eco_params = _read_eco_param_names()

    fixed_map = {}
    for p in fixed_csv_paths:
        fixed_map.update(_load_init_overrides(p))

    existing = {str(p.get("name", "")).strip().upper(): p for p in (params or [])}
    for k_raw, v in fixed_map.items():
        name = str(k_raw).strip().upper()
        if not name:
            continue
        try:
            val = float(v)
        except Exception:
            continue

        if name in existing:
            p = existing[name]
            p["init"] = val
            p["lower"] = val
            p["upper"] = val
            p["status"] = "fixed"
            continue

        params.append(
            {
                "name": name,
                "init": val,
                "lower": val,
                "upper": val,
                "idx": None,
                "status": "fixed",
                "pargp": _infer_pargp_for_name(name, cul_params=cul_params, eco_params=eco_params),
            }
        )

    return params


def apply_tighten_params_csv(params, tighten_csv_paths, tighten_frac=0.05):
    tighten_csv_paths = [p for p in (tighten_csv_paths or []) if p]
    if not tighten_csv_paths:
        return params
    frac = abs(float(tighten_frac))
    if frac <= 0.0:
        return params

    tighten_map = {}
    for p in tighten_csv_paths:
        tighten_map.update(_load_init_overrides(p))

    if not tighten_map:
        return params

    existing = {str(p.get("name", "")).strip().upper(): p for p in (params or [])}
    missing = []
    for k_raw, v in tighten_map.items():
        name = str(k_raw).strip().upper()
        if not name:
            continue
        try:
            val = float(v)
        except Exception:
            continue
        if name not in existing:
            missing.append(name)
            continue

        p = existing[name]
        try:
            lb0 = float(p.get("lower"))
            ub0 = float(p.get("upper"))
        except Exception:
            continue

        if lb0 > ub0:
            lb0, ub0 = ub0, lb0
        if lb0 == ub0:
            continue

        lo = val * (1.0 - frac)
        hi = val * (1.0 + frac)
        lb = max(lb0, min(lo, hi))
        ub = min(ub0, max(lo, hi))
        if lb > ub:
            lb, ub = ub, lb

        p["init"] = max(lb, min(ub, val))
        p["lower"] = lb
        p["upper"] = ub
        p["status"] = "none" if float(lb) != float(ub) else "fixed"

    if missing:
        preview = ", ".join(missing[:12])
        print(f"Tighten CSV missing {len(missing)} parameters (first: {preview})")
    return params


def _load_init_overrides(csv_path):
    if not csv_path or not os.path.exists(csv_path):
        return {}
    df = pd.read_csv(csv_path)
    cols = [str(c) for c in df.columns]

    name_col = None
    value_col = None

    if "name" in cols and "value" in cols:
        name_col = "name"
        value_col = "value"
    elif "Value" in cols:
        value_col = "Value"
        unnamed = [c for c in cols if c.lower().startswith("unnamed")]
        if unnamed:
            name_col = unnamed[0]

    if name_col is None or value_col is None:
        if len(cols) >= 2:
            name_col, value_col = cols[0], cols[1]
        else:
            return {}

    out = {}
    for _, r in df.iterrows():
        k = str(r.get(name_col, "")).strip()
        if not k or k.lower() == "nan":
            continue
        try:
            v = float(r.get(value_col))
        except Exception:
            continue
        out[k.lower()] = v
    return out

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="tomato_full")
    parser.add_argument(
        "--design-config",
        default=None,
        help="Approved staged design JSON; required together with --stage for stage-aware calibration",
    )
    parser.add_argument(
        "--stage",
        default=None,
        help="Design stage (S1/S2/S3/S4); controls released parameters and Phi observations",
    )
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--noptmax", type=int, default=5)
    parser.add_argument("--ies-num-reals", type=int, default=50)
    parser.add_argument("--random-seed", type=int, default=20260715)
    parser.add_argument(
        "--bad-phi-sigma",
        type=float,
        default=None,
        help="Relative high-Phi screening threshold; staged runs default to disabled (1e300); use 2.0 only for D0 diagnostics",
    )
    parser.add_argument("--batch", default=os.path.join(WORKSPACE, "DSSBatch.v48"))
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Versioned user bundle containing FileX/FileA/FileT/SOIL/weather/batch inputs",
    )
    parser.add_argument("--init-from", action="append", default=None)
    parser.add_argument("--fixed-from", action="append", default=None)
    parser.add_argument("--tighten-from", action="append", default=None)
    parser.add_argument("--tighten-frac", type=float, default=0.05)
    parser.add_argument("--include-soil", action="store_true", default=False)
    parser.add_argument("--include-ic", action="store_true", default=False)
    parser.add_argument("--soil-sbdm-delta", type=float, default=None)
    parser.add_argument("--soil-sbdm-frac", type=float, default=0.03)
    parser.add_argument("--ic-sh2o-delta", type=float, default=None)
    parser.add_argument("--ic-sh2o-frac", type=float, default=0.03)
    parser.add_argument(
        "--param-review-mode",
        choices=["auto", "export", "import", "off"],
        default="auto",
    )
    parser.add_argument("--param-review-csv", default=None)
    parser.add_argument(
        "--bounds-review-mode",
        choices=["auto", "require", "off"],
        default="auto",
    )
    parser.add_argument("--bounds-review-csv", default=SENSITIVITY_PARAM_REVIEW_CSV)
    parser.add_argument("--bounds-id", default=None,
                        help="Frozen bounds ID (resolves to data/parameter_registry/bounds_frozen/{crop}/{id}.csv)")
    parser.add_argument("--bounds-crop", default=None,
                        help="Crop name for bounds-id resolution (tomato/eggplant)")
    parser.add_argument("--validate-bounds-review-csv", action="store_true", default=False)
    parser.add_argument("--pwadm-sigma0", type=float, default=250.0)
    parser.add_argument("--pwadm-cv", type=float, default=0.08)
    parser.add_argument("--pwadm-sigma-factor", type=float, default=1.0)
    parser.add_argument("--harvest-early-hno-max", type=int, default=0)
    parser.add_argument("--harvest-early-weight-factor", type=float, default=1.0)
    parser.add_argument(
        "--harvest-early-apply-to",
        choices=["inc", "cum", "both"],
        default="inc",
    )
    n_uptake_group = parser.add_mutually_exclusive_group()
    n_uptake_group.add_argument(
        "--include-n-uptake",
        dest="include_n_uptake",
        action="store_true",
    )
    n_uptake_group.add_argument(
        "--no-include-n-uptake",
        dest="include_n_uptake",
        action="store_false",
    )
    parser.set_defaults(include_n_uptake=True)
    parser.add_argument("--hwamm-sigma", type=float, default=50.0)
    parser.add_argument("--pwamm-sigma", type=float, default=20.0)
    parser.add_argument("--laixm-sigma", type=float, default=0.8)
    parser.add_argument("--laidm-sigma-factor", type=float, default=1.0)
    parser.add_argument("--lwadm-sigma-factor", type=float, default=1.0)
    parser.add_argument("--swadm-sigma-factor", type=float, default=1.0)
    parser.add_argument("--cnamm-sigma", type=float, default=25.0)
    parser.add_argument("--hiamm-sigma", type=float, default=0.10)
    parser.add_argument("--adapm-sigma", type=float, default=None)
    parser.add_argument("--harvest-var", default="CHPDT")
    parser.add_argument("--out-dir", default=WORKSPACE)
    parser.add_argument(
        "--weight-scheme",
        choices=["raw", "legacy", "improved"],
        default="raw",
        help="P0 raw-scale sigma policy. 'legacy' is a compatibility alias; "
             "'improved' may enable audited CV/pwtadj1 options only.",
    )
    parser.add_argument(
        "--apply-normalization",
        action="store_true",
        default=False,
        help="Retired option; P0 rejects candidate-dependent Min-Max normalization",
    )
    parser.add_argument(
        "--apply-log-transform",
        action="store_true",
        default=False,
        help="Retired global switch; use --observation-policy-csv for group-specific transforms",
    )
    parser.add_argument(
        "--apply-pwtadj1",
        action="store_true",
        default=False,
        help="Apply pwtadj1-equivalent weight balancing in improved weight scheme",
    )
    parser.add_argument(
        "--cv-based-sigma",
        action="store_true",
        default=False,
        help="Estimate sigma from observed data CV when using improved weight scheme",
    )
    parser.add_argument(
        "--noptmax0-sims",
        type=str,
        default=None,
        help="Path to baseline (noptmax=0) simulation CSV for pwtadj1 balancing",
    )
    parser.add_argument(
        "--observation-policy-csv",
        type=str,
        default=None,
        help="Audited group policy for transform, treatment-mean sigma, and group multiplier",
    )
    parser.add_argument(
        "--multiseason-design",
        type=str,
        default=None,
        help="T8 multi-season design JSON for joint calibration",
    )
    args = parser.parse_args()

    if bool(args.design_config) != bool(args.stage):
        parser.error("--design-config and --stage must be supplied together")
    design_spec = None
    fixed_from_provenance: list[dict[str, str]] = []
    if args.design_config:
        try:
            design_spec = load_design_config(args.design_config, args.stage)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            parser.error(f"invalid --design-config: {exc}")
        if (args.mode or "").strip().lower() != "eggplant_stage2":
            parser.error("--design-config is currently supported only with --mode eggplant_stage2")
        missing_contract = []
        if not args.input_dir:
            missing_contract.append("--input-dir")
        if not args.bounds_id:
            missing_contract.append("--bounds-id")
        if not args.observation_policy_csv:
            missing_contract.append("--observation-policy-csv")
        if design_spec.stage in {"S2", "S3", "S4"} and not args.fixed_from:
            missing_contract.append("--fixed-from (required for S2-S4)")
        if missing_contract:
            parser.error(
                "staged calibration requires " + ", ".join(missing_contract)
            )
        # Cross-check the CLI selection against the design declaration so a run
        # cannot silently mix a design with another input set. Hash binding in
        # the manifest only enables after-the-fact tracing; this gate prevents
        # the misuse before any artifact is written.
        if design_spec.bounds_id and args.bounds_id != design_spec.bounds_id:
            parser.error(
                f"--bounds-id {args.bounds_id!r} does not match design "
                f"bounds_id {design_spec.bounds_id!r}"
            )
        if design_spec.stage in {"S2", "S3", "S4"}:
            try:
                fixed_from_provenance = _fixed_from_provenance(
                    args.fixed_from,
                    current_stage=design_spec.stage,
                    design_table_id=design_spec.design_table_id,
                    approval_scope=design_spec.approval_scope,
                )
            except (FileNotFoundError, ValueError) as exc:
                parser.error(str(exc))

    # Formal staged calibration defaults to retaining all finite, successful
    # realizations. Legacy non-staged modes preserve the historical 2-sigma
    # behavior unless the caller overrides it explicitly.
    bad_phi_sigma = (
        float(args.bad_phi_sigma)
        if args.bad_phi_sigma is not None
        else (1.0e300 if design_spec is not None else 2.0)
    )
    if not math.isfinite(bad_phi_sigma) or bad_phi_sigma <= 0:
        parser.error("--bad-phi-sigma must be positive and finite; use 1e300 to disable relative screening")

    if args.input_dir:
        USER_INPUT_DIR = str(Path(args.input_dir).expanduser().resolve())
        if not Path(USER_INPUT_DIR).is_dir():
            parser.error(f"--input-dir does not exist: {USER_INPUT_DIR}")
        # Enforce input-bundle integrity and use clauses before any template is
        # parsed or artifact written. An SA counterfactual bundle declares
        # ``parameter_calibration`` as a prohibited use and must hard-fail here;
        # tampered bytes (hash mismatch) or a renamed directory fail the same way.
        try:
            input_manifest = verify_calibrated_input_bundle(USER_INPUT_DIR)
        except InputManifestError as exc:
            parser.error(f"--input-dir failed manifest verification: {exc}")
        # Bundle id and observation policy id must agree with the staged
        # design declaration. The policy id is taken from the CSV filename stem
        # because policy files do not carry an internal id field.
        if design_spec is not None and design_spec.input_bundle and \
                input_manifest.bundle_id != design_spec.input_bundle:
            parser.error(
                f"--input-dir bundle id {input_manifest.bundle_id!r} does not match "
                f"design input_bundle {design_spec.input_bundle!r}"
            )
        if design_spec is not None and design_spec.observation_policy_id and \
                args.observation_policy_csv and \
                Path(args.observation_policy_csv).stem != design_spec.observation_policy_id:
            parser.error(
                f"--observation-policy-csv stem {Path(args.observation_policy_csv).stem!r} "
                f"does not match design observation_policy_id {design_spec.observation_policy_id!r}"
            )

    if args.apply_normalization:
        parser.error("--apply-normalization is retired because candidate-dependent Min-Max changes the objective")
    if args.apply_log_transform:
        parser.error(
            "--apply-log-transform is retired; use --observation-policy-csv so each group "
            "has an explicit transform and sigma definition"
        )
    if args.apply_pwtadj1:
        parser.error(
            "--apply-pwtadj1 is deferred: observation counts and temporal correlation "
            "must be audited before total-group-Phi balancing is enabled"
        )
    try:
        observation_policies = load_observation_policy(args.observation_policy_csv)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    if args.batch:
        try:
            args.batch = str(
                resolve_path(
                    args.batch,
                    bases=(
                        ([Path(USER_INPUT_DIR)] if USER_INPUT_DIR else [])
                        + [PROJECT_ROOT / "data" / "templates" / "batch", WORKSPACE_DIR]
                    ),
                )
            )
        except FileNotFoundError as exc:
            parser.error(str(exc))

    # Validate immutable frozen bounds before parsing templates or creating any
    # run artifacts.  A malformed scientific input must be the first failure.
    _prevalidated_bounds = None
    _prevalidated_bound_issues = []
    if args.bounds_id:
        pre_crop = args.bounds_crop or ("eggplant" if "eggplant" in (args.mode or "").lower() else "tomato")
        _prevalidated_bounds = _resolve_bounds_id(args.bounds_id, crop=pre_crop)
        if not _prevalidated_bounds:
            raise FileNotFoundError(
                f"Cannot resolve --bounds-id {args.bounds_id} "
                f"(searched in data/parameter_registry/bounds_frozen/{pre_crop}/)"
            )
        _prevalidated_bound_issues = assert_valid_frozen_bounds(_prevalidated_bounds)

    mode = (args.mode or "").strip().lower()
    filex = _first_batch_filex_path(args.batch)
    cultivar = _infer_cultivar_from_filex(_resolve_filex_path(filex) or filex) or "TM0001"
    ecotype = _infer_ecotype_from_cul_base(cultivar) or "TM0001"
    evaluate_out_path = _evaluate_out_path_from_batch(args.batch)

    df_override = None
    stage2_outputs = None
    stage_evaluate_df = None

    out_dir = os.path.abspath(args.out_dir) if args.out_dir else WORKSPACE
    os.makedirs(out_dir, exist_ok=True)

    harvest_var = (args.harvest_var or "CHPDT").strip().upper()
    adapm_sigma = float(args.adapm_sigma) if args.adapm_sigma is not None else None
    batch_for_model = args.batch
    try:
        if args.batch and os.path.exists(args.batch):
            bname = os.path.basename(args.batch)
            dst = os.path.join(out_dir, bname)
            if os.path.abspath(args.batch) != os.path.abspath(dst):
                shutil.copy(args.batch, dst)
            batch_for_model = bname
    except Exception:
        batch_for_model = os.path.basename(args.batch) if args.batch else args.batch

    model_cmd_extra = f"--batch {batch_for_model} --harvest-var {harvest_var}"
    if USER_INPUT_DIR:
        model_cmd_extra += f' --input-dir "{USER_INPUT_DIR}"'

    allowed: Optional[Set[str]] = None
    obs_bases: Optional[Set[str]] = None
    critical: Set[str] = set()
    group_sigmas: Optional[Dict[str, float]] = None
    extra_allowed: Optional[Set[str]] = None
    design_observation_report = {}
    ies_contract = {}

    multiseason_mode = False

    if mode == "eggplant_pheno":
        prefix = args.prefix or "eggplant_pheno"
        allowed = {"CSDL", "PPSEN", "EM-FL", "FL-SH", "FL-SD", "SD-PM", "FL-LF"}
        obs_bases = {'ADAP'}
        critical = {'ADAPM'}
        model_out_path = PEST_EVAL_FILE
        group_sigmas = {
            "ADAPM": float(adapm_sigma) if adapm_sigma is not None else 25.0,
        }
        extra_allowed = None
    elif mode == "eggplant_growth":
        prefix = args.prefix or "eggplant_growth"
        allowed = {"SLAVR", "SIZLF", "LFMAX", "XFRT", "WTPSD", "SFDUR", "SDPDV", "PODUR"}
        obs_bases = {"HWAM", "LAIX", "CNAM"}
        critical = set()
        model_out_path = PEST_GROW_FILE
        group_sigmas = {
            "HWAMM": 500.0,
            "LAIXM": 0.8,
            "CNAMM": 25.0,
        }
        extra_allowed = None
    elif mode == "eggplant_joint":
        prefix = args.prefix or "eggplant_joint"
        allowed = {"SLAVR", "SIZLF", "LFMAX", "XFRT", "WTPSD", "SFDUR", "SDPDV", "PODUR"}
        obs_bases = {"HWAM", "LAIX", "CNAM", "CHTA", "CNAA", "PWAM", "H#AM", "HIAM"}
        critical = set()
        model_out_path = PEST_JOINT_FILE
        group_sigmas = {
            "HWAMM": float(args.hwamm_sigma),
            "PWAMM": float(args.pwamm_sigma),
            "LAIXM": float(args.laixm_sigma),
            "CNAMM": float(args.cnamm_sigma),
            "CHTAM": 15.0,
            "CNAAM": 20.0,
            "H#AMM": 50.0,
            "HIAMM": float(args.hiamm_sigma),
        }
        extra_allowed = {"XMAGE", "TRIFL", "RWDTH", "RHGHT"}
    elif mode == "eggplant_stage2":
        prefix = args.prefix or "eggplant_stage2"
        allowed = {
            "CSDL",
            "PPSEN",
            "EM-FL",
            "FL-SH",
            "FL-SD",
            "SD-PM",
            "FL-LF",
            "SLAVR",
            "SIZLF",
            "LFMAX",
            "XFRT",
            "WTPSD",
            "SFDUR",
            "SDPDV",
            "PODUR",
            "THRSH",
        }
        extra_allowed = {
            "XMAGE",
            "TRIFL",
            "RWDTH",
            "RHGHT",
            "KC_SLOPE",
            "VSSINK",
            "RTNO3",
            "RTNH4",
            "RTEXF",
            "NSTFAC",
            "NMOBMX",
            "NVSMOB",
            "NRCVR",
            "XFPHT",
            "XFINT",
            "PL-EM",
            "EM-V1",
            "V1-JU",
            "JU-R0",
            "TB1",
            "TO11",
            "TO21",
            "TM1",
            "TB2",
            "TO12",
            "TO22",
            "TM2",
            "TB3",
            "TO13",
            "TO23",
            "TM3",
        }

        if not bool(args.include_n_uptake):
            extra_allowed = {p for p in extra_allowed if p not in {"RTNO3", "RTNH4", "RTEXF"}}

        if args.multiseason_design:
            multiseason_mode = True
            stage2_outputs = []  # placeholder — real build happens after params ready
            entries = []

        entries = _parse_batch_entries(args.batch)

        if not entries:
            stage_evaluate_df = pd.DataFrame(columns=["@RUN", "TN", "ADAPM", "LAIXM", "CNAMM"])
            df_harvest = pd.DataFrame(columns=["@RUN", "TN", "HNO", "DATE", "PWADM", "PWAIM", "PWADS", "PWAIS"])
            harvest_sigmas = {"PWADM": 1.0}
            df_process = pd.DataFrame(
                columns=["@RUN", "TN", "DATE", "LAIDM", "LWADM", "SWADM", "LAIDS", "LWADS", "SWADS"]
            )
            process_sigmas = {"LAIDM": 2.0, "LWADM": 150.0, "SWADM": 200.0}
        else:
            stage_evaluate_df = _build_evaluate_observations_from_filea(entries)
            events_by_run, points_by_run = _collect_tmt_events_per_run(entries)

            harvest_rows = []
            process_rows = []

            for e in entries:
                run_no = int(e["run"])
                tn = int(e.get("tn", -99))

                for ev in events_by_run.get(run_no, []):
                    obs_cum = ev.get("dry_cum", -99.0) if harvest_var == "CHPDT" else ev.get("fresh_cum", -99.0)
                    obs_inc = ev.get("dry_inc", -99.0) if harvest_var == "CHPDT" else ev.get("fresh_inc", -99.0)
                    harvest_rows.append(
                        {
                            "@RUN": run_no,
                            "TN": tn,
                            "HNO": int(ev["hno"]),
                            "DATE": int(ev["date"]),
                            "PWADM": float(obs_cum),
                            "PWAIM": float(obs_inc),
                            "PWADS": -99.0,
                            "PWAIS": -99.0,
                        }
                    )

                for p in points_by_run.get(run_no, []):
                    process_rows.append(
                        {
                            "@RUN": run_no,
                            "TN": tn,
                            "DATE": int(p["date"]),
                            "LAIDM": float(p["laid"]),
                            "LWADM": float(p["lwad"]),
                            "SWADM": float(p["swad"]),
                            "LAIDS": -99.0,
                            "LWADS": -99.0,
                            "SWADS": -99.0,
                        }
                    )

            df_harvest = pd.DataFrame(harvest_rows)
            df_process = pd.DataFrame(process_rows)

            harvest_sigmas = {"PWADM": 1.0}
            if not df_harvest.empty:
                early_hno_max = int(args.harvest_early_hno_max)
                early_weight_factor = float(args.harvest_early_weight_factor)
                early_apply_to = str(args.harvest_early_apply_to).strip().lower()
                early_scale = 1.0
                if early_weight_factor > 0:
                    early_scale = float(early_weight_factor) ** -0.5
                for hno, g in df_harvest.groupby("HNO"):
                    sigma0 = float(args.pwadm_sigma0)
                    cv = float(args.pwadm_cv)
                    sigma_factor = float(args.pwadm_sigma_factor)

                    med_cum = float(g["PWADM"].median())
                    sigma_cum = (sigma0**2 + (cv * abs(med_cum)) ** 2) ** 0.5
                    sigma_cum = sigma_cum * sigma_factor
                    if early_hno_max > 0 and int(hno) <= early_hno_max and early_apply_to in {"cum", "both"}:
                        sigma_cum = sigma_cum * early_scale
                    harvest_sigmas[f"PWADM_H{int(hno)}"] = float(sigma_cum)

                    med_inc = float(g["PWAIM"].median())
                    sigma_inc = (sigma0**2 + (cv * abs(med_inc)) ** 2) ** 0.5
                    sigma_inc = sigma_inc * sigma_factor
                    if early_hno_max > 0 and int(hno) <= early_hno_max and early_apply_to in {"inc", "both"}:
                        sigma_inc = sigma_inc * early_scale
                    harvest_sigmas[f"PWAIM_H{int(hno)}"] = float(sigma_inc)

            laidm_sigma_factor = float(args.laidm_sigma_factor)
            lwadm_sigma_factor = float(args.lwadm_sigma_factor)
            swadm_sigma_factor = float(args.swadm_sigma_factor)
            process_sigmas = {
                "LAIDM": 2.0 * laidm_sigma_factor,
                "LWADM": 150.0 * lwadm_sigma_factor,
                "SWADM": 200.0 * swadm_sigma_factor,
            }
            if not df_process.empty:
                for var, sigma0, cv in [
                    ("LAIDM", 1.6, 0.50),
                    ("LWADM", 80.0, 0.25),
                    ("SWADM", 100.0, 0.25),
                ]:
                    g = df_process[df_process[var] != -99.0]
                    if g.empty:
                        continue
                    for date, gg in g.groupby("DATE"):
                        med = float(gg[var].median())
                        sigma = (sigma0**2 + (cv * abs(med)) ** 2) ** 0.5
                        if var == "LAIDM":
                            sigma = sigma * laidm_sigma_factor
                        elif var == "LWADM":
                            sigma = sigma * lwadm_sigma_factor
                        elif var == "SWADM":
                            sigma = sigma * swadm_sigma_factor
                        process_sigmas[f"{var}_D{int(date)}"] = float(sigma)

        stage2_outputs = [
            {
                "model_out_path": PEST_EVAL_FILE,
                "obs_bases": {"ADAP"},
                "critical_obs": {"ADAPM"},
                "group_sigmas": {"ADAPM": float(adapm_sigma) if adapm_sigma is not None else 25.0},
                "df": stage_evaluate_df,
            },
            {
                "model_out_path": PEST_JOINT_FILE,
                "obs_bases": {"HWAM", "LAIX", "CNAM", "CHTA", "CNAA", "PWAM", "H#AM", "HIAM"},
                "critical_obs": set(),
                "group_sigmas": {
                    "HWAMM": float(args.hwamm_sigma),
                    "PWAMM": float(args.pwamm_sigma),
                    "LAIXM": float(args.laixm_sigma),
                    "CNAMM": float(args.cnamm_sigma),
                    "CHTAM": 15.0,
                    "CNAAM": 20.0,
                    "H#AMM": 50.0,
                    "HIAMM": float(args.hiamm_sigma),
                },
                "df": stage_evaluate_df,
            },
            {
                "model_out_path": PEST_HARVEST_FILE,
                "obs_bases": {"PWAD", "PWAI"},
                "critical_obs": set(),
                "group_sigmas": harvest_sigmas,
                "df": df_harvest,
            },
            {
                "model_out_path": PEST_TMTGROW_FILE,
                "obs_bases": {"LAID", "LWAD", "SWAD"},
                "critical_obs": set(),
                "group_sigmas": process_sigmas,
                "df": df_process,
            },
        ]
    elif mode == "eggplant_harvest":
        prefix = args.prefix or "eggplant_harvest"
        allowed = {"SLAVR", "SIZLF", "LFMAX", "XFRT", "WTPSD", "SFDUR", "SDPDV", "PODUR"}
        obs_bases = {"PWAD", "PWAI"}
        critical = set()
        model_out_path = PEST_HARVEST_FILE

        entries = _parse_batch_entries(args.batch)
        if not entries:
            print("Warning: batch file is empty; no harvest observations will be created.")
            df_override = pd.DataFrame(columns=["@RUN", "TN", "HNO", "DATE", "PWADM", "PWAIM", "PWADS", "PWAIS"])
            group_sigmas = {"PWADM": 1.0}
        else:
            filex = entries[0]["filex"]
            filex_path = _resolve_filex_path(filex) or (filex if os.path.isabs(filex) else os.path.join(WORKSPACE, filex))
            excode = _infer_excode_from_filex(filex_path)
            tmt_path = os.path.join(os.path.dirname(os.path.abspath(filex_path)), f"{excode}.TMT") if excode else None

            events_by_tn = _read_tmt_harvest_events(tmt_path)

            rows = []
            for e in entries:
                run_no = int(e["run"])
                tn = int(e.get("tn", -99))
                for ev in events_by_run.get(run_no, []):
                    obs_cum = ev.get("dry_cum", -99.0) if harvest_var == "CHPDT" else ev.get("fresh_cum", -99.0)
                    obs_inc = ev.get("dry_inc", -99.0) if harvest_var == "CHPDT" else ev.get("fresh_inc", -99.0)
                    rows.append({
                        "@RUN": run_no,
                        "TN": tn,
                        "HNO": int(ev["hno"]),
                        "DATE": int(ev["date"]),
                        "PWADM": float(obs_cum),
                        "PWAIM": float(obs_inc),
                        "PWADS": -99.0,
                        "PWAIS": -99.0,
                    })

            df_override = pd.DataFrame(rows)
            if df_override.empty:
                group_sigmas = {"PWADM": 1.0}
            else:
                group_sigmas = {"PWADM": 1.0}
                early_hno_max = int(args.harvest_early_hno_max)
                early_weight_factor = float(args.harvest_early_weight_factor)
                early_apply_to = str(args.harvest_early_apply_to).strip().lower()
                early_scale = 1.0
                if early_weight_factor > 0:
                    early_scale = float(early_weight_factor) ** -0.5
                for hno, g in df_override.groupby("HNO"):
                    sigma0 = float(args.pwadm_sigma0)
                    cv = float(args.pwadm_cv)
                    sigma_factor = float(args.pwadm_sigma_factor)
                    med_cum = float(g["PWADM"].median())
                    sigma_cum = (sigma0 ** 2 + (cv * abs(med_cum)) ** 2) ** 0.5
                    sigma_cum = sigma_cum * sigma_factor
                    if early_hno_max > 0 and int(hno) <= early_hno_max and early_apply_to in {"cum", "both"}:
                        sigma_cum = sigma_cum * early_scale
                    group_sigmas[f"PWADM_H{int(hno)}"] = float(sigma_cum)

                    med_inc = float(g["PWAIM"].median())
                    sigma_inc = (sigma0 ** 2 + (cv * abs(med_inc)) ** 2) ** 0.5
                    sigma_inc = sigma_inc * sigma_factor
                    if early_hno_max > 0 and int(hno) <= early_hno_max and early_apply_to in {"inc", "both"}:
                        sigma_inc = sigma_inc * early_scale
                    group_sigmas[f"PWAIM_H{int(hno)}"] = float(sigma_inc)
        extra_allowed = {"XMAGE", "FL-VS", "TRIFL"}
    elif mode == "eggplant_v13":
        prefix = args.prefix or "eggplant_v13"
        allowed = {
            "CSDL",
            "PPSEN",
            "EM-FL",
            "FL-SH",
            "FL-SD",
            "SD-PM",
            "FL-LF",
            "SLAVR",
            "SIZLF",
            "LFMAX",
            "XFRT",
            "WTPSD",
            "SFDUR",
            "SDPDV",
            "PODUR",
            "THRSH",
        }

        entries = _parse_batch_entries(args.batch)

        if not entries:
            df_harvest = pd.DataFrame(columns=["@RUN", "TN", "HNO", "DATE", "PWADM", "PWADS"])
            harvest_sigmas = {"PWADM": 1.0}
            df_process = pd.DataFrame(
                columns=[
                    "@RUN",
                    "TN",
                    "DATE",
                    "L#SDM",
                    "LAIDM",
                    "LWADM",
                    "SWADM",
                    "L#SDS",
                    "LAIDS",
                    "LWADS",
                    "SWADS",
                ]
            )
            process_sigmas = {"L#SDM": 0.6, "LAIDM": 2.0, "LWADM": 150.0, "SWADM": 200.0}
        else:
            events_by_run, points_by_run = _collect_tmt_events_per_run(entries)

            harvest_rows = []
            process_rows = []

            for e in entries:
                run_no = int(e["run"])
                tn = int(e.get("tn", -99))

                for ev in events_by_run.get(run_no, []):
                    obs_cum = ev.get("dry_cum", -99.0) if harvest_var == "CHPDT" else ev.get("fresh_cum", -99.0)
                    obs_inc = ev.get("dry_inc", -99.0) if harvest_var == "CHPDT" else ev.get("fresh_inc", -99.0)
                    harvest_rows.append(
                        {
                            "@RUN": run_no,
                            "TN": tn,
                            "HNO": int(ev["hno"]),
                            "DATE": int(ev["date"]),
                            "PWADM": float(obs_cum),
                            "PWAIM": float(obs_inc),
                            "PWADS": -99.0,
                            "PWAIS": -99.0,
                        }
                    )

                for p in points_by_run.get(run_no, []):
                    process_rows.append(
                        {
                            "@RUN": run_no,
                            "TN": tn,
                            "DATE": int(p["date"]),
                            "L#SDM": float(p.get("lnsd", -99.0)),
                            "LAIDM": float(p["laid"]),
                            "LWADM": float(p["lwad"]),
                            "SWADM": float(p["swad"]),
                            "L#SDS": -99.0,
                            "LAIDS": -99.0,
                            "LWADS": -99.0,
                            "SWADS": -99.0,
                        }
                    )

            df_harvest = pd.DataFrame(harvest_rows)
            if df_harvest.empty:
                harvest_sigmas = {"PWADM": 1.0}
            else:
                harvest_sigmas = {"PWADM": 1.0}
                early_hno_max = int(args.harvest_early_hno_max)
                early_weight_factor = float(args.harvest_early_weight_factor)
                early_apply_to = str(args.harvest_early_apply_to).strip().lower()
                early_scale = 1.0
                if early_weight_factor > 0:
                    early_scale = float(early_weight_factor) ** -0.5

                for hno, g in df_harvest.groupby("HNO"):
                    sigma0 = float(args.pwadm_sigma0)
                    cv = float(args.pwadm_cv)
                    sigma_factor = float(args.pwadm_sigma_factor)

                    med_cum = float(g["PWADM"].median())
                    sigma_cum = (sigma0**2 + (cv * abs(med_cum)) ** 2) ** 0.5
                    sigma_cum = sigma_cum * sigma_factor
                    if early_hno_max > 0 and int(hno) <= early_hno_max and early_apply_to in {"cum", "both"}:
                        sigma_cum = sigma_cum * early_scale
                    harvest_sigmas[f"PWADM_H{int(hno)}"] = float(sigma_cum)

                    med_inc = float(g["PWAIM"].median())
                    sigma_inc = (sigma0**2 + (cv * abs(med_inc)) ** 2) ** 0.5
                    sigma_inc = sigma_inc * sigma_factor
                    if early_hno_max > 0 and int(hno) <= early_hno_max and early_apply_to in {"inc", "both"}:
                        sigma_inc = sigma_inc * early_scale
                    harvest_sigmas[f"PWAIM_H{int(hno)}"] = float(sigma_inc)

            df_process = pd.DataFrame(process_rows)
            process_sigmas = {"L#SDM": 0.6, "LAIDM": 2.0, "LWADM": 150.0, "SWADM": 200.0}
            if not df_process.empty:
                for var, sigma0, cv in [
                    ("L#SDM", 0.5, 0.15),
                    ("LAIDM", 1.6, 0.50),
                    ("LWADM", 80.0, 0.25),
                    ("SWADM", 100.0, 0.25),
                ]:
                    g = df_process[df_process[var] != -99.0]
                    if g.empty:
                        continue
                    for date, gg in g.groupby("DATE"):
                        med = float(gg[var].median())
                        sigma = (sigma0**2 + (cv * abs(med)) ** 2) ** 0.5
                        process_sigmas[f"{var}_D{int(date)}"] = float(sigma)

        stage2_outputs = [
            {
                "model_out_path": PEST_HARVEST_FILE,
                "obs_bases": {"PWAD", "PWAI"},
                "critical_obs": set(),
                "group_sigmas": harvest_sigmas,
                "df": df_harvest,
            },
            {
                "model_out_path": PEST_TMTGROW_FILE,
                "obs_bases": {"L#SD", "LAID", "LWAD", "SWAD"},
                "critical_obs": set(),
                "group_sigmas": process_sigmas,
                "df": df_process,
            },
        ]
        extra_allowed = {
            "PL-EM",
            "EM-V1",
            "V1-JU",
            "JU-R0",
            "FL-VS",
            "TRIFL",
            "RWDTH",
            "RHGHT",
            "OPTBI",
            "SLOBI",
            "XMAGE",
            "XFPHT",
            "XFINT",
            "TB1",
            "TO11",
            "TO21",
            "TM1",
            "TB2",
            "TO12",
            "TO22",
            "TM2",
            "TB3",
            "TO13",
            "TO23",
            "TM3",
        }
    elif mode == "eggplant_process":
        prefix = args.prefix or "eggplant_process"
        allowed = {"SLAVR", "SIZLF", "LFMAX", "XFRT", "WTPSD", "SFDUR", "SDPDV", "PODUR"}
        obs_bases = {"LAID", "LWAD", "SWAD"}
        critical = set()
        model_out_path = PEST_TMTGROW_FILE

        entries = _parse_batch_entries(args.batch)
        if not entries:
            print("Warning: batch file is empty; no process observations will be created.")
            df_override = pd.DataFrame(columns=["@RUN", "TN", "DATE", "LAIDM", "LWADM", "SWADM", "LAIDS", "LWADS", "SWADS"])
            group_sigmas = {"LAIDM": 2.0, "LWADM": 150.0, "SWADM": 200.0}
        else:
            filex = entries[0]["filex"]
            filex_path = _resolve_filex_path(filex) or (filex if os.path.isabs(filex) else os.path.join(WORKSPACE, filex))
            excode = _infer_excode_from_filex(filex_path)
            tmt_path = os.path.join(os.path.dirname(os.path.abspath(filex_path)), f"{excode}.TMT") if excode else None

            points_by_tn = _read_tmt_process_points(tmt_path)
            rows = []
            for e in entries:
                run_no = int(e["run"])
                tn = int(e.get("tn", -99))
                for p in points_by_run.get(run_no, []):
                    rows.append(
                        {
                            "@RUN": run_no,
                            "TN": tn,
                            "DATE": int(p["date"]),
                            "LAIDM": float(p["laid"]),
                            "LWADM": float(p["lwad"]),
                            "SWADM": float(p["swad"]),
                            "LAIDS": -99.0,
                            "LWADS": -99.0,
                            "SWADS": -99.0,
                        }
                    )

            df_override = pd.DataFrame(rows)
            group_sigmas = {"LAIDM": 2.0, "LWADM": 150.0, "SWADM": 200.0}
            if not df_override.empty:
                for var, sigma0, cv in [
                    ("LAIDM", 1.6, 0.50),
                    ("LWADM", 80.0, 0.25),
                    ("SWADM", 100.0, 0.25),
                ]:
                    g = df_override[df_override[var] != -99.0]
                    if g.empty:
                        continue
                    for date, gg in g.groupby("DATE"):
                        med = float(gg[var].median())
                        sigma = (sigma0 ** 2 + (cv * abs(med)) ** 2) ** 0.5
                        group_sigmas[f"{var}_D{int(date)}"] = float(sigma)
        extra_allowed = None
    elif mode == "eggplant_spe_temp":
        prefix = args.prefix or "eggplant_spe_temp"
        allowed = set()
        obs_bases = {"ADAP"}
        critical = {"ADAPM"}
        model_out_path = PEST_EVAL_FILE
        group_sigmas = {
            "ADAPM": float(adapm_sigma) if adapm_sigma is not None else 25.0,
        }
        extra_allowed = {
            "TB1",
            "TO11",
            "TO21",
            "TM1",
            "TB2",
            "TO12",
            "TO22",
            "TM2",
            "TB3",
            "TO13",
            "TO23",
            "TM3",
        }
    else:
        prefix = args.prefix or "tomato_cal"
        allowed = None
        obs_bases = None
        critical = {'ADAPM', 'MDAPM', 'PD1PM'}
        model_out_path = OUT_FILE
        group_sigmas = None
        extra_allowed = None

    params = parse_cul_params(cultivar, allowed_params=allowed)

    if extra_allowed is not None:
        eco_init = _read_eco_init_values(ecotype)
        spe_init = _read_spe_temp_init_values()
        spe_init.update(_read_spe_direct_init_values())
        params.extend(
            parse_extra_params(
                init_map=eco_init,
                bounds_map=ECO_BOUNDS_EGGPLANT,
                allowed_params=extra_allowed,
                pargp="ecotype",
            )
        )
        params.extend(
            parse_extra_params(
                init_map=spe_init,
                bounds_map=SPE_TEMP_BOUNDS_EGGPLANT,
                allowed_params=extra_allowed,
                pargp="species",
            )
        )
        params.extend(
            parse_extra_params(
                init_map=spe_init,
                bounds_map=SPE_DIRECT_BOUNDS_EGGPLANT,
                allowed_params=extra_allowed,
                pargp="species",
            )
        )

    if args.include_soil or args.include_ic:
        filex0 = _first_batch_filex_path(args.batch)
        filex_path0 = _resolve_filex_path(filex0)
        soil_id = _infer_soil_id_from_filex(filex_path0)
        soil_layers = _read_soil_layers(_soil_source_path(), soil_id)
        if args.include_soil:
            params.extend(
                _build_soil_sbdm_params(
                    soil_layers,
                    delta=args.soil_sbdm_delta,
                    frac=args.soil_sbdm_frac,
                )
            )
        if args.include_ic:
            sh2o_vals = _read_initial_sh2o(filex_path0)
            params.extend(
                _build_ic_sh2o_params(
                    sh2o_vals,
                    soil_layers,
                    delta=args.ic_sh2o_delta,
                    frac=args.ic_sh2o_frac,
                )
            )
    print(f"Found {len(params)} adjustable parameters.")

    override = {}
    for p in args.init_from or []:
        override.update(_load_init_overrides(p))
    if override:
        for p in params:
            k = str(p.get("name", "")).strip().lower()
            if k and k in override:
                p["init"] = float(override[k])

    # ── bounds-id resolution (Phase 1) ──
    if args.bounds_id:
        bounds_crop = args.bounds_crop
        if not bounds_crop:
            bounds_crop = "eggplant" if "eggplant" in mode else "tomato"
        resolved = _prevalidated_bounds or _resolve_bounds_id(args.bounds_id, crop=bounds_crop)
        if not resolved:
            raise FileNotFoundError(
                f"Cannot resolve --bounds-id {args.bounds_id} "
                f"(searched in data/parameter_registry/bounds_frozen/{bounds_crop}/)")
        print(f"Using frozen bounds: {resolved}")
        bound_issues = _prevalidated_bound_issues or assert_valid_frozen_bounds(resolved)
        for issue in bound_issues:
            if issue.severity == "warning":
                print(str(issue))
        print(f"Frozen bounds validated: {resolved}")
        brm_csv = resolved
        brm_mode = "require"
    else:
        brm_csv = args.bounds_review_csv
        brm_mode = (args.bounds_review_mode or "auto").strip().lower()

    if brm_mode != "off":
        exists = bool(brm_csv and os.path.exists(brm_csv))
        if brm_mode == "require" and not exists:
            raise FileNotFoundError(f"Bounds review CSV not found: {brm_csv}")
        if exists:
            if args.validate_bounds_review_csv:
                issues = validate_sensitivity_param_review_csv(brm_csv)
                if issues:
                    preview = "\n".join([str(x) for x in issues[:80]])
                    raise SystemExit(f"Bounds review CSV validation failed ({len(issues)} issues)\n{preview}")
                print(f"Bounds review CSV validated: {brm_csv}")

            params, brm_report = apply_bounds_review_csv(
                params,
                brm_csv,
                cultivar=cultivar,
                ecotype=ecotype,
                mode=mode,
            )
            if brm_report.get("applied", 0) > 0:
                print(f"Applied bounds from {brm_csv} to {brm_report['applied']} parameters")
            if brm_report.get("missing", 0) > 0:
                missing_preview = ", ".join([str(x) for x in (brm_report.get("missing_names") or [])[:12]])
                print(f"Bounds CSV missing {brm_report['missing']} parameters (first: {missing_preview})")

    param_review_csv = args.param_review_csv
    if not param_review_csv:
        param_review_csv = os.path.join(out_dir, f"{prefix}_param_review.csv")

    prm_mode = (args.param_review_mode or "auto").strip().lower()
    if prm_mode != "off":
        exists = os.path.exists(param_review_csv)
        if prm_mode in {"auto", "export"} and not exists:
            write_param_review_csv(params, param_review_csv, cultivar=cultivar, ecotype=ecotype, mode=mode)
            print(f"Parameter review CSV written to {param_review_csv}")
            if prm_mode != "export":
                print("Edit this file and re-run with --param-review-mode import")
            raise SystemExit(0)
        if prm_mode == "export":
            write_param_review_csv(params, param_review_csv, cultivar=cultivar, ecotype=ecotype, mode=mode)
            print(f"Parameter review CSV written to {param_review_csv}")
            raise SystemExit(0)
        if exists and prm_mode in {"auto", "import"}:
            params = apply_param_review_csv(params, param_review_csv)

    if args.tighten_from:
        params = apply_tighten_params_csv(params, args.tighten_from, tighten_frac=float(args.tighten_frac))

    if args.fixed_from:
        params = apply_fixed_params_csv(params, args.fixed_from)

    if design_spec is not None:
        # Apply the approved stage after bounds/review overlays so the PST
        # cannot silently release parameters outside the design table. The
        # frozen bounds lookup restores the declared search range of active
        # parameters that an upstream --fixed-from overlay may have collapsed
        # to a single point (e.g. S4 re-releasing S3-representative parameters).
        stage_bounds_lookup = None
        stage_bounds_path = _prevalidated_bounds or (
            _resolve_bounds_id(args.bounds_id, crop=bounds_crop) if args.bounds_id else None
        )
        if stage_bounds_path:
            try:
                stage_bounds_lookup = load_frozen_bounds_lookup(stage_bounds_path)
            except (OSError, ValueError) as exc:
                raise RuntimeError(
                    f"could not load frozen bounds lookup from {stage_bounds_path}: {exc}"
                ) from exc
        if stage_bounds_lookup is None:
            raise RuntimeError(
                f"staged {design_spec.stage} build requires a valid frozen bounds lookup; "
                "provide --bounds-id pointing to a frozen bounds CSV"
            )
        missing_stage_bounds = [
            name for name in design_spec.active_params if name not in stage_bounds_lookup
        ]
        if missing_stage_bounds:
            raise RuntimeError(
                f"frozen bounds are missing active parameters for {design_spec.stage}: "
                + ", ".join(missing_stage_bounds)
            )
        params = apply_parameter_stage(params, design_spec, frozen_bounds=stage_bounds_lookup)
        if stage2_outputs is not None:
            stage2_outputs, design_observation_report = apply_observation_stage(
                stage2_outputs,
                design_spec,
                _parse_batch_entries(args.batch),
                eval_df=stage_evaluate_df,
            )

    if stage2_outputs is not None:
        if multiseason_mode:
            ctx = {
                "_parse_batch_entries": _parse_batch_entries,
                "_build_evaluate_observations_from_filea": _build_evaluate_observations_from_filea,
                "_read_tmt_harvest_events": _read_tmt_harvest_events,
                "_read_tmt_process_points": _read_tmt_process_points,
                "_resolve_filex_path": _resolve_filex_path,
                "_infer_excode_from_filex": _infer_excode_from_filex,
                "PEST_EVAL_FILE": PEST_EVAL_FILE,
                "PEST_JOINT_FILE": PEST_JOINT_FILE,
                "PEST_HARVEST_FILE": PEST_HARVEST_FILE,
                "PEST_TMTGROW_FILE": PEST_TMTGROW_FILE,
                "create_ins_and_pst_multi": create_ins_and_pst_multi,
                "_write_run_manifest": _write_run_manifest,
                "_finalize_ies_contract": _finalize_ies_contract,
                "bad_phi_sigma": bad_phi_sigma,
                "observation_policies": observation_policies,
            }
            # Per-season builder needs USER_INPUT_DIR to resolve FileX.
            # Set it once here so the builder only imports the shared module.
            import src.calibration.build_pest as _bp
            ctx["_bp_module"] = _bp
            _bp.USER_INPUT_DIR = str(Path(args.multiseason_design).parent)  # fallback
            build_multiseason_stage2(args, prefix, allowed, extra_allowed, params, model_cmd_extra, ctx)
            raise SystemExit(0)

        create_ins_and_pst_multi(
            params,
            prefix=prefix,
            noptmax=args.noptmax,
            ies_num_reals=args.ies_num_reals,
            random_seed=args.random_seed,
            outputs=stage2_outputs,
            evaluate_out_path=evaluate_out_path,
            model_cmd_extra=model_cmd_extra,
            out_dir=out_dir,
            weight_scheme=args.weight_scheme,
            apply_normalization=args.apply_normalization,
            apply_log_transform=args.apply_log_transform,
            apply_pwtadj1=args.apply_pwtadj1,
            cv_based_sigma=args.cv_based_sigma,
            noptmax0_sims=args.noptmax0_sims,
            observation_policies=observation_policies,
        )
    else:
        create_ins_and_pst(
            params,
            prefix=prefix,
            noptmax=args.noptmax,
            ies_num_reals=args.ies_num_reals,
            random_seed=args.random_seed,
            obs_bases=obs_bases,
            critical_obs=critical,
            model_out_path=model_out_path,
            group_sigmas=group_sigmas,
            evaluate_out_path=evaluate_out_path,
            df_override=df_override,
            model_cmd_extra=model_cmd_extra,
            out_dir=out_dir,
            weight_scheme=args.weight_scheme,
            apply_normalization=args.apply_normalization,
            apply_log_transform=args.apply_log_transform,
            apply_pwtadj1=args.apply_pwtadj1,
            cv_based_sigma=args.cv_based_sigma,
            noptmax0_sims=args.noptmax0_sims,
            observation_policies=observation_policies,
        )

    # Apply the explicit IES policy after either PST builder has written the
    # control file. Staged runs always freeze sigma_eff-based observation noise;
    # a finite --bad-phi-sigma is reserved for the D0 screening comparison.
    ies_contract = _finalize_ies_contract(
        os.path.join(out_dir, f"{prefix}.pst"),
        out_dir=out_dir,
        prefix=prefix,
        ies_num_reals=args.ies_num_reals,
        random_seed=args.random_seed,
        bad_phi_sigma=bad_phi_sigma,
        observation_noise=bool(design_spec is not None and observation_policies),
    )

    design_audit_path = ""
    if design_spec is not None:
        design_audit_path = str(
            write_design_audit(
                os.path.join(out_dir, f"{prefix}.pst"),
                design_spec,
                _parse_batch_entries(args.batch),
                os.path.join(out_dir, "calibration_design_audit.csv"),
            )
        )

    # ── Generate run_manifest.yaml (Phase 1) ──
    git_info = git_metadata()
    manifest_path = _write_run_manifest(
        out_dir,
        run_id=prefix,
        run_type="calibration",
        crop="eggplant" if "eggplant" in mode else "tomato",
        mode=mode,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        git_commit=git_info.get("git_commit", ""),
        git_branch=git_info.get("git_branch", ""),
        git_dirty=git_info.get("git_dirty", False),
        dssat_root=os.path.dirname(WORKSPACE),
        workspace_root=WORKSPACE,
        batch_file=os.path.basename(args.batch) if args.batch else None,
        batch_sha256=(sha256_file(args.batch) if args.batch and os.path.isfile(args.batch) else ""),
        input_dir=USER_INPUT_DIR or "",
        input_manifest_sha256=(
            sha256_file(Path(USER_INPUT_DIR) / "input_manifest.json")
            if USER_INPUT_DIR and (Path(USER_INPUT_DIR) / "input_manifest.json").is_file()
            else ""
        ),
        bounds_id=args.bounds_id or "",
        bounds_csv=brm_csv if brm_mode != "off" else "",
        bounds_sha256=(sha256_file(brm_csv) if brm_csv and os.path.isfile(brm_csv) else ""),
        tighten_from=[os.path.basename(p) for p in (args.tighten_from or [])],
        tighten_frac=args.tighten_frac,
        noptmax=args.noptmax,
        ies_num_reals=args.ies_num_reals,
        random_seed=args.random_seed,
        harvest_var=harvest_var,
        n_params=len(params),
        design_config=(str(design_spec.path) if design_spec is not None else ""),
        design_table_id=(design_spec.design_table_id if design_spec is not None else ""),
        design_stage=(design_spec.stage if design_spec is not None else ""),
        active_params=(list(design_spec.active_params) if design_spec is not None else []),
        validation_split_id=(design_spec.validation_split_id if design_spec is not None else ""),
        calibration_treatments=(sorted(design_spec.calibration_treatments) if design_spec is not None else []),
        validation_treatments=(sorted(design_spec.validation_treatments) if design_spec is not None else []),
        diagnostic_treatments=(sorted(design_spec.diagnostic_treatments) if design_spec is not None else []),
        design_observation_report=design_observation_report,
        design_representative_outputs=(
            design_spec.observation.get("representative_outputs", {}) if design_spec is not None else {}
        ),
        design_audit_csv=design_audit_path,
        weight_policy_id=(POLICY_VERSION if observation_policies else WEIGHT_POLICY_ID),
        observation_policy_csv=(
            os.path.abspath(args.observation_policy_csv) if args.observation_policy_csv else ""
        ),
        observation_policy_sha256=(
            sha256_file(args.observation_policy_csv)
            if args.observation_policy_csv and os.path.isfile(args.observation_policy_csv)
            else ""
        ),
        bad_phi_sigma=ies_contract.get("bad_phi_sigma"),
        relative_phi_screening=ies_contract.get("relative_phi_screening"),
        observation_noise_contract=ies_contract.get("observation_noise"),
        observation_ensemble=ies_contract.get("observation_ensemble", ""),
        observation_noise_metadata=ies_contract.get("observation_noise_metadata", ""),
        observation_noise_seed=ies_contract.get("observation_noise_seed"),
        observation_ensemble_sha256=ies_contract.get("observation_ensemble_sha256", ""),
        design_config_sha256=(sha256_file(design_spec.path) if design_spec is not None else ""),
        validation_split_sha256=(
            sha256_file(design_spec.observation["split_path"])
            if design_spec is not None and os.path.isfile(design_spec.observation["split_path"])
            else ""
        ),
        approval_scope=(design_spec.approval_scope if design_spec is not None else ""),
        fixed_from=[str(Path(p).resolve()) for p in (args.fixed_from or [])],
        fixed_from_sha256=[
            sha256_file(Path(p).resolve())
            for p in (args.fixed_from or [])
            if Path(p).expanduser().is_file()
        ],
        fixed_from_upstream_run_ids=[item["run_id"] for item in fixed_from_provenance],
        fixed_from_upstream_engineering_status=[item["engineering_status"] for item in fixed_from_provenance],
        fixed_from_upstream_science_status=[item["science_status"] for item in fixed_from_provenance],
        fixed_from_upstream_manifest_sha256=[item["run_manifest_sha256"] for item in fixed_from_provenance],
        fixed_from_upstream_finalize_sha256=[item["finalize_sha256"] for item in fixed_from_provenance],
        operator=os.environ.get("USERNAME", "unknown"),
        command_line=" ".join(sys.argv),
    )
    print(f"Run manifest written to {manifest_path}")
