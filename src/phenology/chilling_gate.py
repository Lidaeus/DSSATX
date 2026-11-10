"""
src/phenology/chilling_gate.py
==============================
Dynamical Low-Temperature Physiological Dormancy Soft Gate (SmoothChillingGate)
for Protected Greenhouse Crops (Eggplant & Tomato).

Eliminates the autumn cold runaway phenomenon (深秋低温飞车) by maintaining a continuous
chilling stress accumulation state-space ODE with daytime recovery hysteresis and
short-daylight synergistic suppression, without requiring artificial calendar harvest dates.

Author: teamwork_preview_worker_m2
Date: 2026-09-20
"""

from typing import Optional, Tuple
import torch
import torch.nn as nn
import torch.nn.functional as F


class SmoothChillingGate(nn.Module):
    """
    Dynamical Low-Temperature Dormancy Soft Gate G_chill(t) in [0.0, 1.0].

    State-Space Formulation:
    ------------------------
    Maintains continuous chilling memory Sc(t) >= 0:
        dSc/dt = I_chill(Tmin(t)) - R_recovery(Tmax(t), Sc(t))

    where:
    - I_chill(Tmin): Softplus chilling inflow activated below tchill_crit (init 11.5°C)
      I_chill = kappa_c * tau_c * ln(1 + exp((tchill_crit - Tmin) / tau_c))
    - R_recovery(Tmax, Sc): Daytime warm temperature de-chilling attenuated by
      dormancy commitment (hysteresis denominator 1 / (1 + 0.05 * Sc))
      R_recovery = lambda_rec * sigmoid((Tmax - trec_crit) / tau_r) * (Sc / (1.0 + 0.05 * Sc))
    - Gate Calculation:
      G_chill(t) = sigmoid(-(Sc - sc_thresh) / delta_s) * [1 - 0.40 * short_day_fac]

    Parameters
    ----------
    tchill_crit : float, default 11.5
        Critical minimum temperature (°C) below which chilling accumulates.
    trec_crit : float, default 22.0
        Critical maximum temperature (°C) required for daytime de-chilling recovery.
    sc_thresh : float, default 45.0
        Chilling accumulation threshold triggering physiological growth cessation.
    delta_s : float, default 6.0
        Smooth transition scale parameter for the logistic cessation gate.
    kappa_c : float, default 0.80
        Chilling induction rate multiplier.
    lambda_rec : float, default 0.15
        Daytime thermal recovery rate multiplier.
    tau_c : float, default 0.80
        Smoothing radius for chilling inflow (°C).
    tau_r : float, default 1.50
        Smoothing radius for recovery activation (°C).
    """

    def __init__(
        self,
        tchill_crit: float = 11.5,
        trec_crit: float = 22.0,
        sc_thresh: float = 45.0,
        delta_s: float = 6.0,
        kappa_c: float = 0.80,
        lambda_rec: float = 0.15,
        tau_c: float = 0.80,
        tau_r: float = 1.50,
    ):
        super().__init__()
        # Trainable parameters with biological priors
        self.tchill_crit = nn.Parameter(torch.tensor(float(tchill_crit), dtype=torch.float32))
        self.trec_crit = nn.Parameter(torch.tensor(float(trec_crit), dtype=torch.float32))
        self.sc_thresh = nn.Parameter(torch.tensor(float(sc_thresh), dtype=torch.float32))
        self.delta_s = nn.Parameter(torch.tensor(float(delta_s), dtype=torch.float32))
        self.kappa_c = nn.Parameter(torch.tensor(float(kappa_c), dtype=torch.float32))
        self.lambda_rec = nn.Parameter(torch.tensor(float(lambda_rec), dtype=torch.float32))

        # Smoothing radii (constant buffers or attributes)
        self.register_buffer("tau_c", torch.tensor(float(tau_c), dtype=torch.float32))
        self.register_buffer("tau_r", torch.tensor(float(tau_r), dtype=torch.float32))

    def forward(
        self,
        tmin_seq: torch.Tensor,
        tmax_seq: torch.Tensor,
        daylength_seq: torch.Tensor,
        return_sc: bool = False,
    ) -> torch.Tensor:
        """
        Sequential forward pass through the chilling dynamics.

        Parameters
        ----------
        tmin_seq : Tensor of shape (B, T)
            Daily minimum temperature series (°C).
        tmax_seq : Tensor of shape (B, T)
            Daily maximum temperature series (°C).
        daylength_seq : Tensor of shape (B, T)
            Daily astronomical daylength series (hours).
        return_sc : bool, default False
            If True, returns tuple (g_chill, sc_seq).

        Returns
        -------
        Tensor of shape (B, T)
            Chilling suppression gate G_chill(t) in [0.0, 1.0].
        """
        if tmin_seq.ndim == 1:
            tmin_seq = tmin_seq.unsqueeze(0)
            tmax_seq = tmax_seq.unsqueeze(0)
            daylength_seq = daylength_seq.unsqueeze(0)
            squeeze_output = True
        else:
            squeeze_output = False

        batch_size, seq_len = tmin_seq.shape
        sc = torch.zeros(batch_size, device=tmin_seq.device, dtype=tmin_seq.dtype)

        g_chill_list = []
        sc_list = []

        # Safe parameter access ensuring strictly positive scale parameters
        tau_c = self.tau_c
        tau_r = self.tau_r
        delta_s = torch.clamp(self.delta_s, min=0.5)

        for t in range(seq_len):
            tmin = tmin_seq[:, t]
            tmax = tmax_seq[:, t]
            dl = daylength_seq[:, t]

            # 1. Chilling inflow: softplus activation below tchill_crit
            # Smoothly approaches 0 when tmin >> tchill_crit, linear when tmin < tchill_crit
            chill_inflow = self.kappa_c * tau_c * F.softplus((self.tchill_crit - tmin) / tau_c)

            # 2. Daytime thermal recovery: sigmoid activation above trec_crit
            # Attenuated by physiological dormancy commitment (1 / (1 + 0.05 * Sc))
            rec_gate = torch.sigmoid((tmax - self.trec_crit) / tau_r)
            commitment_attenuation = sc / (1.0 + 0.05 * sc)
            warm_rec = self.lambda_rec * rec_gate * commitment_attenuation

            # 3. State update: cumulative stress cannot drop below 0
            sc = F.relu(sc + chill_inflow - warm_rec)

            # 4. Gate calculation: logistic suppression
            base_gate = torch.sigmoid(-(sc - self.sc_thresh) / delta_s)

            # 5. Synergistic short-daylight inhibition (< 10.5 hr and moderate chilling Sc > 15.0)
            short_day_fac = torch.sigmoid((10.5 - dl) / 0.5) * torch.sigmoid((sc - 15.0) / 5.0)
            g_chill = base_gate * (1.0 - 0.40 * short_day_fac)

            # Clamp output safely to [0.0, 1.0]
            g_chill = torch.clamp(g_chill, min=0.0, max=1.0)

            g_chill_list.append(g_chill)
            if return_sc:
                sc_list.append(sc)

        g_chill_seq = torch.stack(g_chill_list, dim=1)

        if squeeze_output:
            g_chill_seq = g_chill_seq.squeeze(0)

        if return_sc:
            sc_seq = torch.stack(sc_list, dim=1)
            if squeeze_output:
                sc_seq = sc_seq.squeeze(0)
            return g_chill_seq, sc_seq

        return g_chill_seq
