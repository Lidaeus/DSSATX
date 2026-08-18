"""Experiment specification: parse, hash, and enforce the calibration contract.

An :class:`ExperimentSpec` is the single auditable entry point for every
calibration experiment in the article matrix (E00--E07).  It binds together:

* a **parameter set** (which genetic parameters, with provenance),
* a **frozen bounds** CSV (the only bounds layer calibration may consume),
* an **observation profile** (which variables enter Phi and on what scale),
* a **multi-season design** (which experiment bundles, treatments, roles),
* an **execution config** (IES realisation count, updates, seed).

Every referenced artefact is SHA-256 pinned.  The spec rejects:

* ``DEFAULT_BOUNDS`` or implicit code fallbacks,
* forbidden Phi targets (PWAD, PWAI, HWAM),
* parameter-count mismatches between the declared set and the frozen CSV,
* 26SP labelled as ``validation`` when the experiment uses it for
  calibration or pooled development.

The module deliberately imports no plotting library and no DSSAT/PEST++
runner; it only reads JSON/CSV and computes hashes.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from src.common.project import PROJECT_ROOT, sha256_file


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORBIDDEN_PHI_TARGETS: frozenset[str] = frozenset({"PWAD", "PWAI", "HWAM"})
"""Variables that must never enter the formal Phi under the article contract."""

REQUIRED_PHI_TARGET: str = "CHPDT"
"""The only variable that may serve as the active cumulative-harvest Phi target."""

ALLOWED_SEASON_ROLES: frozenset[str] = frozenset({
    "calibration",
    "validation",
    "frozen_validation",
    "diagnostic",
    "development_calibration",
})
"""Roles a season may take in an experiment spec.

``frozen_validation`` is the pre-E02 label for 26SP.  Once 26SP enters any
calibration or pooled run (E02 single-season diagnostic, E06 pooled), the
spec must relabel it as ``diagnostic`` or ``development_calibration``.
"""

SCHEMA_VERSION: int = 1


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ExperimentSpecError(Exception):
    """Raised when an experiment spec fails contract validation."""


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParameterSet:
    """A frozen, auditable parameter set definition."""

    set_id: str
    path: Path
    sha256: str
    parameters: tuple[str, ...]        # sorted, uppercase
    declared_count: int
    source_file: str
    source_sha256: str
    applicable_observations: str
    approval_note: str


@dataclass(frozen=True)
class ObservationProfile:
    """The observation contract: what enters Phi and on what scale."""

    profile_id: str
    path: Path
    sha256: str
    active_phi_targets: tuple[str, ...]
    diagnostic_targets: tuple[str, ...]
    transform: str            # e.g. "ln(y+1)"
    offset: float
    reference: float


@dataclass(frozen=True)
class SeasonInput:
    """One season's role and input bundle hash in the experiment."""

    season_id: str
    role: str
    input_manifest_path: Path
    input_manifest_sha256: str


@dataclass(frozen=True)
class ExecutionConfig:
    """IES numerical settings that must be identical across comparisons."""

    ies_num_reals: int
    noptmax: int
    seed: int
    min_retention_rate: float = 0.95


@dataclass(frozen=True)
class ExperimentSpec:
    """A validated, SHA-256-pinned calibration experiment specification."""

    experiment_id: str
    scientific_role: str
    path: Path
    sha256: str

    parameter_set: ParameterSet
    bounds_id: str
    bounds_path: Path
    bounds_sha256: str
    bounds_active_count: int           # active params in frozen CSV

    observation_profile: ObservationProfile
    season_inputs: tuple[SeasonInput, ...]
    execution: ExecutionConfig

    multiseason_design_path: Path | None
    multiseason_design_sha256: str | None

    seasonal_parameterization: dict[str, Any] | None
    representative_rule: str
    evaluation_profile: str

    # -- factory ------------------------------------------------------------

    @classmethod
    def load(cls, spec_path: str | Path) -> ExperimentSpec:
        """Parse and fully validate an experiment spec JSON file.

        Raises :class:`ExperimentSpecError` on any contract violation.
        """
        path = Path(spec_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Experiment spec not found: {path}")

        with path.open("r", encoding="utf-8") as fh:
            raw: dict[str, Any] = json.load(fh)

        spec_sha256 = sha256_file(path)

        _require_keys(raw, path.name, "experiment_id", "scientific_role",
                       "parameter_set", "bounds_id", "observation_profile",
                       "execution", "representative_rule", "evaluation_profile")

        experiment_id = str(raw["experiment_id"]).strip()
        scientific_role = str(raw["scientific_role"]).strip()

        # -- parameter set --------------------------------------------------
        pset = _load_parameter_set(raw["parameter_set"])

        # -- frozen bounds --------------------------------------------------
        bounds_id = str(raw["bounds_id"]).strip()
        bounds_path = _resolve_frozen_bounds_path(bounds_id)
        bounds_sha256 = sha256_file(bounds_path)
        bounds_active_count = _count_active_params(bounds_path)

        if bounds_active_count != pset.declared_count:
            raise ExperimentSpecError(
                f"Parameter count mismatch: parameter set '{pset.set_id}' "
                f"declares {pset.declared_count} parameters, but frozen bounds "
                f"'{bounds_id}' has {bounds_active_count} active parameters."
            )

        # Verify every declared parameter exists in the frozen CSV
        frozen_names = _read_frozen_param_names(bounds_path)
        missing = set(pset.parameters) - frozen_names
        if missing:
            raise ExperimentSpecError(
                f"Parameters declared in set '{pset.set_id}' but absent from "
                f"frozen bounds '{bounds_id}': {sorted(missing)}"
            )

        # -- observation profile --------------------------------------------
        obs_profile = _load_observation_profile(raw["observation_profile"])

        # Reject forbidden targets
        forbidden_in_phi = set(obs_profile.active_phi_targets) & FORBIDDEN_PHI_TARGETS
        if forbidden_in_phi:
            raise ExperimentSpecError(
                f"Forbidden variables in active Phi targets: {sorted(forbidden_in_phi)}. "
                f"The article contract prohibits {sorted(FORBIDDEN_PHI_TARGETS)} "
                f"from entering formal Phi."
            )

        # Verify CHPDT is the active target
        if REQUIRED_PHI_TARGET not in obs_profile.active_phi_targets:
            raise ExperimentSpecError(
                f"Observation profile '{obs_profile.profile_id}' must include "
                f"'{REQUIRED_PHI_TARGET}' as an active Phi target."
            )

        # -- season inputs --------------------------------------------------
        raw_seasons = raw.get("season_inputs", [])
        if not isinstance(raw_seasons, list) or not raw_seasons:
            raise ExperimentSpecError("season_inputs must be a non-empty list")

        season_inputs: list[SeasonInput] = []
        for idx, raw_season in enumerate(raw_seasons):
            _require_keys(raw_season, f"season_inputs[{idx}]",
                          "season_id", "role", "input_manifest", "sha256")
            s_id = str(raw_season["season_id"]).strip()
            role = str(raw_season["role"]).strip()
            if role not in ALLOWED_SEASON_ROLES:
                raise ExperimentSpecError(
                    f"season_inputs[{idx}] ({s_id}) has invalid role '{role}'. "
                    f"Allowed: {sorted(ALLOWED_SEASON_ROLES)}"
                )
            manifest_path = _resolve_path(raw_season["input_manifest"])
            declared_sha = str(raw_season["sha256"]).strip().lower()
            actual_sha = sha256_file(manifest_path)
            if declared_sha and declared_sha != actual_sha:
                raise ExperimentSpecError(
                    f"season_inputs[{idx}] ({s_id}) input_manifest SHA-256 mismatch: "
                    f"declared {declared_sha} != actual {actual_sha}"
                )
            season_inputs.append(SeasonInput(
                season_id=s_id,
                role=role,
                input_manifest_path=manifest_path,
                input_manifest_sha256=actual_sha,
            ))

        # -- 26SP role enforcement ------------------------------------------
        _enforce_26sp_role(experiment_id, season_inputs)

        # -- multiseason design (optional, for builder) ---------------------
        ms_design_path = None
        ms_design_sha = None
        ms_raw = raw.get("multiseason_design")
        if ms_raw:
            ms_design_path = _resolve_path(ms_raw)
            ms_design_sha = sha256_file(ms_design_path)

        # -- execution ------------------------------------------------------
        exec_raw = raw["execution"]
        _require_keys(exec_raw, "execution",
                      "ies_num_reals", "noptmax", "seed")
        execution = ExecutionConfig(
            ies_num_reals=int(exec_raw["ies_num_reals"]),
            noptmax=int(exec_raw["noptmax"]),
            seed=int(exec_raw["seed"]),
            min_retention_rate=float(exec_raw.get("min_retention_rate", 0.95)),
        )
        if execution.ies_num_reals < 1:
            raise ExperimentSpecError("ies_num_reals must be >= 1")
        if execution.noptmax < 0:
            raise ExperimentSpecError("noptmax must be >= 0")

        # -- seasonal parameterization (E05 autumn offsets) -----------------
        seasonal_param = raw.get("seasonal_parameterization")
        if seasonal_param is not None:
            _validate_seasonal_parameterization(seasonal_param, season_inputs)

        return cls(
            experiment_id=experiment_id,
            scientific_role=scientific_role,
            path=path,
            sha256=spec_sha256,
            parameter_set=pset,
            bounds_id=bounds_id,
            bounds_path=bounds_path,
            bounds_sha256=bounds_sha256,
            bounds_active_count=bounds_active_count,
            observation_profile=obs_profile,
            season_inputs=tuple(season_inputs),
            execution=execution,
            multiseason_design_path=ms_design_path,
            multiseason_design_sha256=ms_design_sha,
            seasonal_parameterization=seasonal_param,
            representative_rule=str(raw["representative_rule"]).strip(),
            evaluation_profile=str(raw["evaluation_profile"]).strip(),
        )

    # -- receipt ------------------------------------------------------------

    def receipt(self) -> dict[str, Any]:
        """Generate the ``experiment_receipt.json`` content."""
        return {
            "experiment_id": self.experiment_id,
            "scientific_role": self.scientific_role,
            "spec_path": str(self.path),
            "spec_sha256": self.sha256,
            "parameter_set": {
                "set_id": self.parameter_set.set_id,
                "path": str(self.parameter_set.path),
                "sha256": self.parameter_set.sha256,
                "parameters": list(self.parameter_set.parameters),
                "declared_count": self.parameter_set.declared_count,
                "source_file": self.parameter_set.source_file,
                "source_sha256": self.parameter_set.source_sha256,
            },
            "bounds": {
                "bounds_id": self.bounds_id,
                "path": str(self.bounds_path),
                "sha256": self.bounds_sha256,
                "active_count": self.bounds_active_count,
            },
            "observation_profile": {
                "profile_id": self.observation_profile.profile_id,
                "path": str(self.observation_profile.path),
                "sha256": self.observation_profile.sha256,
                "active_phi_targets": list(self.observation_profile.active_phi_targets),
                "diagnostic_targets": list(self.observation_profile.diagnostic_targets),
                "transform": self.observation_profile.transform,
            },
            "season_inputs": [
                {
                    "season_id": s.season_id,
                    "role": s.role,
                    "input_manifest_path": str(s.input_manifest_path),
                    "input_manifest_sha256": s.input_manifest_sha256,
                }
                for s in self.season_inputs
            ],
            "execution": {
                "ies_num_reals": self.execution.ies_num_reals,
                "noptmax": self.execution.noptmax,
                "seed": self.execution.seed,
                "min_retention_rate": self.execution.min_retention_rate,
            },
            "multiseason_design": {
                "path": str(self.multiseason_design_path) if self.multiseason_design_path else None,
                "sha256": self.multiseason_design_sha256,
            } if self.multiseason_design_path else None,
            "seasonal_parameterization": self.seasonal_parameterization,
            "representative_rule": self.representative_rule,
            "evaluation_profile": self.evaluation_profile,
        }


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_parameter_set(ref: str | dict[str, Any]) -> ParameterSet:
    """Load and validate a parameter set JSON file or inline dict."""
    if isinstance(ref, str):
        path = _resolve_path(ref)
    elif isinstance(ref, dict):
        _require_keys(ref, "parameter_set (inline)",
                      "set_id", "path", "parameters", "source_file",
                      "source_sha256", "applicable_observations", "approval_note")
        path = _resolve_path(ref["path"])
        raw = ref
    else:
        raise ExperimentSpecError(f"parameter_set must be a path string or dict, got {type(ref)}")

    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    _require_keys(raw, path.name, "set_id", "parameters", "source_file",
                  "source_sha256", "applicable_observations", "approval_note")

    set_id = str(raw["set_id"]).strip()
    raw_params = raw["parameters"]
    if not isinstance(raw_params, list) or not raw_params:
        raise ExperimentSpecError(
            f"Parameter set '{set_id}' parameters must be a non-empty list"
        )
    params = tuple(sorted(str(p).strip().upper() for p in raw_params))
    if len(set(params)) != len(params):
        raise ExperimentSpecError(
            f"Parameter set '{set_id}' contains duplicate parameter names"
        )

    declared_count = int(raw.get("declared_count", len(params)))
    if declared_count != len(params):
        raise ExperimentSpecError(
            f"Parameter set '{set_id}' declared_count={declared_count} "
            f"but parameters list has {len(params)} entries"
        )

    return ParameterSet(
        set_id=set_id,
        path=path,
        sha256=sha256_file(path),
        parameters=params,
        declared_count=declared_count,
        source_file=str(raw["source_file"]),
        source_sha256=str(raw["source_sha256"]),
        applicable_observations=str(raw["applicable_observations"]),
        approval_note=str(raw["approval_note"]),
    )


def _load_observation_profile(ref: str) -> ObservationProfile:
    """Load and validate an observation profile JSON file."""
    path = _resolve_path(ref)
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    _require_keys(raw, path.name, "profile_id", "active_phi_targets",
                  "transform")

    profile_id = str(raw["profile_id"]).strip()
    active = tuple(str(t).strip().upper()
                   for t in raw["active_phi_targets"])
    diagnostic = tuple(str(t).strip().upper()
                       for t in raw.get("diagnostic_targets", []))

    transform = str(raw["transform"]).strip()
    offset = float(raw.get("offset", 1.0))
    reference = float(raw.get("reference", 1.0))

    return ObservationProfile(
        profile_id=profile_id,
        path=path,
        sha256=sha256_file(path),
        active_phi_targets=active,
        diagnostic_targets=diagnostic,
        transform=transform,
        offset=offset,
        reference=reference,
    )


def _validate_seasonal_parameterization(
    seasonal: dict[str, Any],
    season_inputs: Sequence[SeasonInput],
) -> None:
    """Validate E05 autumn offset configuration."""
    if not isinstance(seasonal, dict):
        raise ExperimentSpecError("seasonal_parameterization must be a dict")

    offsets = seasonal.get("offsets", [])
    if not isinstance(offsets, list):
        raise ExperimentSpecError("seasonal_parameterization.offsets must be a list")

    if len(offsets) == 0:
        raise ExperimentSpecError(
            "seasonal_parameterization.offsets is empty. "
            "E05 autumn offsets must be non-empty and approved before running."
        )

    if len(offsets) > 3:
        raise ExperimentSpecError(
            f"E05 allows at most 3 autumn offsets, got {len(offsets)}"
        )

    season_ids = {s.season_id for s in season_inputs}
    for idx, off in enumerate(offsets):
        _require_keys(off, f"seasonal_parameterization.offsets[{idx}]",
                      "parameter", "transform", "range", "physiological_basis",
                      "frozen_reason", "target_season")
        target = str(off["target_season"]).strip()
        if target not in season_ids:
            raise ExperimentSpecError(
                f"offsets[{idx}] target_season '{target}' not in season_inputs"
            )
        transform = str(off["transform"]).strip().lower()
        if transform not in ("additive", "log", "logit"):
            raise ExperimentSpecError(
                f"offsets[{idx}] transform must be additive/log/logit, got '{transform}'"
            )

    # DMC offset is forbidden under CHPDT-only contract
    for idx, off in enumerate(offsets):
        param = str(off["parameter"]).strip().upper()
        if param in ("DMC", "DMC_OFFSET"):
            raise ExperimentSpecError(
                f"offsets[{idx}] parameter '{param}' is forbidden: "
                f"DMC offset cannot be freely calibrated under CHPDT-only contract."
            )


# ---------------------------------------------------------------------------
# Frozen bounds helpers
# ---------------------------------------------------------------------------

def _resolve_frozen_bounds_path(bounds_id: str) -> Path:
    """Resolve a bounds_id to a frozen bounds CSV path.

    Accepts either a full path or a bare bounds-id (resolved against the
    ``bounds_frozen/eggplant/`` directory).  Rejects paths under
    ``bounds_proposals/`` to prevent bypassing the freeze-approval step.
    """
    # Full path
    candidate = Path(bounds_id)
    if candidate.is_absolute() or candidate.exists():
        resolved = candidate.resolve()
    else:
        # Bare bounds-id: look in frozen directory
        frozen_dir = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant"
        resolved = (frozen_dir / f"{bounds_id}.csv").resolve()

    if not resolved.is_file():
        raise ExperimentSpecError(
            f"Frozen bounds CSV not found for bounds_id '{bounds_id}': {resolved}"
        )

    # Reject proposals path (must go through freeze_bounds.py approval)
    parts = resolved.parts
    if "bounds_proposals" in parts:
        raise ExperimentSpecError(
            f"bounds_id '{bounds_id}' resolves to a proposals path ({resolved}). "
            f"Use freeze_bounds.py to promote proposal -> frozen before calibration."
        )

    return resolved


def _count_active_params(bounds_path: Path) -> int:
    """Count ``active`` parameters in a frozen bounds CSV."""
    count = 0
    with bounds_path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("status", "")).strip().lower() == "active":
                count += 1
    return count


def _read_frozen_param_names(bounds_path: Path) -> set[str]:
    """Return the set of all parameter names in a frozen bounds CSV."""
    names: set[str] = set()
    with bounds_path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name = str(row.get("name", "")).strip().upper()
            if name:
                names.add(name)
    return names


# ---------------------------------------------------------------------------
# 26SP role enforcement
# ---------------------------------------------------------------------------

def _enforce_26sp_role(
    experiment_id: str,
    season_inputs: Sequence[SeasonInput],
) -> None:
    """Enforce that 26SP is not labelled as independent validation when it
    participates in calibration or pooled development.

    The rule (from the article matrix §2 and §3):
    * 26SP as ``frozen_validation`` is only valid before E02.
    * Once 26SP enters any single-season diagnostic (E02) or pooled run (E06),
      it must be labelled ``diagnostic`` or ``development_calibration``.
    * ``validation`` is reserved for a future season/location not used in
      model development (E07).
    """
    for s in season_inputs:
        if s.season_id.upper() == "26SP":
            if s.role == "validation":
                raise ExperimentSpecError(
                    f"Experiment '{experiment_id}': 26SP is labelled 'validation' "
                    f"but has been used in model development (E02/E06). "
                    f"Use 'diagnostic' or 'development_calibration' instead. "
                    f"True validation requires a new season/location (E07)."
                )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _resolve_path(value: str | Path) -> Path:
    """Resolve a path relative to the project root."""
    p = Path(value).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (PROJECT_ROOT / p).resolve()


def _require_keys(obj: dict[str, Any], label: str, *keys: str) -> None:
    """Validate that ``obj`` contains every named key."""
    for k in keys:
        if k not in obj:
            raise ExperimentSpecError(f"{label} is missing required key: {k!r}")


# ---------------------------------------------------------------------------
# Matrix-level consistency
# ---------------------------------------------------------------------------

def validate_matrix_consistency(matrix_json: str | Path) -> list[str]:
    """Validate that experiments in each comparison group share identical
    execution settings, observation profile, and season input manifests.

    The article contract (§3) requires that 23-parameter, 55-parameter, and
    autumn-offset comparisons keep data, weights, seed, and run scale
    identical — otherwise a Phi difference cannot be attributed to the
    parameter dimensionality alone.

    Template specs that fail to load (e.g. E02/E03 before E01 bounds
    approval) are silently skipped; they are validated separately by
    :meth:`ExperimentSpec.load`.

    Parameters
    ----------
    matrix_json
        Path to the article calibration matrix JSON.

    Returns
    -------
    list[str]
        Violation messages.  Empty if every loadable comparison group is
        internally consistent.
    """
    matrix_path = _resolve_path(matrix_json)
    with matrix_path.open("r", encoding="utf-8") as fh:
        matrix = json.load(fh)

    groups = matrix.get("comparison_groups", {})
    if not groups:
        return []

    experiments: dict[str, str] = matrix.get("experiments", {})
    violations: list[str] = []

    for group_id, group_def in groups.items():
        members: list[str] = group_def.get("members", [])
        if len(members) < 2:
            continue

        # Load member specs, skipping template specs that fail contract
        # validation (e.g. E03/E05 before E01 produces 23-active bounds).
        loaded: list[tuple[str, ExperimentSpec]] = []
        for exp_id in members:
            spec_path = experiments.get(exp_id)
            if not spec_path:
                violations.append(
                    f"Group '{group_id}': member '{exp_id}' not in matrix.experiments"
                )
                continue
            try:
                loaded.append((exp_id, ExperimentSpec.load(spec_path)))
            except (ExperimentSpecError, FileNotFoundError):
                continue  # Template spec — validated separately on load

        if len(loaded) < 2:
            continue  # Not enough loadable members to compare

        baseline_id, baseline = loaded[0]
        for exp_id, spec in loaded[1:]:
            if spec.execution.seed != baseline.execution.seed:
                violations.append(
                    f"Group '{group_id}': {exp_id} seed={spec.execution.seed} "
                    f"!= {baseline_id} seed={baseline.execution.seed}"
                )
            if spec.execution.ies_num_reals != baseline.execution.ies_num_reals:
                violations.append(
                    f"Group '{group_id}': {exp_id} ies_num_reals="
                    f"{spec.execution.ies_num_reals} != {baseline_id} "
                    f"{baseline.execution.ies_num_reals}"
                )
            if spec.execution.noptmax != baseline.execution.noptmax:
                violations.append(
                    f"Group '{group_id}': {exp_id} noptmax={spec.execution.noptmax} "
                    f"!= {baseline_id} {baseline.execution.noptmax}"
                )
            if spec.observation_profile.sha256 != baseline.observation_profile.sha256:
                violations.append(
                    f"Group '{group_id}': {exp_id} observation_profile SHA "
                    f"!= {baseline_id} (must share weights/transform)"
                )
            spec_shas = {s.input_manifest_sha256 for s in spec.season_inputs}
            base_shas = {s.input_manifest_sha256 for s in baseline.season_inputs}
            if spec_shas != base_shas:
                violations.append(
                    f"Group '{group_id}': {exp_id} season input manifests "
                    f"!= {baseline_id} (must share data)"
                )

    return violations
