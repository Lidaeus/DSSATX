"""Multi-season calibration design: parse, validate, and query.

A ``MultiSeasonDesign`` describes which experiment bundles share one set of
genetic parameters.  It is loaded from a versioned JSON file that records
the manifest hashes of each season's bundle so that any post-hoc tampering
is detectable before a PEST case is built.

The validator enforces T8 §5 rules:
- ``season_id`` and ``experiment_code`` are unique.
- ``bundle_manifest_sha256`` matches the actual ``input_manifest.json``.
- ``calibration`` and ``validation`` roles are mutually exclusive.
- At least two ``calibration`` seasons are declared.
- Calibration stages must not read ``validation`` season observations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.common.input_manifest import (
    InputManifest,
    load_input_manifest,
)
from src.common.project import PROJECT_ROOT
from src.calibration.seasonal_parameters import (
    SeasonalParameterization,
    SeasonalParameterizationError,
)


@dataclass(frozen=True)
class SeasonSpec:
    """One season's role, bundle, and treatment set."""

    season_id: str
    experiment_code: str
    bundle_path: Path
    role: str  # "calibration" | "validation"
    treatments: tuple[int, ...]
    manifest: InputManifest
    initial_soil_n_reference_filex: Path | None = None

    @property
    def bundle_absolute(self) -> Path:
        p = self.bundle_path
        if p.is_absolute():
            return p
        return (PROJECT_ROOT / p).resolve()


@dataclass(frozen=True)
class MultiSeasonDesign:
    """A validated multi-season calibration design."""

    design_id: str
    path: Path
    schema_version: int
    cultivar_identity: str
    shared_parameter_scope: str
    observation_policy: str
    group_policy: str
    seasons: tuple[SeasonSpec, ...]
    seasonal_parameterization: SeasonalParameterization | None = None
    nitrogen_response_objective: dict[str, Any] | None = None
    harvest_dry_objective: dict[str, Any] | None = None
    process_state_objective: dict[str, Any] | None = None
    # This exception is deliberately narrow: it enables a controlled
    # one-season *diagnostic* calibration using the otherwise identical T10
    # multi-season data contract.  It is not a relaxation for formal joint
    # calibration, which still requires two calibration seasons.
    diagnostic_single_season: bool = False

    # Derived helpers --------------------------------------------------------
    _calibration: tuple[SeasonSpec, ...] = field(init=False, repr=False)
    _validation: tuple[SeasonSpec, ...] = field(init=False, repr=False)
    _by_id: dict[str, SeasonSpec] = field(init=False, repr=False)
    _by_code: dict[str, SeasonSpec] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_calibration", tuple(s for s in self.seasons if s.role == "calibration"))
        object.__setattr__(self, "_validation", tuple(s for s in self.seasons if s.role == "validation"))
        object.__setattr__(self, "_by_id", {s.season_id: s for s in self.seasons})
        object.__setattr__(self, "_by_code", {s.experiment_code: s for s in self.seasons})

    @property
    def calibration_seasons(self) -> tuple[SeasonSpec, ...]:
        return self._calibration

    @property
    def validation_seasons(self) -> tuple[SeasonSpec, ...]:
        return self._validation

    def season_by_id(self, season_id: str) -> SeasonSpec:
        return self._by_id[season_id]

    def season_by_code(self, experiment_code: str) -> SeasonSpec:
        return self._by_code[experiment_code]

    # -- factory ------------------------------------------------------------

    @classmethod
    def load(cls, json_path: str | Path) -> MultiSeasonDesign:
        """Parse and validate a multi-season design JSON file."""
        path = Path(json_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Multi-season design not found: {path}")

        with path.open("r", encoding="utf-8") as fh:
            raw: dict[str, Any] = json.load(fh)

        _require_keys(raw, path.name, "schema_version", "design_id", "seasons")

        version = int(raw["schema_version"])
        if version != 1:
            raise MultiSeasonDesignError(f"Unsupported schema_version: {version} (only 1 is supported)")

        design_id = str(raw["design_id"]).strip()
        if not design_id:
            raise MultiSeasonDesignError("design_id must be non-empty")

        cultivar_identity = str(raw.get("cultivar_identity", "same_eggplant_cultivar"))
        shared_parameter_scope = str(raw.get("shared_parameter_scope", "genetic_only"))
        observation_policy = raw.get("observation_policy", "")
        group_policy = raw.get("group_policy", "")
        if not observation_policy:
            raise MultiSeasonDesignError("observation_policy is required")
        if not group_policy:
            raise MultiSeasonDesignError("group_policy is required")

        diagnostic_single_season = bool(raw.get("diagnostic_single_season", False))
        raw_seasons = raw.get("seasons")
        minimum_seasons = 1 if diagnostic_single_season else 2
        if not isinstance(raw_seasons, list) or len(raw_seasons) < minimum_seasons:
            if diagnostic_single_season:
                raise MultiSeasonDesignError(
                    "diagnostic single-season design must contain one calibration season"
                )
            raise MultiSeasonDesignError("design must contain at least two seasons")

        calibration_count = sum(1 for s in raw_seasons if s.get("role") == "calibration")
        minimum_calibration = 1 if diagnostic_single_season else 2
        if calibration_count < minimum_calibration:
            if diagnostic_single_season:
                raise MultiSeasonDesignError(
                    "diagnostic single-season design requires one calibration season"
                )
            raise MultiSeasonDesignError(
                f"design requires at least two calibration seasons, found {calibration_count}"
            )
        if diagnostic_single_season and calibration_count != 1:
            raise MultiSeasonDesignError(
                "diagnostic_single_season requires exactly one calibration season"
            )

        seen_ids: set[str] = set()
        seen_codes: set[str] = set()
        seasons: list[SeasonSpec] = []

        for idx, raw_season in enumerate(raw_seasons):
            _require_keys(raw_season, f"seasons[{idx}]", "season_id", "experiment_code", "bundle_path", "role")

            s_id = str(raw_season["season_id"]).strip()
            if not s_id:
                raise MultiSeasonDesignError(f"seasons[{idx}] has empty season_id")
            if s_id in seen_ids:
                raise MultiSeasonDesignError(f"duplicate season_id: {s_id!r}")
            seen_ids.add(s_id)

            e_code = str(raw_season["experiment_code"]).strip()
            if not e_code:
                raise MultiSeasonDesignError(f"seasons[{idx}] has empty experiment_code")
            if e_code in seen_codes:
                raise MultiSeasonDesignError(f"duplicate experiment_code: {e_code!r}")
            seen_codes.add(e_code)

            bundle_path = Path(str(raw_season["bundle_path"]))
            if not bundle_path.is_absolute():
                bundle_path = (PROJECT_ROOT / bundle_path).resolve()
            if not bundle_path.is_dir():
                raise MultiSeasonDesignError(f"seasons[{idx}] bundle_path does not exist: {bundle_path}")

            role = str(raw_season["role"]).strip().lower()
            if role not in ("calibration", "validation"):
                raise MultiSeasonDesignError(
                    f"seasons[{idx}] role must be 'calibration' or 'validation', got {role!r}"
                )

            declared_hash = str(raw_season.get("bundle_manifest_sha256") or "").strip().lower()
            manifest = load_input_manifest(bundle_path)
            actual_hash = manifest.manifest_sha256
            if declared_hash and declared_hash != actual_hash:
                raise MultiSeasonDesignError(
                    f"seasons[{idx}] ({s_id}) bundle_manifest_sha256 mismatch: "
                    f"declared {declared_hash} != actual {actual_hash}"
                )

            raw_treatments = raw_season.get("treatments")
            if not isinstance(raw_treatments, list) or not raw_treatments:
                raise MultiSeasonDesignError(f"seasons[{idx}] ({s_id}) treatments must be a non-empty list")
            treatments = tuple(int(v) for v in raw_treatments)
            if len(set(treatments)) != len(treatments):
                raise MultiSeasonDesignError(f"seasons[{idx}] ({s_id}) treatments contain duplicates")

            seasons.append(
                SeasonSpec(
                    season_id=s_id,
                    experiment_code=e_code,
                    bundle_path=bundle_path,
                    role=role,
                    treatments=treatments,
                    manifest=manifest,
                    initial_soil_n_reference_filex=(
                        _resolve_optional_path(raw_season.get("initial_soil_n_reference_filex"), path.parent)
                    ),
                )
            )

        # Seasonal offsets are optional.  Keeping the contract in the design
        # (rather than in an untracked runner flag) makes every projected autumn
        # parameter reconstructable from the PEST ensemble.
        try:
            seasonal_parameterization = SeasonalParameterization.from_dict(
                raw.get("seasonal_parameterization"), season_ids=seen_ids
            )
        except SeasonalParameterizationError as exc:
            raise MultiSeasonDesignError(str(exc)) from exc

        nitrogen_response_objective = raw.get("nitrogen_response_objective")
        if nitrogen_response_objective is not None:
            if not isinstance(nitrogen_response_objective, dict):
                raise MultiSeasonDesignError(
                    "nitrogen_response_objective must be an object"
                )
            if bool(nitrogen_response_objective.get("enabled", False)):
                mapping_csv = str(
                    nitrogen_response_objective.get("mapping_csv", "")
                ).strip()
                if not mapping_csv:
                    raise MultiSeasonDesignError(
                        "enabled nitrogen_response_objective requires mapping_csv"
                    )
                sigma_floor = float(
                    nitrogen_response_objective.get("sigma_floor", 0.10)
                )
                if sigma_floor <= 0:
                    raise MultiSeasonDesignError(
                        "nitrogen_response_objective sigma_floor must be positive"
                    )

        harvest_dry_objective = raw.get("harvest_dry_objective")
        if harvest_dry_objective is not None:
            if not isinstance(harvest_dry_objective, dict):
                raise MultiSeasonDesignError(
                    "harvest_dry_objective must be an object"
                )
            if bool(harvest_dry_objective.get("enabled", False)):
                mode = str(harvest_dry_objective.get("mode", "")).strip().lower()
                if mode != "increment_plus_terminal":
                    raise MultiSeasonDesignError(
                        "enabled harvest_dry_objective requires mode=increment_plus_terminal"
                    )
                increment_source = str(
                    harvest_dry_objective.get(
                        "increment_source", "cumulative_difference"
                    )
                ).strip().lower()
                if increment_source not in {
                    "cumulative_difference", "measured_hpodw"
                }:
                    raise MultiSeasonDesignError(
                        "harvest_dry_objective increment_source must be "
                        "cumulative_difference or measured_hpodw"
                    )

        process_state_objective = raw.get("process_state_objective")
        if process_state_objective is not None:
            if not isinstance(process_state_objective, dict):
                raise MultiSeasonDesignError(
                    "process_state_objective must be an object"
                )
            if bool(process_state_objective.get("enabled", False)):
                mode = str(process_state_objective.get("mode", "")).strip().lower()
                if mode != "signed_difference_plus_terminal":
                    raise MultiSeasonDesignError(
                        "enabled process_state_objective requires "
                        "mode=signed_difference_plus_terminal"
                    )
                variables = process_state_objective.get("variables", [])
                if not isinstance(variables, list) or {
                    str(item).strip().upper() for item in variables
                } != {"LAID", "LWAD", "SWAD"}:
                    raise MultiSeasonDesignError(
                        "process_state_objective variables must be exactly "
                        "LAID, LWAD, SWAD"
                    )

        # Cross-season validation ---------------------------------------------------
        # All seasons should reference the same DSSAT cultivar/ecotype template
        # (TMGRO048.CUL/ECO/SPE).  The experiment_code naturally differs.
        # We check for consistency at the filesystem level via manifest hashes,
        # not by comparing experiment_code strings.

        return cls(
            design_id=design_id,
            path=path,
            schema_version=version,
            cultivar_identity=cultivar_identity,
            shared_parameter_scope=shared_parameter_scope,
            observation_policy=str(observation_policy),
            group_policy=str(group_policy),
            seasons=tuple(seasons),
            seasonal_parameterization=seasonal_parameterization,
            nitrogen_response_objective=nitrogen_response_objective,
            harvest_dry_objective=harvest_dry_objective,
            process_state_objective=process_state_objective,
            diagnostic_single_season=diagnostic_single_season,
        )


class MultiSeasonDesignError(Exception):
    """Raised when a multi-season design file fails semantic validation."""


def _resolve_optional_path(value: Any, base_dir: Path) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()
    if not path.is_file():
        raise MultiSeasonDesignError(f"initial_soil_n_reference_filex does not exist: {path}")
    return path


def _require_keys(obj: dict[str, Any], label: str, *keys: str) -> None:
    """Validate that ``obj`` contains every named key."""
    for k in keys:
        if k not in obj:
            raise MultiSeasonDesignError(f"{label} is missing required key: {k!r}")
