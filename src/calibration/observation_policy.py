"""Auditable observation transforms and treatment-mean uncertainty.

FileA/FileT and normal DSSAT outputs remain on their physical scale.  This
module only transforms the values copied into the tagged ``Pest*.OUT`` files
that PEST reads, and applies the identical transform to the measured value in
the PEST control file.
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


POLICY_VERSION = "observation_policy_v2"
MISSING_VALUE = -99.0
_GROUP_SUFFIX = re.compile(r"_(?:H|D)\d+$", re.IGNORECASE)
_TAGGED_VALUE = re.compile(
    r"(?P<prefix>@(?P<token>[^@\s]+)@\s+)"
    r"(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)"
)


def effective_sigma_for_mean(
    replicate_sd: float,
    n_replicates: int,
    *,
    n_effective: float | None = None,
    model_sigma: float = 0.0,
    sigma_floor: float = 0.0,
) -> float:
    """Combine mean sampling error, model discrepancy, and a sigma floor.

    ``n_effective`` must not exceed the physical replicate count.  It can be
    reduced to represent non-independent blocks or repeated measurements.
    """
    replicate_sd = float(replicate_sd)
    n_replicates = int(n_replicates)
    n_effective = float(n_replicates if n_effective is None else n_effective)
    model_sigma = float(model_sigma)
    sigma_floor = float(sigma_floor)
    if not math.isfinite(replicate_sd) or replicate_sd < 0:
        raise ValueError("replicate_sd must be finite and non-negative")
    if n_replicates < 2:
        raise ValueError("n_replicates must be at least 2 when estimating sigma from repeats")
    if not math.isfinite(n_effective) or not 0 < n_effective <= n_replicates:
        raise ValueError("n_effective must be positive and no larger than n_replicates")
    if any(not math.isfinite(value) or value < 0 for value in (model_sigma, sigma_floor)):
        raise ValueError("model_sigma and sigma_floor must be finite and non-negative")
    sigma = math.sqrt(
        replicate_sd**2 / n_effective + model_sigma**2 + sigma_floor**2
    )
    if sigma <= 0:
        raise ValueError("effective sigma must be positive")
    return sigma


def transform_value(
    value: float,
    transform: str = "raw",
    *,
    offset: float = 0.0,
    reference: float = 1.0,
) -> float:
    """Transform one observation or simulation using an explicit policy."""
    value = float(value)
    transform = str(transform or "raw").strip().lower()
    offset = float(offset)
    reference = float(reference)
    if not all(math.isfinite(item) for item in (value, offset, reference)):
        raise ValueError("value, offset, and reference must be finite")
    if transform == "raw":
        if offset != 0.0 or reference != 1.0:
            raise ValueError("raw transform requires offset=0 and reference=1")
        return value
    if transform != "log":
        raise ValueError(f"Unsupported observation transform: {transform!r}")
    if reference <= 0:
        raise ValueError("log reference must be positive")
    shifted = value + offset
    if shifted <= 0:
        raise ValueError(
            f"log transform requires value + offset > 0, got {value:g} + {offset:g}"
        )
    return math.log(shifted / reference)


def transform_sigma(
    raw_value: float,
    raw_sigma: float,
    transform: str = "raw",
    *,
    offset: float = 0.0,
) -> float:
    """Propagate raw-scale uncertainty to the configured residual scale."""
    raw_value = float(raw_value)
    raw_sigma = float(raw_sigma)
    if not math.isfinite(raw_sigma) or raw_sigma <= 0:
        raise ValueError("raw sigma must be positive and finite")
    transform = str(transform or "raw").strip().lower()
    if transform == "raw":
        return raw_sigma
    if transform != "log":
        raise ValueError(f"Unsupported observation transform: {transform!r}")
    shifted = raw_value + float(offset)
    if not math.isfinite(shifted) or shifted <= 0:
        raise ValueError("log sigma propagation requires raw_value + offset > 0")
    # Lognormal/delta-compatible propagation.  For small relative errors this
    # approaches raw_sigma / shifted, while remaining stable for larger CVs.
    return math.sqrt(math.log1p((raw_sigma / shifted) ** 2))


def load_observation_policy(path: str | Path | None) -> dict[str, dict[str, Any]]:
    """Load a compact CSV policy keyed by exact group or variable root."""
    if path is None:
        return {}
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Observation policy CSV not found: {source}")
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "group" not in (rows[0].keys() if rows else []):
        raise ValueError("Observation policy CSV requires a 'group' column")
    result: dict[str, dict[str, Any]] = {}
    for row_number, row in enumerate(rows, start=2):
        group = str(row.get("group") or "").strip().upper()
        if not group:
            raise ValueError(f"Observation policy row {row_number} has an empty group")
        if group in result:
            raise ValueError(f"Duplicate observation policy group: {group}")
        result[group] = {str(key): value for key, value in row.items()}
    return result


def _optional_float(policy: Mapping[str, Any], name: str) -> float | None:
    value = policy.get(name)
    if value is None or str(value).strip() == "":
        return None
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _resolve_policy(group: str, policies: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    exact = str(group).strip().upper()
    root = _GROUP_SUFFIX.sub("", exact)
    return policies.get(exact) or policies.get(root) or {}


def apply_observation_policy(
    obs_df: pd.DataFrame,
    policies: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[pd.DataFrame, dict[str, dict[str, dict[str, float | str]]]]:
    """Apply transform/sigma/group policy and build the runner token map."""
    policies = policies or {}
    result = obs_df.copy()
    required = {"obsnme", "obsval", "obgnme", "weight", "sim_token", "model_output_file"}
    missing = required - set(result.columns)
    if missing:
        raise ValueError(f"Observation table missing policy fields: {sorted(missing)}")

    token_map: dict[str, dict[str, dict[str, float | str]]] = {}
    updated: list[dict[str, Any]] = []
    for record in result.to_dict("records"):
        raw_obs = float(record.get("raw_obsval", record["obsval"]))
        is_missing = raw_obs == MISSING_VALUE or float(record.get("weight", 0.0)) == 0.0
        policy = _resolve_policy(str(record["obgnme"]), policies)
        transform = str(policy.get("transform") or "raw").strip().lower()
        offset = _optional_float(policy, "offset")
        reference = _optional_float(policy, "reference")
        offset = 0.0 if offset is None else offset
        reference = 1.0 if reference is None else reference
        multiplier = _optional_float(policy, "group_multiplier")
        multiplier = 1.0 if multiplier is None else multiplier
        if multiplier <= 0:
            raise ValueError("group_multiplier must be positive")

        explicit_sigma = _optional_float(policy, "sigma")
        replicate_sd = _optional_float(policy, "replicate_sd")
        if explicit_sigma is not None and replicate_sd is not None:
            raise ValueError(
                f"Group {record['obgnme']} cannot define both sigma and replicate_sd"
            )
        if replicate_sd is not None:
            n_replicates = _optional_float(policy, "n_replicates")
            if n_replicates is None or not float(n_replicates).is_integer():
                raise ValueError("replicate_sd requires an integer n_replicates")
            raw_sigma = effective_sigma_for_mean(
                replicate_sd,
                int(n_replicates),
                n_effective=_optional_float(policy, "n_effective"),
                model_sigma=_optional_float(policy, "model_sigma") or 0.0,
                sigma_floor=_optional_float(policy, "sigma_floor") or 0.0,
            )
            sigma_source = str(policy.get("sigma_source") or "replicate_mean_model")
        elif explicit_sigma is not None:
            raw_sigma = explicit_sigma
            sigma_source = str(policy.get("sigma_source") or "policy_explicit")
        else:
            current_sigma = record.get("sigma")
            if current_sigma is None or pd.isna(current_sigma):
                if transform == "log" and not is_missing:
                    raise ValueError(
                        f"Log-transformed group {record['obgnme']} requires an auditable raw sigma"
                    )
                current_weight = float(record["weight"])
                raw_sigma = 1.0 / current_weight if current_weight > 0 else 1.0
                sigma_source = "legacy_weight_inferred"
            else:
                raw_sigma = float(current_sigma)
                sigma_source = str(policy.get("sigma_source") or record.get("sigma_source") or "builder_default")

        if not math.isfinite(raw_sigma) or raw_sigma <= 0:
            raise ValueError(f"Group {record['obgnme']} has invalid raw sigma: {raw_sigma!r}")
        transformed_obs = 0.0 if is_missing else transform_value(
            raw_obs, transform, offset=offset, reference=reference
        )
        effective_sigma = raw_sigma if is_missing else transform_sigma(
            raw_obs, raw_sigma, transform, offset=offset
        )
        base_weight = 1.0 / effective_sigma
        final_weight = 0.0 if is_missing else base_weight * multiplier

        record.update(
            {
                "raw_obsval": raw_obs,
                "obsval": transformed_obs,
                "raw_sigma": raw_sigma,
                "sigma": effective_sigma,
                "sigma_source": sigma_source,
                "base_weight": base_weight,
                "group_multiplier": multiplier,
                "weight": final_weight,
                "transform": transform,
                "transform_offset": offset,
                "transform_reference": reference,
                "weight_policy_id": POLICY_VERSION,
            }
        )
        updated.append(record)

        if transform != "raw":
            filename = Path(str(record["model_output_file"])).name
            token = str(record["sim_token"])
            spec = {"transform": transform, "offset": offset, "reference": reference}
            previous = token_map.setdefault(filename, {}).get(token)
            if previous is not None and previous != spec:
                raise ValueError(
                    f"Simulation token {token} in {filename} has conflicting transform policies"
                )
            token_map[filename][token] = spec
    return pd.DataFrame(updated), token_map


def write_transform_config(
    path: str | Path,
    token_map: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> Path:
    target = Path(path)
    payload = {"version": POLICY_VERSION, "files": token_map}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def apply_transform_config(path: str | Path, output_dir: str | Path) -> None:
    """Transform tagged PEST outputs in place after DSSAT has generated them."""
    config_path = Path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if payload.get("version") != POLICY_VERSION:
        raise ValueError(f"Unsupported observation transform policy: {payload.get('version')!r}")
    for filename, token_specs in payload.get("files", {}).items():
        target = Path(output_dir) / Path(filename).name
        if not target.is_file():
            raise FileNotFoundError(f"Tagged PEST output not found for transform: {target}")
        text = target.read_text(encoding="utf-8", errors="strict")
        seen: set[str] = set()

        def replace(match: re.Match[str]) -> str:
            token = match.group("token")
            spec = token_specs.get(token)
            if spec is None:
                return match.group(0)
            seen.add(token)
            transformed = transform_value(
                float(match.group("value")),
                str(spec["transform"]),
                offset=float(spec.get("offset", 0.0)),
                reference=float(spec.get("reference", 1.0)),
            )
            return f"{match.group('prefix')}{transformed:.12g}"

        transformed_text = _TAGGED_VALUE.sub(replace, text)
        absent = set(token_specs) - seen
        if absent:
            raise ValueError(f"Transform tokens absent from {target.name}: {sorted(absent)}")
        target.write_text(transformed_text, encoding="utf-8")


__all__ = [
    "POLICY_VERSION",
    "apply_observation_policy",
    "apply_transform_config",
    "effective_sigma_for_mean",
    "load_observation_policy",
    "transform_sigma",
    "transform_value",
    "write_transform_config",
]
