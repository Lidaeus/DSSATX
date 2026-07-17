"""Tests for the equifinality diagnostics module.

Uses synthetic ensembles with known correlation/collinearity structure to
verify the 4-piece evidence chain: posterior diagnostics, correlation matrix,
VIF/condition number, PCA axis ratio, and functional-equifinality detection.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.reporting.equifinality import (
    _detect_multimodality,
    assess_equifinality,
    compute_correlation_matrix,
    compute_pca,
    compute_posterior_diagnostics,
    compute_vif_condition,
    detect_functional_equifinality,
    load_posterior_ensemble,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _make_synthetic_posterior(
    n_real: int = 30,
    active_params: list[str] | None = None,
    *,
    seed: int = 42,
    correlated_pair: tuple[str, str] | None = ("P1", "P2"),
    corr_strength: float = 0.9,
) -> pd.DataFrame:
    """Build a synthetic posterior with optional strong correlation between two params."""
    active_params = active_params or ["P1", "P2", "P3"]
    rng = np.random.default_rng(seed)
    data: dict[str, np.ndarray] = {}
    for p in active_params:
        data[p] = rng.normal(0, 1, n_real)
    if correlated_pair:
        a, b = correlated_pair
        if a in active_params and b in active_params:
            # Mix independent noise with shared signal to set correlation.
            shared = rng.normal(0, 1, n_real)
            data[a] = corr_strength * shared + np.sqrt(1 - corr_strength ** 2) * data[a]
            data[b] = corr_strength * shared + np.sqrt(1 - corr_strength ** 2) * data[b]
    df = pd.DataFrame(data)
    df.insert(0, "real_name", [f"r{i}" for i in range(n_real)])
    return df


@pytest.fixture
def synthetic_ensemble(tmp_path: Path):
    """Write a minimal IES run directory with prior, posterior, phi, and pst-free bounds."""
    active = ["P1", "P2", "P3", "P4"]
    prior = _make_synthetic_posterior(n_real=30, active_params=active, seed=10, corr_strength=0.3)
    # Posterior with strong P1–P2 correlation and P3–P4 weaker.
    posterior = _make_synthetic_posterior(n_real=25, active_params=active, seed=20, corr_strength=0.9)
    # Add a zero-variance (fixed) param to verify filtering.
    posterior["FIXED1"] = 5.0
    prior["FIXED1"] = 5.0

    prefix = "test_case"
    prior.to_csv(tmp_path / f"{prefix}.0.par.csv", index=False)
    posterior.to_csv(tmp_path / f"{prefix}.3.par.csv", index=False)

    # Phi: 4 iterations × 25 realizations; make a few "good" reals with similar low Phi.
    phi_rows = []
    for it in range(4):
        row = {"iteration": it, "total_runs": 25, "mean": 100 - it * 5, "standard_deviation": 10, "min": 90, "max": 120}
        for i in range(25):
            row[f"r{i}"] = 90 + i * 0.5 + (5 if it < 2 else 0)
        phi_rows.append(row)
    pd.DataFrame(phi_rows).to_csv(tmp_path / f"{prefix}.phi.actual.csv", index=False)
    return tmp_path, prefix


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_posterior_diagnostics_compute_shrinkage_and_bounds(synthetic_ensemble):
    tmp_path, prefix = synthetic_ensemble
    prior, posterior, bounds, active = load_posterior_ensemble(tmp_path, prefix)
    diagnostics = compute_posterior_diagnostics(prior, posterior, bounds, active)
    assert "parameter" in diagnostics.columns
    assert "iqr_shrinkage" in diagnostics.columns
    assert "frac_near_lower" in diagnostics.columns
    assert "multimodality_flag" in diagnostics.columns
    assert set(diagnostics["parameter"]) == {"P1", "P2", "P3", "P4"}
    # FIXED1 must NOT appear (zero variance filtered).
    assert "FIXED1" not in set(diagnostics["parameter"])


def test_correlation_matrix_pearson_and_spearman_long_form(synthetic_ensemble):
    tmp_path, prefix = synthetic_ensemble
    prior, posterior, bounds, active = load_posterior_ensemble(tmp_path, prefix)
    corr = compute_correlation_matrix(posterior, active)
    assert {"parameter_a", "parameter_b", "pearson", "spearman"} <= set(corr.columns)
    # 4 active params → C(4,2) = 6 unique pairs.
    assert len(corr) == 6
    # The P1–P2 pair should show high correlation (seeded 0.9).
    p1p2 = corr[
        ((corr["parameter_a"] == "P1") & (corr["parameter_b"] == "P2"))
        | ((corr["parameter_a"] == "P2") & (corr["parameter_b"] == "P1"))
    ]
    assert len(p1p2) == 1
    assert p1p2["pearson"].iloc[0] > 0.7


def test_vif_and_condition_number_on_known_correlated_params(synthetic_ensemble):
    tmp_path, prefix = synthetic_ensemble
    prior, posterior, bounds, active = load_posterior_ensemble(tmp_path, prefix)
    vif_df, condition = compute_vif_condition(posterior, active)
    assert "parameter" in vif_df.columns and "vif" in vif_df.columns
    assert len(vif_df) == 4
    assert np.isfinite(condition) and condition > 0
    # With strong P1–P2 correlation, at least one VIF should be elevated.
    assert vif_df["vif"].max() > 1.5


def test_pca_uses_sqrt_lambda_ratio_axis_metric(synthetic_ensemble):
    tmp_path, prefix = synthetic_ensemble
    prior, posterior, bounds, active = load_posterior_ensemble(tmp_path, prefix)
    loadings, metrics = compute_pca(posterior, active)
    assert {"component", "parameter", "loading", "eigenvalue", "explained_variance_ratio"} <= set(loadings.columns)
    assert "ellipse_axis_ratio" in metrics
    # Axis ratio = sqrt(lambda1/lambda2) ≥ 1 always.
    assert metrics["ellipse_axis_ratio"] >= 1.0
    # PC1 should capture more variance than PC4.
    pc1_var = loadings[loadings["component"] == 1]["explained_variance_ratio"].iloc[0]
    pc4_var = loadings[loadings["component"] == 4]["explained_variance_ratio"].iloc[0]
    assert pc1_var > pc4_var


def test_functional_equifinality_finds_similar_phi_distant_params(synthetic_ensemble):
    tmp_path, prefix = synthetic_ensemble
    prior, posterior, bounds, active = load_posterior_ensemble(tmp_path, prefix)
    phi = pd.read_csv(tmp_path / f"{prefix}.phi.actual.csv")
    summary = {"iteration", "total_runs", "mean", "standard_deviation", "min", "max"}
    real_cols = [c for c in phi.columns if c not in summary]
    long = phi.melt(id_vars=["iteration"], value_vars=real_cols, var_name="realization", value_name="phi")
    long["iteration"] = pd.to_numeric(long["iteration"], errors="coerce")
    long["phi"] = pd.to_numeric(long["phi"], errors="coerce")
    long = long.dropna(subset=["iteration", "phi"])
    pairs = detect_functional_equifinality(posterior, long, active, threshold_frac=0.1)
    expected_cols = {"pair_id", "real_a", "real_b", "phi_a", "phi_b", "phi_total", "parameter_distance", "prediction_distance"}
    assert expected_cols <= set(pairs.columns)
    # prediction_distance is pending deterministic reruns — always NaN here.
    if len(pairs):
        assert pairs["prediction_distance"].isna().all()


def test_equifinality_only_uses_active_params_filters_zero_variance(synthetic_ensemble):
    tmp_path, prefix = synthetic_ensemble
    prior, posterior, bounds, active = load_posterior_ensemble(tmp_path, prefix)
    assert "FIXED1" not in active
    assert set(active) == {"P1", "P2", "P3", "P4"}


def test_multimodality_detector_flags_clear_gap():
    # Two well-separated clusters.
    bimodal = np.concatenate([np.full(10, 0.0), np.full(10, 10.0)])
    assert bool(_detect_multimodality(bimodal)) is True
    unimodal = np.linspace(0, 10, 20)
    assert bool(_detect_multimodality(unimodal)) is False


def test_assess_equifinality_full_pipeline(synthetic_ensemble):
    """End-to-end: assess_equifinality produces a warn-level report + artifacts."""
    tmp_path, prefix = synthetic_ensemble
    report, artifacts = assess_equifinality(tmp_path, prefix)
    assert report.run_type == "equifinality"
    # process_completed must pass.
    assert any(c.check_id == "process_completed" and c.status == "pass" for c in report.checks)
    # Equifinality checks are warn-level (never hard fail).
    eq_checks = [c for c in report.checks if c.check_id.startswith("equifinality_")]
    assert len(eq_checks) >= 4
    assert all(c.status in {"pass", "warn"} for c in eq_checks)
    # Artifacts dict has all expected keys.
    for key in ("diagnostics", "correlation", "vif", "pca_loadings", "functional_pairs", "pca_metrics"):
        assert key in artifacts
