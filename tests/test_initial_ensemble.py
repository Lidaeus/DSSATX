"""Tests for LHS/Sobol initial ensemble generation and reinflation configuration."""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.calibration.initial_ensemble import (
    generate_lhs_ensemble,
    write_ensemble_csv,
)


def test_generate_lhs_ensemble_basic():
    """Test basic LHS ensemble generation."""
    bounds_df = pd.DataFrame({
        "name": ["PAR1", "PAR2", "PAR3"],
        "init": [1.0, 2.0, 3.0],
        "lower": [0.5, 1.0, 2.0],
        "upper": [1.5, 3.0, 4.0],
        "status": ["active", "active", "active"],
    })

    ensemble = generate_lhs_ensemble(
        n_reals=50,
        bounds_df=bounds_df,
        seed=42,
        method="lhs",
    )

    assert len(ensemble) == 50
    assert "real_name" in ensemble.columns
    assert "PAR1" in ensemble.columns
    assert "PAR2" in ensemble.columns
    assert "PAR3" in ensemble.columns

    # Check bounds are respected
    assert ensemble["PAR1"].min() >= 0.5
    assert ensemble["PAR1"].max() <= 1.5
    assert ensemble["PAR2"].min() >= 1.0
    assert ensemble["PAR2"].max() <= 3.0
    assert ensemble["PAR3"].min() >= 2.0
    assert ensemble["PAR3"].max() <= 4.0


def test_generate_sobol_ensemble():
    """Test Sobol sequence ensemble generation."""
    bounds_df = pd.DataFrame({
        "name": ["PAR1", "PAR2"],
        "init": [1.0, 2.0],
        "lower": [0.0, 0.0],
        "upper": [2.0, 4.0],
        "status": ["active", "active"],
    })

    # Sobol works best with power-of-2 sample sizes
    ensemble = generate_lhs_ensemble(
        n_reals=64,
        bounds_df=bounds_df,
        seed=123,
        method="sobol",
    )

    assert len(ensemble) == 64
    # Sobol should have better space-filling than random
    # Check that samples are well-distributed
    par1_bins = np.histogram_bin_edges(ensemble["PAR1"], bins=8)
    par2_bins = np.histogram_bin_edges(ensemble["PAR2"], bins=8)
    # Each bin should have roughly similar counts
    hist1, _ = np.histogram(ensemble["PAR1"], bins=par1_bins)
    hist2, _ = np.histogram(ensemble["PAR2"], bins=par2_bins)
    # Sobol should have relatively uniform distribution
    assert hist1.std() < len(ensemble) / 4  # Not too uneven
    assert hist2.std() < len(ensemble) / 4


def test_lhs_reproducibility():
    """Test that LHS is reproducible with same seed."""
    bounds_df = pd.DataFrame({
        "name": ["PAR1"],
        "init": [1.0],
        "lower": [0.0],
        "upper": [2.0],
        "status": ["active"],
    })

    a = generate_lhs_ensemble(n_reals=20, bounds_df=bounds_df, seed=999, method="lhs")
    b = generate_lhs_ensemble(n_reals=20, bounds_df=bounds_df, seed=999, method="lhs")

    assert np.allclose(a["PAR1"].values, b["PAR1"].values)


def test_lhs_different_seeds():
    """Test that different seeds produce different ensembles."""
    bounds_df = pd.DataFrame({
        "name": ["PAR1"],
        "init": [1.0],
        "lower": [0.0],
        "upper": [2.0],
        "status": ["active"],
    })

    a = generate_lhs_ensemble(n_reals=20, bounds_df=bounds_df, seed=1, method="lhs")
    b = generate_lhs_ensemble(n_reals=20, bounds_df=bounds_df, seed=2, method="lhs")

    # Different seeds should produce different samples
    assert not np.allclose(a["PAR1"].values, b["PAR1"].values)


def test_include_base_realization():
    """Test that include_base adds initial values as first realization."""
    bounds_df = pd.DataFrame({
        "name": ["PAR1", "PAR2"],
        "init": [1.5, 2.5],
        "lower": [1.0, 2.0],
        "upper": [2.0, 3.0],
        "status": ["active", "active"],
    })

    ensemble = generate_lhs_ensemble(
        n_reals=10,
        bounds_df=bounds_df,
        seed=42,
        method="lhs",
        include_base=True,
    )

    assert len(ensemble) == 11  # 10 + 1 base
    assert ensemble.iloc[0]["real_name"] == "base"
    assert ensemble.iloc[0]["PAR1"] == 1.5
    assert ensemble.iloc[0]["PAR2"] == 2.5


def test_write_ensemble_csv():
    """Test writing ensemble to CSV file."""
    bounds_df = pd.DataFrame({
        "name": ["PAR1"],
        "init": [1.0],
        "lower": [0.0],
        "upper": [2.0],
        "status": ["active"],
    })

    ensemble = generate_lhs_ensemble(n_reals=10, bounds_df=bounds_df, seed=42, method="lhs")

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "test_ensemble.csv"
        write_ensemble_csv(ensemble, out_path)

        assert out_path.exists()
        loaded = pd.read_csv(out_path)
        assert len(loaded) == 10
        assert "real_name" in loaded.columns
        assert "PAR1" in loaded.columns


def test_inactive_parameters_excluded():
    """Test that inactive parameters are excluded from ensemble."""
    bounds_df = pd.DataFrame({
        "name": ["PAR1", "PAR2", "PAR3"],
        "init": [1.0, 2.0, 3.0],
        "lower": [0.5, 1.0, 2.0],
        "upper": [1.5, 3.0, 4.0],
        "status": ["active", "fixed", "active"],
    })

    ensemble = generate_lhs_ensemble(
        n_reals=20,
        bounds_df=bounds_df,
        seed=42,
        method="lhs",
    )

    # Only active parameters should be in ensemble
    assert "PAR1" in ensemble.columns
    assert "PAR3" in ensemble.columns
    assert "PAR2" not in ensemble.columns


def test_invalid_method_raises():
    """Test that invalid method raises ValueError."""
    bounds_df = pd.DataFrame({
        "name": ["PAR1"],
        "init": [1.0],
        "lower": [0.0],
        "upper": [2.0],
        "status": ["active"],
    })

    with pytest.raises(ValueError, match="Unknown method"):
        generate_lhs_ensemble(
            n_reals=10,
            bounds_df=bounds_df,
            seed=42,
            method="invalid",
        )


def test_no_active_parameters_raises():
    """Test that no active parameters raises ValueError."""
    bounds_df = pd.DataFrame({
        "name": ["PAR1"],
        "init": [1.0],
        "lower": [0.0],
        "upper": [2.0],
        "status": ["fixed"],
    })

    with pytest.raises(ValueError, match="No active parameters"):
        generate_lhs_ensemble(
            n_reals=10,
            bounds_df=bounds_df,
            seed=42,
            method="lhs",
        )