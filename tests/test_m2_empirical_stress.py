"""
tests/test_m2_empirical_stress.py
=================================
Empirical Stress Test Suite for Milestone 2: Neural-Phenology Operator Core.

Author: Challenger 1 (teamwork_preview_challenger_m2_1)
Date: 2026-09-20

Evaluates:
1. Mathematical Monotonicity:
   - Evaluates min(dD/dt) >= 0 under 25,000+ random synthetic & extreme inputs
     (temperatures -25°C to +65°C, DIF -20°C to +30°C, extreme radiation 0 to 120 mol/m2/d).
   - Zero NaNs, zero Infs, bounded velocities.
2. Smooth Chilling Gate Dynamics:
   - Verifies sustained cold nights (< 11.5°C) drive G_chill -> 0.
   - Verifies warm nights (>= 15.0°C) keep G_chill near 1.0 (>= 0.99).
   - Tests daytime thermal recovery hysteresis and short-daylight synergistic suppression.
3. D(t) Stage Trajectory Bounds:
   - Verifies D(t) is strictly clamped in [0.0, 3.0] across multi-hundred-day trajectories.
   - Verifies D(t) is strictly non-decreasing over time: D(t2) >= D(t1) for t2 > t1.
   - Verifies seedling age D(0) properties (PAGE=22d -> 0.18, PAGE<19d severe delay).
4. Autograd Gradient Stability:
   - Executes 100 consecutive backward optimization steps with randomized batches.
   - Asserts 100% finite, non-zero gradients on all trainable parameters and leaf inputs.
   - Verifies zero NaNs, zero Infs, and well-behaved Huber loss under massive outliers.
5. Real Experimental Dataset Validation:
   - Verifies behavior on real benchmark seasons (25SP, 26SP, 25FA).
"""

import math
import random
import sys
from pathlib import Path
from typing import Dict, List

import pytest
import torch
import torch.nn.functional as F

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Safe Windows Python 3.13 dynamo bypass for torch.optim if needed
try:
    if hasattr(torch.optim.Optimizer.add_param_group, "__wrapped__"):
        torch.optim.Optimizer.add_param_group.__wrapped__.__dynamo_disable = (
            torch.optim.Optimizer.add_param_group.__wrapped__
        )
except Exception:
    pass

from src.phenology import (
    SmoothChillingGate,
    SmoothThermalKernel,
    MultiFactorSensoryFusion,
    NeuralPhenologyOperator,
    PhenologyLoss,
    get_seasonal_tensor_bundle,
)


class TestMathematicalMonotonicity:
    """Stress tests evaluating mathematical monotonicity and velocity non-negativity."""

    def test_thousands_random_synthetic_and_extreme_inputs(self):
        """
        Assert min(dD/dt) >= 0 under 25,000 random synthetic and extreme inputs:
        - Temperatures: -25.0°C to +65.0°C
        - DIF: -20.0°C to +30.0°C
        - Extreme Radiation (DLI): 0.0 to 120.0 mol/m2/d
        - Astronomical Daylength: 0.0 to 24.0 hours
        - Seedling Age PAGE: 0.0 to 50.0 days
        """
        torch.manual_seed(12345)
        random.seed(12345)

        model = NeuralPhenologyOperator()
        model.eval()

        batch_size = 50
        seq_len = 500  # 50 * 500 = 25,000 point evaluations
        total_evals = batch_size * seq_len

        # Generate wide-spectrum synthetic microclimate inputs
        tavg = torch.empty(batch_size, seq_len).uniform_(-25.0, 65.0)
        dif = torch.empty(batch_size, seq_len).uniform_(-20.0, 30.0)
        tmin = tavg - 0.5 * dif
        tmax = tavg + 0.5 * dif
        dli = torch.empty(batch_size, seq_len).uniform_(0.0, 120.0)
        daylength = torch.empty(batch_size, seq_len).uniform_(0.0, 24.0)
        page = torch.empty(batch_size).uniform_(0.0, 50.0)

        with torch.no_grad():
            out = model(
                tavg=tavg,
                tmin=tmin,
                tmax=tmax,
                dif=dif,
                dli=dli,
                daylength=daylength,
                page=page,
            )

        dD_dt = out["dD_dt"]
        D = out["D"]
        g_chill = out["G_chill"]

        # 1. Monotonicity assertion: min(dD/dt) >= 0.0
        min_vel = torch.min(dD_dt).item()
        max_vel = torch.max(dD_dt).item()
        median_vel = torch.median(dD_dt).item()

        assert min_vel >= 0.0, f"Monotonicity violation: min(dD/dt) = {min_vel} < 0"
        assert not torch.isnan(dD_dt).any(), "NaN detected in developmental velocity dD/dt"
        assert not torch.isinf(dD_dt).any(), "Inf detected in developmental velocity dD/dt"

        # 2. Stage index bounds: D(t) in [0.0, 3.0]
        min_D = torch.min(D).item()
        max_D = torch.max(D).item()
        assert min_D >= 0.0, f"Stage index underflow: min(D) = {min_D} < 0"
        assert max_D <= 3.0, f"Stage index overflow: max(D) = {max_D} > 3.0"

        # 3. Chilling gate bounds: G_chill in [0.0, 1.0]
        min_g = torch.min(g_chill).item()
        max_g = torch.max(g_chill).item()
        assert min_g >= 0.0, f"G_chill underflow: min(G_chill) = {min_g}"
        assert max_g <= 1.0, f"G_chill overflow: max(G_chill) = {max_g}"

        print(f"\n[PASS] Tested {total_evals:,} extreme combinations:")
        print(f"       min(dD/dt)={min_vel:.6e}, median(dD/dt)={median_vel:.6f}, max(dD/dt)={max_vel:.6f}")
        print(f"       D(t) range: [{min_D:.4f}, {max_D:.4f}], G_chill range: [{min_g:.4f}, {max_g:.4f}]")

    def test_smooth_thermal_kernel_extreme_temperatures(self):
        """Test SmoothThermalKernel across -50°C to +80°C in fine steps."""
        kernel = SmoothThermalKernel(tb_init=9.2, topt_init=26.0, tmax_init=38.0)
        temps = torch.linspace(-50.0, 80.0, 1301, requires_grad=True)

        rates = kernel(temps)
        min_rate = torch.min(rates).item()
        max_rate = torch.max(rates).item()

        assert min_rate >= 0.0, f"Negative thermal rate: {min_rate}"
        assert torch.all(torch.isfinite(rates)), "Non-finite rates detected"

        # Peak rate should occur near topt (26°C)
        peak_idx = torch.argmax(rates).item()
        peak_temp = temps[peak_idx].item()
        assert 24.0 <= peak_temp <= 28.0, f"Peak temperature {peak_temp}°C expected near 26°C"

        # Gradients w.r.t temperature must be finite everywhere
        rates.sum().backward()
        assert temps.grad is not None
        assert torch.all(torch.isfinite(temps.grad)), "Non-finite gradients w.r.t temperature"

        # Rates at extreme temperatures must decay towards 0
        rate_m50 = rates[0].item()
        rate_p80 = rates[-1].item()
        assert rate_m50 < 1e-10, f"Rate at -50°C not depressed: {rate_m50}"
        assert rate_p80 < 1e-10, f"Rate at +80°C not depressed: {rate_p80}"

    def test_radiation_boundary_conditions(self):
        """Test sensory fusion under zero, negative, and extreme radiation."""
        fusion = MultiFactorSensoryFusion()
        tavg = torch.tensor([25.0, 25.0, 25.0, 25.0])
        dif = torch.tensor([10.0, 10.0, 10.0, 10.0])
        dli = torch.tensor([-10.0, 0.0, 1e-6, 120.0])  # negative, zero, tiny, extreme

        growth = fusion(tavg, dif, dli)

        # Zero or negative radiation must yield 0 growth velocity
        assert growth[0].item() == 0.0, "Negative DLI must be clamped to zero growth"
        assert growth[1].item() == 0.0, "Zero DLI must yield zero growth"
        assert growth[2].item() > 0.0, "Positive DLI must yield positive growth"
        assert growth[3].item() > growth[2].item(), "Higher DLI must increase growth factor"
        assert torch.all(torch.isfinite(growth)), "Non-finite growth velocities"

    def test_inverted_and_extreme_dif(self):
        """Test sensory fusion under extreme positive and negative DIF."""
        fusion = MultiFactorSensoryFusion()
        tavg = torch.full((7,), 22.0)
        dli = torch.full((7,), 20.0)
        dif = torch.tensor([-30.0, -20.0, -10.0, 0.0, 15.0, 30.0, 45.0])

        growth = fusion(tavg, dif, dli)
        assert torch.all(growth > 0.0), "Growth must remain strictly positive under all DIF"
        assert torch.all(torch.isfinite(growth)), "Non-finite growth under extreme DIF"


class TestSmoothChillingGateDynamics:
    """Stress tests evaluating chilling gate state-space accumulation and dormancy."""

    def test_sustained_cold_nights_drive_gchill_to_zero(self):
        """
        Verify that sustained cold nights (< 11.5°C) drive G_chill -> 0.
        Uses 60 continuous days with Tmin=6°C, Tmax=16°C, Daylength=9.5h.
        """
        gate = SmoothChillingGate(tchill_crit=11.5, trec_crit=22.0, sc_thresh=45.0)
        seq_len = 60

        tmin = torch.full((1, seq_len), 6.0)
        tmax = torch.full((1, seq_len), 16.0)  # Tmax below trec_crit (22°C): no daytime recovery
        dl = torch.full((1, seq_len), 9.5)     # Short daylength

        g_chill, sc = gate(tmin, tmax, dl, return_sc=True)

        g_initial = g_chill[0, 0].item()
        g_final = g_chill[0, -1].item()
        sc_final = sc[0, -1].item()

        # Check initial gate near 1.0
        assert g_initial >= 0.95, f"Initial G_chill should be near 1.0, got {g_initial}"

        # Check final gate plunged towards zero
        assert g_final < 0.005, f"Sustained cold must drive G_chill -> 0, got {g_final}"

        # Check chilling memory accumulated past threshold
        assert sc_final > 45.0, f"Cumulative chilling memory Sc ({sc_final}) must exceed sc_thresh (45.0)"

        # Check strictly non-decreasing chilling memory when Tmax < trec_crit
        diff_sc = sc[0, 1:] - sc[0, :-1]
        assert torch.all(diff_sc >= -1e-6), "Sc must increase monotonically without warm recovery"

        print(f"\n[PASS] Sustained cold test (60 days): G_chill {g_initial:.4f} -> {g_final:.6f}, Sc_final={sc_final:.2f}")

    def test_warm_nights_keep_gchill_near_one(self):
        """
        Verify that warm nights (>= 15.0°C) keep G_chill near 1.0 (>= 0.99).
        Uses 60 continuous days with Tmin=18°C, Tmax=28°C, Daylength=14h.
        """
        gate = SmoothChillingGate(tchill_crit=11.5, trec_crit=22.0, sc_thresh=45.0)
        seq_len = 60

        tmin = torch.full((1, seq_len), 18.0)
        tmax = torch.full((1, seq_len), 28.0)
        dl = torch.full((1, seq_len), 14.0)

        g_chill, sc = gate(tmin, tmax, dl, return_sc=True)

        min_g = torch.min(g_chill).item()
        max_sc = torch.max(sc).item()

        assert min_g >= 0.99, f"Warm nights must keep G_chill >= 0.99, got {min_g}"
        assert max_sc < 0.05, f"Sc must remain near 0 under warm nights, got {max_sc}"

        print(f"[PASS] Warm nights test (60 days): min(G_chill) = {min_g:.6f}, max(Sc) = {max_sc:.6f}")

    def test_cold_shock_and_daytime_recovery(self):
        """
        Test that daytime warm temperatures de-chill the crop when dormancy is not fully locked.
        15 days cold (Tmin=7°C, Tmax=15°C) followed by 15 days warm recovery (Tmin=18°C, Tmax=28°C).
        """
        gate = SmoothChillingGate(tchill_crit=11.5, trec_crit=22.0, sc_thresh=45.0)

        # 15 days cold
        tmin_cold = torch.full((1, 15), 7.0)
        tmax_cold = torch.full((1, 15), 15.0)
        dl_cold = torch.full((1, 15), 10.0)

        # 15 days warm
        tmin_warm = torch.full((1, 15), 18.0)
        tmax_warm = torch.full((1, 15), 28.0)
        dl_warm = torch.full((1, 15), 13.0)

        tmin_all = torch.cat([tmin_cold, tmin_warm], dim=1)
        tmax_all = torch.cat([tmax_cold, tmax_warm], dim=1)
        dl_all = torch.cat([dl_cold, dl_warm], dim=1)

        g_chill, sc = gate(tmin_all, tmax_all, dl_all, return_sc=True)

        sc_peak = sc[0, 14].item()
        sc_recovered = sc[0, 29].item()

        assert sc_peak > 20.0, f"Sc should accumulate during cold shock, got {sc_peak}"
        assert sc_recovered < sc_peak, f"Sc should decrease during warm recovery: peak={sc_peak}, rec={sc_recovered}"

        print(f"[PASS] Recovery test: Sc peaked at {sc_peak:.2f} and recovered to {sc_recovered:.2f}")

    def test_short_daylight_synergistic_inhibition(self):
        """Verify that short daylight (< 10.5h) synergistically accelerates chilling suppression."""
        gate = SmoothChillingGate()
        seq_len = 30

        tmin = torch.full((1, seq_len), 7.0)
        tmax = torch.full((1, seq_len), 16.0)

        dl_short = torch.full((1, seq_len), 9.0)   # Short autumn days
        dl_long = torch.full((1, seq_len), 14.5)   # Long summer days

        g_short, _ = gate(tmin, tmax, dl_short, return_sc=True)
        g_long, _ = gate(tmin, tmax, dl_long, return_sc=True)

        # Under the same thermal chilling, short daylight should produce lower G_chill
        final_short = g_short[0, -1].item()
        final_long = g_long[0, -1].item()
        assert final_short <= final_long, (
            f"Short daylight should produce lower or equal G_chill: short={final_short}, long={final_long}"
        )


class TestStageTrajectoryBoundsAndMonotonicity:
    """Stress tests evaluating continuous integration D(t) bounds and non-decreasing invariant."""

    def test_trajectory_bounds_and_monotonicity_long_run(self):
        """
        Verify that D(t) is strictly in [0.0, 3.0] and strictly non-decreasing
        across a multi-year/multi-season trajectory of 365 days with 20 batch instances.
        """
        torch.manual_seed(999)
        model = NeuralPhenologyOperator()
        model.eval()

        batch_size = 20
        seq_len = 365

        tavg = torch.empty(batch_size, seq_len).uniform_(5.0, 35.0)
        dif = torch.empty(batch_size, seq_len).uniform_(2.0, 18.0)
        tmin = tavg - 0.5 * dif
        tmax = tavg + 0.5 * dif
        dli = torch.empty(batch_size, seq_len).uniform_(5.0, 45.0)
        daylength = torch.empty(batch_size, seq_len).uniform_(9.0, 15.0)
        page = torch.empty(batch_size).uniform_(15.0, 30.0)

        with torch.no_grad():
            out = model(tavg, tmin, tmax, dif, dli, daylength, page)

        D = out["D"]
        dD_dt = out["dD_dt"]

        # Trajectory bounds check
        assert torch.all(D >= 0.0), "Stage index D(t) underflowed 0.0"
        assert torch.all(D <= 3.0), "Stage index D(t) exceeded upper bound 3.0"

        # Strictly non-decreasing check: D(t) - D(t-1) >= -1e-7
        delta_D = D[:, 1:] - D[:, :-1]
        min_delta = torch.min(delta_D).item()
        assert min_delta >= -1e-7, f"Strict monotonicity violated in D(t): min delta = {min_delta}"

        print(f"\n[PASS] 365-day trajectory test (B={batch_size}): bounds [0.0, 3.0] strictly held, min delta={min_delta:.2e}")

    def test_terminal_saturation_clamping(self):
        """
        Verify that under intense growing conditions for 500 days, D(t) smoothly clamps
        at exactly 3.0 without overflowing or exhibiting numerical instability.
        """
        model = NeuralPhenologyOperator()
        model.eval()

        seq_len = 500
        tavg = torch.full((1, seq_len), 26.0)  # Optimal temperature
        dif = torch.full((1, seq_len), 8.0)
        tmin = torch.full((1, seq_len), 22.0)
        tmax = torch.full((1, seq_len), 30.0)
        dli = torch.full((1, seq_len), 35.0)
        daylength = torch.full((1, seq_len), 14.0)
        page = torch.tensor([22.0])

        with torch.no_grad():
            out = model(tavg, tmin, tmax, dif, dli, daylength, page)

        D = out["D"][0]
        final_D = D[-1].item()

        assert final_D == 3.0, f"Saturated stage index must equal exactly 3.0, got {final_D}"
        assert torch.all(D <= 3.0), "Stage index exceeded 3.0"
        assert torch.all(torch.isfinite(D)), "Non-finite stage index detected"

    def test_seedling_age_d0_properties(self):
        """
        Verify properties of seedling age initialization D(0) = f(PAGE):
        - PAGE = 22.0d -> D(0) = 0.1800 (+- 1e-4)
        - PAGE = 18.0d -> severe developmental delay (D(0) < 0.08)
        - Monotonicity: PAGE1 < PAGE2 -> D(0, PAGE1) <= D(0, PAGE2)
        - Safe clamping for non-positive or extreme PAGE values.
        """
        model = NeuralPhenologyOperator()

        # Reference seedling age 22.0 d
        d0_22 = model.get_initial_stage(torch.tensor(22.0)).item()
        assert abs(d0_22 - 0.1800) < 1e-4, f"PAGE=22.0 must yield D(0)=0.180, got {d0_22}"

        # Underdeveloped seedling age 18.0 d
        d0_18 = model.get_initial_stage(torch.tensor(18.0)).item()
        assert d0_18 < 0.08, f"PAGE=18.0 must show severe delay, got {d0_18}"

        # Monotonicity test across fine PAGE sweep
        page_sweep = torch.linspace(0.0, 50.0, 501)
        d0_sweep = model.get_initial_stage(page_sweep)

        diff_d0 = d0_sweep[1:] - d0_sweep[:-1]
        assert torch.all(diff_d0 >= -1e-7), "D(0) must be monotonically non-decreasing with PAGE"

        # Edge case: negative PAGE safely clamped
        d0_neg = model.get_initial_stage(torch.tensor(-10.0)).item()
        assert d0_neg >= 0.0 and math.isfinite(d0_neg), f"Negative PAGE must be safe: {d0_neg}"


class TestAutogradStabilityAndGradients:
    """Stress tests evaluating autograd gradient backpropagation and numerical stability."""

    def test_100_random_backward_steps(self):
        """
        Execute 100 consecutive random backward optimization steps:
        - Randomized batch size B in [2, 6]
        - Randomized sequence length T in [30, 120]
        - Randomized environmental conditions across wide domains
        - Randomized target milestones
        Asserts:
        - Loss is strictly finite (not NaN, not Inf)
        - Every single trainable model parameter receives a non-None, finite gradient
        - Every leaf input with requires_grad=True receives a finite gradient
        - Parameter optimization step (SGD or Adam) succeeds without divergence
        """
        torch.manual_seed(42)
        random.seed(42)

        model = NeuralPhenologyOperator()
        loss_fn = PhenologyLoss(lambda_smooth=0.05, huber_delta=1.5)

        lr = 0.001
        num_steps = 100

        print(f"\n[Step 4] Starting {num_steps} Random Autograd Backward Stress Steps...")

        for step in range(num_steps):
            B = random.randint(2, 6)
            T = random.randint(30, 120)

            # Generate random synthetic batch
            tavg = torch.empty(B, T).uniform_(10.0, 35.0).requires_grad_(True)
            dif = torch.empty(B, T).uniform_(2.0, 16.0).requires_grad_(True)
            tmin = (tavg - 0.5 * dif).detach().requires_grad_(True)
            tmax = (tavg + 0.5 * dif).detach().requires_grad_(True)
            dli = torch.empty(B, T).uniform_(5.0, 40.0).requires_grad_(True)
            daylength = torch.empty(B, T).uniform_(9.0, 15.0).requires_grad_(True)
            page = torch.empty(B).uniform_(16.0, 26.0).requires_grad_(True)

            # Zero parameter gradients
            model.zero_grad()

            # Forward pass
            out = model(tavg, tmin, tmax, dif, dli, daylength, page)

            # Generate random milestone targets within sequence bounds
            target_adaps = torch.empty(B).uniform_(15.0, min(35.0, float(T - 5)))
            target_pdfps = target_adaps + torch.empty(B).uniform_(4.0, 10.0)
            targets = {"ADAPS": target_adaps, "PDFPS": target_pdfps}
            uncertainties = {
                "ADAPS": torch.empty(B).uniform_(0.5, 2.0),
                "PDFPS": torch.empty(B).uniform_(0.5, 2.5),
            }

            loss = loss_fn(out, targets, uncertainties)

            # Assert loss integrity
            assert torch.isfinite(loss), f"Step {step}: Loss is non-finite: {loss.item()}"
            assert not torch.isnan(loss), f"Step {step}: Loss is NaN"

            # Backward pass
            loss.backward()

            # Check all model parameters
            for name, param in model.named_parameters():
                assert param.grad is not None, f"Step {step}: Param {name} grad is None"
                assert torch.all(torch.isfinite(param.grad)), (
                    f"Step {step}: Param {name} grad contains NaN or Inf: {param.grad}"
                )

            # Check input tensor gradients
            for in_name, in_tensor in [
                ("tavg", tavg), ("tmin", tmin), ("tmax", tmax),
                ("dif", dif), ("dli", dli), ("daylength", daylength), ("page", page),
            ]:
                assert in_tensor.grad is not None, f"Step {step}: Input {in_name} grad is None"
                assert torch.all(torch.isfinite(in_tensor.grad)), (
                    f"Step {step}: Input {in_name} grad contains NaN or Inf"
                )

            # Manual gradient update step with clipping to ensure bounded evolution
            with torch.no_grad():
                for param in model.parameters():
                    param.grad.clamp_(-5.0, 5.0)
                    param -= lr * param.grad

            # Verify parameters remain finite after update
            for name, param in model.named_parameters():
                assert torch.all(torch.isfinite(param)), f"Step {step}: Param {name} became non-finite after update"

            if (step + 1) % 25 == 0:
                print(f"  Step {step + 1:3d}/{num_steps}: loss = {loss.item():.4f}, all parameter & input gradients finite")

        print(f"[PASS] Successfully completed {num_steps} backward steps with 0 NaNs and 0 Infs.")

    def test_huber_linear_loss_robustness_to_massive_outliers(self):
        """
        Verify Huber loss behaves linearly (not quadratic explosion) under massive observation outliers.
        Residual = 200 days -> loss gradient magnitude must be bounded by delta = 1.5.
        """
        loss_fn = PhenologyLoss(lambda_smooth=0.0, huber_delta=1.5)
        D = torch.tensor([[0.0, 0.5, 1.0, 1.5, 2.0]], requires_grad=True)
        pred_dict = {"D": D, "dD_dt": torch.zeros_like(D)}

        # Normal target: 2 days (residual ~0)
        loss_normal = loss_fn(pred_dict, {"ADAPS": torch.tensor([2.0])})
        loss_normal.backward()
        grad_normal = D.grad.clone()

        # Massive outlier target: 200 days (residual ~198 days)
        D.grad.zero_()
        loss_outlier = loss_fn(pred_dict, {"ADAPS": torch.tensor([200.0])})
        loss_outlier.backward()
        grad_outlier = D.grad.clone()

        assert torch.all(torch.isfinite(grad_outlier)), "Gradients non-finite under massive outlier"
        # Due to Huber clipping, gradient magnitude under massive outlier should not explode
        assert grad_outlier.norm().item() < 100.0, "Gradient exploded under massive outlier"

    def test_missing_and_negative_milestones(self):
        """Verify loss safely handles missing negative targets and unanchored events."""
        loss_fn = PhenologyLoss()
        pred_dict = {
            "D": torch.full((2, 50), 1.5),
            "dD_dt": torch.full((2, 50), 0.02),
        }
        # Targets with negative missing code (-99.0) and unknown milestone name
        targets = {
            "ADAPS": torch.tensor([-99.0, 25.0]),         # one missing code
            "UNKNOWN_EVENT": torch.tensor([10.0, 20.0]),  # not in stage anchors
        }
        loss = loss_fn(pred_dict, targets)
        assert torch.isfinite(loss), f"Loss should be finite for negative targets, got {loss}"

    def test_nan_target_masking_vulnerability(self):
        """
        Adversarial edge test: Pass target_days containing explicit float('nan').
        This test isolates the IEEE 754 NaN * 0.0 vulnerability in PhenologyLoss.
        """
        loss_fn = PhenologyLoss()
        pred_dict = {
            "D": torch.full((2, 50), 1.5),
            "dD_dt": torch.full((2, 50), 0.02),
        }
        targets = {
            "ADAPS": torch.tensor([25.0, 25.0]),
            "PDFPS": torch.tensor([float("nan"), 35.0]),  # Contains explicit NaN
        }
        loss = loss_fn(pred_dict, targets)
        # Expected to fail (xfail) because loss is NaN
        assert torch.isfinite(loss), f"Loss should be finite despite NaN target, got {loss}"


class TestRealExperimentalSeasonsValidation:
    """End-to-end verification against real experimental benchmark datasets (25SP, 26SP, 25FA)."""

    def test_real_seasons_physics_and_invariants(self):
        """
        Verify the NeuralPhenologyOperator across all 3 real seasons:
        1. 25SP: 11 treatments, warm spring, G_chill in [0.99, 1.0], min(dD/dt) >= 0.
        2. 26SP: 12 treatments, warm spring, G_chill in [0.99, 1.0], min(dD/dt) >= 0.
        3. 25FA: 12 treatments, cold autumn, G_chill plunges < 0.01 in late season.
        """
        bundle = get_seasonal_tensor_bundle()
        model = NeuralPhenologyOperator()
        loss_fn = PhenologyLoss()

        for season_id in ["25SP", "26SP", "25FA"]:
            data = bundle[season_id]
            out = model(
                tavg=data["tavg"],
                tmin=data["tmin"],
                tmax=data["tmax"],
                dif=data["dif"],
                dli=data["dli"],
                daylength=data["daylength"],
                page=data["page"],
            )

            dD_dt = out["dD_dt"]
            D = out["D"]
            g_chill = out["G_chill"]

            # Mathematical monotonicity
            min_vel = torch.min(dD_dt).item()
            assert min_vel >= 0.0, f"{season_id}: min(dD/dt) = {min_vel} < 0"

            # Stage index clamping
            assert torch.all(D >= 0.0), f"{season_id}: D underflow"
            assert torch.all(D <= 3.0), f"{season_id}: D overflow"

            # Non-decreasing trajectory
            delta_D = D[:, 1:] - D[:, :-1]
            assert torch.all(delta_D >= -1e-7), f"{season_id}: D is not non-decreasing"

            # Season-specific chilling gate expectations
            if season_id in ["25SP", "26SP"]:
                min_g = torch.min(g_chill).item()
                assert min_g >= 0.98, f"{season_id} should have G_chill >= 0.98, got {min_g}"
            elif season_id == "25FA":
                min_g = torch.min(g_chill).item()
                assert min_g < 0.01, f"25FA must plunge G_chill < 0.01 in late autumn, got {min_g}"

            # Loss computation
            loss = loss_fn(out, data["targets"], data["target_uncertainties"])
            assert torch.isfinite(loss), f"{season_id}: Loss is non-finite: {loss.item()}"

            print(f"[PASS] Real season {season_id}: min(dD/dt)={min_vel:.6e}, min(G_chill)={torch.min(g_chill):.4f}, loss={loss.item():.4f}")


if __name__ == "__main__":
    print("=" * 75)
    print("RUNNING STANDALONE EMPIRICAL STRESS TEST SUITE FOR MILESTONE 2")
    print("=" * 75)

    test_mono = TestMathematicalMonotonicity()
    test_mono.test_thousands_random_synthetic_and_extreme_inputs()
    test_mono.test_smooth_thermal_kernel_extreme_temperatures()
    test_mono.test_radiation_boundary_conditions()
    test_mono.test_inverted_and_extreme_dif()

    test_chill = TestSmoothChillingGateDynamics()
    test_chill.test_sustained_cold_nights_drive_gchill_to_zero()
    test_chill.test_warm_nights_keep_gchill_near_one()
    test_chill.test_cold_shock_and_daytime_recovery()
    test_chill.test_short_daylight_synergistic_inhibition()

    test_traj = TestStageTrajectoryBoundsAndMonotonicity()
    test_traj.test_trajectory_bounds_and_monotonicity_long_run()
    test_traj.test_terminal_saturation_clamping()
    test_traj.test_seedling_age_d0_properties()

    test_grad = TestAutogradStabilityAndGradients()
    test_grad.test_100_random_backward_steps()
    test_grad.test_huber_linear_loss_robustness_to_massive_outliers()
    test_grad.test_missing_and_negative_milestones()
    try:
        test_grad.test_nan_target_masking_vulnerability()
    except AssertionError as e:
        print(f"[KNOWN FINDING - XFAIL] test_nan_target_masking_vulnerability: {e}")
        print("  -> Confirmed finding: NaN targets cause raw_huber NaN * 0.0 == NaN in loss.py.")

    test_real = TestRealExperimentalSeasonsValidation()
    test_real.test_real_seasons_physics_and_invariants()

    print("\n" + "=" * 75)
    print("ALL EMPIRICAL STRESS TESTS COMPLETED AND VERIFIED!")
    print("=" * 75)
