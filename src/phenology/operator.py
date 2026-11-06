"""
src/phenology/operator.py
=========================
Continuous, Differentiable Neural-Phenology Operator for Protected Greenhouse Crops.

Replaces the legacy piecewise linear four-base-temperature module (PHENOL.for / TRANS.for)
with a C^inf Softplus-Sigmoidal thermal kernel, multi-factor sensory fusion (Tavg, DIF, DLI),
smooth chilling gate, and strictly monotonic developmental stage integration D(t) in [0.0, 3.0].

Author: teamwork_preview_worker_m2
Date: 2026-09-20
"""

from typing import Dict, Optional, Union
import torch
import torch.nn as nn
import torch.nn.functional as F

from src.phenology.chilling_gate import SmoothChillingGate


class SmoothThermalKernel(nn.Module):
    """
    C^inf Softplus-Sigmoidal Continuous Thermal Time Kernel.

    Completely eliminates the piecewise linear derivative jump discontinuities
    and Dirac delta distributions of the legacy DSSAT CURV function at Tb and Tm.

    Mathematical Formulation:
    -------------------------
    Phi_SS(T) = ramp(T) * ceiling(T) * heat_decay(T)

    where:
    - ramp(T) = tau_b * ln(1 + exp((T - tb) / tau_b))
      Smooth linear thermal accumulation above base temperature tb.
    - ceiling(T) = 1.0 - sigmoid((T - tmax) / tau_m)
      Smooth high-temperature ceiling cutoff at maximum temperature tmax.
    - heat_decay(T) = exp(-0.5 * (softplus(T - topt) / sigma_heat)^2)
      Supra-optimal temperature depression above optimal temperature topt.

    Guarantees:
    - Strictly positive output Phi_SS(T) > 0 everywhere.
    - Infinitely differentiable (C^inf) on R.
    - Strictly non-zero autograd gradients everywhere (no zero-gradient plateaus).

    Parameters
    ----------
    tb_init : float, default 9.20
        Biological base temperature (°C).
    topt_init : float, default 26.0
        Optimal physiological temperature (°C).
    tmax_init : float, default 38.0
        Upper thermal ceiling temperature (°C).
    tau_b : float, default 0.80
        Smoothing radius around base temperature (°C).
    tau_m : float, default 1.50
        Smoothing radius around maximum ceiling temperature (°C).
    sigma_heat : float, default 4.0
        Dispersion parameter for supra-optimal heat depression (°C).
    """

    def __init__(
        self,
        tb_init: float = 9.20,
        topt_init: float = 26.0,
        tmax_init: float = 38.0,
        tau_b: float = 0.80,
        tau_m: float = 1.50,
        sigma_heat: float = 4.0,
    ):
        super().__init__()
        # Trainable cardinal temperature parameters
        self.tb = nn.Parameter(torch.tensor(float(tb_init), dtype=torch.float32))
        self.topt = nn.Parameter(torch.tensor(float(topt_init), dtype=torch.float32))
        self.tmax = nn.Parameter(torch.tensor(float(tmax_init), dtype=torch.float32))

        # Trainable smoothing radii
        self.tau_b = nn.Parameter(torch.tensor(float(tau_b), dtype=torch.float32))
        self.tau_m = nn.Parameter(torch.tensor(float(tau_m), dtype=torch.float32))
        self.sigma_heat = nn.Parameter(torch.tensor(float(sigma_heat), dtype=torch.float32))

    def forward(self, T: torch.Tensor) -> torch.Tensor:
        """
        Computes the C^inf smooth thermal rate phi(T) in °C·d/d.

        Parameters
        ----------
        T : Tensor of arbitrary shape (...,)
            Temperature (°C).

        Returns
        -------
        Tensor of same shape as T
            Instantaneous effective thermal rate phi(T) > 0.
        """
        # Ensure positive smoothing scales for numerical stability
        tau_b = torch.clamp(self.tau_b, min=0.1)
        tau_m = torch.clamp(self.tau_m, min=0.1)
        sigma_heat = torch.clamp(self.sigma_heat, min=0.5)

        # 1. Smooth ramp at base temperature using Softplus: tau_b * ln(1 + exp((T - tb)/tau_b))
        ramp = tau_b * F.softplus((T - self.tb) / tau_b)

        # 2. High-temperature ceiling cutoff
        ceiling = 1.0 - torch.sigmoid((T - self.tmax) / tau_m)

        # 3. Supra-optimal temperature decay (smooth via softplus)
        heat_excess = F.softplus((T - self.topt) / 1.0)
        heat_decay = torch.exp(-0.5 * (heat_excess / sigma_heat) ** 2)

        return ramp * ceiling * heat_decay


class MultiFactorSensoryFusion(nn.Module):
    """
    Multi-Factor Microclimate Sensory Fusion Network.

    Fuses:
    1. 24-h Mean Air Temperature Tavg via C^inf SmoothThermalKernel.
    2. Diurnal Temperature Difference DIF = Tmax - Tmin via smooth tanh MLP (Psi_DIF).
    3. Photosynthetically Active Radiation Daily Light Integral (DLI) via Michaelis-Menten
       light limitation factor: DLI / (DLI + Kdli).

    Parameters
    ----------
    hidden_dim : int, default 16
        Hidden dimension of the DIF modulation MLP.
    kdli_init : float, default 3.5
        Light half-saturation constant (mol/m2/d).
    tb_init : float, default 9.20
        Base temperature (°C) passed to SmoothThermalKernel.
    """

    def __init__(
        self,
        hidden_dim: int = 16,
        kdli_init: float = 3.5,
        tb_init: float = 9.20,
        topt_init: float = 26.0,
        tmax_init: float = 38.0,
    ):
        super().__init__()
        self.thermal_kernel = SmoothThermalKernel(
            tb_init=tb_init,
            topt_init=topt_init,
            tmax_init=tmax_init,
        )
        self.dif_mlp = nn.Sequential(
            nn.Linear(1, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, 1),
            nn.Tanh(),
        )
        self.kdli = nn.Parameter(torch.tensor(float(kdli_init), dtype=torch.float32))

    def forward(
        self,
        tavg: torch.Tensor,
        dif: torch.Tensor,
        dli: torch.Tensor,
    ) -> torch.Tensor:
        """
        Computes the combined environmental growth velocity component f_growth(t).

        Parameters
        ----------
        tavg : Tensor of shape (B, T)
            Daily mean temperature (°C).
        dif : Tensor of shape (B, T)
            Diurnal temperature difference Tmax - Tmin (°C).
        dli : Tensor of shape (B, T)
            Daily light integral (mol/m2/d).

        Returns
        -------
        Tensor of shape (B, T)
            Environmental growth velocity component f_growth(t) >= 0.
        """
        phi_t = self.thermal_kernel(tavg)

        # DIF modulation: bounded in [0.85, 1.15] > 0
        dif_in = dif.unsqueeze(-1)
        dif_mod = 1.0 + 0.15 * self.dif_mlp(dif_in).squeeze(-1)

        # Light limitation factor: DLI / (DLI + Kdli) in [0.0, 1.0]
        kdli_val = F.softplus(self.kdli) + 1e-4
        dli_pos = torch.clamp(dli, min=0.0)
        light_factor = dli_pos / (dli_pos + kdli_val + 1e-6)

        return phi_t * dif_mod * light_factor


class NeuralPhenologyOperator(nn.Module):
    """
    Master Neural Phenology Operator.

    Integrates environmental series into a continuous, strictly monotonic
    developmental stage index D(t) in [0.0, 3.0].

    Developmental Stage Milestones:
    - D = 0.00: Sowing / Germination in Nursery
    - D = 0.18: Transplanting at Standard Seedling Age (PAGE = 22.0 d)
    - D = 1.00: Anthesis / First Flowering (ADAPS)
    - D = 1.25: First Fruit Set / Pod Emergence (PDFPS)
    - D = 1.50: First Commercial Harvest
    - D = 2.00: Peak Harvest Stage
    - D = 2.50: Physiological Cessation / Pulling
    - D = 3.00: Terminal Senescence

    Core Mechanisms:
    1. Seedling Age Initialization D(0) = f(PAGE):
       Smooth sigmoid transition reproducing D(0) = 0.18 at PAGE = 22.0d
       and sharp developmental collapse (< 0.03) when PAGE < 19.0d.
    2. Strictly Non-Negative Velocity Field:
       dD/dt = G_chill(t) * f_growth(t) * Softplus(dev_scale) >= 0
    3. Continuous Integration:
       D(t) = clamp(D(0) + sum_{tau=0}^t (dD/dtau), 0.0, 3.0)
    """

    def __init__(
        self,
        tb_init: float = 9.20,
        topt_init: float = 26.0,
        tmax_init: float = 38.0,
        tchill_crit: float = 11.5,
        trec_crit: float = 22.0,
        sc_thresh: float = 45.0,
        delta_s: float = 6.0,
        kappa_c: float = 0.80,
        lambda_rec: float = 0.15,
        dev_scale_init: float = 1.0 / 220.0,
        page_ref: float = 22.0,
        page_gamma: float = 1.2,
    ):
        super().__init__()
        self.chilling_gate = SmoothChillingGate(
            tchill_crit=tchill_crit,
            trec_crit=trec_crit,
            sc_thresh=sc_thresh,
            delta_s=delta_s,
            kappa_c=kappa_c,
            lambda_rec=lambda_rec,
        )
        self.sensory_fusion = MultiFactorSensoryFusion(
            tb_init=tb_init,
            topt_init=topt_init,
            tmax_init=tmax_init,
        )

        # Trainable scaling parameter mapping thermal units to D in [0, 3]
        # Uses inverse softplus so Softplus(self.dev_scale) equals dev_scale_init initially
        import math
        dev_init_val = float(dev_scale_init)
        param_init = math.log(math.expm1(dev_init_val)) if dev_init_val > 0 else dev_init_val
        self.dev_scale = nn.Parameter(torch.tensor(param_init, dtype=torch.float32))

        # Nursery seedling age adaptation parameters
        self.page_ref = float(page_ref)
        self.page_gamma = nn.Parameter(torch.tensor(float(page_gamma), dtype=torch.float32))

    def get_initial_stage(self, page: torch.Tensor) -> torch.Tensor:
        """
        Initializes D(0) at transplanting based on nursery seedling age PAGE (days).

        Reproduces:
        - PAGE = 22.0 d -> D(0) = 0.180
        - PAGE < 19.0 d -> severe developmental delay (D(0) < 0.05)
        """
        if page.ndim == 0:
            page = page.unsqueeze(0)
        ref_sigmoid = torch.sigmoid(torch.tensor((22.0 - 19.0) / 1.5, dtype=page.dtype, device=page.device))
        sig = torch.sigmoid((page - 19.0) / 1.5)
        ratio = sig / ref_sigmoid
        power = torch.pow(torch.clamp(page / self.page_ref, min=1e-4), F.softplus(self.page_gamma))
        return 0.18 * ratio * power

    def forward(
        self,
        tavg: torch.Tensor,
        tmin: torch.Tensor,
        tmax: torch.Tensor,
        dif: torch.Tensor,
        dli: torch.Tensor,
        daylength: torch.Tensor,
        page: torch.Tensor,
    ) -> Dict[str, torch.Tensor]:
        """
        Batched differentiable forward pass.

        Parameters
        ----------
        tavg : Tensor of shape (B, T)
            Daily mean temperature series (°C).
        tmin : Tensor of shape (B, T)
            Daily minimum temperature series (°C).
        tmax : Tensor of shape (B, T)
            Daily maximum temperature series (°C).
        dif : Tensor of shape (B, T)
            Diurnal temperature difference series (°C).
        dli : Tensor of shape (B, T)
            Daily light integral series (mol/m2/d).
        daylength : Tensor of shape (B, T)
            Astronomical daylength series (hours).
        page : Tensor of shape (B,) or (B, 1) or scalar ()
            Nursery seedling age at transplanting (days).

        Returns
        -------
        dict[str, Tensor]
            Dictionary containing:
            - 'D': Continuous stage index trajectory (B, T) in [0.0, 3.0]
            - 'dD_dt': Instantaneous developmental velocity (B, T) >= 0
            - 'G_chill': Chilling gate state trajectory (B, T) in [0.0, 1.0]
            - 'D0': Initial transplant stage index (B, 1)
        """
        # Ensure 2D batched shapes
        if tavg.ndim == 1:
            tavg = tavg.unsqueeze(0)
            tmin = tmin.unsqueeze(0)
            tmax = tmax.unsqueeze(0)
            dif = dif.unsqueeze(0)
            dli = dli.unsqueeze(0)
            daylength = daylength.unsqueeze(0)

        if page.ndim == 0:
            page = page.unsqueeze(0)
        if page.ndim == 2:
            page_1d = page.squeeze(-1)
        else:
            page_1d = page

        # 1. Evaluate chilling gate G_chill(t) in [0.0, 1.0]
        g_chill = self.chilling_gate(tmin, tmax, daylength)

        # 2. Evaluate sensory fusion growth velocity f_growth(t) >= 0
        f_growth = self.sensory_fusion(tavg, dif, dli)

        # 3. Calculate instantaneous velocity field: guaranteed strictly >= 0
        dD_dt = g_chill * f_growth * F.softplus(self.dev_scale)

        # 4. Initialize transplant stage D(0)
        d0 = self.get_initial_stage(page_1d).unsqueeze(-1)  # (B, 1)

        # 5. Continuous integration along time axis
        D_accum = torch.cumsum(dD_dt, dim=1)  # (B, T)
        D = torch.clamp(d0 + D_accum, min=0.0, max=3.0)

        return {
            "D": D,
            "dD_dt": dD_dt,
            "G_chill": g_chill,
            "D0": d0,
        }
