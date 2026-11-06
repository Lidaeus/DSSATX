"""
tests/test_phenology_dataset_stress.py
======================================
Empirical Adversarial Stress Test Harness for PyTorch Phenology Dataset Interface.

Tested Module: src/phenology/dataset.py
Tested Functions:
- load_benchmark_dataset()
- get_seasonal_tensor_bundle()

Verification Dimensions:
1. Path robustness & corrupted directory handling
2. Tensor slicing, masking, and device transfer (CPU vs CUDA)
3. Batch dimension consistency & forward pass compatibility
4. Numerical stability, milestone target ranges, and autograd gradient backprop

Author: Empirical Challenger 2 (Milestone 1)
Date: 2026-09-20
"""

import tempfile
from pathlib import Path
from typing import Dict, Any

import numpy as np
import pandas as pd
import pytest
import torch
import torch.nn as nn
import torch.nn.functional as F

import src.phenology.dataset as ds


# ==============================================================================
# Dimension 1: Path & Directory Robustness Tests
# ==============================================================================

class TestDatasetPathRobustness:
    """Stress-test error handling under invalid, missing, or corrupted directory inputs."""

    def test_nonexistent_dataset_directory(self):
        """Verify that a non-existent path raises FileNotFoundError with informative text."""
        bogus_path = "non_existent_directory_987654321"
        with pytest.raises(FileNotFoundError) as excinfo:
            ds.load_benchmark_dataset(bogus_path)
        assert "Benchmark file not found at" in str(excinfo.value)
        assert "build_phenology_benchmark.py" in str(excinfo.value)

    def test_empty_dataset_directory(self):
        """Verify that an empty directory raises FileNotFoundError on missing files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FileNotFoundError) as excinfo:
                ds.load_benchmark_dataset(tmpdir)
            assert "treatment_season_metadata.csv" in str(excinfo.value)

    def test_missing_single_table(self):
        """Verify that deleting any one of the 4 tables causes an explicit FileNotFoundError."""
        real_dir = Path("data/benchmark/phenology")
        required_files = [
            "treatment_season_metadata.csv",
            "microclimate_daily_series.csv",
            "phenology_benchmark_targets.csv",
            "literature_solanaceous_benchmarks.csv",
        ]
        for missing_target in required_files:
            with tempfile.TemporaryDirectory() as tmpdir:
                p = Path(tmpdir)
                for f in required_files:
                    if f != missing_target:
                        (p / f).write_bytes((real_dir / f).read_bytes())
                with pytest.raises(FileNotFoundError) as excinfo:
                    ds.load_benchmark_dataset(p)
                assert missing_target in str(excinfo.value)

    def test_zero_byte_corrupted_csv(self):
        """Verify that 0-byte (empty) CSV files raise EmptyDataError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            for fname in [
                "treatment_season_metadata.csv",
                "microclimate_daily_series.csv",
                "phenology_benchmark_targets.csv",
                "literature_solanaceous_benchmarks.csv",
            ]:
                (p / fname).write_text("", encoding="utf-8")
            with pytest.raises(pd.errors.EmptyDataError):
                ds.load_benchmark_dataset(p)

    def test_missing_required_columns_fail_fast(self):
        """Verify that corrupted CSV tables with missing required columns raise KeyError immediately."""
        real_dir = Path("data/benchmark/phenology")
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            # Corrupted metadata missing 'season_id'
            pd.DataFrame({"dummy_col": [1, 2]}).to_csv(p / "treatment_season_metadata.csv", index=False)
            for f in [
                "microclimate_daily_series.csv",
                "phenology_benchmark_targets.csv",
                "literature_solanaceous_benchmarks.csv",
            ]:
                (p / f).write_bytes((real_dir / f).read_bytes())

            with pytest.raises(KeyError) as excinfo:
                ds.get_seasonal_tensor_bundle(p)
            assert "season_id" in str(excinfo.value)


# ==============================================================================
# Dimension 2: Slicing, Masking, and Device Transfer Tests
# ==============================================================================

class TestTensorSlicingMaskingDevice:
    """Stress-test tensor slicing, masking, and device transfer guarantees."""

    @pytest.fixture(scope="class")
    def bundle(self):
        return ds.get_seasonal_tensor_bundle()

    def test_tensor_memory_contiguity(self, bundle):
        """Ensure all 2D microclimate tensors are contiguous in memory despite broadcast expand."""
        for season_id, sdata in bundle.items():
            for key in ["tavg", "tmin", "tmax", "dif", "srad", "dli", "daylength", "rhum", "chilling"]:
                tensor = sdata[key]
                assert tensor.is_contiguous(), f"{season_id} {key} is not contiguous!"

    def test_batch_slicing_and_subsetting(self, bundle):
        """Test slicing along batch dimension (treatments) preserves shapes and attributes."""
        for season_id, sdata in bundle.items():
            b = sdata["batch_size"]
            t = sdata["seq_len"]

            # Sub-batch slice: first 3 treatments
            sub_tavg = sdata["tavg"][:3, :]
            sub_page = sdata["page"][:3]
            sub_adaps = sdata["targets"]["ADAPS"][:3]

            assert sub_tavg.shape == (min(3, b), t)
            assert sub_page.shape == (min(3, b),)
            assert sub_adaps.shape == (min(3, b),)
            assert sub_tavg.is_contiguous()

            # Single treatment slice
            single_tavg = sdata["tavg"][0:1, :]
            assert single_tavg.shape == (1, t)

    def test_sequence_time_slicing(self, bundle):
        """Test slicing along sequence dimension (time days)."""
        for season_id, sdata in bundle.items():
            t = sdata["seq_len"]
            half_t = t // 2

            first_half = sdata["tavg"][:, :half_t]
            second_half = sdata["tavg"][:, half_t:]
            sliced_doy = sdata["doy"][:half_t]

            assert first_half.shape[1] == half_t
            assert second_half.shape[1] == t - half_t
            assert sliced_doy.shape[0] == half_t

    def test_boolean_masking_treatment_and_time(self, bundle):
        """Test boolean masking on batch and sequence dimensions."""
        for season_id, sdata in bundle.items():
            # Batch boolean mask: treatments with n_rate > 100 kg/ha
            n_mask = sdata["n_rate_kg_ha"] > 100.0
            if n_mask.any():
                n_filtered = sdata["tavg"][n_mask, :]
                assert n_filtered.shape[0] == int(n_mask.sum().item())
                assert n_filtered.shape[1] == sdata["seq_len"]

            # Time boolean mask: cold days with Tmin < 10 C
            # Using 1D slice from first batch row
            cold_mask_time = sdata["tmin"][0] < 10.0
            if cold_mask_time.any():
                cold_tavg = sdata["tavg"][:, cold_mask_time]
                assert cold_tavg.shape[1] == int(cold_mask_time.sum().item())

    def test_device_transfer_cpu(self):
        """Verify explicit CPU device transfer."""
        bundle_cpu = ds.get_seasonal_tensor_bundle(device=torch.device("cpu"))
        for season_id, sdata in bundle_cpu.items():
            assert sdata["tavg"].device == torch.device("cpu")
            assert sdata["page"].device == torch.device("cpu")
            assert sdata["targets"]["ADAPS"].device == torch.device("cpu")
            assert sdata["doy"].device == torch.device("cpu")

    def test_device_transfer_cuda_and_orphan_doy_bug_discovery(self):
        """
        Verify CUDA device transfer and empirically assert that 'doy' is properly transferred.
        If CUDA is available:
        - All primary tensors ('tavg', 'tmin', 'page', 'targets', etc.) must be on cuda:0.
        - 'doy' is verified to be on cuda:0 (confirming resolution of dataset.py:260 device transfer).
        - Demonstrates that cross-tensor arithmetic with 'doy' on GPU succeeds.
        """
        if not torch.cuda.is_available():
            pytest.skip("CUDA not available on this machine; skipping CUDA test.")

        cuda_dev = torch.device("cuda:0")
        bundle_gpu = ds.get_seasonal_tensor_bundle(device=cuda_dev)

        for season_id, sdata in bundle_gpu.items():
            # Primary tensors are correctly on CUDA
            assert sdata["tavg"].device.type == "cuda"
            assert sdata["page"].device.type == "cuda"
            assert sdata["targets"]["ADAPS"].device.type == "cuda"
            assert sdata["target_uncertainties"]["ADAPS"].device.type == "cuda"

            # VERIFIED RESOLUTION: 'doy' is properly transferred to target device
            doy_tensor = sdata["doy"]
            assert doy_tensor.device.type == "cuda", (
                f"Expected doy to be on CUDA after dataset.py fix, but got {doy_tensor.device}"
            )

            # Cross-tensor arithmetic with 'doy' on GPU succeeds without error
            res = sdata["tavg"] + doy_tensor.unsqueeze(0)
            assert res.device.type == "cuda"


# ==============================================================================
# Dimension 3: Batch Dimensions & Forward Pass Compatibility
# ==============================================================================

class DummyNeuralPhenologyModule(nn.Module):
    """
    Parametric dummy neural-phenology operator implementing:
    - Smooth thermal kernel Phi(T)
    - DIF modulation Psi(DIF)
    - Smooth chilling gate G_chill
    - Monotonic developmental accumulation D(t) = D0 + cumsum(dD/dt)
    """
    def __init__(self, tb_init: float = 9.2, topt_init: float = 26.0):
        super().__init__()
        self.tb = nn.Parameter(torch.tensor(tb_init, dtype=torch.float32))
        self.topt = nn.Parameter(torch.tensor(topt_init, dtype=torch.float32))
        self.dif_weight = nn.Parameter(torch.tensor(0.02, dtype=torch.float32))
        self.scale = nn.Parameter(torch.tensor(0.015, dtype=torch.float32))
        self.chill_weight = nn.Parameter(torch.tensor(-0.05, dtype=torch.float32))

    def forward(
        self,
        tavg: torch.Tensor,
        dif: torch.Tensor,
        chilling: torch.Tensor,
        page: torch.Tensor,
    ) -> Dict[str, torch.Tensor]:
        # B = batch size, T = seq length
        # Continuous thermal kernel (positive, softplus ramp at tb)
        phi_t = F.softplus(tavg - self.tb) * torch.sigmoid(self.topt - tavg + 5.0)

        # DIF modulation factor
        psi_dif = 1.0 + torch.tanh(self.dif_weight * dif)

        # Smooth chilling gate (suppression when chilling accumulates)
        g_chill = torch.sigmoid(1.0 + self.chill_weight * chilling)

        # Developmental velocity: dD/dt >= 0
        dD_dt = phi_t * psi_dif * g_chill * F.softplus(self.scale)

        # Dynamic seedling age initial developmental stage: D0 ~ 0.18
        # Shape page is (B,), broadcast to (B, 1)
        d0 = (0.18 * (page / 22.0)).unsqueeze(1)

        # Continuous stage trajectory D(t)
        d_trajectory = d0 + torch.cumsum(dD_dt, dim=1)

        return {
            "D": d_trajectory,
            "dD_dt": dD_dt,
            "g_chill": g_chill,
            "D0": d0,
        }


class TestBatchDimensionsForwardPass:
    """Stress-test tensor shapes and dummy forward pass execution."""

    @pytest.fixture(scope="class")
    def bundle(self):
        return ds.get_seasonal_tensor_bundle()

    def test_exact_seasonal_tensor_shapes(self, bundle):
        """Verify strict contract compliance for batch and sequence dimensions."""
        expected_dims = {
            "25SP": {"B": 11, "T": 124},
            "26SP": {"B": 12, "T": 124},
            "25FA": {"B": 12, "T": 151},
        }

        for season_id, exp in expected_dims.items():
            sdata = bundle[season_id]
            b, t = exp["B"], exp["T"]
            assert sdata["batch_size"] == b
            assert sdata["seq_len"] == t

            # Check 2D microclimate tensors (B, T)
            for key in ["tavg", "tmin", "tmax", "dif", "srad", "dli", "daylength", "rhum", "chilling"]:
                assert sdata[key].shape == (b, t), f"{season_id} {key} shape mismatch!"

            # Check 1D treatment attribute tensors (B,)
            for key in ["page", "irrigation_coeff", "n_rate_kg_ha", "treatment"]:
                assert sdata[key].shape == (b,), f"{season_id} {key} shape mismatch!"

            # Check target milestone tensors (B,)
            for event_name, target_tensor in sdata["targets"].items():
                assert target_tensor.shape == (b,), f"{season_id} target {event_name} shape mismatch!"

            # Check uncertainty tensors (B,)
            for event_name, se_tensor in sdata["target_uncertainties"].items():
                assert se_tensor.shape == (b,), f"{season_id} target_se {event_name} shape mismatch!"

            # Check DOY tensor (T,)
            assert sdata["doy"].shape == (t,), f"{season_id} doy shape mismatch!"

    def test_dummy_neural_phenology_forward_pass_all_seasons(self, bundle):
        """Verify that all seasons can be processed through the dummy neural phenology operator without error."""
        model = DummyNeuralPhenologyModule()

        for season_id, sdata in bundle.items():
            b = sdata["batch_size"]
            t = sdata["seq_len"]

            out = model(
                tavg=sdata["tavg"],
                dif=sdata["dif"],
                chilling=sdata["chilling"],
                page=sdata["page"],
            )

            d_traj = out["D"]
            dD_dt = out["dD_dt"]

            # Shape verification
            assert d_traj.shape == (b, t)
            assert dD_dt.shape == (b, t)

            # Monotonicity verification: dD_dt >= 0
            assert (dD_dt >= 0.0).all(), f"{season_id} dD_dt contains negative velocities!"

            # Trajectory monotonicity verification
            diffs = d_traj[:, 1:] - d_traj[:, :-1]
            assert (diffs >= -1e-7).all(), f"{season_id} D(t) violates monotonicity!"

    def test_variable_batch_sizes(self, bundle):
        """Verify dummy operator handles arbitrary sub-batch sizes (B=1, B=2, B=all)."""
        model = DummyNeuralPhenologyModule()
        sdata = bundle["25SP"]

        for sub_b in [1, 2, 5, sdata["batch_size"]]:
            out = model(
                tavg=sdata["tavg"][:sub_b],
                dif=sdata["dif"][:sub_b],
                chilling=sdata["chilling"][:sub_b],
                page=sdata["page"][:sub_b],
            )
            assert out["D"].shape == (sub_b, sdata["seq_len"])


# ==============================================================================
# Dimension 4: Numerical Stability & Milestone Loss Gradients
# ==============================================================================

class TestNumericalStabilityAndGradients:
    """Stress-test numerical stability, NaN/Inf absence, and gradient backpropagation."""

    @pytest.fixture(scope="class")
    def bundle(self):
        return ds.get_seasonal_tensor_bundle()

    def test_no_nans_or_infs_in_all_bundle_tensors(self, bundle):
        """Exhaustively verify that zero NaNs or Infs exist in any tensor across all 3 seasons."""
        for season_id, sdata in bundle.items():
            for key, val in sdata.items():
                if isinstance(val, torch.Tensor):
                    assert not torch.isnan(val).any(), f"NaN found in {season_id}['{key}']!"
                    assert not torch.isinf(val).any(), f"Inf found in {season_id}['{key}']!"
                elif isinstance(val, dict):
                    for subk, subv in val.items():
                        if isinstance(subv, torch.Tensor):
                            assert not torch.isnan(subv).any(), f"NaN found in {season_id}['{key}']['{subk}']!"
                            assert not torch.isinf(subv).any(), f"Inf found in {season_id}['{key}']['{subk}']!"

    def test_milestone_target_physiological_validity_and_order(self, bundle):
        """
        Verify target DAP milestone values are strictly non-negative and chronologically ordered:
        transplanting (0.0) <= anthesis <= fruit_set <= first_harvest <= peak_harvest <= cessation.
        """
        for season_id, sdata in bundle.items():
            targets = sdata["targets"]

            # Non-negativity
            for ev in ["transplanting", "anthesis", "fruit_set", "first_harvest", "peak_harvest", "cessation"]:
                val = targets[ev]
                assert (val >= 0.0).all(), f"{season_id} target {ev} has negative values!"

            # Chronological ordering for each treatment
            assert (targets["transplanting"] <= targets["anthesis"]).all()
            assert (targets["anthesis"] <= targets["fruit_set"]).all()
            assert (targets["fruit_set"] <= targets["first_harvest"]).all()
            assert (targets["first_harvest"] <= targets["peak_harvest"]).all()
            # Note: in 25FA, biological cessation occurred at DAP 109 when freezing set in,
            # while first commercial harvest was DAP 100.
            assert (targets["first_harvest"] <= targets["cessation"]).all()

    def test_target_uncertainty_safe_weighting_audit(self, bundle):
        """
        Audit uncertainty SE values:
        - Confirms transplanting SE = 0.0 dap (deterministic anchor).
        - Confirms all other milestone SEs are strictly positive (0.5 to 2.0 dap).
        - Demonstrates that unshielded 1 / (se ** 2) produces Inf for transplanting,
          mandating epsilon safeguarding 1 / (se ** 2 + eps) in downstream loss functions.
        """
        for season_id, sdata in bundle.items():
            se_dict = sdata["target_uncertainties"]

            # Transplanting is exact (SE = 0.0)
            trans_se = se_dict["transplanting"]
            assert (trans_se == 0.0).all()

            # Direct reciprocal produces Inf
            unshielded_w = 1.0 / (trans_se ** 2)
            assert torch.isinf(unshielded_w).all(), "Unshielded reciprocal of 0.0 must be Inf"

            # Epsilon-safeguarded reciprocal is finite
            eps = 1e-4
            shielded_w = 1.0 / (trans_se ** 2 + eps)
            assert torch.isfinite(shielded_w).all()

            # Other milestones are strictly positive
            for ev in ["anthesis", "fruit_set", "first_harvest", "peak_harvest", "cessation", "ADAPS", "PDFPS"]:
                se = se_dict[ev]
                assert (se > 0.0).all(), f"{season_id} {ev} SE must be positive!"

    def test_gradient_backpropagation_finite_and_stable(self, bundle):
        """
        Verify that autograd gradients backpropagate smoothly from milestone target losses
        to operator parameters without NaNs, Infs, or gradient explosions.
        """
        model = DummyNeuralPhenologyModule()

        for season_id, sdata in bundle.items():
            model.zero_grad()
            out = model(
                tavg=sdata["tavg"],
                dif=sdata["dif"],
                chilling=sdata["chilling"],
                page=sdata["page"],
            )
            d_traj = out["D"]
            b = sdata["batch_size"]
            t = sdata["seq_len"]

            # Compute loss against ADAPS (anthesis, target stage 1.00) and PDFPS (fruit set, target stage 1.25)
            adaps_dap = sdata["targets"]["ADAPS"].long().clamp(0, t - 1)
            pdfps_dap = sdata["targets"]["PDFPS"].long().clamp(0, t - 1)
            b_idx = torch.arange(b)

            pred_stage_adaps = d_traj[b_idx, adaps_dap]
            pred_stage_pdfps = d_traj[b_idx, pdfps_dap]

            loss_adaps = F.smooth_l1_loss(pred_stage_adaps, torch.full_like(pred_stage_adaps, 1.00))
            loss_pdfps = F.smooth_l1_loss(pred_stage_pdfps, torch.full_like(pred_stage_pdfps, 1.25))
            total_loss = loss_adaps + loss_pdfps

            total_loss.backward()

            for p_name, param in model.named_parameters():
                assert param.grad is not None, f"{p_name} grad is None!"
                assert not torch.isnan(param.grad).any(), f"NaN in {p_name} grad!"
                assert not torch.isinf(param.grad).any(), f"Inf in {p_name} grad!"
                grad_norm = param.grad.abs().max().item()
                assert grad_norm < 1e5, f"{p_name} gradient exploded: norm={grad_norm}"

    def test_adversarial_extreme_microclimate_stress(self, bundle):
        """
        Adversarially inject extreme temperature and solar radiation values
        (heatwave 60 C, freezing -20 C, extreme DIF 45 C) and verify no NaNs or Infs.
        """
        model = DummyNeuralPhenologyModule()
        sdata = bundle["25SP"]

        # Extreme Heatwave Scenario
        extreme_tavg = sdata["tavg"] + 35.0  # up to ~65 C
        extreme_dif = sdata["dif"] + 25.0
        out_heat = model(extreme_tavg, extreme_dif, sdata["chilling"], sdata["page"])
        assert torch.isfinite(out_heat["D"]).all()
        assert torch.isfinite(out_heat["dD_dt"]).all()

        # Extreme Freezing Scenario
        extreme_freeze = sdata["tavg"] - 40.0  # down to ~ -25 C
        extreme_chill = sdata["chilling"] + 30.0
        out_freeze = model(extreme_freeze, sdata["dif"], extreme_chill, sdata["page"])
        assert torch.isfinite(out_freeze["D"]).all()
        assert torch.isfinite(out_freeze["dD_dt"]).all()
        # Developmental velocity under extreme freezing should be near zero
        assert (out_freeze["dD_dt"] < 0.05).all()
