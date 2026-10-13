"""Symmetrical physiological tolerance interval objective penalty function.

Implements the two-sided physiological tolerance interval regularization:
    J_CNC(theta) = sum_{t in T_sub} w_{t, N3}^2 * L(NNI_sim(t; N3), [1.00, 1.30])
                 + sum_{t in T_sub} w_{t, N0}^2 * L(NNI_sim(t; N0), [0.40, 0.70])

Where:
    L(x, [x_min, x_max]) = max(0.0, x_min - x)^2 + max(0.0, x - x_max)^2

Eliminates the blindness to lower-bound collapse in N0 (NNI < 0.40)
and the false penalization of biological luxury consumption in N3 (NNI in [1.00, 1.30]).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple, Union


# Default physiological tolerance intervals for standard nitrogen levels
PHYSIOLOGICAL_NNI_INTERVALS: dict[str, tuple[float, float]] = {
    "N0": (0.40, 0.70),  # Deficient/severe limitation target
    "N1": (0.70, 1.00),  # Mild limitation target
    "N2": (0.85, 1.15),  # Optimal/near-critical target
    "N3": (1.00, 1.30),  # Luxury consumption tolerance interval
}

# Standard weights
DEFAULT_VARIANCE_NORMALIZED_WEIGHT: float = 0.25  # In range [0.05, 0.50]
DEFAULT_GROUP_POLICY_WEIGHT: float = 1.00         # In range [0.50, 1.25]


def tolerance_interval_loss(val: float, lower: float, upper: float) -> float:
    """Compute symmetrical quadratic loss outside the physiological tolerance interval.

    L(val, [lower, upper]) = max(0.0, lower - val)^2 + max(0.0, val - upper)^2

    Parameters
    ----------
    val : float
        Simulated NNI value.
    lower : float
        Lower acceptable bound (e.g. 0.40 for N0, 1.00 for N3).
    upper : float
        Upper acceptable bound (e.g. 0.70 for N0, 1.30 for N3).

    Returns
    -------
    float
        Zero if val is inside [lower, upper], else squared distance from the violated bound.
    """
    import math

    if math.isnan(val) or math.isinf(val):
        raise ValueError(f"Simulated NNI value must not be NaN or infinite, got {val}")
    if math.isnan(lower) or math.isnan(upper) or lower > upper:
        raise ValueError(f"Lower bound ({lower}) cannot exceed upper bound ({upper})")

    loss_lower = max(0.0, lower - val) ** 2
    loss_upper = max(0.0, val - upper) ** 2
    return loss_lower + loss_upper


@dataclass(frozen=True)
class CNCPenaltyComponent:
    """Details of penalty evaluation for one observation point."""

    nitrogen_level: str
    time_label: str
    nni_sim: float
    lower_bound: float
    upper_bound: float
    weight: float
    unweighted_loss: float
    weighted_penalty: float  # (weight^2) * unweighted_loss


def compute_cnc_objective_penalty(
    simulated_nni: Mapping[str, Sequence[float]],
    weights: Optional[Mapping[str, float]] = None,
    intervals: Optional[Mapping[str, tuple[float, float]]] = None,
    default_weight: float = DEFAULT_VARIANCE_NORMALIZED_WEIGHT,
) -> tuple[float, list[CNCPenaltyComponent]]:
    """Compute the total Scheme A objective penalty across nitrogen levels and subsampled dates.

    Parameters
    ----------
    simulated_nni : Mapping[str, Sequence[float]]
        Dict mapping nitrogen level ('N0', 'N3', etc.) to a sequence of simulated NNI values
        at key phenological subsampled dates.
    weights : Mapping[str, float], optional
        Dict mapping nitrogen level to scalar observation weight w. Default uses `default_weight`.
    intervals : Mapping[str, tuple[float, float]], optional
        Dict mapping nitrogen level to (lower, upper) tolerance interval. Defaults to
        `PHYSIOLOGICAL_NNI_INTERVALS`.
    default_weight : float, optional
        Weight to use when not specified in `weights`. Default is 0.25.

    Returns
    -------
    tuple[float, list[CNCPenaltyComponent]]
        Total weighted penalty J_CNC and list of detailed penalty components.
    """
    active_intervals = dict(PHYSIOLOGICAL_NNI_INTERVALS)
    if intervals:
        active_intervals.update(intervals)

    active_weights = weights or {}
    total_penalty = 0.0
    components: list[CNCPenaltyComponent] = []

    for n_level, nni_series in simulated_nni.items():
        if n_level not in active_intervals:
            continue
        lower, upper = active_intervals[n_level]
        w = active_weights.get(n_level, default_weight)
        w_sq = w ** 2

        for idx, nni_val in enumerate(nni_series):
            # Skip invalid/sentinel values
            if (
                math.isnan(nni_val)
                or math.isinf(nni_val)
                or nni_val <= 0.0
                or nni_val == -99.0
            ):
                continue

            unweighted = tolerance_interval_loss(nni_val, lower, upper)
            penalty = w_sq * unweighted
            total_penalty += penalty

            components.append(
                CNCPenaltyComponent(
                    nitrogen_level=n_level,
                    time_label=f"sample_{idx+1}",
                    nni_sim=nni_val,
                    lower_bound=lower,
                    upper_bound=upper,
                    weight=w,
                    unweighted_loss=unweighted,
                    weighted_penalty=penalty,
                )
            )

    return total_penalty, components
