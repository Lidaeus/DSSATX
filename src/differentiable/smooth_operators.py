"""
Differentiable CROPGRO Smooth Operators
======================================
Provides C^infinity / C^1 smooth relaxations for discrete physiological functions
in DSSAT CROPGRO, enabling end-to-end autodiff and gradient-based parameter estimation.

References:
  - DSSAT CROPGRO PHENOL.for: four-point cardinal temperature function (CURV)
  - DSSAT CROPGRO PHOTO.for: canopy gross photosynthesis with light saturation
"""

import math

import torch
import torch.nn.functional as F


def smooth_cardinal_temperature(
    T: torch.Tensor,
    tb: torch.Tensor,
    to1: torch.Tensor,
    to2: torch.Tensor,
    tm: torch.Tensor,
    beta: float = 3.0,
) -> torch.Tensor:
    """
    Smooth temperature response function replacing CROPGRO's piecewise 4-point
    cardinal curve (CURV function in Utilities/UTILS.for:342-365).

    Original DSSAT PHENOL.for piecewise linear:
      T <= TB:         0
      TB < T <= TO1:   (T - TB) / (TO1 - TB)
      TO1 < T <= TO2:  1.0
      TO2 < T < TM:    1.0 - (T - TO2) / (TM - TO2)
      T >= TM:         0

    Smooth relaxation via softplus differences:
      f_up(T)   = [softplus(β(T - tb)) - softplus(β(T - to1))] / [β(to1 - tb)]
      f_down(T) = [softplus(β(tm - T)) - softplus(β(to2 - T))] / [β(tm - to2)]
      result    = clamp(f_up × f_down, 0, 1)

    With beta=3.0, maximum approximation error in the transition zones is ~3-5%.
    """
    eps = 1e-6
    d_up = torch.clamp(to1 - tb, min=eps)
    d_down = torch.clamp(tm - to2, min=eps)

    up_term = (F.softplus(beta * (T - tb)) - F.softplus(beta * (T - to1))) / (beta * d_up)
    down_term = (F.softplus(beta * (tm - T)) - F.softplus(beta * (to2 - T))) / (beta * d_down)

    resp = torch.clamp(up_term * down_term, min=0.0, max=1.0)
    return resp


def smooth_gate(x: torch.Tensor, x_center: torch.Tensor, width: float = 1.0) -> torch.Tensor:
    """
    Smooth Heaviside step function via sigmoid.
    Replaces discrete IF-THEN phase switches in CROPGRO DEMAND.for and PODS.for.
    """
    return torch.sigmoid((x - x_center) / max(width, 1e-6))


def smooth_window(x: torch.Tensor, x_start: torch.Tensor, x_end: torch.Tensor, width: float = 1.0) -> torch.Tensor:
    """Smooth boxcar / window function active between x_start and x_end."""
    gate_start = smooth_gate(x, x_start, width)
    gate_end = smooth_gate(x, x_end, width)
    return torch.clamp(gate_start * (1.0 - gate_end), min=0.0, max=1.0)


def soft_positive(x: torch.Tensor, floor: float = 0.01) -> torch.Tensor:
    """
    Soft positivity constraint with nonzero gradient everywhere.
    Unlike torch.clamp(x, min=floor), this has no gradient dead zone at the boundary.
    """
    return floor + F.softplus(x - floor)


def bounded_param(p_raw: torch.Tensor, p_min: float, p_max: float) -> torch.Tensor:
    """
    Bijective mapping from unconstrained real space (-inf, +inf) to physical
    interval (p_min, p_max) via sigmoid. Guarantees zero boundary hitting during
    gradient descent — parameters asymptotically approach but never reach bounds.
    """
    return p_min + (p_max - p_min) * torch.sigmoid(p_raw)


def inverse_bounded_param(p_val: float, p_min: float, p_max: float) -> float:
    """Inverse logit mapping to initialize raw unconstrained parameter from physical value."""
    frac = (p_val - p_min) / (p_max - p_min)
    frac = max(min(frac, 0.9999), 0.0001)
    return math.log(frac / (1.0 - frac))
