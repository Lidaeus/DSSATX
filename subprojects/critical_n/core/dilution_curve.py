"""Critical nitrogen dilution curve and NNI formulations.

Implements the Greenwood-Lemaire allometric power-law curve:
    Nc(W) = a * (max(W0, W))^(-b)

And Nitrogen Nutrition Index (NNI):
    NNI = N_act / Nc(W)

Provides numerical singularity protection for W -> 0 and Scheme B gating references.
"""

from __future__ import annotations

import math
from typing import Optional, Union


DEFAULT_CNC_A: float = 4.85      # Baseline critical N at W <= W0 (%)
DEFAULT_CNC_B: float = 0.38      # Dilution exponent slope (dimensionless)
DEFAULT_CNC_W0: float = 1.00     # Canopy closure threshold (t DM/ha)
DEFAULT_CNC_NC_INF: float = 1.70 # Asymptotic lower bound for multi-harvest crops (%)
DEFAULT_CNC_C_INF: float = 1.70  # Standard alias
DEFAULT_CNC_GAMMA: float = 0.65  # Scheme B photo-response slope
DEFAULT_CNC_NNIMIN: float = 0.30 # Scheme B minimum photo floor
SENTINEL_VALUE: float = -99.0    # Fixed-column missing/pre-emergence sentinel


def critical_n_concentration(
    w: float,
    a: float = DEFAULT_CNC_A,
    b: float = DEFAULT_CNC_B,
    w0: float = DEFAULT_CNC_W0,
    nc_inf: float = DEFAULT_CNC_NC_INF,
) -> float:
    """Compute critical nitrogen concentration Nc (%) with asymptotic lower bound.

    Formulation:
        Nc(W) = Nc_inf + (a - Nc_inf) * [max(W0, W)]^(-b)

    Parameters
    ----------
    w : float
        Crop dry biomass (t DM/ha). Must be non-negative.
    a : float, optional
        Maximum critical N concentration at seedling stage (W <= W0), default 4.85%.
    b : float, optional
        Dilution exponent slope, default 0.38.
    w0 : float, optional
        Canopy closure dry biomass threshold (t DM/ha) below which Nc remains constant at `a`.
        Default 1.00 t DM/ha.
    nc_inf : float, optional
        Asymptotic lower-bound nitrogen concentration (%), default 1.70%.
        Guarantees that Nc(W) does not decay to zero under large cumulative yields.
        When nc_inf == 0.0, reduces to the classic Greenwood-Lemaire power-law model.

    Returns
    -------
    float
        Critical N concentration Nc in percent dry weight (%).

    Raises
    ------
    ValueError
        If w < 0, a <= 0, b < 0, w0 <= 0, nc_inf < 0, nc_inf > a, or on NaN/Inf.
    """
    if (
        math.isnan(w)
        or math.isnan(a)
        or math.isnan(b)
        or math.isnan(w0)
        or math.isnan(nc_inf)
    ):
        raise ValueError(f"Parameters and inputs must not be NaN: w={w}, a={a}, b={b}, w0={w0}, nc_inf={nc_inf}")
    if (
        math.isinf(w)
        or math.isinf(a)
        or math.isinf(b)
        or math.isinf(w0)
        or math.isinf(nc_inf)
    ):
        raise ValueError(f"Parameters and inputs must not be infinite: w={w}, a={a}, b={b}, w0={w0}, nc_inf={nc_inf}")
    if w < 0.0:
        raise ValueError(f"Biomass w must be non-negative, got {w}")
    if a <= 0.0:
        raise ValueError(f"Parameter a must be positive, got {a}")
    if b < 0.0:
        raise ValueError(f"Parameter b must be non-negative, got {b}")
    if w0 <= 0.0:
        raise ValueError(f"Threshold w0 must be positive, got {w0}")
    if nc_inf < 0.0:
        raise ValueError(f"Asymptotic limit nc_inf must be non-negative, got {nc_inf}")
    if nc_inf > a:
        raise ValueError(f"Asymptotic limit nc_inf ({nc_inf}) cannot exceed seedling maximum a ({a})")

    w_eff = max(w0, w)
    return nc_inf + (a - nc_inf) * (w_eff ** (-b))


def nni(
    n_act: float,
    nc: float,
    *,
    sentinel_on_invalid: bool = False,
) -> float:
    """Calculate Nitrogen Nutrition Index (NNI = N_act / Nc).

    Parameters
    ----------
    n_act : float
        Actual tissue/canopy total nitrogen concentration (%).
    nc : float
        Critical nitrogen concentration (%). Must be positive.
    sentinel_on_invalid : bool, optional
        If True, return SENTINEL_VALUE (-99.0) when nc <= 0 or on NaN/inf instead of raising ValueError.

    Returns
    -------
    float
        Dimensionless NNI ratio.

    Raises
    ------
    ValueError
        If nc <= 0 and sentinel_on_invalid is False, or if n_act < 0, or on NaN/Inf.
    """
    if math.isnan(n_act) or math.isnan(nc) or math.isinf(n_act) or math.isinf(nc):
        if sentinel_on_invalid:
            return SENTINEL_VALUE
        raise ValueError(f"Inputs must not be NaN or infinite, got n_act={n_act}, nc={nc}")

    if n_act < 0.0:
        if sentinel_on_invalid:
            return SENTINEL_VALUE
        raise ValueError(f"Actual nitrogen concentration n_act must be non-negative, got {n_act}")

    if nc <= 0.0:
        if sentinel_on_invalid:
            return SENTINEL_VALUE
        raise ValueError(f"Critical nitrogen concentration nc must be positive, got {nc}")

    return n_act / nc


def scheme_b_sigmoid_gate(
    nni_val: float,
    gamma: float = DEFAULT_CNC_GAMMA,
    nni_min: float = DEFAULT_CNC_NNIMIN,
) -> float:
    """Compute Scheme B bounded sigmoid gating multiplier S(NNI) for AGEFAC.

    S(NNI) = nni_min + (1.05 - nni_min) / (1.0 + exp(-4.0 * (NNI - 1.0) / gamma))

    Parameters
    ----------
    nni_val : float
        Nitrogen Nutrition Index.
    gamma : float, optional
        Elasticity slope parameter, default 0.65.
    nni_min : float, optional
        Minimum survival photosynthetic floor, default 0.30.

    Returns
    -------
    float
        Gating multiplier bounded in [nni_min, 1.05].
    """
    if gamma <= 0.0:
        raise ValueError(f"gamma must be positive, got {gamma}")
    if nni_min < 0.0 or nni_min > 1.0:
        raise ValueError(f"nni_min must be in [0, 1], got {nni_min}")

    arg = -4.0 * (nni_val - 1.0) / gamma
    # Guard against floating-point overflow
    arg = max(-50.0, min(50.0, arg))
    gate = nni_min + (1.05 - nni_min) / (1.0 + math.exp(arg))
    return max(nni_min, min(1.05, gate))


def scheme_b_vegetative_denominator(
    wtlf: float,
    stmwt: float,
    wcrlf: float = 0.0,
    wcrst: float = 0.0,
    min_denom: float = 10.0,
) -> float:
    """Safely compute structural vegetative denominator to prevent ZeroDivisionError.

    Denom_veg = max(min_denom, WTLF + STMWT - WCRLF - WCRST) (g DM / m^2).
    """
    raw_denom = (wtlf + stmwt) - (wcrlf + wcrst)
    return max(min_denom, raw_denom)
