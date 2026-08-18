"""Season-specific projections of shared DSSAT calibration parameters.

The PEST++ control file estimates one *shared* parameter vector.  A small,
pre-declared set of autumn adjustments is represented as additional PEST
parameters and is projected immediately before the autumn DSSAT invocation.
This keeps the calibrated object explicit:

* spring uses the shared value; and
* autumn uses a documented transform of the shared value and its offset.

The module deliberately does not implement a general time-varying acclimation
model.  With one autumn experiment, the adjustments are conditional seasonal
corrections, not a second set of cultivar genetic coefficients.
"""

from __future__ import annotations

import csv
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from src.common.param_registry import PHYSICAL_BOUNDS


class SeasonalParameterizationError(ValueError):
    """Raised when a seasonal-offset design is ambiguous or unsafe."""


@dataclass(frozen=True)
class SeasonalOffset:
    """One target parameter and the autumn adjustment applied to it."""

    offset_name: str
    parameter_name: str
    transform: str
    target_season_ids: tuple[str, ...]
    rationale: str = ""


@dataclass(frozen=True)
class SeasonalParameterization:
    """Validated shared-parameter plus seasonal-offset contract."""

    reference_season_id: str
    offsets: tuple[SeasonalOffset, ...]

    @classmethod
    def from_dict(
        cls,
        raw: object,
        *,
        season_ids: Iterable[str],
    ) -> "SeasonalParameterization | None":
        """Parse an optional JSON design block.

        ``None`` preserves the T8/T10-M0 behaviour of exactly shared
        parameters.  The compact schema intentionally has one offset per
        parameter; grouping several parameters behind one offset obscures the
        posterior interpretation.
        """
        if raw in (None, False):
            return None
        if not isinstance(raw, dict):
            raise SeasonalParameterizationError("seasonal_parameterization must be an object")
        if raw.get("enabled", True) is False:
            return None

        known_seasons = {str(value).strip() for value in season_ids}
        reference = str(raw.get("reference_season_id", "")).strip()
        if reference not in known_seasons:
            raise SeasonalParameterizationError(
                "seasonal_parameterization.reference_season_id must name a declared season"
            )
        raw_offsets = raw.get("offsets")
        if not isinstance(raw_offsets, list) or not raw_offsets:
            raise SeasonalParameterizationError(
                "seasonal_parameterization.offsets must be a non-empty list when enabled"
            )

        offsets: list[SeasonalOffset] = []
        offset_names: set[str] = set()
        parameter_names: set[str] = set()
        allowed_transforms = {"additive", "log_multiplier", "logit_additive"}
        for index, item in enumerate(raw_offsets):
            if not isinstance(item, dict):
                raise SeasonalParameterizationError(f"offsets[{index}] must be an object")
            offset_name = str(item.get("offset_name", "")).strip().upper()
            parameter_name = str(item.get("parameter_name", "")).strip().upper()
            transform = str(item.get("transform", "")).strip().lower()
            target_raw = item.get("target_season_ids")
            if not offset_name or not parameter_name:
                raise SeasonalParameterizationError(
                    f"offsets[{index}] requires offset_name and parameter_name"
                )
            if transform not in allowed_transforms:
                raise SeasonalParameterizationError(
                    f"offsets[{index}] transform must be one of {sorted(allowed_transforms)}"
                )
            if not isinstance(target_raw, list) or not target_raw:
                raise SeasonalParameterizationError(
                    f"offsets[{index}].target_season_ids must be a non-empty list"
                )
            targets = tuple(str(value).strip() for value in target_raw)
            if len(set(targets)) != len(targets) or any(value not in known_seasons for value in targets):
                raise SeasonalParameterizationError(
                    f"offsets[{index}] targets must be unique declared seasons"
                )
            if reference in targets:
                raise SeasonalParameterizationError(
                    f"offsets[{index}] must not modify the reference season {reference!r}"
                )
            if offset_name in offset_names:
                raise SeasonalParameterizationError(f"duplicate seasonal offset name: {offset_name}")
            if parameter_name in parameter_names:
                raise SeasonalParameterizationError(
                    f"each seasonal parameter requires one offset; duplicate target: {parameter_name}"
                )
            offset_names.add(offset_name)
            parameter_names.add(parameter_name)
            offsets.append(
                SeasonalOffset(
                    offset_name=offset_name,
                    parameter_name=parameter_name,
                    transform=transform,
                    target_season_ids=targets,
                    rationale=str(item.get("rationale", "")).strip(),
                )
            )
        return cls(reference_season_id=reference, offsets=tuple(offsets))

    @property
    def offset_names(self) -> set[str]:
        return {item.offset_name for item in self.offsets}

    def project(self, values: Mapping[str, float], season_id: str) -> tuple[dict[str, float], list[dict[str, object]]]:
        """Return the DSSAT parameter vector and an auditable projection table."""
        normalized = {str(name).strip().upper(): float(value) for name, value in values.items()}
        missing = [item.offset_name for item in self.offsets if item.offset_name not in normalized]
        missing += [item.parameter_name for item in self.offsets if item.parameter_name not in normalized]
        if missing:
            raise SeasonalParameterizationError(
                "parameter CSV is missing seasonal terms: " + ", ".join(sorted(set(missing)))
            )

        # Offset values are PEST-only terms, never passed to the DSSAT file writer.
        projected = {name: value for name, value in normalized.items() if name not in self.offset_names}
        audit: list[dict[str, object]] = []
        for item in self.offsets:
            shared = normalized[item.parameter_name]
            offset = normalized[item.offset_name]
            applied = season_id in item.target_season_ids
            actual = _apply_offset(shared, offset if applied else 0.0, item.transform)
            projected[item.parameter_name] = actual
            audit.append(
                {
                    "season_id": season_id,
                    "parameter": item.parameter_name,
                    "shared_value": shared,
                    "offset_name": item.offset_name,
                    "offset_value": offset,
                    "offset_applied": applied,
                    "transform": item.transform,
                    "season_value": actual,
                    "rationale": item.rationale,
                }
            )
        return projected, audit


def _apply_offset(shared: float, offset: float, transform: str) -> float:
    if transform == "additive":
        return shared + offset
    if transform == "log_multiplier":
        if shared <= 0:
            raise SeasonalParameterizationError("log_multiplier requires a strictly positive shared value")
        return shared * math.exp(offset)
    if transform == "logit_additive":
        if not 0.0 < shared < 1.0:
            raise SeasonalParameterizationError(
                "logit_additive requires its shared parameter to be strictly inside (0, 1)"
            )
        logit = math.log(shared / (1.0 - shared))
        shifted = logit + offset
        # Numerically stable logistic transform; it enforces the open physical
        # interval without clipping an IES realization after it was proposed.
        if shifted >= 0:
            return 1.0 / (1.0 + math.exp(-shifted))
        exp_shifted = math.exp(shifted)
        return exp_shifted / (1.0 + exp_shifted)
    raise SeasonalParameterizationError(f"unsupported seasonal transform: {transform!r}")


def seasonal_offset_params_from_frozen_bounds(
    parameterization: SeasonalParameterization | None,
    frozen_bounds_path: str | Path,
) -> list[dict[str, object]]:
    """Materialize PEST-only offset parameters from the approved frozen file."""
    if parameterization is None:
        return []
    path = Path(frozen_bounds_path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = {
            str(row.get("name", "")).strip().upper(): row
            for row in csv.DictReader(handle)
            if str(row.get("name", "")).strip()
        }

    params: list[dict[str, object]] = []
    for item in parameterization.offsets:
        row = rows.get(item.offset_name)
        if row is None:
            raise SeasonalParameterizationError(
                f"frozen bounds are missing seasonal offset {item.offset_name}"
            )
        if str(row.get("location", "")).strip().upper() != "DERIVED":
            raise SeasonalParameterizationError(
                f"seasonal offset {item.offset_name} must use location=DERIVED in frozen bounds"
            )
        status = str(row.get("status", "")).strip().lower()
        if status not in {"active", "fixed", "disabled"}:
            raise SeasonalParameterizationError(
                f"seasonal offset {item.offset_name} has invalid frozen status {status!r}"
            )
        if status == "disabled":
            raise SeasonalParameterizationError(
                f"enabled seasonal design cannot reference disabled offset {item.offset_name}"
            )
        try:
            init = float(row["init"])
            lower = float(row["lower"])
            upper = float(row["upper"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SeasonalParameterizationError(
                f"seasonal offset {item.offset_name} has non-numeric frozen bounds"
            ) from exc
        if not lower <= init <= upper:
            raise SeasonalParameterizationError(
                f"seasonal offset {item.offset_name} requires lower <= init <= upper"
            )
        if not math.isclose(init, 0.0, abs_tol=1e-12):
            raise SeasonalParameterizationError(
                f"seasonal offset {item.offset_name} must be centered at zero (init=0)"
            )
        params.append(
            {
                "name": item.offset_name,
                "init": init,
                "lower": lower,
                "upper": upper,
                "idx": None,
                "status": "fixed" if status == "fixed" else "none",
                "pargp": "seasonal_offset",
                "seasonal_offset": True,
            }
        )
    return params


def validate_projected_physical_bounds(
    parameters: Iterable[Mapping[str, object]],
    parameterization: SeasonalParameterization | None,
) -> None:
    """Prove frozen parameter/offset rectangles remain DSSAT-physical.

    This is a build-time contract, not a runtime clipping rule.  It prevents a
    valid PEST++ draw from becoming an invalid crop-model input solely because
    an autumn offset was added.
    """
    if parameterization is None:
        return
    by_name = {str(item.get("name", "")).strip().upper(): item for item in parameters}
    for item in parameterization.offsets:
        base = by_name.get(item.parameter_name)
        offset = by_name.get(item.offset_name)
        if base is None or offset is None:
            raise SeasonalParameterizationError(
                f"cannot validate {item.offset_name}: missing shared or offset bounds"
            )
        try:
            b_lo, b_hi = float(base["lower"]), float(base["upper"])
            d_lo, d_hi = float(offset["lower"]), float(offset["upper"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SeasonalParameterizationError(f"non-numeric bounds for {item.parameter_name}") from exc
        candidates = [
            _apply_offset(shared, delta, item.transform)
            for shared in (b_lo, b_hi)
            for delta in (d_lo, d_hi)
        ]
        physical = PHYSICAL_BOUNDS.get(item.parameter_name)
        if physical is None:
            continue
        lo, hi = physical
        tolerance = 1.0e-12 * max(1.0, abs(lo), abs(hi))
        if min(candidates) < lo - tolerance or max(candidates) > hi + tolerance:
            raise SeasonalParameterizationError(
                f"{item.parameter_name}+{item.offset_name} can project outside physical "
                f"bounds [{lo:g}, {hi:g}]"
            )


def write_projected_parameter_csv(
    source_csv: str | Path,
    destination_csv: str | Path,
    parameterization: SeasonalParameterization | None,
    season_id: str,
) -> list[dict[str, object]]:
    """Project a PEST CSV for one season without mutating the source file."""
    source = Path(source_csv)
    destination = Path(destination_csv)
    if parameterization is None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return []
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if len(fieldnames) < 2:
        raise SeasonalParameterizationError(f"unrecognized PEST parameter CSV: {source}")
    name_col = "name" if "name" in fieldnames else fieldnames[0]
    value_col = "value" if "value" in fieldnames else fieldnames[1]
    values: dict[str, float] = {}
    for row in rows:
        name = str(row.get(name_col, "")).strip().upper()
        if not name:
            continue
        try:
            values[name] = float(row.get(value_col, ""))
        except (TypeError, ValueError) as exc:
            raise SeasonalParameterizationError(f"non-numeric value for {name} in {source}") from exc

    projected, audit = parameterization.project(values, season_id)

    output_rows = []
    for row in rows:
        name = str(row.get(name_col, "")).strip().upper()
        if name not in projected:
            continue
        new_row = dict(row)
        new_row[value_col] = f"{projected[name]:.15g}"
        output_rows.append(new_row)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)
    return audit
