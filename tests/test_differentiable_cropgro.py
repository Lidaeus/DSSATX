"""
Test & Benchmark Suite for Differentiable CROPGRO (Diff-CROPGRO)
================================================================
Phase 1.5 — validates mechanism-fidelity fixes:
  1. Smooth operator mathematical properties (continuity, bounds, gradients);
  2. Nonlinear photosynthesis saturation behavior;
  3. LAI ↔ leaf biomass bidirectional conservation under senescence;
  4. Forward simulation stability under extreme conditions;
  5. Autograd gradient propagation through all 14 parameters;
  6. Gradient-based calibration convergence on synthetic twin experiment.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))

import torch

from src.differentiable.diff_cropgro_core import DifferentiableCROPGRO
from src.differentiable.adjoint_inversion import AutogradCalibrationEngine
from src.differentiable.smooth_operators import (
    bounded_param,
    inverse_bounded_param,
    smooth_cardinal_temperature,
    smooth_gate,
    soft_positive,
)


# =====================================================================
# Test 1: Smooth operator mathematical properties
# =====================================================================
def test_smooth_operators():
    """Verify smooth operator continuity, boundary behavior, and differentiability."""
    T = torch.linspace(5.0, 45.0, 200, requires_grad=True)
    tb = torch.tensor(8.58)
    to1 = torch.tensor(25.0)
    to2 = torch.tensor(30.0)
    tm = torch.tensor(40.0)

    resp = smooth_cardinal_temperature(T, tb, to1, to2, tm, beta=3.0)

    # Range check: response must be in [0, 1]
    assert resp.min() >= 0.0, f"Response min {resp.min():.4f} < 0"
    assert resp.max() <= 1.0, f"Response max {resp.max():.4f} > 1"

    # Below base temperature should yield near zero
    below_base = resp[T.data < 7.0]
    assert below_base.max().item() < 0.05, f"Response below TB = {below_base.max():.3f}, expected < 0.05"

    # Above ceiling temperature should yield near zero
    above_ceil = resp[T.data > 41.0]
    assert above_ceil.max().item() < 0.05, f"Response above TM = {above_ceil.max():.3f}, expected < 0.05"

    # Optimum range [TO1, TO2] should yield near 1.0
    opt_mask = (T.data >= 25.0) & (T.data <= 30.0)
    assert resp[opt_mask].mean().item() > 0.90, "Optimum range mean < 0.90"

    # Gradient must exist everywhere (no dead zones)
    loss = resp.sum()
    loss.backward()
    assert T.grad is not None, "Gradient w.r.t. temperature is None"
    assert torch.isfinite(T.grad).all(), "Gradient contains non-finite values"

    # soft_positive: verify gradient is nonzero near the floor
    x = torch.tensor([-1.0, 0.0, 0.005, 0.02, 1.0], requires_grad=True)
    y = soft_positive(x, floor=0.01)
    y.sum().backward()
    assert (x.grad > 0).all(), f"soft_positive gradient has zeros: {x.grad}"
    assert (y >= 0.01).all(), f"soft_positive output below floor: {y}"

    # bounded_param ↔ inverse_bounded_param roundtrip
    for val in [8.1, 8.58, 9.4]:
        raw = inverse_bounded_param(val, 8.0, 9.5)
        recovered = bounded_param(torch.tensor(raw), 8.0, 9.5).item()
        assert abs(recovered - val) < 0.01, f"Roundtrip error: {val} → {recovered}"

    print("  PASS: test_smooth_operators")


# =====================================================================
# Test 2: Nonlinear photosynthesis saturation
# =====================================================================
def test_photosynthesis_saturation():
    """
    Verify the photosynthesis model exhibits light saturation (FIX P1).
    At high LAI, additional LAI should yield diminishing PG returns.
    """
    model = DifferentiableCROPGRO()
    params = model.get_physical_params()

    # Create two scenarios: LAI=2.0 vs LAI=6.0, same weather
    weather = torch.tensor([[25.0, 18.0, 13.0]])  # warm, high radiation
    stress = torch.tensor([[1.0, 1.0]])             # no stress

    state_low_lai = torch.tensor([[2.0, 100.0, 50.0, 30.0, 0.0, 0.0, 1.2]])
    state_high_lai = torch.tensor([[6.0, 300.0, 150.0, 90.0, 0.0, 0.0, 1.2]])

    next_low = model.forward_step(state_low_lai, weather, stress, params)
    next_high = model.forward_step(state_high_lai, weather, stress, params)

    # At LAI=6, light interception ≈ 95% → marginal PG gain over LAI=2 (~75%) should be small
    # Total biomass increment = sum of organ increments
    dw_low = (next_low[0, 1:5] - state_low_lai[0, 1:5]).sum().item()
    dw_high = (next_high[0, 1:5] - state_high_lai[0, 1:5]).sum().item()

    # High LAI should NOT give proportionally 3× more growth (that would be linear RUE)
    ratio = dw_high / max(dw_low, 1e-6)
    assert ratio < 2.0, (
        f"Biomass growth ratio (LAI=6 / LAI=2) = {ratio:.2f}; "
        f"expected < 2.0 for saturating photosynthesis (linear RUE would give ~3×)"
    )
    assert ratio > 1.0, f"High LAI should still grow more than low LAI, ratio = {ratio:.2f}"

    print(f"  PASS: test_photosynthesis_saturation (growth ratio LAI6/LAI2 = {ratio:.2f})")


# =====================================================================
# Test 3: LAI ↔ leaf biomass conservation under senescence
# =====================================================================
def test_lai_biomass_conservation():
    """
    Verify that senescence reduces BOTH LAI and W_L proportionally (FIX P2).
    Under sustained stress, W_L must decrease — not only increase.
    """
    model = DifferentiableCROPGRO()
    params = model.get_physical_params()

    # Simulate 30 days of severe nitrogen stress on a mature canopy
    n_days = 30
    weather = torch.tensor([[22.0, 14.0, 12.0]]).repeat(1, n_days, 1)
    stress = torch.tensor([[1.0, 0.3]]).repeat(1, n_days, 1)   # severe N stress

    # Start with large established canopy
    init_states = torch.tensor([[4.5, 250.0, 150.0, 80.0, 50.0, 100.0, 1.8]])

    states_traj, _ = model.simulate(weather, stress, init_states=init_states)

    initial_wl = states_traj[0, 0, 1].item()
    final_wl = states_traj[0, -1, 1].item()
    initial_lai = states_traj[0, 0, 0].item()
    final_lai = states_traj[0, -1, 0].item()

    # Under severe N stress for 30 days, both LAI and W_L should decrease
    assert final_lai < initial_lai, (
        f"LAI should decrease under stress: {initial_lai:.2f} → {final_lai:.2f}"
    )
    assert final_wl < initial_wl, (
        f"W_L should decrease under stress (FIX P2): {initial_wl:.1f} → {final_wl:.1f}; "
        f"old code had W_L only increasing"
    )

    # SLA consistency: LAI/W_L ratio should remain in physiologically reasonable range
    final_sla = (final_lai * 10000.0) / max(final_wl, 0.1)  # cm2/g
    assert 80.0 < final_sla < 400.0, f"SLA = {final_sla:.1f} cm2/g is physiologically unreasonable"

    print(f"  PASS: test_lai_biomass_conservation "
          f"(LAI: {initial_lai:.2f}->{final_lai:.2f}, W_L: {initial_wl:.0f}->{final_wl:.0f} g/m2)")


# =====================================================================
# Test 4: Robustness under extreme conditions
# =====================================================================
def test_extreme_conditions():
    """
    Model must remain numerically stable (no NaN, no explosion) under:
    - Zero radiation (continuous overcast)
    - Temperature below base temp (cold snap)
    - Simultaneous water + N stress
    """
    model = DifferentiableCROPGRO()
    n_days = 60

    # Extreme scenario: 3°C (below TB), zero radiation, full stress
    weather_extreme = torch.tensor([[3.0, 0.0, 8.0]]).repeat(1, n_days, 1)
    stress_extreme = torch.tensor([[0.1, 0.1]]).repeat(1, n_days, 1)

    states, yields = model.simulate(weather_extreme, stress_extreme)

    assert torch.isfinite(states).all(), "States contain NaN or Inf under extreme conditions"
    assert (states[:, :, :6] >= 0.0).all(), "Negative biomass/LAI detected"
    # Yield should be near zero under these conditions
    assert yields[0, -1].item() < 5000.0, "Unrealistic yield under extreme cold + zero radiation"

    print("  PASS: test_extreme_conditions (no NaN/Inf under extreme stress)")


# =====================================================================
# Test 5: Autograd gradient propagation through all parameters
# =====================================================================
def test_autograd_all_parameters():
    """Every learnable parameter must receive a finite, non-None gradient."""
    batch_size = 4
    n_days = 60

    torch.manual_seed(42)
    t_avg = 18.0 + 8.0 * torch.sin(torch.linspace(0, 3.14, n_days)).unsqueeze(0).repeat(batch_size, 1)
    srad = 14.0 + 4.0 * torch.rand(batch_size, n_days)
    daylength = 13.0 * torch.ones(batch_size, n_days)
    weather_seq = torch.stack([t_avg, srad, daylength], dim=-1)

    swfac = torch.tensor([1.0, 0.65, 1.0, 0.60]).unsqueeze(1).repeat(1, n_days)
    nstres = torch.tensor([1.0, 1.0, 0.55, 0.50]).unsqueeze(1).repeat(1, n_days)
    stress_seq = torch.stack([swfac, nstres], dim=-1)

    model = DifferentiableCROPGRO()
    states_traj, fresh_yield = model.simulate(weather_seq, stress_seq)

    # Water-nitrogen response check
    final_yield = fresh_yield[:, -1]
    assert final_yield[0] > final_yield[1], "W3N3 should exceed W1N3"
    assert final_yield[0] > final_yield[2], "W3N3 should exceed W3N0"

    # Gradient check on ALL parameters
    loss = fresh_yield.mean()
    loss.backward()

    no_grad_params = []
    for name, param in model.raw_params.items():
        if param.grad is None:
            no_grad_params.append(name)
        else:
            assert torch.isfinite(param.grad).all(), f"Gradient for {name} is non-finite"

    assert len(no_grad_params) == 0, (
        f"Parameters with no gradient: {no_grad_params}. "
        f"All {len(model.PARAM_BOUNDS)} parameters must receive gradients."
    )

    print(f"  PASS: test_autograd_all_parameters ({len(model.PARAM_BOUNDS)} params, all gradients OK)")


# =====================================================================
# Test 6: Synthetic twin experiment — gradient calibration convergence
# =====================================================================
def test_gradient_calibration_convergence():
    """
    Synthetic twin experiment: generate 'true' observations from one parameter set,
    then recover it from a perturbed starting point using gradient descent.

    NOTE ON BENCHMARK FAIRNESS (FIX P6):
    This test uses a simplified model (14 params, 2 treatments, exogenous stress,
    80 days, synthetic data). It demonstrates that autograd gradients converge
    correctly — NOT that this is directly comparable to PEST++ IES calibrating
    70 parameters on 13 treatments with fully coupled water-soil-crop dynamics
    and real field observations. Speedup claims should not be extrapolated.
    """
    batch_size = 2
    n_days = 80

    t_avg = 22.0 * torch.ones(batch_size, n_days)
    srad = 16.0 * torch.ones(batch_size, n_days)
    daylength = 12.5 * torch.ones(batch_size, n_days)
    weather_seq = torch.stack([t_avg, srad, daylength], dim=-1)

    swfac = torch.tensor([1.0, 0.70]).unsqueeze(1).repeat(1, n_days)
    nstres = torch.tensor([1.0, 0.75]).unsqueeze(1).repeat(1, n_days)
    stress_seq = torch.stack([swfac, nstres], dim=-1)

    # "True" model
    true_params = {"tb1": 8.80, "lfmax": 2.20, "slavr": 195.0, "xfrt": 0.880}
    true_model = DifferentiableCROPGRO(init_params=true_params)
    with torch.no_grad():
        true_states, true_yield = true_model.simulate(weather_seq, stress_seq)

    obs_days = torch.tensor([40, 60, 80])
    obs_targets = {
        "fresh_yield": (obs_days, true_yield[:, obs_days], 1.0),
        "lai": (obs_days, true_states[:, obs_days, 0], 0.5),
    }

    # Perturbed model to calibrate
    perturbed_params = {"tb1": 9.30, "lfmax": 1.40, "slavr": 140.0, "xfrt": 0.780}
    calib_model = DifferentiableCROPGRO(init_params=perturbed_params)
    engine = AutogradCalibrationEngine(calib_model, learning_rate=0.08)

    start_t = time.time()
    res = engine.calibrate(weather_seq, stress_seq, obs_targets, max_epochs=50, verbose=False)
    elapsed = time.time() - start_t

    initial_loss = res["loss_history"][0]
    final_loss = res["best_loss"]
    loss_reduction = (initial_loss - final_loss) / max(initial_loss, 1e-8)

    # Convergence criterion: ≥80% loss reduction
    assert loss_reduction > 0.80, f"Loss reduction {loss_reduction:.1%} is below 80%"

    # Timing: synthetic twin with 14 params should complete well under 60 seconds on CPU
    assert elapsed < 60.0, f"Calibration took {elapsed:.1f}s (expected < 60s)"

    print(f"  PASS: test_gradient_calibration_convergence "
          f"(Loss: {initial_loss:.4f} -> {final_loss:.4f}, "
          f"reduction {loss_reduction:.1%}, elapsed {elapsed:.1f}s)")


# =====================================================================
# Main
# =====================================================================
if __name__ == "__main__":
    print("Diff-CROPGRO Phase 1.5 Test Suite")
    print("=" * 50)
    test_smooth_operators()
    test_photosynthesis_saturation()
    test_lai_biomass_conservation()
    test_extreme_conditions()
    test_autograd_all_parameters()
    test_gradient_calibration_convergence()
    print("=" * 50)
    print("All 6 tests passed.")
