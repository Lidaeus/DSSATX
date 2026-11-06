"""
Differentiable CROPGRO Autograd Inversion Engine
=================================================
Gradient-based parameter calibration using PyTorch automatic differentiation
(standard BPTT — backpropagation through time), replacing PEST++ zero-order
ensemble sampling with exact first-order gradient descent.

Terminology note:
  This module uses standard reverse-mode autodiff (BPTT) with O(T) memory,
  NOT the adjoint ODE method (which achieves O(1) memory by re-solving the ODE
  backward). True adjoint integration via torchdiffeq.odeint_adjoint is planned
  for Phase 3 when long-season (300+ day) simulations require memory efficiency.
"""

import time
from typing import Dict, List, Tuple

import torch
import torch.nn as nn

from src.differentiable.diff_cropgro_core import DifferentiableCROPGRO


class NativeAdamOptimizer:
    """
    Self-contained pure-PyTorch Adam optimizer.
    Avoids Windows triton/torch.compile dependency issues that crash
    torch.optim.Adam on this platform (PyTorch 2.11 + broken triton stub).
    """

    def __init__(
        self,
        params: List[torch.nn.Parameter],
        lr: float = 0.05,
        betas: Tuple[float, float] = (0.9, 0.999),
        eps: float = 1e-8,
        weight_decay: float = 1e-4,
    ):
        self.params = [p for p in params if p.requires_grad]
        self.lr = lr
        self.beta1, self.beta2 = betas
        self.eps = eps
        self.weight_decay = weight_decay
        self.m = [torch.zeros_like(p.data) for p in self.params]
        self.v = [torch.zeros_like(p.data) for p in self.params]
        self.step_count = 0

    def zero_grad(self):
        for p in self.params:
            if p.grad is not None:
                p.grad.detach_()
                p.grad.zero_()

    def step(self):
        self.step_count += 1
        with torch.no_grad():
            for i, p in enumerate(self.params):
                if p.grad is None:
                    continue
                grad = p.grad.data
                if self.weight_decay != 0.0:
                    grad = grad + self.weight_decay * p.data

                self.m[i] = self.beta1 * self.m[i] + (1.0 - self.beta1) * grad
                self.v[i] = self.beta2 * self.v[i] + (1.0 - self.beta2) * (grad ** 2)

                m_hat = self.m[i] / (1.0 - self.beta1 ** self.step_count)
                v_hat = self.v[i] / (1.0 - self.beta2 ** self.step_count)

                p.data.sub_(self.lr * m_hat / (torch.sqrt(v_hat) + self.eps))


class AutogradCalibrationEngine:
    """
    Gradient-based inverse calibration engine for Diff-CROPGRO parameters.

    Uses standard BPTT (backpropagation through time) for exact gradient
    computation. This is NOT the adjoint ODE method — see module docstring.
    """

    def __init__(
        self,
        model: DifferentiableCROPGRO,
        learning_rate: float = 0.05,
        weight_decay: float = 1e-4,
    ):
        self.model = model
        self.lr = learning_rate
        params = list(self.model.parameters())
        self.optimizer = NativeAdamOptimizer(params, lr=learning_rate, weight_decay=weight_decay)

    def calibrate(
        self,
        weather_seq: torch.Tensor,
        stress_seq: torch.Tensor,
        obs_targets: Dict[str, Tuple[torch.Tensor, torch.Tensor, float]],
        max_epochs: int = 150,
        tolerance: float = 1e-5,
        verbose: bool = True,
    ) -> Dict:
        """
        Run gradient-based calibration loop.

        Args:
          weather_seq: (B, N_days, 3)
          stress_seq:  (B, N_days, 2) — exogenous stress, see P4 limitation
          obs_targets: dict mapping variable name → (time_indices, observed_values, weight)
          max_epochs:  maximum gradient update iterations
          tolerance:   convergence tolerance for loss reduction
          verbose:     print progress

        Returns:
          dict with loss_history, param_history, best_loss, best_params, elapsed_seconds
        """
        loss_history = []
        param_history = []
        start_time = time.time()
        best_loss = float("inf")
        best_params = {}

        for epoch in range(max_epochs):
            self.optimizer.zero_grad()
            states_traj, fresh_yield_traj = self.model.simulate(weather_seq, stress_seq)
            total_loss = torch.tensor(0.0, device=self.model.device)

            if "fresh_yield" in obs_targets:
                idx, obs_val, weight = obs_targets["fresh_yield"]
                sim_val = fresh_yield_traj[:, idx]
                yield_loss = torch.sum(weight * ((sim_val - obs_val) / (obs_val.mean() + 1e-3)) ** 2)
                total_loss = total_loss + yield_loss

            if "lai" in obs_targets:
                idx, obs_val, weight = obs_targets["lai"]
                sim_val = states_traj[:, idx, 0]
                lai_loss = torch.sum(weight * ((sim_val - obs_val) / (obs_val.mean() + 1e-3)) ** 2)
                total_loss = total_loss + lai_loss

            if "biomass" in obs_targets:
                idx, obs_val, weight = obs_targets["biomass"]
                sim_val = torch.sum(states_traj[:, idx, 1:6], dim=-1)
                bm_loss = torch.sum(weight * ((sim_val - obs_val) / (obs_val.mean() + 1e-3)) ** 2)
                total_loss = total_loss + bm_loss

            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
            self.optimizer.step()

            current_loss = total_loss.item()
            loss_history.append(current_loss)

            curr_phys = {k: v.item() for k, v in self.model.get_physical_params().items()}
            param_history.append(curr_phys)

            if current_loss < best_loss:
                best_loss = current_loss
                best_params = dict(curr_phys)

            if verbose and (epoch % 20 == 0 or epoch == max_epochs - 1):
                print(f"Epoch {epoch:03d} | Loss: {current_loss:10.4f} | "
                      f"tb1={curr_phys['tb1']:.2f}°C, lfmax={curr_phys['lfmax']:.3f}, "
                      f"xfrt={curr_phys['xfrt']:.3f}, slavr={curr_phys['slavr']:.1f}")

            if epoch > 10 and abs(loss_history[-2] - loss_history[-1]) < tolerance:
                if verbose:
                    print(f"Converged at epoch {epoch} with tolerance {tolerance}")
                break

        elapsed_seconds = time.time() - start_time

        return {
            "loss_history": loss_history,
            "param_history": param_history,
            "best_loss": best_loss,
            "best_params": best_params,
            "elapsed_seconds": elapsed_seconds,
            "epochs_run": len(loss_history),
        }


# Backward-compatible alias for code that imports the old name
AdjointCalibrationEngine = AutogradCalibrationEngine
