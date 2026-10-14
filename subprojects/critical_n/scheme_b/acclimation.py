"""Photosynthetic acclimation coupling module for CROPGRO nitrogen dynamics (Scheme B).

Implements the continuous physiological coupling between Nitrogen Nutrition Index (NNI)
and canopy gross photosynthesis (PHOTO / AGEFAC):
    AGEFAC_CNC = AGEFAC_native * S(NNI)

Provides three smooth continuous response functions:
1. Bounded Sigmoid (logistic saturation):
       S(NNI) = NNI_min + (S_max - NNI_min) / (1.0 + exp(-4.0 * (NNI - 1.0) / gamma))
2. Hill function (cooperative binding kinetics):
       S(NNI) = S_min + (S_max - S_min) * (NNI^h / (K_half^h + NNI^h)) * Norm
3. Michaelis-Menten (saturating enzyme kinetics):
       S(NNI) = S_min + (S_max - S_min) * ((1 + Km) * NNI / (Km + NNI))

All functions are strictly bounded within [S_min, S_max] (typically [0.30, 1.05]),
eliminating runaway positive feedback (excessive vegetative growth under high N)
and sudden stalling (catastrophic collapse under moderate N deficiency).
"""

from __future__ import annotations

import enum
import math
from typing import Tuple


DEFAULT_CNC_A: float = 4.85
DEFAULT_CNC_B: float = 0.38
DEFAULT_CNC_W0: float = 1.00

DEFAULT_GAMMA: float = 0.65
DEFAULT_NNI_MIN: float = 0.30
DEFAULT_S_MAX: float = 1.05

DEFAULT_HILL_COEF: float = 3.0
DEFAULT_HILL_K_HALF: float = 0.85

DEFAULT_MM_KM: float = 0.35


class AcclimationType(str, enum.Enum):
    """Supported continuous photosynthetic acclimation functional forms."""
    SIGMOID = "sigmoid"
    HILL = "hill"
    MICHAELIS_MENTEN = "michaelis_menten"


def bounded_sigmoid_acclimation(
    nni: float,
    gamma: float = DEFAULT_GAMMA,
    nni_min: float = DEFAULT_NNI_MIN,
    s_max: float = DEFAULT_S_MAX,
    x_mid: float = 1.0,
    normalize_at_one: bool = False,
) -> float:
    """Compute bounded sigmoid photosynthetic acclimation multiplier S(NNI).

    Formula:
        S(NNI) = nni_min + (s_max - nni_min) / (1.0 + exp(-4.0 * (NNI - x_mid) / gamma))

    When normalize_at_one is True, aligns the function such that at NNI = 1.0,
    S(1.0) == 1.00 (critical nitrogen neutrality):
        - For NNI <= 1.0: transitions smoothly from nni_min up to 1.00
        - For NNI > 1.0: transitions from 1.00 up to s_max (luxury excess boost)

    Parameters
    ----------
    nni : float
        Nitrogen Nutrition Index.
    gamma : float, optional
        Elasticity slope parameter, default 0.65.
    nni_min : float, optional
        Minimum photosynthetic floor, default 0.30.
    s_max : float, optional
        Upper saturation multiplier, default 1.05.
    x_mid : float, optional
        Inflection midpoint, default 1.0.
    normalize_at_one : bool, optional
        If True, normalizes response to equal 1.0 at NNI=1.0. Default False.

    Returns
    -------
    float
        Acclimation factor bounded in [nni_min, s_max].
    """
    if math.isnan(nni) or math.isinf(nni):
        raise ValueError(f"NNI must not be NaN or infinite, got {nni}")
    if gamma <= 0.0:
        raise ValueError(f"gamma must be positive, got {gamma}")
    if nni_min < 0.0 or nni_min >= s_max:
        raise ValueError(f"nni_min must be in [0, s_max), got nni_min={nni_min}, s_max={s_max}")

    arg = -4.0 * (nni - x_mid) / gamma
    # Guard against floating point overflow
    arg = max(-50.0, min(50.0, arg))
    logistic = 1.0 / (1.0 + math.exp(arg))

    if normalize_at_one:
        arg_one = -4.0 * (1.0 - x_mid) / gamma
        arg_one = max(-50.0, min(50.0, arg_one))
        logistic_one = 1.0 / (1.0 + math.exp(arg_one))
        if 0.0 < logistic_one < 1.0:
            if nni <= 1.0:
                frac = logistic / logistic_one
                val = nni_min + (1.0 - nni_min) * frac
            else:
                rem = 1.0 - logistic_one
                frac = (logistic - logistic_one) / rem
                val = 1.0 + (s_max - 1.0) * frac
        else:
            val = nni_min + (s_max - nni_min) * logistic
    else:
        val = nni_min + (s_max - nni_min) * logistic

    return max(nni_min, min(s_max, val))


def hill_acclimation(
    nni: float,
    hill_coef: float = DEFAULT_HILL_COEF,
    k_half: float = DEFAULT_HILL_K_HALF,
    s_min: float = DEFAULT_NNI_MIN,
    s_max: float = DEFAULT_S_MAX,
) -> float:
    """Compute Hill-type cooperative photosynthetic acclimation multiplier.

    Formula:
        Fraction(x) = x^h / (k_half^h + x^h)
        Normalized to 1.0 at NNI = 1.0:
        NormFactor = (k_half^h + 1.0) / 1.0
        S(NNI) = s_min + (s_max - s_min) * min(1.0, Fraction(NNI) * NormFactor)

    Parameters
    ----------
    nni : float
        Nitrogen Nutrition Index.
    hill_coef : float, optional
        Hill cooperativity exponent h, default 3.0.
    k_half : float, optional
        Half-saturation constant K_0.5, default 0.85.
    s_min : float, optional
        Minimum survival floor, default 0.30.
    s_max : float, optional
        Maximum upper saturation, default 1.05.

    Returns
    -------
    float
        Acclimation factor bounded in [s_min, s_max].
    """
    if math.isnan(nni) or math.isinf(nni):
        raise ValueError(f"NNI must not be NaN or infinite, got {nni}")
    if hill_coef <= 0.0:
        raise ValueError(f"hill_coef must be positive, got {hill_coef}")
    if k_half <= 0.0:
        raise ValueError(f"k_half must be positive, got {k_half}")
    if s_min < 0.0 or s_min >= s_max:
        raise ValueError(f"s_min must be in [0, s_max), got s_min={s_min}, s_max={s_max}")

    x = max(0.0, nni)
    xh = x ** hill_coef
    kh = k_half ** hill_coef

    # Normalized such that at NNI=1.0, the response aligns smoothly with 1.0
    norm = (kh + 1.0)
    frac = (xh / (kh + xh)) * norm if (kh + xh) > 0.0 else 0.0
    frac = min(1.0, frac)

    val = s_min + (s_max - s_min) * frac
    return max(s_min, min(s_max, val))


def michaelis_menten_acclimation(
    nni: float,
    km: float = DEFAULT_MM_KM,
    s_min: float = DEFAULT_NNI_MIN,
    s_max: float = DEFAULT_S_MAX,
) -> float:
    """Compute Michaelis-Menten saturating photosynthetic acclimation multiplier.

    Formula:
        NormFraction(x) = ((1.0 + km) * x) / (km + x)
        S(NNI) = s_min + (s_max - s_min) * min(1.0, NormFraction(NNI))

    Parameters
    ----------
    nni : float
        Nitrogen Nutrition Index.
    km : float, optional
        Michaelis affinity constant Km, default 0.35.
    s_min : float, optional
        Minimum survival floor, default 0.30.
    s_max : float, optional
        Maximum saturation level, default 1.05.

    Returns
    -------
    float
        Acclimation factor bounded in [s_min, s_max].
    """
    if math.isnan(nni) or math.isinf(nni):
        raise ValueError(f"NNI must not be NaN or infinite, got {nni}")
    if km <= 0.0:
        raise ValueError(f"km must be positive, got {km}")
    if s_min < 0.0 or s_min >= s_max:
        raise ValueError(f"s_min must be in [0, s_max), got s_min={s_min}, s_max={s_max}")

    x = max(0.0, nni)
    if x <= 0.0:
        return s_min

    frac = ((1.0 + km) * x) / (km + x)
    frac = min(1.0, frac)
    val = s_min + (s_max - s_min) * frac
    return max(s_min, min(s_max, val))


def compute_nni_from_states(
    wtlf: float,
    wtnlf: float,
    cwad: float,
    cum_harvest_dry: float = 0.0,
    cnc_a: float = DEFAULT_CNC_A,
    cnc_b: float = DEFAULT_CNC_B,
    cnc_w0: float = DEFAULT_CNC_W0,
    min_leaf_biomass: float = 5.0,
) -> Tuple[float, float, float, float]:
    """Compute effective biomass, critical nitrogen, actual leaf N%, and NNI.

    Parameters
    ----------
    wtlf : float
        Leaf dry weight (g DM/m^2).
    wtnlf : float
        Leaf nitrogen mass (g N/m^2).
    cwad : float
        Standing tops dry biomass (kg DM/ha).
    cum_harvest_dry : float, optional
        Cumulative harvested fruit dry biomass (kg DM/ha), default 0.0.
    cnc_a : float, optional
        Dilution coefficient a (%), default 4.85.
    cnc_b : float, optional
        Dilution exponent b, default 0.38.
    cnc_w0 : float, optional
        Dilution starting threshold W0 (t DM/ha), default 1.00.
    min_leaf_biomass : float, optional
        Minimum leaf biomass threshold below which seedling neutrality (NNI=1.0) is returned,
        default 5.0 g DM/m^2.

    Returns
    -------
    tuple of (w_eff, nc, pcnl, nni)
        w_eff : float (t DM/ha)
        nc : float (%)
        pcnl : float (%)
        nni : float (dimensionless)
    """
    if wtlf < min_leaf_biomass or cwad <= 0.0:
        # Seedling neutral mapping prior to significant canopy formation
        w_eff = max(0.001, (cwad + cum_harvest_dry) / 1000.0)
        nc = cnc_a
        pcnl = (wtnlf / max(1.0, wtlf)) * 100.0 if wtlf > 0.0 else cnc_a
        return (w_eff, nc, pcnl, 1.0)

    # Cumulative effective biomass (t DM/ha)
    w_eff = (cwad + cum_harvest_dry) / 1000.0
    w_calc = max(cnc_w0, w_eff)
    nc = cnc_a * ((w_calc / cnc_w0) ** (-cnc_b))

    pcnl = (wtnlf / wtlf) * 100.0
    nni = pcnl / nc if nc > 0.0 else 1.0
    return (w_eff, nc, pcnl, nni)


def couple_photosynthesis(
    native_agefac: float,
    nni: float,
    acclimation_type: AcclimationType = AcclimationType.SIGMOID,
    gamma: float = DEFAULT_GAMMA,
    nni_min: float = DEFAULT_NNI_MIN,
    s_max: float = DEFAULT_S_MAX,
    x_mid: float = 1.0,
    normalize_at_one: bool = False,
    hill_coef: float = DEFAULT_HILL_COEF,
    k_half: float = DEFAULT_HILL_K_HALF,
    km: float = DEFAULT_MM_KM,
) -> float:
    """Couple native photosynthetic factor AGEFAC with continuous NNI acclimation.

    Parameters
    ----------
    native_agefac : float
        Native DSSAT leaf nitrogen factor on photosynthesis (AGEFAC or AGEFCC).
    nni : float
        Nitrogen Nutrition Index.
    acclimation_type : AcclimationType, optional
        Functional form (SIGMOID, HILL, or MICHAELIS_MENTEN).
    gamma, nni_min, s_max, x_mid, normalize_at_one, hill_coef, k_half, km : float / bool
        Parameter values for the respective functional forms.

    Returns
    -------
    float
        Coupled photosynthetic factor AGEFAC_CNC.
    """
    if acclimation_type == AcclimationType.SIGMOID:
        multiplier = bounded_sigmoid_acclimation(
            nni,
            gamma=gamma,
            nni_min=nni_min,
            s_max=s_max,
            x_mid=x_mid,
            normalize_at_one=normalize_at_one,
        )
    elif acclimation_type == AcclimationType.HILL:
        multiplier = hill_acclimation(nni, hill_coef=hill_coef, k_half=k_half, s_min=nni_min, s_max=s_max)
    elif acclimation_type == AcclimationType.MICHAELIS_MENTEN:
        multiplier = michaelis_menten_acclimation(nni, km=km, s_min=nni_min, s_max=s_max)
    else:
        raise ValueError(f"Unsupported acclimation_type: {acclimation_type}")

    return native_agefac * multiplier
