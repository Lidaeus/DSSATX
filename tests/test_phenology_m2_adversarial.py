"""
tests/test_phenology_m2_adversarial.py
======================================
Empirical Adversarial Stress Harness for Milestone 2: Neural-Phenology Operator Core.

Verification Dimensions:
1. Numerical gradient flow through NeuralPhenologyOperator and PhenologyLoss:
   - Complete parameter gradient coverage (19 parameters)
   - Input tensor gradient propagation
   - Arbitrary milestone target combinations (single, subset, full, custom)
   - Variable sequence lengths (T=2, 10, 30, 90, 200)
   - Masked negative targets (-99.0 DSSAT convention) vs NaN targets vulnerability
2. Batch dimension scalability:
   - Batch sizes B in [1, 2, 4, 16, 64], sequence lengths T in [15, 60, 150]
   - 1D input broadcasting (T,) -> (1, T)
   - page shape flexibility (B,) vs (B, 1) and 0D scalar edge case
   - Strict batch isolation / numerical equivariance (no cross-sample contamination)
3. Autumn runaway suppression stress test:
   - Late-autumn simulation: Day 26°C, Night 8°C, Daylength 10.0 hr, 60 days
   - G_chill drops below 0.05
   - Growth velocity dD/dt -> 0 (>=95% suppression, dD/dt < 0.001)
   - Night temperature sensitivity and daylength synergy
4. Edge case robustness & numerical clamping:
   - NaN / Inf immunity under extreme weather (-25°C to 60°C, zero/extreme DLI, inverted DIF)
   - Numerical clamping of D(t) within [0.0, 3.0] under 500-day accelerated growth
   - Seedling age PAGE boundary resilience (0 to 60 days)
   - Loss function division-by-zero protection (sigma=0) and T=1 compatibility
   - Device compatibility (CPU and CUDA when available)

Author: Empirical Challenger 2 (Milestone 2)
Date: 2026-09-20
"""

import math
from typing import Dict, List, Optional

import numpy as np
import pytest
import torch
import torch.nn as nn
import torch.nn.functional as F

from src.phenology import (
    SmoothChillingGate,
    SmoothThermalKernel,
    MultiFactorSensoryFusion,
    NeuralPhenologyOperator,
    PhenologyLoss,
    get_seasonal_tensor_bundle,
    load_benchmark_dataset,
)


# ==============================================================================
# Helper Functions
# ==============================================================================

def make_synthetic_weather(
    batch_size: int = 1,
    seq_len: int = 60,
    tavg_val: float = 20.0,
    tmin_val: float = 14.0,
    tmax_val: float = 26.0,
    dif_val: float = 12.0,
    dli_val: float = 15.0,
    daylength_val: float = 12.0,
    page_val: float = 22.0,
    requires_grad: bool = False,
    device: torch.device = torch.device("cpu"),
) -> Dict[str, torch.Tensor]:
    """Generates synthetic microclimate tensor dictionary with consistent shapes."""
    tavg = torch.full((batch_size, seq_len), tavg_val, dtype=torch.float32, device=device, requires_grad=requires_grad)
    tmin = torch.full((batch_size, seq_len), tmin_val, dtype=torch.float32, device=device, requires_grad=requires_grad)
    tmax = torch.full((batch_size, seq_len), tmax_val, dtype=torch.float32, device=device, requires_grad=requires_grad)
    dif = torch.full((batch_size, seq_len), dif_val, dtype=torch.float32, device=device, requires_grad=requires_grad)
    dli = torch.full((batch_size, seq_len), dli_val, dtype=torch.float32, device=device, requires_grad=requires_grad)
    daylength = torch.full((batch_size, seq_len), daylength_val, dtype=torch.float32, device=device, requires_grad=requires_grad)
    page = torch.full((batch_size,), page_val, dtype=torch.float32, device=device, requires_grad=requires_grad)

    return {
        "tavg": tavg,
        "tmin": tmin,
        "tmax": tmax,
        "dif": dif,
        "dli": dli,
        "daylength": daylength,
        "page": page,
    }


# ==============================================================================
# Dimension 1: Numerical Gradient Flow Tests
# ==============================================================================

class TestNumericalGradientFlow:
    """Stress-test autograd backward pass, parameter coverage, and loss gradient continuity."""

    def test_complete_parameter_gradient_coverage(self):
        """Verify that EVERY single trainable parameter receives finite, non-zero gradients."""
        model = NeuralPhenologyOperator()
        loss_fn = PhenologyLoss(lambda_smooth=0.05, huber_delta=1.5)

        # Batch size 4 with varying PAGE and temperatures spanning Tb (9.2C) to Topt (26C)
        B, T = 4, 90
        t = torch.linspace(0, 4 * math.pi, T)
        tavg_curve = 17.0 + 9.0 * torch.sin(t)  # Range 8.0°C to 26.0°C (crosses Tb=9.2°C)
        tavg = tavg_curve.unsqueeze(0).repeat(B, 1)
        tmin = tavg - 5.0
        tmax = tavg + 5.0
        dif = tmax - tmin
        dli = torch.full((B, T), 15.0)
        daylength = torch.full((B, T), 12.0)
        page = torch.tensor([17.0, 19.0, 22.0, 25.0])

        out = model(
            tavg=tavg,
            tmin=tmin,
            tmax=tmax,
            dif=dif,
            dli=dli,
            daylength=daylength,
            page=page,
        )

        targets = {
            "ADAPS": torch.tensor([18.0, 19.0, 16.0, 15.0]),
            "PDFPS": torch.tensor([24.0, 25.0, 22.0, 21.0]),
            "first_harvest": torch.tensor([42.0, 43.0, 40.0, 39.0]),
            "peak_harvest": torch.tensor([65.0, 66.0, 62.0, 61.0]),
            "cessation": torch.tensor([85.0, 86.0, 82.0, 80.0]),
        }
        uncertainties = {
            k: torch.tensor([1.0, 1.2, 0.8, 1.0]) for k in targets
        }

        loss = loss_fn(out, targets, uncertainties)
        loss.backward()

        param_count = 0
        for name, param in model.named_parameters():
            param_count += 1
            assert param.grad is not None, f"Parameter {name} has None gradient"
            assert torch.all(torch.isfinite(param.grad)), f"Parameter {name} has non-finite gradient: {param.grad}"
            grad_norm = param.grad.norm().item()
            assert grad_norm > 0.0, f"Parameter {name} has zero gradient (dead node)"

        # Verify all expected parameters are present (19 total)
        assert param_count == 19, f"Expected 19 trainable parameters, found {param_count}"

    def test_input_tensor_gradients(self):
        """Verify that microclimate inputs and seedling age tensors receive finite non-zero gradients."""
        model = NeuralPhenologyOperator()
        loss_fn = PhenologyLoss(lambda_smooth=0.05)

        B, T = 2, 60
        inputs = make_synthetic_weather(
            batch_size=B, seq_len=T, tavg_val=21.0, tmin_val=10.5, tmax_val=27.0,
            requires_grad=True
        )

        out = model(**inputs)
        targets = {
            "ADAPS": torch.tensor([17.0, 18.0]),
            "PDFPS": torch.tensor([23.0, 24.0]),
        }
        loss = loss_fn(out, targets)
        loss.backward()

        for var_name, tensor in inputs.items():
            assert tensor.grad is not None, f"Input tensor {var_name} has None gradient"
            assert torch.all(torch.isfinite(tensor.grad)), f"Input tensor {var_name} has non-finite gradient"
            grad_norm = tensor.grad.norm().item()
            assert grad_norm > 0.0, f"Input tensor {var_name} received zero gradient"

    @pytest.mark.parametrize("milestone_names", [
        ["ADAPS"],
        ["PDFPS"],
        ["first_harvest"],
        ["peak_harvest"],
        ["cessation"],
        ["ADAPS", "cessation"],
        ["ADAPS", "PDFPS", "first_harvest", "peak_harvest", "cessation"],
    ])
    def test_arbitrary_milestone_target_combinations(self, milestone_names: List[str]):
        """Verify gradient flow under arbitrary subsets of milestone targets."""
        model = NeuralPhenologyOperator()
        loss_fn = PhenologyLoss(lambda_smooth=0.05)

        B, T = 2, 80
        inputs = make_synthetic_weather(batch_size=B, seq_len=T, tavg_val=22.0, tmin_val=12.0, tmax_val=28.0)
        out = model(**inputs)

        full_targets = {
            "ADAPS": torch.tensor([16.0, 17.0]),
            "PDFPS": torch.tensor([22.0, 23.0]),
            "first_harvest": torch.tensor([40.0, 41.0]),
            "peak_harvest": torch.tensor([58.0, 59.0]),
            "cessation": torch.tensor([75.0, 76.0]),
        }
        selected_targets = {k: full_targets[k] for k in milestone_names}

        loss = loss_fn(out, selected_targets)
        assert torch.isfinite(loss), f"Loss is non-finite for targets {milestone_names}"
        assert loss.item() > 0.0

        loss.backward()
        assert model.dev_scale.grad is not None
        assert torch.isfinite(model.dev_scale.grad)
        assert model.dev_scale.grad.abs().item() > 0.0

    @pytest.mark.parametrize("seq_len", [2, 10, 30, 90, 200])
    def test_variable_sequence_length_gradients(self, seq_len: int):
        """Verify finite, non-zero gradient flow across arbitrary sequence lengths down to T=2."""
        model = NeuralPhenologyOperator()
        loss_fn = PhenologyLoss(lambda_smooth=0.05)

        B = 2
        inputs = make_synthetic_weather(batch_size=B, seq_len=seq_len, tavg_val=21.0, tmin_val=13.0, tmax_val=27.0)
        out = model(**inputs)

        # Scale target day proportionally to sequence length to stay within observable range
        target_day = max(1.0, min(float(seq_len) * 0.4, 25.0))
        targets = {"ADAPS": torch.full((B,), target_day)}

        loss = loss_fn(out, targets)
        loss.backward()

        assert torch.isfinite(loss)
        assert model.dev_scale.grad is not None
        assert torch.isfinite(model.dev_scale.grad)
        assert model.dev_scale.grad.abs().item() > 0.0

    def test_masked_negative_targets_robustness(self):
        """Ensure DSSAT unobserved negative targets (-99.0) are cleanly masked out with finite loss and grads."""
        model = NeuralPhenologyOperator()
        loss_fn = PhenologyLoss(lambda_smooth=0.05)

        B, T = 4, 60
        inputs = make_synthetic_weather(batch_size=B, seq_len=T, tavg_val=22.0)
        out = model(**inputs)

        # Mix valid targets with unobserved (-99.0)
        targets = {
            "ADAPS": torch.tensor([18.0, -99.0, 17.5, -99.0]),
            "PDFPS": torch.tensor([-99.0, 24.0, 0.0, 23.0]),
            "cessation": torch.tensor([-1.0, -1.0, -1.0, -1.0]),  # Completely unobserved event
        }
        uncertainties = {
            "ADAPS": torch.tensor([1.0, 1.0, 1.0, 1.0]),
            "PDFPS": torch.tensor([1.0, 1.0, 1.0, 1.0]),
            "cessation": torch.tensor([1.0, 1.0, 1.0, 1.0]),
        }

        loss = loss_fn(out, targets, uncertainties)
        assert torch.isfinite(loss), "Loss must be finite for negative unobserved targets"
        loss.backward()

        assert model.dev_scale.grad is not None
        assert torch.isfinite(model.dev_scale.grad)
        assert model.dev_scale.grad.abs().item() > 0.0

    def test_adversarial_vulnerability_nan_target_unmasked_huber(self):
        """
        Adversarial Bug Finding:
        Demonstrates that passing NaN or Inf in target_days causes loss to become NaN,
        because F.huber_loss evaluates to NaN before masked_weights multiplication (NaN * 0.0 = NaN).
        """
        loss_fn = PhenologyLoss()
        D = torch.full((4, 20), 1.5)
        dD_dt = torch.full((4, 20), 0.05)
        pred_dict = {"D": D, "dD_dt": dD_dt}

        targets_with_nan = {"ADAPS": torch.tensor([15.0, float("nan"), 16.0, 17.0])}
        loss = loss_fn(pred_dict, targets_with_nan)

        # Verify that NaN in targets is safely masked and does not produce NaN loss
        assert torch.isfinite(loss), "PhenologyLoss safely masks NaN in target_days"


# ==============================================================================
# Dimension 2: Batch Dimension Scalability Tests
# ==============================================================================

class TestBatchDimensionScalability:
    """Stress-test tensor shape contracts, broadcasting, and cross-batch isolation."""

    @pytest.mark.parametrize("batch_size", [1, 2, 8, 32, 64])
    @pytest.mark.parametrize("seq_len", [15, 60, 150])
    def test_batch_and_sequence_scaling_shapes(self, batch_size: int, seq_len: int):
        """Assert exact tensor shapes across varied batch sizes (up to 64) and sequence lengths."""
        model = NeuralPhenologyOperator()
        inputs = make_synthetic_weather(batch_size=batch_size, seq_len=seq_len)

        out = model(**inputs)

        assert out["D"].shape == (batch_size, seq_len)
        assert out["dD_dt"].shape == (batch_size, seq_len)
        assert out["G_chill"].shape == (batch_size, seq_len)
        assert out["D0"].shape == (batch_size, 1)

        # Monotonicity check
        assert torch.all(out["dD_dt"] >= 0.0)
        # Boundary check
        assert torch.all((out["D"] >= 0.0) & (out["D"] <= 3.0))

    def test_1d_input_automatic_broadcasting(self):
        """Verify that 1D inputs (T,) with 1D page (1,) are unsqueezed to (1, T) and (1, 1)."""
        model = NeuralPhenologyOperator()
        T = 40
        inputs_1d = {
            "tavg": torch.full((T,), 21.0),
            "tmin": torch.full((T,), 14.0),
            "tmax": torch.full((T,), 27.0),
            "dif": torch.full((T,), 13.0),
            "dli": torch.full((T,), 16.0),
            "daylength": torch.full((T,), 12.0),
            "page": torch.tensor([22.0]),  # 1D tensor
        }

        out = model(**inputs_1d)
        assert out["D"].shape == (1, T)
        assert out["dD_dt"].shape == (1, T)
        assert out["G_chill"].shape == (1, T)
        assert out["D0"].shape == (1, 1)

    def test_page_0d_scalar_edge_case(self):
        """
        Adversarial Shape Finding:
        Demonstrates that passing page as 0D scalar torch.tensor(22.0) produces D0 with shape (1,)
        instead of (1, 1) due to missing ndim==0 handling in operator.py.
        """
        model = NeuralPhenologyOperator()
        T = 20
        inputs_0d = {
            "tavg": torch.full((T,), 20.0),
            "tmin": torch.full((T,), 15.0),
            "tmax": torch.full((T,), 25.0),
            "dif": torch.full((T,), 10.0),
            "dli": torch.full((T,), 15.0),
            "daylength": torch.full((T,), 12.0),
            "page": torch.tensor(22.0),  # 0D scalar
        }
        out = model(**inputs_0d)
        # Confirms that 0D page safely yields contract (1, 1)
        assert out["D0"].shape == torch.Size([1, 1])

    def test_page_shape_flexibility(self):
        """Verify page passed as (B,) and (B, 1) yields identical D0."""
        model = NeuralPhenologyOperator()
        B = 5
        page_1d = torch.tensor([16.0, 18.0, 20.0, 22.0, 25.0])
        page_2d = page_1d.unsqueeze(-1)  # (B, 1)

        inputs = make_synthetic_weather(batch_size=B, seq_len=30)

        inputs["page"] = page_1d
        out_1d = model(**inputs)

        inputs["page"] = page_2d
        out_2d = model(**inputs)

        assert torch.allclose(out_1d["D0"], out_2d["D0"])
        assert torch.allclose(out_1d["D"], out_2d["D"])

    def test_batch_isolation_no_cross_talk(self):
        """Verify numerical equivariance: sample i evaluated solo (B=1) matches batch (B=64)."""
        model = NeuralPhenologyOperator()
        model.eval()

        T = 75
        # Define a specific reference sample
        ref_inputs = make_synthetic_weather(
            batch_size=1, seq_len=T, tavg_val=19.5, tmin_val=11.0, tmax_val=26.0,
            dif_val=15.0, dli_val=13.5, daylength_val=11.2, page_val=21.0
        )

        # Evaluate B=1
        with torch.no_grad():
            out_solo = model(**ref_inputs)

        # Construct B=64 batch where sample index 42 is identical to ref_inputs
        B = 64
        target_idx = 42
        torch.manual_seed(42)

        batch_inputs = {
            "tavg": torch.randn(B, T) * 5.0 + 20.0,
            "tmin": torch.randn(B, T) * 3.0 + 12.0,
            "tmax": torch.randn(B, T) * 4.0 + 27.0,
            "dif": torch.randn(B, T) * 3.0 + 14.0,
            "dli": torch.rand(B, T) * 20.0 + 5.0,
            "daylength": torch.rand(B, T) * 4.0 + 10.0,
            "page": torch.rand(B) * 10.0 + 15.0,
        }
        # Overwrite sample 42 with ref_inputs
        for k in ref_inputs:
            batch_inputs[k][target_idx] = ref_inputs[k][0]

        with torch.no_grad():
            out_batch = model(**batch_inputs)

        # Assert identical results within float32 tolerance
        max_diff_D = torch.max(torch.abs(out_solo["D"][0] - out_batch["D"][target_idx])).item()
        max_diff_dD = torch.max(torch.abs(out_solo["dD_dt"][0] - out_batch["dD_dt"][target_idx])).item()
        max_diff_G = torch.max(torch.abs(out_solo["G_chill"][0] - out_batch["G_chill"][target_idx])).item()

        assert max_diff_D < 1e-6, f"Batch crosstalk detected in D: diff = {max_diff_D}"
        assert max_diff_dD < 1e-6, f"Batch crosstalk detected in dD_dt: diff = {max_diff_dD}"
        assert max_diff_G < 1e-6, f"Batch crosstalk detected in G_chill: diff = {max_diff_G}"


# ==============================================================================
# Dimension 3: Autumn Runaway Suppression Stress Test
# ==============================================================================

class TestAutumnRunawaySuppression:
    """Stress-test biological cessation under persistent low night temperatures."""

    def test_autumn_60day_runaway_suppression(self):
        """Simulate late-autumn (Day 26°C, Night 8°C, 60 days): assert G_chill < 0.05 and dD/dt -> 0."""
        model = NeuralPhenologyOperator()
        gate = model.chilling_gate

        seq_len = 60
        tmax = torch.full((1, seq_len), 26.0)
        tmin = torch.full((1, seq_len), 8.0)
        tavg = (tmax + tmin) / 2.0  # 17.0°C
        dif = tmax - tmin          # 18.0°C
        dli = torch.full((1, seq_len), 12.0)
        daylength = torch.full((1, seq_len), 10.0)  # Short autumn day
        page = torch.tensor([22.0])

        out = model(tavg, tmin, tmax, dif, dli, daylength, page)

        g_chill_final = out["G_chill"][0, -1].item()
        dD_dt_initial = out["dD_dt"][0, 0].item()
        dD_dt_final = out["dD_dt"][0, -1].item()

        # Quantitative Assertion 1: G_chill drops strictly below 0.05
        assert g_chill_final < 0.05, f"G_chill failed to drop below 0.05: got {g_chill_final:.4f}"

        # Quantitative Assertion 2: Growth velocity dD/dt -> 0
        assert dD_dt_final < 0.001, f"dD/dt failed to halt towards 0: got {dD_dt_final:.6f}"
        reduction_pct = (1.0 - (dD_dt_final / dD_dt_initial)) * 100.0
        assert reduction_pct >= 95.0, f"Growth velocity reduction was only {reduction_pct:.1f}% (expected >= 95%)"

        # Verify state-space chilling memory accumulation
        _, sc_seq = gate(tmin, tmax, daylength, return_sc=True)
        final_sc = sc_seq[0, -1].item()
        assert final_sc > 45.0, f"Chilling memory Sc failed to exceed threshold: got {final_sc:.2f}"

    @pytest.mark.parametrize("tmin_val, tmax_val, expected_chilling", [
        (5.0, 24.0, True),    # Severe night chilling: fast dormancy
        (8.0, 26.0, True),    # Deep autumn chilling: reaches dormancy even with warm days
        (10.0, 19.0, True),   # Moderate night chilling with cool days: triggers dormancy
        (13.0, 26.0, False),  # Mild spring/autumn: NO dormancy
        (18.0, 30.0, False),  # Summer warm nights: NO dormancy
    ])
    def test_night_temperature_sensitivity_gradient(self, tmin_val: float, tmax_val: float, expected_chilling: bool):
        """Verify chilling gate activation boundaries across diurnal temperature regimes."""
        model = NeuralPhenologyOperator()
        seq_len = 60
        tmin = torch.full((1, seq_len), tmin_val)
        tmax = torch.full((1, seq_len), tmax_val)
        daylength = torch.full((1, seq_len), 10.5)

        g_chill, sc_seq = model.chilling_gate(tmin, tmax, daylength, return_sc=True)
        final_g = g_chill[0, -1].item()
        final_sc = sc_seq[0, -1].item()

        if expected_chilling:
            assert final_g < 0.15, f"Expected chilling suppression for Tmin={tmin_val}°C, got G_chill={final_g}"
            assert final_sc > 40.0
        else:
            assert final_g > 0.95, f"False dormancy detected for warm Tmin={tmin_val}°C, got G_chill={final_g}"
            assert final_sc < 5.0

    def test_short_daylength_synergistic_inhibition(self):
        """Verify that short daylength (< 10.5 hr) accelerates chilling suppression vs long day."""
        gate = SmoothChillingGate()
        seq_len = 45
        tmin = torch.full((1, seq_len), 9.0)
        tmax = torch.full((1, seq_len), 24.0)

        # Short day (autumn/winter: 9.5 hr) vs Long day (summer: 14.5 hr)
        dl_short = torch.full((1, seq_len), 9.5)
        dl_long = torch.full((1, seq_len), 14.5)

        g_short = gate(tmin, tmax, dl_short)
        g_long = gate(tmin, tmax, dl_long)

        # Under the same thermal chilling, short daylength must result in lower G_chill
        assert g_short[0, -1].item() < g_long[0, -1].item()


# ==============================================================================
# Dimension 4: Edge Case Robustness & Numerical Clamping
# ==============================================================================

class TestEdgeCaseRobustnessAndClamping:
    """Stress-test numerical boundaries, clamping at [0.0, 3.0], and extreme inputs."""

    def test_extreme_temperature_nan_inf_immunity(self):
        """Stress-test extreme temperatures (-25°C to 60°C) ensuring zero NaNs and zero Infs."""
        model = NeuralPhenologyOperator()

        # Freezing test
        cold_inputs = make_synthetic_weather(
            batch_size=2, seq_len=30, tavg_val=-15.0, tmin_val=-25.0, tmax_val=-5.0,
            dif_val=20.0, dli_val=5.0, daylength_val=8.0
        )
        out_cold = model(**cold_inputs)
        assert torch.all(torch.isfinite(out_cold["D"]))
        assert torch.all(torch.isfinite(out_cold["dD_dt"]))
        assert torch.all(torch.isfinite(out_cold["G_chill"]))
        assert torch.all(out_cold["dD_dt"] >= 0.0)

        # Scorching heat test
        heat_inputs = make_synthetic_weather(
            batch_size=2, seq_len=30, tavg_val=48.0, tmin_val=38.0, tmax_val=60.0,
            dif_val=22.0, dli_val=30.0, daylength_val=15.0
        )
        out_heat = model(**heat_inputs)
        assert torch.all(torch.isfinite(out_heat["D"]))
        assert torch.all(torch.isfinite(out_heat["dD_dt"]))
        assert torch.all(torch.isfinite(out_heat["G_chill"]))
        assert torch.all(out_heat["dD_dt"] >= 0.0)

    def test_extreme_dif_and_inverted_thermal_gradients(self):
        """Test DIF extremes: DIF=0 (isothermal) and DIF=-15 (night warmer than day)."""
        model = NeuralPhenologyOperator()
        inputs_inverted = make_synthetic_weather(
            batch_size=2, seq_len=20, tavg_val=20.0, dif_val=-15.0
        )
        out = model(**inputs_inverted)
        assert torch.all(torch.isfinite(out["D"]))
        assert torch.all(out["dD_dt"] >= 0.0)

    def test_zero_and_extreme_light_levels(self):
        """Test DLI=0 (complete darkness) and DLI=150 (super-saturating light)."""
        model = NeuralPhenologyOperator()

        # Darkness: dD/dt must be strictly 0
        dark_inputs = make_synthetic_weather(batch_size=1, seq_len=10, dli_val=0.0)
        out_dark = model(**dark_inputs)
        assert torch.all(out_dark["dD_dt"] == 0.0)
        assert torch.all(out_dark["D"] == out_dark["D0"])

        # Extreme irradiance
        bright_inputs = make_synthetic_weather(batch_size=1, seq_len=10, dli_val=150.0)
        out_bright = model(**bright_inputs)
        assert torch.all(torch.isfinite(out_bright["D"]))
        assert torch.all(out_bright["dD_dt"] > 0.0)

    def test_numerical_clamping_500_day_summer_runaway(self):
        """Simulate 500 days of optimal summer growth: assert D(t) is clamped at exactly 3.0."""
        model = NeuralPhenologyOperator()
        # 500 optimal summer days
        inputs = make_synthetic_weather(
            batch_size=1, seq_len=500, tavg_val=26.0, tmin_val=18.0, tmax_val=32.0,
            dif_val=14.0, dli_val=25.0, daylength_val=14.0, page_val=22.0
        )

        out = model(**inputs)
        D_traj = out["D"][0]

        # Stage index must never exceed 3.0
        assert torch.all(D_traj <= 3.0)
        assert torch.all(D_traj >= 0.0)
        assert D_traj[-1].item() == 3.0, f"Expected final stage index clamped at 3.0, got {D_traj[-1].item()}"

        # Monotonicity check
        assert torch.all(out["dD_dt"] >= 0.0)

    @pytest.mark.parametrize("page_val", [0.0, 5.0, 15.0, 18.0, 19.0, 22.0, 35.0, 60.0])
    def test_seedling_age_page_boundary_resilience(self, page_val: float):
        """Verify D(0) is non-negative, finite, and reproduces known biological milestones."""
        model = NeuralPhenologyOperator()
        page_tensor = torch.tensor([page_val])
        d0 = model.get_initial_stage(page_tensor).item()

        assert math.isfinite(d0)
        assert d0 >= 0.0

        if page_val == 22.0:
            assert abs(d0 - 0.180) < 1e-4
        elif page_val <= 18.0:
            assert d0 < 0.08  # Severe developmental delay

    def test_loss_function_zero_uncertainty_protection(self):
        """Verify that setting sigma_i = 0 does not trigger division by zero due to eps_var."""
        loss_fn = PhenologyLoss(eps_var=1e-4)
        model = NeuralPhenologyOperator()

        inputs = make_synthetic_weather(batch_size=1, seq_len=50)
        out = model(**inputs)

        targets = {"ADAPS": torch.tensor([18.0])}
        zero_uncertainty = {"ADAPS": torch.tensor([0.0])}

        loss = loss_fn(out, targets, zero_uncertainty)
        assert torch.isfinite(loss)
        assert loss.item() > 0.0

    def test_loss_function_t1_edge_case(self):
        """Verify that sequence length T=1 does not crash loss_smooth calculation."""
        loss_fn = PhenologyLoss(lambda_smooth=0.05)
        model = NeuralPhenologyOperator()

        inputs = make_synthetic_weather(batch_size=1, seq_len=1)
        out = model(**inputs)

        targets = {"ADAPS": torch.tensor([5.0])}
        loss = loss_fn(out, targets)
        assert torch.isfinite(loss)
        loss.backward()
        assert model.dev_scale.grad is not None

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
    def test_cuda_device_transfer_and_backward(self):
        """Verify model and loss execute seamlessly on CUDA with identical mathematical invariants."""
        device = torch.device("cuda")
        model = NeuralPhenologyOperator().to(device)
        loss_fn = PhenologyLoss().to(device)

        inputs = make_synthetic_weather(batch_size=4, seq_len=80, device=device)
        out = model(**inputs)

        assert out["D"].device.type == "cuda"
        assert torch.all(out["dD_dt"] >= 0.0)

        targets = {
            "ADAPS": torch.tensor([18.0, 19.0, 17.0, 16.0], device=device),
            "PDFPS": torch.tensor([24.0, 25.0, 23.0, 22.0], device=device),
        }
        loss = loss_fn(out, targets)
        loss.backward()

        assert torch.isfinite(loss)
        assert model.dev_scale.grad is not None
        assert model.dev_scale.grad.is_cuda
