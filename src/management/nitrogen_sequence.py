"""PSO-facing nitrogen-sequence codec and FileX materialiser.

The design follows the four management dimensions used by Liao et al. (2026):
total N, fertilisation frequency, basal/topdressing ratio, and application
timing.  A continuous particle position is decoded into a feasible mixed
integer sequence before direct DSSAT evaluation.  No surrogate model is used.

Only the nitrogen-bearing FE005 rows are rewritten.  Fertiliser form,
application method/depth, and the phosphorus/potassium rows remain frozen so
that the optimisation does not introduce an unreported nutrient confounder.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from src.common.experiment_inputs import parse_filex
from src.dssat.run_dssat import _yyddd_add_days
from src.management.core import _replace_field, _section


@dataclass(frozen=True)
class NitrogenSequenceBounds:
    total_n_kg_ha: tuple[float, float] = (60.0, 320.0)
    basal_fraction: tuple[float, float] = (0.15, 0.50)
    basal_dap: tuple[int, int] = (-7, 3)
    topdress_count: tuple[int, int] = (4, 10)
    topdress_dap: tuple[int, int] = (14, 96)
    minimum_interval_days: int = 5
    minimum_topdress_n_kg_ha: float = 2.0
    maximum_topdress_n_kg_ha: float = 75.0

    @property
    def maximum_count(self) -> int:
        return int(self.topdress_count[1])

    @property
    def vector_size(self) -> int:
        # total, basal fraction, basal DAP, frequency, K timing latents,
        # and K allocation latents.
        return 4 + 2 * self.maximum_count


@dataclass(frozen=True)
class NitrogenEvent:
    event_role: str
    dap: int
    amount_kg_ha: float


@dataclass(frozen=True)
class NitrogenSequence:
    total_n_kg_ha: float
    basal_fraction: float
    basal_dap: int
    topdress_count: int
    events: tuple[NitrogenEvent, ...]


@dataclass(frozen=True)
class AHPResult:
    weights: tuple[float, ...]
    lambda_max: float
    consistency_ratio: float


def _scale(value: float, lower: float, upper: float) -> float:
    return lower + float(value) * (upper - lower)


def _decode_integer(value: float, lower: int, upper: int) -> int:
    levels = upper - lower + 1
    return lower + min(levels - 1, int(float(value) * levels))


def _repair_ordered_daps(
    latent: Sequence[float],
    count: int,
    lower: int,
    upper: int,
    minimum_interval: int,
) -> tuple[int, ...]:
    if lower + (count - 1) * minimum_interval > upper:
        raise ValueError("timing window cannot accommodate the requested event count")
    requested = sorted(round(_scale(v, lower, upper)) for v in latent[:count])
    repaired: list[int] = []
    for index, value in enumerate(requested):
        feasible_lower = lower + index * minimum_interval
        feasible_upper = upper - (count - index - 1) * minimum_interval
        if repaired:
            feasible_lower = max(feasible_lower, repaired[-1] + minimum_interval)
        repaired.append(int(min(max(value, feasible_lower), feasible_upper)))
    return tuple(repaired)


def _bounded_allocation(
    total: float,
    raw_weights: Sequence[float],
    count: int,
    minimum: float,
    maximum: float,
) -> tuple[float, ...]:
    if count * minimum - 1e-9 > total or count * maximum + 1e-9 < total:
        raise ValueError("topdressing total is incompatible with per-event bounds")
    weights = np.asarray([max(float(v), 1e-9) for v in raw_weights[:count]], dtype=float)
    result = np.full(count, minimum, dtype=float)
    remaining = float(total - count * minimum)
    active = np.ones(count, dtype=bool)
    while remaining > 1e-10 and active.any():
        active_weights = weights[active]
        proposal = remaining * active_weights / active_weights.sum()
        indices = np.where(active)[0]
        capacities = maximum - result[indices]
        accepted = np.minimum(proposal, capacities)
        result[indices] += accepted
        remaining -= float(accepted.sum())
        active[indices[capacities - accepted <= 1e-10]] = False
    if remaining > 1e-7:
        raise ValueError("unable to repair topdressing allocation")
    rounded = [round(float(v), 3) for v in result]
    rounded[-1] = round(rounded[-1] + round(total - sum(rounded), 3), 3)
    return tuple(rounded)


def decode_pso_position(
    position: Sequence[float],
    bounds: NitrogenSequenceBounds | None = None,
) -> NitrogenSequence:
    """Decode one unit-box PSO position into a feasible N-event sequence."""
    bounds = bounds or NitrogenSequenceBounds()
    if len(position) != bounds.vector_size:
        raise ValueError(
            f"PSO position requires {bounds.vector_size} values, got {len(position)}"
        )
    if any(float(v) < 0.0 or float(v) > 1.0 for v in position):
        raise ValueError("PSO position must lie in the closed unit box")

    total = _scale(position[0], *bounds.total_n_kg_ha)
    basal_fraction = _scale(position[1], *bounds.basal_fraction)
    basal_dap = round(_scale(position[2], *bounds.basal_dap))
    count = _decode_integer(position[3], *bounds.topdress_count)
    timing_start = 4
    weight_start = timing_start + bounds.maximum_count
    daps = _repair_ordered_daps(
        position[timing_start:weight_start],
        count,
        *bounds.topdress_dap,
        bounds.minimum_interval_days,
    )

    basal_amount = round(total * basal_fraction, 3)
    topdress_total = round(total - basal_amount, 3)
    amounts = _bounded_allocation(
        topdress_total,
        position[weight_start:],
        count,
        bounds.minimum_topdress_n_kg_ha,
        bounds.maximum_topdress_n_kg_ha,
    )
    events = [NitrogenEvent("basal", int(basal_dap), basal_amount)]
    events.extend(
        NitrogenEvent("topdress", dap, amount)
        for dap, amount in zip(daps, amounts)
    )
    # Correct any three-decimal residual on the basal event.
    residual = round(total, 3) - round(sum(e.amount_kg_ha for e in events), 3)
    if residual:
        events[0] = NitrogenEvent("basal", int(basal_dap), round(basal_amount + residual, 3))
    return NitrogenSequence(
        total_n_kg_ha=round(total, 3),
        basal_fraction=basal_fraction,
        basal_dap=int(basal_dap),
        topdress_count=count,
        events=tuple(events),
    )


def ahp_priority_weights(
    pairwise_matrix: Sequence[Sequence[float]],
    consistency_threshold: float = 0.10,
) -> AHPResult:
    """Return principal-eigenvector AHP weights and enforce Saaty CR <= 0.10."""
    matrix = np.asarray(pairwise_matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or matrix.shape[0] < 2:
        raise ValueError("AHP pairwise matrix must be square with at least two criteria")
    if np.any(matrix <= 0) or not np.allclose(np.diag(matrix), 1.0, atol=1e-8):
        raise ValueError("AHP matrix entries must be positive with a unit diagonal")
    if not np.allclose(matrix * matrix.T, 1.0, atol=1e-6):
        raise ValueError("AHP pairwise matrix must be reciprocal")
    eigenvalues, eigenvectors = np.linalg.eig(matrix)
    index = int(np.argmax(eigenvalues.real))
    lambda_max = float(eigenvalues[index].real)
    vector = np.abs(eigenvectors[:, index].real)
    weights = vector / vector.sum()
    n = matrix.shape[0]
    consistency_index = max(0.0, (lambda_max - n) / (n - 1))
    random_index = {
        2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24,
        7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49,
    }.get(n)
    if random_index is None:
        raise ValueError("AHP consistency ratio is defined here for 2--10 criteria")
    ratio = 0.0 if random_index == 0 else consistency_index / random_index
    if ratio > consistency_threshold + 1e-12:
        raise ValueError(
            f"AHP consistency ratio {ratio:.4f} exceeds {consistency_threshold:.4f}"
        )
    return AHPResult(tuple(float(v) for v in weights), lambda_max, float(ratio))


def ahp_utility_score(
    indicators: dict[str, float],
    criteria: Sequence[dict[str, Any]],
    weights: Sequence[float],
    anchors: dict[str, tuple[float, float]],
) -> float:
    """Score indicators on fixed anchors; larger scores are always preferred."""
    if len(criteria) != len(weights):
        raise ValueError("criterion and AHP-weight counts differ")
    score = 0.0
    for criterion, weight in zip(criteria, weights):
        name = str(criterion["name"])
        lower, upper = anchors[name]
        if upper <= lower:
            raise ValueError(f"invalid fixed normalization anchors for {name}")
        value = min(max(float(indicators[name]), lower), upper)
        utility = (value - lower) / (upper - lower)
        if criterion["direction"] == "minimize":
            utility = 1.0 - utility
        elif criterion["direction"] != "maximize":
            raise ValueError(f"unsupported criterion direction: {criterion['direction']}")
        score += float(weight) * utility
    return float(score)


def _fertilizer_rows(
    lines: list[str], factor_level: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    start, end = _section(lines, "*FERTILIZERS (INORGANIC)")
    header: list[str] = []
    designated: list[dict[str, Any]] = []
    other_n: list[dict[str, Any]] = []
    for index in range(start + 1, end):
        if lines[index].strip().startswith("@"):
            header = lines[index].strip()[1:].upper().split()
            continue
        fields = lines[index].split()
        if not header or len(fields) < len(header):
            continue
        try:
            if int(fields[0]) != factor_level:
                continue
            row = {
                "line": index,
                "date_field": header.index("FDATE"),
                "amount_field": header.index("FAMN"),
                "date": int(fields[header.index("FDATE")]),
                "amount": float(fields[header.index("FAMN")]),
                "fertilizer_code": fields[header.index("FMCD")].upper(),
            }
        except (ValueError, IndexError):
            continue
        if row["fertilizer_code"] == "FE005":
            designated.append(row)
        elif row["amount"] > 1e-9:
            other_n.append(row)
    return designated, other_n


def materialize_nitrogen_sequence(
    source_filex: str | Path,
    output_dir: str | Path,
    sequence: NitrogenSequence,
    planting_yyddd: int,
    target_treatment: int,
    policy_id: str,
) -> dict[str, Any]:
    """Write a decoded sequence into FE005 slots and emit an auditable ledger."""
    source = Path(source_filex)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    lines = source.read_text(encoding="utf-8", errors="ignore").splitlines()
    treatment = parse_filex(source)["treatments"].get(int(target_treatment))
    if not treatment:
        raise KeyError(f"TN{target_treatment} is absent from the FileX")
    slots, other_n = _fertilizer_rows(lines, int(treatment["MF"]))
    if other_n:
        raise ValueError("non-FE005 rows contain nitrogen and would create an untracked input")
    if len(slots) < len(sequence.events):
        raise ValueError(
            f"FileX has {len(slots)} FE005 slots but sequence needs {len(sequence.events)}"
        )

    for slot in slots:
        lines[slot["line"]] = _replace_field(
            lines[slot["line"]], slot["amount_field"], 0.0
        )
    ledger_rows: list[dict[str, Any]] = []
    for slot, event in zip(slots, sequence.events):
        date_code = _yyddd_add_days(int(planting_yyddd), int(event.dap))
        line = lines[slot["line"]]
        line = _replace_field(line, slot["date_field"], float(date_code))
        line = _replace_field(line, slot["amount_field"], event.amount_kg_ha)
        lines[slot["line"]] = line
        ledger_rows.append(
            {
                "policy_id": policy_id,
                "event_role": event.event_role,
                "dap": event.dap,
                "date_code": date_code,
                "amount_kg_ha": event.amount_kg_ha,
                "fertilizer_code": "FE005",
                "rainfall_considered": "false",
            }
        )

    destination = output / source.name
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    ledger = output / "NitrogenSequence.csv"
    with ledger.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ledger_rows[0]))
        writer.writeheader()
        writer.writerows(ledger_rows)
    manifest = {
        "policy_id": policy_id,
        "target_treatment": int(target_treatment),
        "total_n_kg_ha": round(sum(row["amount_kg_ha"] for row in ledger_rows), 3),
        "basal_fraction": sequence.basal_fraction,
        "basal_dap": sequence.basal_dap,
        "topdress_count": sequence.topdress_count,
        "fertilizer_code": "FE005",
        "fertilizer_form_method_depth_frozen": True,
        "phosphorus_potassium_rows_unchanged": True,
        "rainfall_considered": False,
        "surrogate_model": False,
        "source_filex": str(source.resolve()),
        "scenario_filex": str(destination.resolve()),
        "nitrogen_sequence_ledger": str(ledger.resolve()),
    }
    (output / "nitrogen_sequence_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
