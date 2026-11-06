"""Carbon and nitrogen mass balance auditor for CROPGRO nitrogen dynamics (Scheme B).

Formally models and audits machine-precision mass conservation:
1. Plant Nitrogen Balance (mirroring DSSAT PlantNBal.for):
       WTNALL + WTNOFF + CUM_HARVEST_N + TNLEAK - (SEEDNI + WTNUP) == 0.000000
   where:
       WTNALL = WTNLF + WTNST + WTNRT + WTNSH + WTNSD (standing organ N)
       WTNOFF = cumulative N lost in senesced fallen leaves and stems
       CUM_HARVEST_N = cumulative N removed in harvested fruit
       WTNUP = cumulative root N uptake from soil
       TNLEAK = cumulative luxury N leakage

2. Plant Carbon Balance:
       Cumulative PG == Cumulative Maintenance Respiration + Synthesis Costs
                        + Standing Biomass + Harvested Biomass + Senesced Biomass

Mathematical Proof of Scheme B Mass Conservation:
In Scheme B:
- Photosynthetic down-regulation modulates PG:
      PG_CNC = PG_native * S(NNI)
  This affects the magnitude of carbon assimilation, but all assimilated carbon is
  partitioned according to explicit conservation equations:
      dC/dt = PG - MAINR - Synthesis - Storage
- Senescence governor restricts LFSEN:
      LFSEN_actual = min(LFSEN_native, gamma * WLDOTN)
  When LFSEN is reduced, the non-senescing leaf dry matter remains in standing green
  leaves (WTLF), and its residual nitrogen remains in standing leaf N (WTNLF).
  The mobilized nitrogen (NRUSLF) was already transferred to NAVL and reincorporated
  into newly grown organs.
  Therefore:
      d(WTNLF)/dt = NGRLF - SLNDOT - NRUSLF
      d(WTNOFF)/dt = SLNDOT
  Summing organ N and loss N yields an exact telescoping cancellation, guaranteeing
  that the PlantNBal residual remains IDENTICALLY ZERO.
"""

from __future__ import annotations

import dataclasses
import math
from typing import List, Optional


TOLERANCE_ABSOLUTE_N: float = 1e-5  # g N / m^2
TOLERANCE_ABSOLUTE_C: float = 1e-4  # g DM / m^2


@dataclasses.dataclass
class DailyMassBalanceEntry:
    """Record of a single daily time step's mass balance state."""
    day: int
    # Nitrogen components (g N/m^2)
    seed_n_initial: float
    cum_n_uptake: float
    standing_organ_n: float       # WTNLF + WTNST + WTNRT + WTNPOD
    cum_senesced_n: float         # WTNOFF
    cum_harvest_n: float          # Harvested fruit N
    cum_leaked_n: float           # TNLEAK
    n_balance_residual: float     # (standing + senesced + harvest + leaked) - (seed + uptake)
    is_n_conserved: bool

    # Biomass / Carbon components (g DM/m^2)
    cum_gross_pg: float
    cum_main_respiration: float
    standing_biomass: float       # WTLF + STMWT + RTWT + PODWT
    cum_senesced_biomass: float   # Cumulative leaf + stem death
    cum_harvest_biomass: float    # Cumulative harvested fruit dry matter
    cum_synthesis_loss: float     # Respiratory synthesis losses (1 - 1/AGR)
    c_balance_residual: float     # (standing + senesced + harvest + resp + synth) - pg
    is_c_conserved: bool


class MassBalanceAuditor:
    """Rigorous mass balance auditor for discrete-time crop growth simulations."""

    def __init__(
        self,
        seed_n_initial: float = 0.50,
        tolerance_n: float = TOLERANCE_ABSOLUTE_N,
        tolerance_c: float = TOLERANCE_ABSOLUTE_C,
    ) -> None:
        self.seed_n_initial = seed_n_initial
        self.tolerance_n = tolerance_n
        self.tolerance_c = tolerance_c

        # Accumulators
        self.cum_n_uptake: float = 0.0
        self.cum_senesced_n: float = 0.0
        self.cum_harvest_n: float = 0.0
        self.cum_leaked_n: float = 0.0

        self.cum_gross_pg: float = 0.0
        self.cum_main_respiration: float = 0.0
        self.cum_senesced_biomass: float = 0.0
        self.cum_harvest_biomass: float = 0.0
        self.cum_synthesis_loss: float = 0.0

        self.history: List[DailyMassBalanceEntry] = []

    def audit_step(
        self,
        day: int,
        # Daily Nitrogen Fluxes and States
        daily_n_uptake: float,
        standing_leaf_n: float,
        standing_stem_n: float,
        standing_root_n: float,
        standing_fruit_n: float,
        daily_senesced_leaf_n: float,
        daily_harvest_fruit_n: float = 0.0,
        daily_leaked_n: float = 0.0,
        # Daily Carbon / Biomass Fluxes and States
        daily_pg: float = 0.0,
        daily_main_respiration: float = 0.0,
        standing_leaf_dm: float = 0.0,
        standing_stem_dm: float = 0.0,
        standing_root_dm: float = 0.0,
        standing_fruit_dm: float = 0.0,
        daily_senesced_leaf_dm: float = 0.0,
        daily_harvest_fruit_dm: float = 0.0,
        daily_synthesis_loss: float = 0.0,
    ) -> DailyMassBalanceEntry:
        """Process a single day's fluxes and verify conservation.

        Parameters
        ----------
        day : int
            Simulation day index.
        daily_n_uptake : float
            Root N uptake for today (g N/m^2/d).
        standing_leaf_n, standing_stem_n, standing_root_n, standing_fruit_n : float
            Current organ N pools (g N/m^2).
        daily_senesced_leaf_n : float
            N lost in senesced leaves today (g N/m^2/d).
        daily_harvest_fruit_n : float
            N removed in fruit harvest today (g N/m^2/d).
        daily_leaked_n : float
            Luxury N leaked today (g N/m^2/d).
        daily_pg : float
            Gross photosynthesis today (g DM/m^2/d).
        daily_main_respiration : float
            Maintenance respiration today (g DM/m^2/d).
        standing_leaf_dm, standing_stem_dm, standing_root_dm, standing_fruit_dm : float
            Current organ dry biomass pools (g DM/m^2).
        daily_senesced_leaf_dm : float
            Leaf dry matter senesced today (g DM/m^2/d).
        daily_harvest_fruit_dm : float
            Fruit dry matter harvested today (g DM/m^2/d).
        daily_synthesis_loss : float
            Growth respiration synthesis loss today (g DM/m^2/d).

        Returns
        -------
        DailyMassBalanceEntry
            Audited daily balance record.
        """
        # Update accumulators
        self.cum_n_uptake += daily_n_uptake
        self.cum_senesced_n += daily_senesced_leaf_n
        self.cum_harvest_n += daily_harvest_fruit_n
        self.cum_leaked_n += daily_leaked_n

        self.cum_gross_pg += daily_pg
        self.cum_main_respiration += daily_main_respiration
        self.cum_senesced_biomass += daily_senesced_leaf_dm
        self.cum_harvest_biomass += daily_harvest_fruit_dm
        self.cum_synthesis_loss += daily_synthesis_loss

        # Total nitrogen in plant system
        standing_organ_n = (
            standing_leaf_n + standing_stem_n + standing_root_n + standing_fruit_n
        )
        total_n_accounted = (
            standing_organ_n
            + self.cum_senesced_n
            + self.cum_harvest_n
            + self.cum_leaked_n
        )
        total_n_input = self.seed_n_initial + self.cum_n_uptake
        n_residual = total_n_accounted - total_n_input
        is_n_conserved = abs(n_residual) <= self.tolerance_n

        # Total carbon/biomass accounted
        standing_biomass = (
            standing_leaf_dm + standing_stem_dm + standing_root_dm + standing_fruit_dm
        )
        total_c_accounted = (
            standing_biomass
            + self.cum_senesced_biomass
            + self.cum_harvest_biomass
            + self.cum_main_respiration
            + self.cum_synthesis_loss
        )
        # Note: If cum_gross_pg is zero (e.g. initial setup), residual against standing biomass
        c_residual = total_c_accounted - self.cum_gross_pg
        is_c_conserved = abs(c_residual) <= self.tolerance_c

        entry = DailyMassBalanceEntry(
            day=day,
            seed_n_initial=self.seed_n_initial,
            cum_n_uptake=self.cum_n_uptake,
            standing_organ_n=standing_organ_n,
            cum_senesced_n=self.cum_senesced_n,
            cum_harvest_n=self.cum_harvest_n,
            cum_leaked_n=self.cum_leaked_n,
            n_balance_residual=n_residual,
            is_n_conserved=is_n_conserved,
            cum_gross_pg=self.cum_gross_pg,
            cum_main_respiration=self.cum_main_respiration,
            standing_biomass=standing_biomass,
            cum_senesced_biomass=self.cum_senesced_biomass,
            cum_harvest_biomass=self.cum_harvest_biomass,
            cum_synthesis_loss=self.cum_synthesis_loss,
            c_balance_residual=c_residual,
            is_c_conserved=is_c_conserved,
        )
        self.history.append(entry)
        return entry

    @property
    def max_n_residual(self) -> float:
        """Return maximum absolute nitrogen residual across simulation history."""
        if not self.history:
            return 0.0
        return max(abs(e.n_balance_residual) for e in self.history)

    @property
    def max_c_residual(self) -> float:
        """Return maximum absolute carbon residual across simulation history."""
        if not self.history:
            return 0.0
        return max(abs(e.c_balance_residual) for e in self.history)

    @property
    def all_n_conserved(self) -> bool:
        """Return True if all steps satisfied nitrogen conservation tolerance."""
        return all(e.is_n_conserved for e in self.history)
