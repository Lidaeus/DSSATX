"""High-fidelity dynamic state-space simulation proxy of CROPGRO C-N dynamics.

Enables rigorous side-by-side verification and ablation of Scheme B vs. Native CROPGRO:
- Daily discrete-time integration of organ biomass (WTLF, STMWT, RTWT, PODWT)
- Daily discrete-time integration of organ nitrogen (WTNLF, WTNST, WTNRT, PODN)
- Multi-harvest greenhouse fruit pick events (CUMHARVEST, CUMHARVEST_N)
- Cumulative effective biomass W_eff and Greenwood-Lemaire dilution curve Nc(W_eff)
- Endogenous N mobilization (NMINEA, NRUSLF)
- Photosynthetic acclimation coupling (Native uncoupled vs Scheme B continuous NNI gate)
- Senescence governor (Native uninhibited avalanche vs Scheme B rate limiter)
- Daily machine-precision carbon and nitrogen mass balance auditing.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Dict, List, Literal, Optional, Tuple

from subprojects.critical_n.scheme_b.acclimation import (
    AcclimationType,
    bounded_sigmoid_acclimation,
    couple_photosynthesis,
    DEFAULT_CNC_A,
    DEFAULT_CNC_B,
    DEFAULT_CNC_W0,
    DEFAULT_GAMMA,
    DEFAULT_NNI_MIN,
    DEFAULT_S_MAX,
)
from subprojects.critical_n.scheme_b.senescence_limiter import (
    DEFAULT_SENESCENCE_GAMMA,
    SenescenceGovernor,
)
from subprojects.critical_n.scheme_b.mass_balance import MassBalanceAuditor


@dataclasses.dataclass
class SimulationDailyRecord:
    """Complete diagnostic record for one simulation day."""
    dap: int                             # Days after planting
    # Biomass pools (g DM / m^2)
    wtlf: float                          # Green leaf dry weight
    stmwt: float                         # Stem dry weight
    rtwt: float                          # Root dry weight
    podwt: float                         # Standing fruit dry weight
    lai: float                           # Leaf area index (m^2/m^2)
    cwad: float                          # Standing tops dry weight (kg DM/ha)
    cum_harvest_dry: float               # Cumulative harvested fruit (kg DM/ha)
    w_eff: float                         # Cumulative effective biomass (t DM/ha)
    # Nitrogen pools (g N / m^2)
    wtnlf: float                         # Leaf N
    wtnst: float                         # Stem N
    wtnrt: float                         # Root N
    podn: float                          # Standing fruit N
    cum_harvest_n: float                 # Cumulative harvested fruit N (g N/m^2)
    soil_n: float                        # Available soil mineral N (g N/m^2)
    # Physiological concentrations & indices
    pcnl: float                          # Leaf N concentration (%)
    nc: float                            # Critical N concentration (%)
    nni: float                           # Nitrogen Nutrition Index
    # Daily Fluxes
    pg: float                            # Gross daily photosynthesis (g DM/m^2/d)
    wldotn: float                        # Daily new leaf dry weight (g DM/m^2/d)
    trnu: float                          # Daily root N uptake (g N/m^2/d)
    nruslf: float                        # Daily leaf N mobilized (g N/m^2/d)
    native_lfsen: float                  # Uninhibited mobilization senescence (g DM/m^2/d)
    governed_lfsen: float                # Governed mobilization senescence (g DM/m^2/d)
    sldot: float                         # Total leaf senescence loss (g DM/m^2/d)
    slndot: float                        # N lost in senesced leaves (g N/m^2/d)
    avalanche_flag: bool                 # True if native_lfsen > wldotn occurred
    # Mass balance audit
    n_balance_residual: float            # Machine-precision residual (g N/m^2)
    c_balance_residual: float            # Machine-precision residual (g DM/m^2)


class CropGroSimulationEngine:
    """Discrete-time state-space simulator of CROPGRO crop growth and nitrogen dynamics."""

    def __init__(
        self,
        mode: Literal["native", "scheme_b"] = "scheme_b",
        # CNC parameters
        cnc_a: float = DEFAULT_CNC_A,
        cnc_b: float = DEFAULT_CNC_B,
        cnc_w0: float = DEFAULT_CNC_W0,
        # Scheme B acclimation parameters
        acclimation_type: AcclimationType = AcclimationType.SIGMOID,
        acclimation_gamma: float = DEFAULT_GAMMA,
        acclimation_min: float = DEFAULT_NNI_MIN,
        acclimation_max: float = DEFAULT_S_MAX,
        # Scheme B senescence limiter parameters
        senescence_gamma: float = DEFAULT_SENESCENCE_GAMMA,
        # Crop physiological parameters
        senrte: float = 1.80,          # Leaf senescence coefficient per unit mobilized protein
        sla: float = 240.0,            # Specific leaf area (cm^2 / g)
        phtmax: float = 38.0,          # Potential maximum daily photosynthesis (g DM/m^2/d)
        kcan: float = 0.65,            # Canopy light extinction coefficient
        prolfi: float = 0.28,          # Initial leaf protein fraction (g protein/g DM, 4.48% N)
        prolff: float = 0.11,          # Minimum structural leaf protein fraction (1.76% N)
        agrvg: float = 1.35,           # Vegetative synthesis respiration requirement (g CH2O/g DM)
        seed_n_initial: float = 0.50,  # Initial seedling nitrogen reserve (g N/m^2)
    ) -> None:
        self.mode = mode
        self.cnc_a = cnc_a
        self.cnc_b = cnc_b
        self.cnc_w0 = cnc_w0

        self.acclimation_type = acclimation_type
        self.acclimation_gamma = acclimation_gamma
        self.acclimation_min = acclimation_min
        self.acclimation_max = acclimation_max

        self.senescence_gamma = senescence_gamma
        self.senrte = senrte
        self.sla = sla
        self.phtmax = phtmax
        self.kcan = kcan
        self.prolfi = prolfi
        self.prolff = prolff
        self.agrvg = agrvg
        self.seed_n_initial = seed_n_initial

        self.senescence_governor = SenescenceGovernor(
            gamma=senescence_gamma, standing_buffer_ratio=0.0
        )
        self.auditor = MassBalanceAuditor(seed_n_initial=seed_n_initial)

    def run_simulation(
        self,
        duration_days: int = 100,
        initial_soil_n: float = 15.0,        # Initial mineral N in root zone (g N/m^2)
        daily_n_fertilizer: float = 0.25,     # Daily fertilizer N injection (g N/m^2/d)
        harvest_days: Optional[List[int]] = None,
        harvest_fraction: float = 0.60,      # Fraction of standing fruit harvested per pick
    ) -> List[SimulationDailyRecord]:
        """Execute full daily simulation run.

        Parameters
        ----------
        duration_days : int
            Total days after planting to simulate (e.g. 100).
        initial_soil_n : float
            Starting soil mineral N pool (g N/m^2).
        daily_n_fertilizer : float
            Daily N fertigation applied into available soil pool (g N/m^2/d).
        harvest_days : list of int, optional
            List of DAPs on which multi-harvest events occur. Defaults to [50, 65, 80, 95].
        harvest_fraction : float
            Fraction of standing fruit harvested on each harvest day.

        Returns
        -------
        list of SimulationDailyRecord
            Daily time series of all states, fluxes, and mass balances.
        """
        if harvest_days is None:
            harvest_days = [50, 65, 80, 95]

        # Initial vegetative seedling pools (g DM / m^2)
        wtlf: float = 12.0
        stmwt: float = 8.0
        rtwt: float = 5.0
        podwt: float = 0.0

        # Initial nitrogen pools (g N / m^2)
        # Seedling leaf N at PROLFI (4.48% N)
        wtnlf: float = wtlf * (self.prolfi * 0.16)
        wtnst: float = stmwt * (0.16 * 0.16)
        wtnrt: float = rtwt * (0.12 * 0.16)
        podn: float = 0.0

        # Exact initial seed nitrogen reserve matching initial organs
        seed_n_initial = wtnlf + wtnst + wtnrt + podn
        self.auditor = MassBalanceAuditor(seed_n_initial=seed_n_initial)

        soil_n: float = initial_soil_n
        cum_harvest_dry: float = 0.0       # kg DM/ha
        cum_harvest_n: float = 0.0         # g N/m^2

        history: List[SimulationDailyRecord] = []

        for dap in range(1, duration_days + 1):
            # 1. Update daily available soil N from fertigation
            soil_n += daily_n_fertilizer

            # 2. Canopy geometry and leaf area index
            lai = max(0.01, wtlf * (self.sla / 10000.0))
            pgfac = 1.0 - math.exp(-self.kcan * lai)

            # Standing tops biomass (kg DM/ha)
            cwad = (wtlf + stmwt + podwt) * 10.0
            w_eff = (cwad + cum_harvest_dry) / 1000.0   # t DM/ha

            # 3. Critical Nitrogen & actual leaf concentration
            w_calc = max(self.cnc_w0, w_eff)
            nc = self.cnc_a * (w_calc ** (-self.cnc_b))
            pcnl = (wtnlf / max(0.1, wtlf)) * 100.0
            nni = pcnl / nc if nc > 0.0 else 1.0

            # 4. Photosynthesis (RATE stage)
            # Native leaf N factor based on RNITP
            base_agefac = max(0.10, min(1.20, pcnl / 4.0))
            agefcc = (1.0 - math.exp(-2.0 * base_agefac)) / (1.0 - math.exp(-2.0))

            if self.mode == "scheme_b":
                # Couple with continuous NNI acclimation
                coupled_factor = couple_photosynthesis(
                    native_agefac=agefcc,
                    nni=nni,
                    acclimation_type=self.acclimation_type,
                    gamma=self.acclimation_gamma,
                    nni_min=self.acclimation_min,
                    s_max=self.acclimation_max,
                )
                photo_factor = coupled_factor
            else:
                photo_factor = agefcc

            pg = self.phtmax * pgfac * photo_factor
            # Maintenance respiration (1.5% of living vegetative mass)
            main_resp = 0.015 * (wtlf + stmwt + rtwt + podwt * 0.5)
            pgavl = max(0.0, pg - main_resp)

            # 5. Nitrogen demand (DEMAND stage)
            # Fruiting stage starts at DAP 35
            is_fruiting = dap >= 35
            pod_sink_potential = 3.5 if is_fruiting else 0.0

            # Organ target N concentrations
            target_n_leaf = self.prolfi * 0.16
            target_n_stem = 0.025
            target_n_root = 0.018
            target_n_pod = 0.025

            # Vegetative N demand
            veg_c_potential = max(0.0, pgavl - pod_sink_potential * 1.4)
            pot_wldotn = veg_c_potential * 0.45 / self.agrvg
            pot_wsdotn = veg_c_potential * 0.35 / self.agrvg
            pot_wrdotn = veg_c_potential * 0.20 / self.agrvg

            ndmveg = (
                pot_wldotn * target_n_leaf
                + pot_wsdotn * target_n_stem
                + pot_wrdotn * target_n_root
            )
            ndmrep = pod_sink_potential * target_n_pod
            ndmtot = ndmveg + ndmrep

            # 6. Soil root N uptake (NUPTAK stage)
            # Michaelis-Menten root uptake kinetics
            root_uptake_capacity = (rtwt * 0.12) * (soil_n / (2.5 + soil_n))
            trnu = min(soil_n, min(ndmtot, root_uptake_capacity))
            trnu = max(0.0, trnu)
            soil_n -= trnu

            # 7. Endogenous mobilization (MOBIL stage)
            # Minable protein in leaves and stems
            min_leaf_n = wtlf * (self.prolff * 0.16)
            minable_leaf_n = max(0.0, wtnlf - min_leaf_n)
            min_stem_n = stmwt * 0.012
            minable_stem_n = max(0.0, wtnst - min_stem_n)

            deficit = max(0.0, ndmtot - trnu)
            nminea = min(deficit, minable_leaf_n * 0.35 + minable_stem_n * 0.25)

            # Leaf mobilization fraction
            tot_minable = minable_leaf_n + minable_stem_n
            if tot_minable > 0.0:
                nruslf = nminea * (minable_leaf_n / tot_minable)
                nrusst = nminea - nruslf
            else:
                nruslf = 0.0
                nrusst = 0.0

            # 8. Growth synthesis & assimilate partitioning (VEGGR & PODS)
            total_n_avl = trnu + nminea
            n_supply_ratio = min(1.0, total_n_avl / max(0.001, ndmtot))

            # Fruit growth receives priority
            actual_wpdotn = min(pod_sink_potential, pgavl / 1.4) * min(1.0, n_supply_ratio * 1.1)

            rem_c = max(0.0, pgavl - actual_wpdotn * 1.4)
            wldotn = (rem_c * 0.45 / self.agrvg) * n_supply_ratio
            wsdotn = (rem_c * 0.35 / self.agrvg) * n_supply_ratio
            wrdotn = (rem_c * 0.20 / self.agrvg) * n_supply_ratio

            # Precise algebraic N allocation closed to total_n_avl:
            pot_n_pod = actual_wpdotn * target_n_pod
            pot_n_lf = wldotn * target_n_leaf
            pot_n_st = wsdotn * target_n_stem
            pot_n_rt = wrdotn * target_n_root
            sum_pot_n = pot_n_pod + pot_n_lf + pot_n_st + pot_n_rt

            if sum_pot_n > 0.0:
                alloc_factor = min(1.0, total_n_avl / sum_pot_n)
                actual_podn_gr = pot_n_pod * alloc_factor
                ngrlf = pot_n_lf * alloc_factor
                ngr_st = pot_n_st * alloc_factor
                ngr_rt = pot_n_rt * alloc_factor
                nleak = max(0.0, total_n_avl - (actual_podn_gr + ngrlf + ngr_st + ngr_rt))
            else:
                actual_podn_gr = 0.0
                ngrlf = 0.0
                ngr_st = 0.0
                ngr_rt = 0.0
                nleak = total_n_avl

            # Total synthesis carbon loss: (AGRVG - 1.0) * biomass
            synth_loss = (
                wldotn * (self.agrvg - 1.0)
                + wsdotn * (self.agrvg - 1.0)
                + wrdotn * (self.agrvg - 1.0)
                + actual_wpdotn * (1.4 - 1.0)
            )

            # 9. Leaf Senescence (SENES stage)
            native_lfsen = self.senrte * (nruslf / 0.16)
            avalanche_flag = (native_lfsen > wldotn) and (wldotn > 0.01)

            if self.mode == "scheme_b":
                gov_res = self.senescence_governor.govern_senescence(
                    native_lfsen=native_lfsen,
                    wldotn=wldotn,
                    wtlf=wtlf,
                    is_mature=(dap >= duration_days - 5),
                )
                governed_lfsen = gov_res.governed_lfsen
            else:
                governed_lfsen = min(wtlf, native_lfsen)

            # Background natural senescence (0.5% of green leaf)
            bg_sen = 0.005 * wtlf
            sldot = min(wtlf, governed_lfsen + bg_sen)
            # Senesced leaves retain minimal residual structural N
            slndot = sldot * (self.prolff * 0.16)

            # 10. Fruit harvest event
            harvest_fruit_dm = 0.0
            harvest_fruit_n = 0.0
            if dap in harvest_days and podwt > 10.0:
                harvest_fruit_dm = podwt * harvest_fraction
                harvest_fruit_n = podn * harvest_fraction
                podwt -= harvest_fruit_dm
                podn -= harvest_fruit_n
                cum_harvest_dry += harvest_fruit_dm * 10.0  # kg DM/ha
                cum_harvest_n += harvest_fruit_n            # g N/m^2

            # 11. State integration (GROW stage)
            wtlf = max(0.1, wtlf + wldotn - sldot)
            stmwt = max(0.1, stmwt + wsdotn)
            rtwt = max(0.1, rtwt + wrdotn)
            podwt = max(0.0, podwt + actual_wpdotn)

            wtnlf = max(0.005, wtnlf + ngrlf - slndot - nruslf)
            wtnst = max(0.005, wtnst + ngr_st - nrusst)
            wtnrt = max(0.005, wtnrt + ngr_rt)
            podn = max(0.0, podn + actual_podn_gr)

            # 12. Mass balance audit
            mb_entry = self.auditor.audit_step(
                day=dap,
                daily_n_uptake=trnu,
                standing_leaf_n=wtnlf,
                standing_stem_n=wtnst,
                standing_root_n=wtnrt,
                standing_fruit_n=podn,
                daily_senesced_leaf_n=slndot,
                daily_harvest_fruit_n=harvest_fruit_n,
                daily_leaked_n=nleak,
                daily_pg=pg,
                daily_main_respiration=main_resp,
                standing_leaf_dm=wtlf,
                standing_stem_dm=stmwt,
                standing_root_dm=rtwt,
                standing_fruit_dm=podwt,
                daily_senesced_leaf_dm=sldot,
                daily_harvest_fruit_dm=harvest_fruit_dm,
                daily_synthesis_loss=synth_loss,
            )

            record = SimulationDailyRecord(
                dap=dap,
                wtlf=wtlf,
                stmwt=stmwt,
                rtwt=rtwt,
                podwt=podwt,
                lai=lai,
                cwad=cwad,
                cum_harvest_dry=cum_harvest_dry,
                w_eff=w_eff,
                wtnlf=wtnlf,
                wtnst=wtnst,
                wtnrt=wtnrt,
                podn=podn,
                cum_harvest_n=cum_harvest_n,
                soil_n=soil_n,
                pcnl=pcnl,
                nc=nc,
                nni=nni,
                pg=pg,
                wldotn=wldotn,
                trnu=trnu,
                nruslf=nruslf,
                native_lfsen=native_lfsen,
                governed_lfsen=governed_lfsen,
                sldot=sldot,
                slndot=slndot,
                avalanche_flag=avalanche_flag,
                n_balance_residual=mb_entry.n_balance_residual,
                c_balance_residual=mb_entry.c_balance_residual,
            )
            history.append(record)

        return history
