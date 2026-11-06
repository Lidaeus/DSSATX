"""
Differentiable CROPGRO Core Dynamical System (Diff-CROPGRO)
===========================================================
PyTorch-based continuous, fully differentiable crop growth engine for TMGRO048
(Eggplant on Tomato model).

Phase 1.5 — Mechanism-fidelity fixes:
  P1: Nonlinear light-saturation photosynthesis curve (PHOTO.for:105-112)
  P2: Leaf area ↔ leaf biomass bidirectional conservation during senescence
  P3: Magic numbers replaced with documented SPE constants or learnable parameters
  P9: soft_positive replaces hard clamp where gradients matter

Known limitations (documented, to be addressed in later phases):
  P4: Water and nitrogen stress (SWFAC, NSTRES) are treated as exogenous inputs,
      not computed internally from soil-plant coupled dynamics. This means the
      model cannot learn how parameter changes affect stress, which limits
      the realism of water-nitrogen response gradients.
"""

from typing import Dict, Optional, Tuple

import torch
import torch.nn as nn

from src.differentiable.smooth_operators import (
    bounded_param,
    inverse_bounded_param,
    smooth_cardinal_temperature,
    smooth_gate,
    soft_positive,
)


class DifferentiableCROPGRO(nn.Module):
    """
    End-to-End Differentiable CROPGRO Crop Model.

    States (B, T, 7):
      0: LAI   — Leaf Area Index (m2/m2)
      1: W_L   — Leaf dry biomass (g/m2)
      2: W_S   — Stem dry biomass (g/m2)
      3: W_R   — Root dry biomass (g/m2)
      4: W_F   — Fruit dry biomass currently on plant (g/m2)
      5: W_H   — Cumulative harvested fruit dry biomass (g/m2)
      6: D_P   — Continuous developmental stage index (dimensionless)
    """

    # =====================================================================
    # Species-level constants from TMGRO048.SPE (fixed, NOT calibratable).
    # Source references are Fortran file:line in DSSAT v4.8.
    # =====================================================================
    SPE = {
        # --- Photosynthesis (PHOTO.for:105-195) ---
        "PHTMAX": 55.0,       # Max canopy gross photosynthesis at light saturation (g CH2O/m2/d)
        "PARMAX": 100.0,      # PAR flux at which photosynthesis saturates (mol quanta/m2/d)
        "PGREF": 1.36,        # Reference leaf photosynthesis rate (mg CO2/m2/s) (TMGRO048.SPE line 12)
        "SRAD_TO_PAR": 2.285, # MJ/m2/d total radiation → mol quanta/m2/d PAR (≈ 0.50 × 4.57)
        # Photosynthesis cardinal temperatures (TMGRO048.SPE FNPGT array)
        "FNPGT_TB": 6.0,      # Photo base temperature (°C)
        "FNPGT_TO1": 18.0,    # Photo optimum lower (°C)
        "FNPGT_TO2": 28.0,    # Photo optimum upper (°C)
        "FNPGT_TM": 42.0,     # Photo ceiling temperature (°C)
        # --- Carbon conversion ---
        "CH2O_TO_DM": 0.68,   # CH2O → structural dry matter efficiency (g DM / g CH2O)
        # --- Vegetative partitioning ratios (VEGGR.for:250-280) ---
        # In CROPGRO these are V-stage dependent; we use representative mid-season values
        "FRSTM_RATIO": 0.55,  # Stem sink potential relative to leaf sink (dimensionless)
        "FRRT_RATIO": 0.30,   # Root sink potential relative to (leaf + stem) sink
        # --- Senescence ---
        "SHADE_SEN_LAI_THRESHOLD": 3.5,  # LAI above which shading senescence activates
        "SHADE_SEN_RATE": 0.010,         # Daily fractional LAI loss from self-shading at high LAI
    }

    # =====================================================================
    # Calibratable (learnable) parameter bounds.
    # Strictly aligned with src/common/param_registry.py PHYSICAL_BOUNDS.
    # =====================================================================
    PARAM_BOUNDS = {
        # --- Phenology development (PHENOL.for) ---
        "tb1": (8.0, 9.5),        # Base temperature for development (°C)
        "to1": (22.0, 28.0),      # Optimum lower temperature for development (°C)
        "to2": (28.0, 32.0),      # Optimum upper temperature for development (°C)
        "tm1": (38.0, 44.0),      # Ceiling temperature for development (°C)
        "em_fl": (18.0, 30.0),    # Transplant → first flower duration (P-days)
        # --- Photosynthesis (PHOTO.for) ---
        "lfmax": (1.0, 2.5),      # Max single-leaf net photosynthesis rate (mg CO2/m2/s)
        "kcan": (0.30, 0.65),     # Canopy light extinction coefficient (Beer-Lambert)
        # --- Canopy structure ---
        "slavr": (120.0, 250.0),  # Specific leaf area during vegetative growth (cm2/g)
        # --- Reproductive source-sink (DEMAND.for, VEGGR.for) ---
        "xfrt": (0.75, 0.94),     # Max fraction of daily assimilate to reproductive organs
        "podur": (7.0, 20.0),     # Fruit expansion / pod addition duration (P-days)
        "sfdur": (25.0, 60.0),    # Seed/fruit filling duration (P-days)
        # --- Senescence (SENES.for) ---
        "senrte": (1.5, 6.0),     # Senescence rate scaling under N stress
        # --- Harvest dynamics ---
        "kharv": (0.04, 0.15),    # Continuous harvest turnover rate (1/day)
        "fruit_dm_ratio": (0.05, 0.12),  # Fruit dry matter fraction (DM/FW)
    }

    # Reference default starting values (from Champion C15, real_72)
    DEFAULT_INITS = {
        "tb1": 8.58, "to1": 25.0, "to2": 30.0, "tm1": 40.0,
        "em_fl": 24.2,
        "lfmax": 2.10,    # mg CO2/m2/s — typical eggplant value
        "kcan": 0.51,
        "slavr": 185.0,
        "xfrt": 0.869,
        "podur": 12.0, "sfdur": 45.0,
        "senrte": 3.50,
        "kharv": 0.085,
        "fruit_dm_ratio": 0.072,
    }

    def __init__(self, init_params: Optional[Dict[str, float]] = None, device: str = "cpu"):
        super().__init__()
        self.device = torch.device(device)
        self.raw_params = nn.ParameterDict()

        inits = dict(self.DEFAULT_INITS)
        if init_params:
            inits.update(init_params)

        for name, (p_min, p_max) in self.PARAM_BOUNDS.items():
            val = inits.get(name, (p_min + p_max) / 2.0)
            raw_val = inverse_bounded_param(val, p_min, p_max)
            self.raw_params[name] = nn.Parameter(
                torch.tensor(raw_val, dtype=torch.float32, device=self.device)
            )

    def get_physical_params(self) -> Dict[str, torch.Tensor]:
        """Maps raw unconstrained parameters to physical bounded values."""
        phys = {}
        for name, (p_min, p_max) in self.PARAM_BOUNDS.items():
            phys[name] = bounded_param(self.raw_params[name], p_min, p_max)
        return phys

    def forward_step(
        self,
        states: torch.Tensor,
        weather: torch.Tensor,
        stress: torch.Tensor,
        params: Dict[str, torch.Tensor],
        dt: float = 1.0,
    ) -> torch.Tensor:
        """
        Advance state vector by dt (1 day).

        Args:
          states:  (B, 7) [LAI, W_L, W_S, W_R, W_F, W_H, D_P]
          weather: (B, 3) [T_avg (°C), SRAD (MJ/m2/d), DayLength (hr)]
          stress:  (B, 2) [SWFAC (water stress 0~1), NSTRES (N stress 0~1)]
                   NOTE: these are exogenous inputs — see module docstring for limitation P4.
          params:  dict of bounded physical parameter tensors
          dt:      time step in days

        Returns:
          next_states: (B, 7)
        """
        S = self.SPE
        lai = states[:, 0]
        w_l = states[:, 1]
        w_s = states[:, 2]
        w_r = states[:, 3]
        w_f = states[:, 4]
        w_h = states[:, 5]
        d_p = states[:, 6]

        t_avg = weather[:, 0]
        srad = weather[:, 1]

        swfac = stress[:, 0]
        nstres = stress[:, 1]
        min_stress = torch.min(swfac, nstres)

        # ==================================================================
        # 1. Phenological development rate (PHENOL.for)
        #    Uses development cardinal temps (tb1/to1/to2/tm1)
        # ==================================================================
        t_factor_dev = smooth_cardinal_temperature(
            t_avg, params["tb1"], params["to1"], params["to2"], params["tm1"], beta=3.0
        )
        d_rate = t_factor_dev / params["em_fl"]
        next_d_p = d_p + d_rate * dt

        # ==================================================================
        # 2. Canopy gross photosynthesis (PHOTO.for:105-195)
        #    FIX P1: Nonlinear light-saturation curve replaces linear RUE.
        # ==================================================================
        # 2a. Convert total solar radiation to PAR (PHOTO.for:70)
        par = srad * S["SRAD_TO_PAR"]

        # 2b. Potential max canopy photosynthesis at light saturation (PHOTO.for:105-112)
        ptsmax = S["PHTMAX"] * (1.0 - torch.exp(-par / S["PARMAX"]))

        # 2c. Canopy light interception via Beer-Lambert (PHOTO.for:115-125)
        pgfac = 1.0 - torch.exp(-params["kcan"] * soft_positive(lai, floor=0.01))

        # 2d. Temperature effect on photosynthesis (PHOTO.for:130-135)
        #     Uses photosynthesis-specific cardinal temps from SPE (different from development!)
        t_factor_photo = smooth_cardinal_temperature(
            t_avg,
            torch.tensor(S["FNPGT_TB"], device=self.device),
            torch.tensor(S["FNPGT_TO1"], device=self.device),
            torch.tensor(S["FNPGT_TO2"], device=self.device),
            torch.tensor(S["FNPGT_TM"], device=self.device),
            beta=3.0,
        )

        # 2e. Cultivar leaf photosynthesis capacity scaling (PHOTO.for:82-90)
        pglfmx = (1.0 - torch.exp(-1.6 * params["lfmax"])) / (
            1.0 - torch.exp(torch.tensor(-1.6 * S["PGREF"], device=self.device))
        )

        # 2f. Final daily canopy gross photosynthesis (g CH2O / m2 / day)
        pg_ch2o = ptsmax * pgfac * t_factor_photo * pglfmx * min_stress

        # 2g. Convert CH2O to structural dry matter available for growth
        pg = pg_ch2o * S["CH2O_TO_DM"]

        # ==================================================================
        # 3. Source-sink carbon partitioning (DEMAND.for & VEGGR.for)
        #    FIX P3: Magic numbers replaced with documented SPE constants.
        # ==================================================================
        # Smooth activation of reproductive phase (D_P >= 1.0 → first flower)
        repro_gate = smooth_gate(next_d_p, torch.tensor(1.0, device=self.device), width=0.15)

        # 3a. Vegetative sink potentials
        #     Leaf sink driven by temperature-dependent expansion capacity
        sink_l_pot = (params["slavr"] / 100.0) * t_factor_dev
        # Stem and root sinks as documented fractions of leaf sink (VEGGR.for:250-280)
        sink_s_pot = sink_l_pot * S["FRSTM_RATIO"]
        sink_r_pot = (sink_l_pot + sink_s_pot) * S["FRRT_RATIO"]

        # 3b. Reproductive sink potential — activates during fruiting phase
        #     Magnitude scales with xfrt, podur (fruit number load), sfdur (filling duration)
        sink_f_pot = (
            repro_gate
            * params["xfrt"]
            * (params["podur"] / 12.0)      # Normalized to typical podur ≈ 12 P-days
            * (params["sfdur"] / 45.0)       # Normalized to typical sfdur ≈ 45 P-days
            * t_factor_dev
        )

        # 3c. Reproductive vs vegetative competition (DEMAND.for:560-580)
        #     When fruit sink is active, vegetative sinks are down-regulated
        veg_suppress = 1.0 - repro_gate * params["xfrt"]
        sink_l = sink_l_pot * veg_suppress
        sink_s = sink_s_pot * veg_suppress
        sink_r = sink_r_pot * veg_suppress
        sink_f = sink_f_pot

        # 3d. Simplex normalization — guarantees mass conservation (sum = 1.0)
        sum_sinks = sink_l + sink_s + sink_r + sink_f + 1e-6
        frac_l = sink_l / sum_sinks
        frac_s = sink_s / sum_sinks
        frac_r = sink_r / sum_sinks
        frac_f = sink_f / sum_sinks

        # ==================================================================
        # 4. Biomass growth increments
        # ==================================================================
        dw_l = frac_l * pg * dt
        dw_s = frac_s * pg * dt
        dw_r = frac_r * pg * dt
        dw_f = frac_f * pg * dt

        # ==================================================================
        # 5. Continuous / periodic harvesting of mature fruit (CHPDT)
        # ==================================================================
        # Harvest begins when D_P >= 1.6 (≈ first mature fruit)
        harv_gate = smooth_gate(next_d_p, torch.tensor(1.6, device=self.device), width=0.2)
        r_harv = harv_gate * params["kharv"] * soft_positive(w_f, floor=0.0) * dt

        # ==================================================================
        # 6. Leaf area index dynamics: expansion AND senescence
        #    FIX P2: Senescence now removes BOTH LAI and W_L proportionally.
        # ==================================================================
        # 6a. LAI expansion from new leaf growth
        dlai_grow = dw_l * (params["slavr"] / 10000.0)  # cm2/g → m2/m2 per g/m2

        # 6b. Senescence losses
        # Self-shading senescence at high LAI (SENES.for)
        shade_gate = smooth_gate(
            lai, torch.tensor(S["SHADE_SEN_LAI_THRESHOLD"], device=self.device), width=0.5
        )
        shading_sen_rate = shade_gate * S["SHADE_SEN_RATE"] * dt

        # Stress-induced senescence: N mobilization killing leaves (SENES.for:198)
        # LFSEN = SENRTE × NRUSLF / 0.16  →  simplified as proportional to (1 - min_stress)
        stress_sen_rate = (1.0 - min_stress) * (params["senrte"] * 0.005) * dt

        # Total senescence as a fraction of current canopy
        sen_frac = torch.clamp(shading_sen_rate + stress_sen_rate, min=0.0, max=0.5)

        dlai_sen = sen_frac * lai
        dw_l_sen = sen_frac * w_l   # FIX P2: leaf biomass removed proportionally

        # 6c. Update states with conservation
        next_lai = soft_positive(lai + dlai_grow - dlai_sen, floor=0.01)
        next_w_l = soft_positive(w_l + dw_l - dw_l_sen, floor=0.1)
        next_w_s = w_s + dw_s
        next_w_r = w_r + dw_r
        next_w_f = soft_positive(w_f + dw_f - r_harv, floor=0.0)
        next_w_h = w_h + r_harv

        next_states = torch.stack(
            [next_lai, next_w_l, next_w_s, next_w_r, next_w_f, next_w_h, next_d_p], dim=-1
        )
        return next_states

    def simulate(
        self,
        weather_seq: torch.Tensor,
        stress_seq: torch.Tensor,
        init_states: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Simulate full crop season trajectory across batch of treatments.

        Args:
          weather_seq: (B, N_days, 3) [T_avg, SRAD, DayLength]
          stress_seq:  (B, N_days, 2) [SWFAC, NSTRES]
                       NOTE: stress is exogenous — see limitation P4 in module docstring.
          init_states: (B, 7) or None (transplant seedling defaults)

        Returns:
          trajectories:    (B, N_days + 1, 7)
          fresh_yield_cum: (B, N_days + 1) in kg/ha
        """
        batch_size, n_days, _ = weather_seq.shape
        params = self.get_physical_params()

        if init_states is None:
            # Standard transplant seedling state (PAGE ≈ 22 days)
            init_s = torch.tensor(
                [0.08, 4.0, 2.5, 1.5, 0.0, 0.0, 0.25],
                dtype=torch.float32,
                device=self.device,
            ).repeat(batch_size, 1)
        else:
            init_s = init_states

        traj = [init_s]
        curr_s = init_s

        for t in range(n_days):
            w_t = weather_seq[:, t, :]
            s_t = stress_seq[:, t, :]
            curr_s = self.forward_step(curr_s, w_t, s_t, params, dt=1.0)
            traj.append(curr_s)

        # NOTE: Full trajectory is cached for BPTT. Memory is O(T), not O(1).
        # True adjoint ODE method (torchdiffeq.odeint_adjoint) would give O(1)
        # memory but is not used in this prototype.
        states_stack = torch.stack(traj, dim=1)  # (B, N_days + 1, 7)

        # Fresh yield (kg/ha) = cumulative dry harvest (g/m2) × 10 / fruit_dm_ratio
        w_h = states_stack[:, :, 5]
        fresh_yield = (w_h * 10.0) / params["fruit_dm_ratio"]

        return states_stack, fresh_yield
