"""Modular parameter-system for CROPGRO-Eggplant SA and calibration.

Implements the 11-module parameter extension framework from
``docs/reference/参数拓展方案参考.MD``.  Each module is a JSON declaration
under ``configs/sa/parameter_modules/`` that lists parameters, their physical
and default bounds, array-anchor structure, required observations, and
intra-module constraints.  Modules are composed into a complete bounds
CSV for a given SA or calibration scenario.

Design principles (from the extension plan):

* **Three layers**: structural-mandatory, sensitivity-screening,
  measurement-or-prior-fixed — encoded as ``priority`` per module.
* **Array dimensionality reduction**: array parameters (XVGROW-YVREF,
  XLEAF-YLEAF-YSTEM, etc.) are exposed as a small number of *anchor*
  parameters; the full array is reconstructed by interpolation at injection
  time (``array_expander.py``).  Anchors are first-class PEST parameters.
* **Constraints are explicit**: temperature ordering (TB<TO1<TO2<TM),
  LNGSH<=XMPAGE, partition-sum-to-one, mutual-exclusivity pairs, etc. are
  validated when modules are composed.
* **No silent promotion**: a parameter absent from the composed module set
  never enters the bounds.  The frozen-bounds CSV remains the only layer
  calibration may consume.

This module imports no plotting library and no DSSAT/PEST runner.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from src.common.project import PROJECT_ROOT

MODULES_DIR = PROJECT_ROOT / "configs" / "sa" / "parameter_modules"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParameterSpec:
    """One calibratable parameter (or anchor) in a module."""

    name: str
    location: str                         # CUL | ECO | SPE
    physical_bounds: tuple[float, float]
    default_bounds: tuple[float, float]
    role: str = "scalar"                  # scalar | array_anchor | structural_choice
    init_source: str = ""
    units: str = ""
    scientific_note: str = ""
    # Array-anchor metadata (only when role == "array_anchor"):
    anchor_of: str = ""                   # parent array name, e.g. "YVREF"
    anchor_index: int = -1                # index into the parent array (1-based)
    # Whether the parameter already exists in the v4 55-active set.
    existing_v4: bool = False


@dataclass(frozen=True)
class ConstraintSpec:
    """A constraint that must hold for the composed parameter set."""

    constraint_id: str
    constraint_type: str                  # ordering | sum_to_one | range | mutual_exclusive
    parameters: tuple[str, ...]
    expression: str                       # human-readable, e.g. "LNGSH.init <= XMPAGE.init"
    params: dict[str, Any] = field(default_factory=dict)  # type-specific config


@dataclass(frozen=True)
class ParameterModule:
    """A named group of parameters (one of the 11 modules)."""

    module_id: str
    display_name_en: str
    display_name_zh: str
    priority: str                         # batch_1 | batch_2 | conditional
    required_observations: tuple[str, ...]
    parameters: tuple[ParameterSpec, ...]
    constraints: tuple[ConstraintSpec, ...] = ()


@dataclass(frozen=True)
class ValidationIssue:
    """A constraint violation found during composition."""

    severity: str                         # error | warning
    constraint_id: str
    message: str


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ParameterModuleError(Exception):
    """Raised when a module declaration or composition violates the contract."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_module(module_id: str | Path) -> ParameterModule:
    """Load a parameter module from its JSON declaration.

    Accepts either a bare module_id (resolved against ``MODULES_DIR``) or a
    full path.  Raises :class:`ParameterModuleError` on any contract violation.
    """
    p = Path(module_id)
    if not p.is_absolute() and not p.suffix:
        # bare module_id → 0N_module_id.json (numeric prefix for ordering)
        candidates = sorted(MODULES_DIR.glob(f"*_{module_id}.json"))
        if not candidates:
            raise ParameterModuleError(f"module '{module_id}' not found in {MODULES_DIR}")
        p = candidates[0]
    if not p.is_file():
        raise ParameterModuleError(f"module file not found: {p}")

    raw = json.loads(p.read_text(encoding="utf-8"))
    return _parse_module(raw, p.name)


def load_all_modules() -> dict[str, ParameterModule]:
    """Load every module JSON in ``MODULES_DIR`` (excluding ``_`` prefixed files)."""
    modules: dict[str, ParameterModule] = {}
    for p in sorted(MODULES_DIR.glob("*.json")):
        if p.name.startswith("_"):
            continue
        raw = json.loads(p.read_text(encoding="utf-8"))
        mod = _parse_module(raw, p.name)
        modules[mod.module_id] = mod
    return modules


def _parse_module(raw: dict[str, Any], source_name: str) -> ParameterModule:
    """Parse a raw JSON dict into a validated ParameterModule."""
    for key in ("module_id", "display_name_en", "display_name_zh", "priority", "parameters"):
        if key not in raw:
            raise ParameterModuleError(f"{source_name} missing required key: {key!r}")

    params: list[ParameterSpec] = []
    for i, pr in enumerate(raw["parameters"]):
        params.append(_parse_param(pr, f"{source_name}.parameters[{i}]"))

    constraints = tuple(
        _parse_constraint(c, f"{source_name}.constraints[{j}]")
        for j, c in enumerate(raw.get("constraints", []))
    )

    # Check for duplicate parameter names within the module.
    names = [p.name for p in params]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ParameterModuleError(f"{source_name} has duplicate parameters: {dupes}")

    return ParameterModule(
        module_id=str(raw["module_id"]),
        display_name_en=str(raw["display_name_en"]),
        display_name_zh=str(raw["display_name_zh"]),
        priority=str(raw["priority"]),
        required_observations=tuple(str(o) for o in raw.get("required_observations", [])),
        parameters=tuple(params),
        constraints=constraints,
    )


def _parse_param(raw: dict[str, Any], label: str) -> ParameterSpec:
    """Parse one parameter entry from JSON."""
    for key in ("name", "location", "physical_bounds", "default_bounds"):
        if key not in raw:
            raise ParameterModuleError(f"{label} missing key: {key!r}")
    pb = raw["physical_bounds"]
    db = raw["default_bounds"]
    if not (isinstance(pb, list) and len(pb) == 2):
        raise ParameterModuleError(f"{label} physical_bounds must be [lo, hi]")
    if not (isinstance(db, list) and len(db) == 2):
        raise ParameterModuleError(f"{label} default_bounds must be [lo, hi]")
    return ParameterSpec(
        name=str(raw["name"]).strip().upper(),
        location=str(raw["location"]).strip().upper(),
        physical_bounds=(float(pb[0]), float(pb[1])),
        default_bounds=(float(db[0]), float(db[1])),
        role=str(raw.get("role", "scalar")),
        init_source=str(raw.get("init_source", "")),
        units=str(raw.get("units", "")),
        scientific_note=str(raw.get("scientific_note", "")),
        anchor_of=str(raw.get("anchor_of", "")),
        anchor_index=int(raw.get("anchor_index", -1)),
        existing_v4=bool(raw.get("existing_v4", False)),
    )


def _parse_constraint(raw: dict[str, Any], label: str) -> ConstraintSpec:
    """Parse one constraint entry from JSON."""
    for key in ("constraint_id", "constraint_type", "parameters"):
        if key not in raw:
            raise ParameterModuleError(f"{label} missing key: {key!r}")
    params = tuple(str(p).strip().upper() for p in raw["parameters"])
    extra = {k: v for k, v in raw.items() if k not in
             ("constraint_id", "constraint_type", "parameters", "expression")}
    return ConstraintSpec(
        constraint_id=str(raw["constraint_id"]),
        constraint_type=str(raw["constraint_type"]),
        parameters=params,
        expression=str(raw.get("expression", "")),
        params=extra,
    )


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def compose_bounds(
    module_ids: Sequence[str],
    *,
    include_existing_v4: bool = True,
    v4_bounds_path: str | Path | None = None,
    status_for_new: str = "active",
    activate_parameters: Sequence[str] = (),
    fix_parameters: Sequence[str] = (),
) -> tuple[list[dict[str, str]], list[ValidationIssue]]:
    """Compose a frozen-bounds row list from selected modules.

    Parameters
    ----------
    module_ids
        Module IDs to include.
    include_existing_v4
        If True, include all 55 active + fixed parameters from the current v4
        frozen bounds as a baseline (new parameters are added on top).
    v4_bounds_path
        Override path to the v4 frozen bounds CSV.
    status_for_new
        Status to assign to newly-added parameters not in v4.
    activate_parameters
        Parameter names to force to ``active`` after composition.
    fix_parameters
        Parameter names to force to ``fixed`` after composition.

    Returns
    -------
    (rows, issues)
        ``rows`` is a list of dicts matching the frozen-bounds CSV schema.
        ``issues`` is a list of constraint violations found.
    """
    modules = [load_module(mid) for mid in module_ids]
    issues: list[ValidationIssue] = []

    # Start from v4 baseline if requested.
    rows_by_name: dict[str, dict[str, str]] = {}
    if include_existing_v4:
        if not v4_bounds_path:
            raise ParameterModuleError(
                "compose_bounds requires an explicit baseline bounds CSV when "
                "include_existing_v4=True; pass --baseline-bounds/--v4-bounds "
                "for the current calibration domain"
            )
        v4_path = Path(v4_bounds_path)
        if not v4_path.is_file():
            raise ParameterModuleError(f"baseline bounds file not found: {v4_path}")
        with v4_path.open("r", encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                r = {(k.lstrip("\ufeff") if k else k): v for k, v in r.items()}
                name = str(r.get("name", "")).strip().upper()
                if name:
                    row = dict(r)
                    row["__baseline"] = "1"
                    rows_by_name[name] = row

    # Add new parameters from modules.
    for mod in modules:
        for pspec in mod.parameters:
            if pspec.existing_v4 and pspec.name in rows_by_name:
                continue  # already in v4; don't duplicate
            if pspec.name in rows_by_name:
                issues.append(ValidationIssue(
                    severity="warning",
                    constraint_id="duplicate_parameter",
                    message=f"Parameter {pspec.name!r} appears in multiple sources; "
                            f"first occurrence kept.",
                ))
                continue
            lo, hi = pspec.default_bounds
            rows_by_name[pspec.name] = {
                "name": pspec.name,
                "init": f"{(lo + hi) / 2:.6g}",
                "lower": f"{lo:.6g}",
                "upper": f"{hi:.6g}",
                "status": status_for_new,
                "pargp": f"module_{mod.module_id}",
                "location": pspec.location,
                "file": _file_for_location(pspec.location),
                "cultivar": "TM0008",
                "ecotype": "TM0001",
                "mode": "both",
                "review_note": pspec.scientific_note,
                "decision_role": f"module_{mod.priority}",
                "evidence_basis": pspec.scientific_note,
            }

    _apply_status_overrides(
        rows_by_name,
        activate_parameters=activate_parameters,
        fix_parameters=fix_parameters,
    )
    issues.extend(_auto_resolve_mutual_exclusive(rows_by_name, modules))

    # Validate constraints across all included modules + cross-module constraints.
    issues.extend(_validate_constraints(rows_by_name, modules))

    rows = sorted(
        ({k: v for k, v in row.items() if not str(k).startswith("__")} for row in rows_by_name.values()),
        key=lambda r: r.get("name", ""),
    )
    return rows, issues


def _file_for_location(location: str) -> str:
    """Map a location code to the template basename."""
    mapping = {
        "CUL": "TMGRO048.CUL.base",
        "ECO": "TMGRO048.ECO.base",
        "SPE": "TMGRO048.SPE.base",
    }
    return mapping.get(location.upper(), "")


def _apply_status_overrides(
    rows_by_name: dict[str, dict[str, str]],
    *,
    activate_parameters: Sequence[str],
    fix_parameters: Sequence[str],
) -> None:
    """Apply explicit status overrides after composition."""
    for name in (str(p).strip().upper() for p in fix_parameters):
        if not name:
            continue
        if name not in rows_by_name:
            raise ParameterModuleError(f"status override references unknown parameter: {name}")
        _collapse_to_fixed(rows_by_name[name])
    for name in (str(p).strip().upper() for p in activate_parameters):
        if not name:
            continue
        if name not in rows_by_name:
            raise ParameterModuleError(f"status override references unknown parameter: {name}")
        rows_by_name[name]["status"] = "active"


def _collapse_to_fixed(row: dict[str, str]) -> None:
    """Convert a bounds row to a validator-compliant fixed parameter."""
    init = str(row.get("init", "")).strip()
    row["status"] = "fixed"
    row["lower"] = init
    row["upper"] = init


# ---------------------------------------------------------------------------
# Constraint validation
# ---------------------------------------------------------------------------

def _validate_constraints(
    rows_by_name: dict[str, dict[str, str]],
    modules: Sequence[ParameterModule],
) -> list[ValidationIssue]:
    """Validate all module-level and cross-module constraints."""
    issues: list[ValidationIssue] = []
    for c, source in _collect_constraints(modules):
        issues.extend(_check_one_constraint(c, source, rows_by_name))

    return issues


def _collect_constraints(modules: Sequence[ParameterModule]) -> list[tuple[ConstraintSpec, str]]:
    """Collect module-local and cross-module constraints in evaluation order."""
    all_constraints: list[tuple[ConstraintSpec, str]] = []
    for mod in modules:
        for c in mod.constraints:
            all_constraints.append((c, mod.module_id))

    xc_path = MODULES_DIR / "_constraints.json"
    if xc_path.is_file():
        xc_raw = json.loads(xc_path.read_text(encoding="utf-8"))
        for i, c_raw in enumerate(xc_raw.get("constraints", [])):
            c = _parse_constraint(c_raw, f"_constraints.json[{i}]")
            all_constraints.append((c, "cross_module"))
    return all_constraints


def _auto_resolve_mutual_exclusive(
    rows_by_name: dict[str, dict[str, str]],
    modules: Sequence[ParameterModule],
) -> list[ValidationIssue]:
    """Prefer one active member per mutual-exclusive set and downgrade the rest."""
    issues: list[ValidationIssue] = []
    for c, source in _collect_constraints(modules):
        if c.constraint_type != "mutual_exclusive":
            continue
        active = [
            p
            for p in c.parameters
            if p in rows_by_name and str(rows_by_name[p].get("status", "")).lower() == "active"
        ]
        if len(active) <= 1:
            continue

        preferred = next(
            (
                p
                for p in active
                if str(rows_by_name[p].get("__baseline", "")).strip() == "1"
            ),
            active[0],
        )
        downgraded: list[str] = []
        for name in active:
            if name == preferred:
                continue
            _collapse_to_fixed(rows_by_name[name])
            downgraded.append(name)
        issues.append(
            ValidationIssue(
                "warning",
                c.constraint_id,
                f"Auto-resolved mutual-exclusive set in {source}: kept {preferred} active, "
                f"downgraded {downgraded} to fixed",
            )
        )
    return issues


def _check_one_constraint(
    c: ConstraintSpec,
    source: str,
    rows_by_name: dict[str, dict[str, str]],
) -> list[ValidationIssue]:
    """Check a single constraint against the composed bounds."""
    present = [p for p in c.parameters if p in rows_by_name]
    # Only validate when ALL constrained parameters are present in the composition.
    if len(present) < len(c.parameters):
        return []

    if c.constraint_type == "ordering":
        return _check_ordering(c, source, rows_by_name)
    elif c.constraint_type == "sum_to_one":
        return _check_sum_to_one(c, source, rows_by_name)
    elif c.constraint_type == "range":
        return _check_range(c, source, rows_by_name)
    elif c.constraint_type == "mutual_exclusive":
        return _check_mutual_exclusive(c, source, rows_by_name)
    else:
        return [ValidationIssue("warning", c.constraint_id,
                f"Unknown constraint type {c.constraint_type!r} in {source}")]


def _get_numeric(row: dict[str, str], key: str) -> float | None:
    """Extract a numeric value from a bounds row, or None if not parseable."""
    try:
        return float(row.get(key, ""))
    except (ValueError, TypeError):
        return None


def _check_ordering(c, source, rows_by_name):
    """Check that init/lower/upper values maintain a strict or non-strict order.

    Config params:
        relation: "<" (strict) or "<=" (non-strict)
        field: "init" | "lower" | "upper" (which value to compare; default "init")
        rectangular: bool — if True, also check upper(left) < lower(right)
    """
    issues = []
    relation = c.params.get("relation", "<=")
    field = c.params.get("field", "init")
    rectangular = bool(c.params.get("rectangular", False))

    for left, right in zip(c.parameters, c.parameters[1:]):
        lv = _get_numeric(rows_by_name[left], field)
        rv = _get_numeric(rows_by_name[right], field)
        if lv is None or rv is None:
            continue
        if relation == "<" and not (lv < rv):
            issues.append(ValidationIssue("error", c.constraint_id,
                f"{left}.{field}={lv} must be < {right}.{field}={rv} ({source})"))
        elif relation == "<=" and not (lv <= rv):
            issues.append(ValidationIssue("error", c.constraint_id,
                f"{left}.{field}={lv} must be <= {right}.{field}={rv} ({source})"))

        if rectangular:
            lu = _get_numeric(rows_by_name[left], "upper")
            rl = _get_numeric(rows_by_name[right], "lower")
            if lu is not None and rl is not None and not (lu < rl):
                issues.append(ValidationIssue("error", c.constraint_id,
                    f"{left}.upper={lu} must be < {right}.lower={rl} (rectangular, {source})"))
    return issues


def _check_sum_to_one(c, source, rows_by_name):
    """Check that init values of listed parameters sum to ~1.0 (within tolerance)."""
    tolerance = float(c.params.get("tolerance", 0.01))
    total = 0.0
    for p in c.parameters:
        v = _get_numeric(rows_by_name[p], "init")
        if v is not None:
            total += v
    if abs(total - 1.0) > tolerance:
        return [ValidationIssue("warning", c.constraint_id,
            f"{' + '.join(c.parameters)}.init = {total:.4f}, expected ~1.0 ({source})")]
    return []


def _check_range(c, source, rows_by_name):
    """Check that a parameter's bounds lie within a specified range."""
    lo = float(c.params.get("lower", 0.0))
    hi = float(c.params.get("upper", 1.0))
    issues = []
    for p in c.parameters:
        row = rows_by_name[p]
        pl = _get_numeric(row, "lower")
        pu = _get_numeric(row, "upper")
        if pl is not None and not (lo <= pl):
            issues.append(ValidationIssue("error", c.constraint_id,
                f"{p}.lower={pl} must be >= {lo} ({source})"))
        if pu is not None and not (pu <= hi):
            issues.append(ValidationIssue("error", c.constraint_id,
                f"{p}.upper={pu} must be <= {hi} ({source})"))
    return issues


def _check_mutual_exclusive(c, source, rows_by_name):
    """Check that at most one of the listed parameters is 'active'."""
    active = [p for p in c.parameters
              if str(rows_by_name.get(p, {}).get("status", "")).lower() == "active"]
    if len(active) > 1:
        return [ValidationIssue("error", c.constraint_id,
            f"Mutual-exclusive parameters all active: {active} ({source}). "
            f"Fix all but one.")]
    return []


__all__ = [
    "MODULES_DIR",
    "ParameterSpec", "ConstraintSpec", "ParameterModule", "ValidationIssue",
    "ParameterModuleError",
    "load_module", "load_all_modules", "compose_bounds",
]
