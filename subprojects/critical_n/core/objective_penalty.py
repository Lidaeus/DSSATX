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


def tolerance_relaxation_operator(val: float, lower: float, upper: float) -> float:
    """Compute one-sided signed relaxation projection operator r_tol(NNI; [lower, upper]).

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
        0.000000 if lower <= val <= upper (inside physiological tolerance interval).
        val - lower (< 0.0) if val < lower (deficit violation).
        val - upper (> 0.0) if val > upper (excess luxury violation).

    Raises
    ------
    ValueError
        If inputs are NaN/inf or lower > upper.
    """
    if math.isnan(val) or math.isinf(val):
        raise ValueError(f"Simulated NNI value must not be NaN or infinite, got {val}")
    if math.isnan(lower) or math.isnan(upper) or lower > upper:
        raise ValueError(f"Lower bound ({lower}) cannot exceed upper bound ({upper})")

    if val < lower:
        return val - lower
    elif val > upper:
        return val - upper
    else:
        return 0.0


def pseudo_huber_loss(residual: float, delta: float = 0.50) -> float:
    """Smooth C^inf Pseudo-Huber loss function for robust parameter estimation.

    h_delta(r) = delta^2 * (sqrt(1 + (r / delta)^2) - 1)

    Parameters
    ----------
    residual : float
        Residual or distance outside tolerance interval.
    delta : float, optional
        Transition scale parameter, default 0.50.

    Returns
    -------
    float
        0.000000 if residual == 0.0.
        Approaches 0.5 * r^2 for |r| << delta.
        Approaches delta * |r| - delta^2 for |r| >> delta.
    """
    if math.isnan(residual) or math.isinf(residual):
        raise ValueError(f"Residual must not be NaN or infinite, got {residual}")
    if math.isnan(delta) or delta <= 0.0:
        raise ValueError(f"Scale parameter delta must be positive, got {delta}")

    if residual == 0.0:
        return 0.0

    ratio = residual / delta
    return (delta ** 2) * (math.sqrt(1.0 + ratio * ratio) - 1.0)


def relaxed_pseudo_huber_residual(
    val: float,
    lower: float,
    upper: float,
    delta: float = 0.50,
) -> float:
    """Compute signed Pseudo-Huber smoothed residual for PEST++ zero-residual tolerance fitting.

    r_tol = sign(z) * sqrt(2 * h_delta(z))

    Guarantees:
    - Within [lower, upper]: residual is strictly 0.000000 (zero penalty).
    - Squared residual (r_tol)^2 == 2 * h_delta(z) ~ z^2 for small violations.
    - Smooth, continuous transition at boundary points lower and upper.
    """
    z = tolerance_relaxation_operator(val, lower, upper)
    if z == 0.0:
        return 0.0
    loss = pseudo_huber_loss(z, delta)
    sign = 1.0 if z > 0.0 else -1.0
    return sign * math.sqrt(2.0 * loss)


def tolerance_interval_loss(
    val: float,
    lower: float,
    upper: float,
    delta: float = 0.50,
    method: str = "quadratic",
) -> float:
    """Compute loss outside the physiological tolerance interval.

    Within [lower, upper], returns strictly 0.000000.
    Outside:
      If method == 'pseudo_huber': returns 2 * h_delta(z).
      If method == 'quadratic': returns z^2.

    Parameters
    ----------
    val : float
        Simulated NNI value.
    lower : float
        Lower acceptable bound.
    upper : float
        Upper acceptable bound.
    delta : float, optional
        Pseudo-Huber scale parameter, default 0.50.
    method : str, optional
        'quadratic' or 'pseudo_huber', default 'quadratic'.

    Returns
    -------
    float
        Loss value. Exactly 0.0 if val in [lower, upper].
    """
    z = tolerance_relaxation_operator(val, lower, upper)
    if z == 0.0:
        return 0.0

    if method == "pseudo_huber":
        return 2.0 * pseudo_huber_loss(z, delta)
    elif method == "quadratic":
        return z ** 2
    else:
        raise ValueError(f"Unknown penalty method: '{method}', expected 'quadratic' or 'pseudo_huber'")


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
    relaxed_residual: float = 0.0  # r_tol(NNI; [lower, upper])


def compute_cnc_objective_penalty(
    simulated_nni: Mapping[str, Sequence[float]],
    weights: Optional[Mapping[str, float]] = None,
    intervals: Optional[Mapping[str, tuple[float, float]]] = None,
    default_weight: float = DEFAULT_VARIANCE_NORMALIZED_WEIGHT,
    delta: float = 0.50,
    method: str = "quadratic",
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
    delta : float, optional
        Pseudo-Huber scale parameter, default 0.50.
    method : str, optional
        Penalty method: 'quadratic' (default) or 'pseudo_huber'.

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
            # Skip invalid / pre-emergence sentinel values (< 0.0 or -99.0)
            if (
                math.isnan(nni_val)
                or math.isinf(nni_val)
                or nni_val < 0.0
                or nni_val == -99.0
            ):
                continue

            unweighted = tolerance_interval_loss(nni_val, lower, upper, delta=delta, method=method)
            r_tol = relaxed_pseudo_huber_residual(nni_val, lower, upper, delta=delta)
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
                    relaxed_residual=r_tol,
                )
            )

    return total_penalty, components
