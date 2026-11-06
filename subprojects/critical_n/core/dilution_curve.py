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

# --- Scheme C (CANE): curve-anchored N status envelope (2026-10-31) ---
DEFAULT_CANE_RFNMX: float = 1.20  # Luxury ceiling / critical ratio
DEFAULT_CANE_RFNMN: float = 0.88  # Functional floor / critical ratio
DEFAULT_CANE_KSTEM: float = 0.573 # Stem / leaf critical N ratio


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
    return nc_inf + (a - nc_inf) * ((w_eff / w0) ** (-b))


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


def cane_gate(pcnl_pct: float, nmin_l_fraction: float) -> float:
    """Functional-N status gate S in [0, 1] (Scheme C, decision D2 x D6).

    Mirrors DEMAND.for (CANE branch): the luxury-ceiling gate is the
    functional pool status saturating at 1.0 once leaf N reaches the
    curve-anchored functional boundary c_opt,L = Nmin_L(W).

        S = min(1.0, (PCNL/100) / Nmin_L)   for PCNL > 0, Nmin_L > 1e-6

    A centred sigmoid on this bounded functional index is degenerate
    (max 0.5 at centre); the linear saturating form preserves the
    approved intent "deficient -> shrink toward critical, adequate ->
    fully open" without extra parameters.
    """
    if nmin_l_fraction <= 1.0e-6 or pcnl_pct <= 0.0:
        return 1.0
    return min(1.0, (pcnl_pct / 100.0) / nmin_l_fraction)


def cane_envelope(
    w: float,
    *,
    a: float = DEFAULT_CNC_A,
    b: float = DEFAULT_CNC_B,
    w0: float = DEFAULT_CNC_W0,
    nc_inf: float = DEFAULT_CNC_NC_INF,
    prolfi: float,
    prolfg: float,
    prolff: float,
    prosti: float,
    prostg: float,
    prostf: float,
    rfnmx: float = DEFAULT_CANE_RFNMX,
    rfnmn: float = DEFAULT_CANE_RFNMN,
    kstem: float = DEFAULT_CANE_KSTEM,
    pcnl: Optional[float] = None,
) -> dict:
    """Curve-anchored N envelope (Scheme C / CANE), line-by-line mirror of
    DEMAND.for CANE branch. All returned concentrations are percentages.

    Structure (fractions internally, 0.16 protein->N):
        Nmin_L(W) = max(PROLFF*0.16, RFNMN*Nc)          floor + GROW c_opt,L
        Nmax_L(W) = max(Nc+(min(PROLFI*0.16, RFNMX*Nc)-Nc)*S, Nmin_L+0.003)
        FNINL(W)  = max(Nmin_L+0.002, min(Nmax_L, 1.05*Nc))
        Nmin_S/Nmax_S/FNINS analogous with Nc_S = KSTEM*Nc (+0.001 margin)
        NVSTL     = max(Nmin_L, min(FNINL, Nc))          refill to critical

    pcnl (actual leaf N %, yesterday-close) drives the luxury gate; None
    or <= 0 keeps the gate fully open (S = 1, e.g. pre-emergence).
    """
    if rfnmn >= rfnmx:
        raise ValueError(f"CANE RFNMN ({rfnmn}) must be < RFNMX ({rfnmx})")
    nc_pct = critical_n_concentration(w, a=a, b=b, w0=w0, nc_inf=nc_inf)
    nc_f = nc_pct / 100.0
    # PROLFG/PROSTG file fallback (<= 0 -> derive), retained for parity
    prolfg_eff = prolfg if prolfg > 0.0 else prolfi * 0.815
    prostg_eff = prostg if prostg > 0.0 else prosti * 0.723

    nmin_l = max(prolff * 0.16, rfnmn * nc_f)
    nc_s = kstem * nc_f
    nmin_s = max(prostf * 0.16, rfnmn * nc_s)

    gate = cane_gate(pcnl if pcnl is not None else 0.0, nmin_l)

    nmax_l = min(prolfi * 0.16, rfnmx * nc_f)
    nmax_l = nc_f + (nmax_l - nc_f) * gate
    fninl = max(nmin_l + 0.002, min(nmax_l, 1.05 * nc_f))

    nmax_s = min(prosti * 0.16, rfnmx * nc_s)
    nmax_s = nc_s + (nmax_s - nc_s) * gate
    fnins = max(nmin_s + 0.001, min(nmax_s, 1.05 * nc_s))

    nvstl = max(nmin_l, min(fninl, nc_f))
    nvsts = max(nmin_s, min(fnins, nc_s))

    return {
        "nc_pct": nc_pct,
        "gate": gate,
        "nmin_l_pct": 100.0 * nmin_l,
        "nmax_l_pct": 100.0 * nmax_l,
        "fninl_pct": 100.0 * fninl,
        "nmin_s_pct": 100.0 * nmin_s,
        "nmax_s_pct": 100.0 * nmax_s,
        "fnins_pct": 100.0 * fnins,
        "nvstl_pct": 100.0 * nvstl,
        "nvsts_pct": 100.0 * nvsts,
        "prolfg_eff": prolfg_eff,
        "prostg_eff": prostg_eff,
    }


def legacy_static_envelope(
    w: float,
    *,
    a: float = DEFAULT_CNC_A,
    b: float = DEFAULT_CNC_B,
    w0: float = DEFAULT_CNC_W0,
    nc_inf: float = DEFAULT_CNC_NC_INF,
    prolfi: float,
    prolfg: float,
    prolff: float,
    prosti: float,
    prostg: float,
    prostf: float,
) -> dict:
    """Pre-CANE envelope (DEMAND.for legacy branch), for equivalence tests."""
    nc_pct = critical_n_concentration(w, a=a, b=b, w0=w0, nc_inf=nc_inf)
    prolfg_eff = prolfg if prolfg > 0.0 else prolfi * 0.815
    prostg_eff = prostg if prostg > 0.0 else prosti * 0.723
    fninl = min(prolfi * 0.16, max(prolfg_eff * 0.16 + 0.002, 1.05 * nc_pct / 100.0))
    if prolfi > prolff:
        fr_dil = (fninl - prolff * 0.16) / ((prolfi - prolff) * 0.16)
        fr_dil = max(0.0, min(1.0, fr_dil))
    else:
        fr_dil = 1.0
    fnins = prostf * 0.16 + (prosti - prostf) * 0.16 * fr_dil
    fnins = min(prosti * 0.16, fnins)
    fnins = max(prostg_eff * 0.16 + 0.001, fnins)
    return {
        "nc_pct": nc_pct,
        "fninl_pct": 100.0 * fninl,
        "fnins_pct": 100.0 * fnins,
        "fr_dil": fr_dil,
    }
