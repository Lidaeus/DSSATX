"""Cumulative effective biomass and nitrogen formulations.

Addresses the multi-harvest fruit removal sawtooth discontinuity:
    W_eff(t) = (CWAD(t) + CUMHARVEST(t)) / 1000.0          (t DM/ha)
    N_act,cum(t) = 100.0 * (CNAD(t) + CUMHARVEST_N(t)) / (CWAD(t) + CUMHARVEST(t))  (%)

Ensures continuous, monotonic trajectories across multi-harvest events with
Delta W_eff == 0, Delta Nc == 0, Delta NNI == 0 at harvest time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from subprojects.critical_n.core.dilution_curve import (
    DEFAULT_CNC_A,
    DEFAULT_CNC_B,
    DEFAULT_CNC_NC_INF,
    DEFAULT_CNC_W0,
    SENTINEL_VALUE,
    critical_n_concentration,
    nni,
)

MIN_CANOPY_BIOMASS_T_HA: float = 0.05  # 50 kg/ha threshold for valid NNI calculation


@dataclass(frozen=True)
class BiomassStepResult:
    """State snapshot at a single simulation time step."""

    das: int
    cwad: float
    cnad: float
    cum_harvest_dm: float
    cum_harvest_n: float
    w_standing: float       # CWAD / 1000.0 (t DM/ha)
    w_eff: float            # (CWAD + CUMHARVEST) / 1000.0 (t DM/ha)
    n_act_standing: float   # (CNAD / CWAD) * 100 (%) or SENTINEL_VALUE
    n_act_cum: float        # 100 * (CNAD + CUMHARVEST_N) / (CWAD + CUMHARVEST) (%) or SENTINEL_VALUE
    nc_crit: float          # Critical N concentration Nc(W_eff) (%) or SENTINEL_VALUE
    nni_val: float          # NNI = n_act_cum / nc_crit or SENTINEL_VALUE
    is_valid: bool          # True if W_eff >= MIN_CANOPY_BIOMASS_T_HA and CWAD > 0
    chpdtn: float = 0.0     # Explicit state variable: cumulative mature fruit total N (kg N/ha)


def effective_biomass(
    cwad: float,
    cum_harvest_dm: float = 0.0,
) -> float:
    """Calculate cumulative effective aboveground dry biomass W_eff (t DM/ha).

    Parameters
    ----------
    cwad : float
        Current standing tops dry weight (kg DM/ha).
    cum_harvest_dm : float, optional
        Cumulative removed harvested fruit dry weight (kg DM/ha). Default 0.0.

    Returns
    -------
    float
        Cumulative effective biomass in t DM/ha.
    """
    if (
        math.isnan(cwad)
        or math.isnan(cum_harvest_dm)
        or math.isinf(cwad)
        or math.isinf(cum_harvest_dm)
    ):
        return 0.0
    total_dm_kg = max(0.0, cwad) + max(0.0, cum_harvest_dm)
    return total_dm_kg / 1000.0


def actual_cumulative_n_conc(
    cwad: float,
    cnad: float,
    cum_harvest_dm: float = 0.0,
    cum_harvest_n: float = 0.0,
    chpdtn: Optional[float] = None,
) -> float:
    """Calculate cumulative aboveground total nitrogen concentration N_act,cum (%).

    Parameters
    ----------
    cwad : float
        Current standing tops dry weight (kg DM/ha).
    cnad : float
        Current standing tops total nitrogen (kg N/ha).
    cum_harvest_dm : float, optional
        Cumulative removed harvested fruit dry weight (kg DM/ha).
    cum_harvest_n : float, optional
        Cumulative removed harvested fruit nitrogen (kg N/ha).
    chpdtn : float, optional
        Explicit cumulative harvested fruit nitrogen alias (kg N/ha).
        Overrides cum_harvest_n if provided.

    Returns
    -------
    float
        Tissue nitrogen percentage (%). Returns SENTINEL_VALUE if total DM < 50 kg/ha or NaN.
    """
    if (
        math.isnan(cwad)
        or math.isnan(cnad)
        or math.isnan(cum_harvest_dm)
        or math.isnan(cum_harvest_n)
        or (chpdtn is not None and math.isnan(chpdtn))
        or math.isinf(cwad)
        or math.isinf(cnad)
    ):
        return SENTINEL_VALUE

    effective_harvest_n = chpdtn if chpdtn is not None else cum_harvest_n
    total_dm_kg = max(0.0, cwad) + max(0.0, cum_harvest_dm)
    total_n_kg = max(0.0, cnad) + max(0.0, effective_harvest_n)

    if total_dm_kg < (MIN_CANOPY_BIOMASS_T_HA * 1000.0) or total_dm_kg <= 0.0:
        return SENTINEL_VALUE

    return (total_n_kg / total_dm_kg) * 100.0


class CumulativeStateTracker:
    """Stateful tracker for multi-step simulation trajectories with harvest accumulation."""

    def __init__(
        self,
        cnc_a: float = DEFAULT_CNC_A,
        cnc_b: float = DEFAULT_CNC_B,
        cnc_w0: float = DEFAULT_CNC_W0,
        cnc_nc_inf: float = DEFAULT_CNC_NC_INF,
        default_fruit_n_pct: float = 1.78,
    ) -> None:
        self.cnc_a = cnc_a
        self.cnc_b = cnc_b
        self.cnc_w0 = cnc_w0
        self.cnc_nc_inf = cnc_nc_inf
        self.default_fruit_n_pct = default_fruit_n_pct
        self.cum_harvest_dm: float = 0.0
        self.cum_harvest_n: float = 0.0
        self._prev_cwad: Optional[float] = None
        self._prev_cnad: Optional[float] = None

    def reset(self) -> None:
        """Reset internal accumulator for a new run/treatment."""
        self.cum_harvest_dm = 0.0
        self.cum_harvest_n = 0.0
        self._prev_cwad = None
        self._prev_cnad = None

    def step(
        self,
        das: int,
        cwad: float,
        cnad: float,
        harvest_dm: Optional[float] = None,
        harvest_n: Optional[float] = None,
        direct_chpdt: Optional[float] = None,
        direct_chpdtn: Optional[float] = None,
    ) -> BiomassStepResult:
        """Advance by one daily time step and return full state metrics.

        Parameters
        ----------
        das : int
            Days after simulation start.
        cwad : float
            Standing tops dry weight (kg DM/ha).
        cnad : float
            Standing tops nitrogen (kg N/ha).
        harvest_dm : float, optional
            Incremental fruit harvest dry weight on this date (kg DM/ha).
        harvest_n : float, optional
            Incremental fruit harvest N on this date (kg N/ha).
        direct_chpdt : float, optional
            Direct cumulative harvested pod dry weight from FreshWt.OUT (kg DM/ha).
            If provided, overrides incremental harvest_dm accumulation.
        direct_chpdtn : float, optional
            Direct cumulative harvested pod N (kg N/ha) (CHPDTN explicit state).
            If provided, directly sets cumulative fruit nitrogen state.
        """
        # Handle dry matter harvest accumulation
        if direct_chpdt is not None:
            self.cum_harvest_dm = max(0.0, direct_chpdt)
        elif harvest_dm is not None:
            self.cum_harvest_dm += max(0.0, harvest_dm)
        elif self._prev_cwad is not None and cwad < self._prev_cwad:
            # Automatic harvest drop detection: if CWAD drops and no senescence shock
            drop_dm = self._prev_cwad - cwad
            if drop_dm > 20.0:  # harvest threshold
                self.cum_harvest_dm += drop_dm

        # Handle nitrogen harvest accumulation
        if direct_chpdtn is not None:
            self.cum_harvest_n = max(0.0, direct_chpdtn)
        elif direct_chpdt is not None:
            # Estimate harvest N if not directly accumulated
            if harvest_n is not None:
                self.cum_harvest_n += max(0.0, harvest_n)
            else:
                self.cum_harvest_n = self.cum_harvest_dm * (self.default_fruit_n_pct / 100.0)
        elif harvest_dm is not None:
            if harvest_n is not None:
                self.cum_harvest_n += max(0.0, harvest_n)
            else:
                self.cum_harvest_n += max(0.0, harvest_dm) * (self.default_fruit_n_pct / 100.0)
        elif self._prev_cwad is not None and cwad < self._prev_cwad:
            drop_dm = self._prev_cwad - cwad
            if drop_dm > 20.0:  # harvest threshold
                drop_n = max(0.0, (self._prev_cnad or 0.0) - cnad)
                if drop_n > 0.0:
                    self.cum_harvest_n += drop_n
                else:
                    self.cum_harvest_n += drop_dm * (self.default_fruit_n_pct / 100.0)

        self._prev_cwad = cwad
        self._prev_cnad = cnad

        w_standing = cwad / 1000.0
        w_eff = effective_biomass(cwad, self.cum_harvest_dm)

        # Standing N calculation
        if cwad > 0 and w_standing >= MIN_CANOPY_BIOMASS_T_HA:
            n_act_standing = (cnad / cwad) * 100.0
        else:
            n_act_standing = SENTINEL_VALUE

        # Cumulative N calculation
        n_act_cum = actual_cumulative_n_conc(
            cwad, cnad, self.cum_harvest_dm, self.cum_harvest_n
        )

        is_valid = (w_eff >= MIN_CANOPY_BIOMASS_T_HA and cwad > 0 and n_act_cum != SENTINEL_VALUE)

        if is_valid:
            nc_crit = critical_n_concentration(w_eff, self.cnc_a, self.cnc_b, self.cnc_w0, self.cnc_nc_inf)
            nni_val = nni(n_act_cum, nc_crit)
        else:
            nc_crit = SENTINEL_VALUE
            nni_val = SENTINEL_VALUE

        return BiomassStepResult(
            das=das,
            cwad=cwad,
            cnad=cnad,
            cum_harvest_dm=self.cum_harvest_dm,
            cum_harvest_n=self.cum_harvest_n,
            w_standing=w_standing,
            w_eff=w_eff,
            n_act_standing=n_act_standing,
            n_act_cum=n_act_cum,
            nc_crit=nc_crit,
            nni_val=nni_val,
            is_valid=is_valid,
            chpdtn=self.cum_harvest_n,
        )


def verify_sawtooth_elimination(
    pre_harvest_cwad: float,
    pre_harvest_cnad: float,
    fruit_dm: float,
    fruit_n: float,
    post_harvest_cwad: float,
    post_harvest_cnad: float,
    cnc_a: float = DEFAULT_CNC_A,
    cnc_b: float = DEFAULT_CNC_B,
    cnc_w0: float = DEFAULT_CNC_W0,
    cnc_nc_inf: float = DEFAULT_CNC_NC_INF,
) -> dict[str, float]:
    """Analytical verification of sawtooth jump elimination across harvest.

    Returns comparison dictionary of raw jumps vs cumulative jumps.
    """
    # 1. Standing raw metrics
    w_pre = pre_harvest_cwad / 1000.0
    w_post = post_harvest_cwad / 1000.0
    n_act_pre = (pre_harvest_cnad / pre_harvest_cwad) * 100.0
    n_act_post = (post_harvest_cnad / post_harvest_cwad) * 100.0
    nc_pre = critical_n_concentration(w_pre, cnc_a, cnc_b, cnc_w0, cnc_nc_inf)
    nc_post = critical_n_concentration(w_post, cnc_a, cnc_b, cnc_w0, cnc_nc_inf)
    nni_pre = n_act_pre / nc_pre
    nni_post = n_act_post / nc_post

    standing_delta_w = w_post - w_pre
    standing_delta_n_act = n_act_post - n_act_pre
    standing_delta_nc = nc_post - nc_pre
    standing_delta_nni = nni_post - nni_pre

    # 2. Cumulative effective metrics with explicit fruit CHPDTN
    cum_dm_pre = 0.0
    cum_n_pre = 0.0
    cum_dm_post = fruit_dm
    cum_n_post = fruit_n

    w_eff_pre = (pre_harvest_cwad + cum_dm_pre) / 1000.0
    w_eff_post = (post_harvest_cwad + cum_dm_post) / 1000.0
    n_eff_pre = ((pre_harvest_cnad + cum_n_pre) / (pre_harvest_cwad + cum_dm_pre)) * 100.0
    n_eff_post = ((post_harvest_cnad + cum_n_post) / (post_harvest_cwad + cum_dm_post)) * 100.0
    nc_eff_pre = critical_n_concentration(w_eff_pre, cnc_a, cnc_b, cnc_w0, cnc_nc_inf)
    nc_eff_post = critical_n_concentration(w_eff_post, cnc_a, cnc_b, cnc_w0, cnc_nc_inf)
    nni_eff_pre = n_eff_pre / nc_eff_pre
    nni_eff_post = n_eff_post / nc_eff_post

    cum_delta_w = w_eff_post - w_eff_pre
    cum_delta_n_act = n_eff_post - n_eff_pre
    cum_delta_nc = nc_eff_post - nc_eff_pre
    cum_delta_nni = nni_eff_post - nni_eff_pre

    return {
        "standing_delta_w": standing_delta_w,
        "standing_delta_n_act": standing_delta_n_act,
        "standing_delta_nc": standing_delta_nc,
        "standing_delta_nni": standing_delta_nni,
        "cum_delta_w": cum_delta_w,
        "cum_delta_n_act": cum_delta_n_act,
        "cum_delta_nc": cum_delta_nc,
        "cum_delta_nni": cum_delta_nni,
    }
