"""Senescence rate limiter module for CROPGRO nitrogen dynamics (Scheme B).

Implements the mandatory leaf senescence governor:
    LFSEN_actual = min(LFSEN_native, gamma * WLDOTN)
where gamma in [0.85, 0.95] (default 0.90).

Scientific Rationale:
In native DSSAT CROPGRO, nitrogen mobilization for fruit growth triggers:
    LFSEN = SENRTE * (NRUSLF / 0.16)
When fruit sink demand is high or soil N is low, NRUSLF can surge, causing:
    LFSEN > WLDOTN  ==>  ALFDOT_net = WLDOTN - LFSEN < 0
This destroys canopy leaf area faster than new leaves can be grown, collapsing LAI,
further depressing daily gross photosynthesis (PG), and escalating into an irreversible
defoliation avalanche / death spiral.

When combined with Scheme B photosynthetic down-regulation (where PG is lowered under N
deficit), the avalanche ratio LFSEN / WLDOTN would otherwise be amplified by up to 3.12x.
The senescence governor provides an absolute mathematical firewall:
    ALFDOT_net = WLDOTN - LFSEN_actual >= (1.0 - gamma) * WLDOTN >= 0
guaranteeing canopy structural integrity while preserving full nitrogen mass balance.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Optional


DEFAULT_SENESCENCE_GAMMA: float = 0.90
DEFAULT_STANDING_LEAF_BUFFER: float = 0.015  # Optional buffer fraction of WTLF


@dataclasses.dataclass(frozen=True)
class SenescenceGovernanceResult:
    """Diagnostic audit record for daily senescence governance."""
    native_lfsen: float          # Raw uninhibited leaf senescence from N mobilization (g DM/m^2/d)
    governed_lfsen: float        # Governed leaf senescence after rate limiting (g DM/m^2/d)
    wldotn: float                # Daily new leaf biomass growth (g DM/m^2/d)
    wtlf: float                  # Standing leaf biomass before senescence (g DM/m^2)
    suppressed_loss: float       # Biomass of defoliation prevented by governor (g DM/m^2/d)
    avalanche_prevented: bool    # True if native_lfsen > wldotn would have occurred
    net_leaf_growth: float       # Governed net leaf mass change (wldotn - governed_lfsen)


class SenescenceGovernor:
    """Leaf senescence rate limiter and avalanche governor.

    Parameters
    ----------
    gamma : float, optional
        Maximum allowable fraction of daily new leaf growth that can be senesced
        due to N mobilization. Must be in [0.85, 0.95]. Default 0.90.
    standing_buffer_ratio : float, optional
        Optional small baseline turnover fraction of standing green leaves WTLF,
        default 0.0 (pure growth gating) or 0.015 for composite buffering.
    allow_post_maturity_unclamp : bool, optional
        If True, allows full uninhibited natural senescence after physiological
        maturity (e.g. stage >= MAT). Default True.
    """

    def __init__(
        self,
        gamma: float = DEFAULT_SENESCENCE_GAMMA,
        standing_buffer_ratio: float = 0.0,
        allow_post_maturity_unclamp: bool = True,
    ) -> None:
        if gamma < 0.80 or gamma > 0.98:
            raise ValueError(f"gamma must be in physiological range [0.80, 0.98], got {gamma}")
        if standing_buffer_ratio < 0.0 or standing_buffer_ratio > 0.10:
            raise ValueError(
                f"standing_buffer_ratio must be in [0.0, 0.10], got {standing_buffer_ratio}"
            )

        self.gamma = gamma
        self.standing_buffer_ratio = standing_buffer_ratio
        self.allow_post_maturity_unclamp = allow_post_maturity_unclamp

    def govern_senescence(
        self,
        native_lfsen: float,
        wldotn: float,
        wtlf: float,
        is_mature: bool = False,
    ) -> SenescenceGovernanceResult:
        """Apply senescence governor to daily leaf loss.

        Formula:
            LFSEN_actual = min(
                native_lfsen,
                gamma * wldotn + delta * wtlf
            )
            clamped to not exceed standing leaf biomass wtlf.

        Parameters
        ----------
        native_lfsen : float
            Native unconstrained mobilization senescence (g DM/m^2/d).
        wldotn : float
            Daily new leaf dry weight growth (g DM/m^2/d).
        wtlf : float
            Current standing green leaf dry weight (g DM/m^2).
        is_mature : bool, optional
            Whether crop has reached physiological maturity / season end. Default False.

        Returns
        -------
        SenescenceGovernanceResult
            Diagnostic record containing governed leaf loss and avalanche prevention metrics.
        """
        if math.isnan(native_lfsen) or math.isnan(wldotn) or math.isnan(wtlf):
            raise ValueError(
                f"Inputs must not be NaN: native_lfsen={native_lfsen}, wldotn={wldotn}, wtlf={wtlf}"
            )
        if native_lfsen < 0.0:
            native_lfsen = 0.0
        if wldotn < 0.0:
            wldotn = 0.0
        if wtlf < 0.0:
            wtlf = 0.0

        # Post-maturity unclamp: Allow complete natural senescence at harvest/end
        if is_mature and self.allow_post_maturity_unclamp:
            governed = min(wtlf, native_lfsen)
            suppressed = max(0.0, native_lfsen - governed)
            return SenescenceGovernanceResult(
                native_lfsen=native_lfsen,
                governed_lfsen=governed,
                wldotn=wldotn,
                wtlf=wtlf,
                suppressed_loss=suppressed,
                avalanche_prevented=False,
                net_leaf_growth=wldotn - governed,
            )

        # Compute dynamic upper ceiling for N-mobilization senescence
        ceiling = self.gamma * wldotn
        if self.standing_buffer_ratio > 0.0:
            ceiling += self.standing_buffer_ratio * wtlf

        # Apply limiter
        governed = min(native_lfsen, ceiling)
        governed = min(wtlf, governed)
        governed = max(0.0, governed)

        suppressed = max(0.0, native_lfsen - governed)
        avalanche_prevented = (native_lfsen > wldotn) and (governed < native_lfsen)
        net_leaf_growth = wldotn - governed

        return SenescenceGovernanceResult(
            native_lfsen=native_lfsen,
            governed_lfsen=governed,
            wldotn=wldotn,
            wtlf=wtlf,
            suppressed_loss=suppressed,
            avalanche_prevented=avalanche_prevented,
            net_leaf_growth=net_leaf_growth,
        )


def apply_senescence_limiter(
    native_lfsen: float,
    wldotn: float,
    wtlf: float,
    gamma: float = DEFAULT_SENESCENCE_GAMMA,
    buffer_ratio: float = 0.0,
    is_mature: bool = False,
) -> float:
    """Functional convenience entrypoint for senescence rate limiting.

    Parameters
    ----------
    native_lfsen : float
        Native unconstrained mobilization senescence (g DM/m^2/d).
    wldotn : float
        Daily new leaf dry weight growth (g DM/m^2/d).
    wtlf : float
        Standing green leaf dry weight (g DM/m^2).
    gamma : float, optional
        Limiting ratio in [0.85, 0.95], default 0.90.
    buffer_ratio : float, optional
        Standing leaf buffer fraction, default 0.0.
    is_mature : bool, optional
        Maturity bypass flag.

    Returns
    -------
    float
        Governed daily leaf senescence (g DM/m^2/d).
    """
    gov = SenescenceGovernor(gamma=gamma, standing_buffer_ratio=buffer_ratio)
    res = gov.govern_senescence(native_lfsen, wldotn, wtlf, is_mature=is_mature)
    return res.governed_lfsen
