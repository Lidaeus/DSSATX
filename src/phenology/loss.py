"""
src/phenology/loss.py
=====================
Differentiable Multi-Milestone Phenology Loss Function.

Features:
- Continuous soft milestone prediction via soft-threshold interpolation:
  (anthesis 1.00, fruit set 1.25, first harvest 1.50, peak harvest 2.00, cessation 2.50).
- Huber milestone event loss robust to observation noise and heavy tails.
- Inverse-variance reciprocal uncertainty weighting: w_i = 1 / (sigma_i^2 + 1e-4).
- Trajectory curvature smoothness penalty: mean((d^2 D / dt^2)^2).
- Bounded, smooth, and analytically differentiable everywhere.

Author: teamwork_preview_worker_m2
Date: 2026-09-20
"""

from typing import Dict, Optional, Tuple, Union
import torch
import torch.nn as nn
import torch.nn.functional as F


DEFAULT_STAGE_ANCHORS: Dict[str, float] = {
    "anthesis": 1.00,
    "ADAPS": 1.00,
    "fruit_set": 1.25,
    "PDFPS": 1.25,
    "first_harvest": 1.50,
    "peak_harvest": 2.00,
    "cessation": 2.50,
    "CESSATION": 2.50,
}


class PhenologyLoss(nn.Module):
    """
    Composite Differentiable Loss for Neural Phenology Training.

    Total Loss:
    -----------
    L_total = L_milestone + lambda_smooth * L_smooth

    where:
    - L_milestone: Weighted Huber loss across all observed developmental milestones
      w_i = 1 / (sigma_i^2 + 1e-4)
    - L_smooth: Mean squared second difference of stage D(t) over daily time steps
      L_smooth = mean((d^2 D / dt^2)^2)

    Parameters
    ----------
    lambda_smooth : float, default 0.05
        Weighting coefficient for the curvature smoothness penalty.
    huber_delta : float, default 1.5
        Transition threshold for the Huber loss function (days).
    tau_soft : float, default 0.05
        Soft-threshold sigmoid temperature for milestone day interpolation.
    stage_anchors : dict[str, float], optional
        Custom milestone stage index anchors. Defaults to DEFAULT_STAGE_ANCHORS.
    eps_var : float, default 1e-4
        Numerical epsilon added to measurement variance for stability.
    """

    def __init__(
        self,
        lambda_smooth: float = 0.05,
        huber_delta: float = 1.5,
        tau_soft: float = 0.05,
        stage_anchors: Optional[Dict[str, float]] = None,
        eps_var: float = 1e-4,
    ):
        super().__init__()
        self.lambda_smooth = float(lambda_smooth)
        self.huber_delta = float(huber_delta)
        self.tau_soft = float(tau_soft)
        self.eps_var = float(eps_var)

        self.stage_anchors = dict(DEFAULT_STAGE_ANCHORS)
        if stage_anchors is not None:
            self.stage_anchors.update(stage_anchors)

    def predict_milestone_days(
        self,
        D: torch.Tensor,
        stage_targets: Optional[Dict[str, float]] = None,
    ) -> Dict[str, torch.Tensor]:
        """
        Computes continuous, differentiable milestone occurrence days from D(t).

        For each target stage D*, the continuous expected crossing day is:
            t_hat = sum_{t=0}^{T-1} (1.0 - sigmoid((D(t) - D*) / tau_soft))

        Parameters
        ----------
        D : Tensor of shape (B, T)
            Predicted stage index trajectories in [0.0, 3.0].
        stage_targets : dict[str, float], optional
            Milestone names and corresponding stage target values.

        Returns
        -------
        dict[str, Tensor]
            Predicted milestone days of shape (B,) for each milestone.
        """
        if stage_targets is None:
            stage_targets = self.stage_anchors

        predictions: Dict[str, torch.Tensor] = {}
        for name, stage_val in stage_targets.items():
            prob_before = 1.0 - torch.sigmoid((D - stage_val) / self.tau_soft)
            pred_day = torch.sum(prob_before, dim=1)
            predictions[name] = pred_day

        return predictions

    def forward(
        self,
        pred_dict: Dict[str, torch.Tensor],
        target_milestones: Dict[str, torch.Tensor],
        target_uncertainties: Optional[Dict[str, torch.Tensor]] = None,
        return_components: bool = False,
    ) -> Union[torch.Tensor, Tuple[torch.Tensor, Dict[str, torch.Tensor]]]:
        """
        Computes the composite differentiable phenology loss.

        Parameters
        ----------
        pred_dict : dict[str, Tensor]
            Output dictionary from NeuralPhenologyOperator containing 'D' and 'dD_dt'.
        target_milestones : dict[str, Tensor]
            Target observed milestone days (B,) e.g. {"ADAPS": days, "PDFPS": days}.
        target_uncertainties : dict[str, Tensor], optional
            Measurement standard errors sigma_i (B,) for each milestone.
        return_components : bool, default False
            If True, returns tuple (total_loss, metrics_dict).

        Returns
        -------
        Tensor (scalar) or tuple (Tensor, dict)
            Total differentiable loss.
        """
        D = pred_dict["D"]          # (B, T)
        dD_dt = pred_dict["dD_dt"]  # (B, T)

        # 1. Continuous milestone day prediction
        pred_milestones = self.predict_milestone_days(D)

        loss_milestone = torch.tensor(0.0, device=D.device, dtype=D.dtype)
        num_active_milestones = 0
        milestone_losses: Dict[str, torch.Tensor] = {}

        # 2. Compute weighted Huber loss across provided target events
        for name, target_days in target_milestones.items():
            if name not in self.stage_anchors:
                continue

            pred_days = pred_milestones[name]

            # Mask out unobserved or invalid targets (target_days <= 0 or non-finite)
            valid_mask = (target_days > 0.0) & torch.isfinite(target_days)
            if not torch.any(valid_mask):
                continue

            # NaN-safe target masking to avoid NaN * 0 == NaN in backward/forward
            safe_target = torch.where(valid_mask, target_days, pred_days.detach())

            # Inverse-variance reciprocal weighting: 1 / (sigma^2 + eps_var)
            if target_uncertainties is not None and name in target_uncertainties:
                sigma = target_uncertainties[name]
                weights = 1.0 / (sigma ** 2 + self.eps_var)
            else:
                weights = torch.ones_like(target_days)

            # Huber loss per sample
            raw_huber = F.huber_loss(pred_days, safe_target, delta=self.huber_delta, reduction="none")
            masked_weights = weights * valid_mask.float()
            sum_weights = torch.sum(masked_weights)

            if sum_weights > 0:
                weighted_event_loss = torch.sum(raw_huber * masked_weights) / sum_weights
            else:
                weighted_event_loss = torch.tensor(0.0, device=D.device, dtype=D.dtype)

            loss_milestone = loss_milestone + weighted_event_loss
            milestone_losses[name] = weighted_event_loss.detach()
            num_active_milestones += 1

        if num_active_milestones > 1:
            loss_milestone = loss_milestone / num_active_milestones

        # 3. Curvature smoothness penalty: mean((d^2 D / dt^2)^2)
        if dD_dt.shape[1] > 1:
            d2D_dt2 = dD_dt[:, 1:] - dD_dt[:, :-1]
            loss_smooth = torch.mean(d2D_dt2 ** 2)
        else:
            loss_smooth = torch.tensor(0.0, device=D.device, dtype=D.dtype)

        # 4. Total bounded, differentiable loss
        total_loss = loss_milestone + self.lambda_smooth * loss_smooth

        if return_components:
            components = {
                "total_loss": total_loss.detach(),
                "loss_milestone": loss_milestone.detach(),
                "loss_smooth": loss_smooth.detach(),
                "pred_milestones": {k: v.detach() for k, v in pred_milestones.items()},
                "milestone_losses": milestone_losses,
            }
            return total_loss, components

        return total_loss
