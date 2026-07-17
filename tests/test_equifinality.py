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
    """Write a minimal IES run directory with prior, posterior, phi, and a stub .pst.

    The .pst is a minimal pyemu-readable stub so that _read_bounds_from_pst can
    extract parlbnd/parubnd for the active + a collapsed parameter.
    """
    active = ["P1", "P2", "P3", "P4"]
    prior = _make_synthetic_posterior(n_real=30, active_params=active, seed=10, corr_strength=0.3)
    # Posterior with strong P1–P2 correlation and P3–P4 weaker.
    posterior = _make_synthetic_posterior(n_real=25, active_params=active, seed=20, corr_strength=0.9)
    # Add a zero-variance (collapsed) param to verify it is flagged, not dropped.
    posterior["COLLAPSED1"] = 5.0
    prior["COLLAPSED1"] = 5.0

    prefix = "test_case"
    prior.to_csv(tmp_path / f"{prefix}.0.par.csv", index=False)
    posterior.to_csv(tmp_path / f"{prefix}.3.par.csv", index=False)

    # No .pst written — _read_bounds_from_pst falls back to treating all
    # numeric posterior columns as calibrated (P1-P4 + COLLAPSED1).
    # This tests the R0.2 fallback path; the real-run path uses a valid .pst.

    # Phi: 4 iterations × 25 realizations; make a few "good" reals with similar low Phi.
    phi_rows = []
    for it in range(4):
        row = {"iteration": it, "total_runs": 25, "mean": 100 - it * 5, "standard_deviation": 10, "min": 90, "max": 120}
        for i in range(25):
            row[f"r{i}"] = 90 + i * 0.5 + (5 if it < 2 else 0)
        phi_rows.append(row)
    pd.DataFrame(phi_rows).to_csv(tmp_path / f"{prefix}.phi.actual.csv", index=False)

    # Write run_status.json so upstream binding (R0.1) finds "validated".
    import json
    (tmp_path / "run_status.json").write_text(
        json.dumps({"status": "completed", "scientific_status": "validated"}), encoding="utf-8"
    )
    return tmp_path, prefix


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_posterior_diagnostics_compute_shrinkage_and_bounds(synthetic_ensemble):
    tmp_path, prefix = synthetic_ensemble
    prior, posterior, bounds, active, all_cal = load_posterior_ensemble(tmp_path, prefix)
    diagnostics = compute_posterior_diagnostics(prior, posterior, bounds, all_cal, active)
    assert "parameter" in diagnostics.columns
    assert "iqr_shrinkage" in diagnostics.columns
    assert "collapsed" in diagnostics.columns  # R0.2: collapsed flag
    # R0.2: diagnostics cover ALL calibrated params (incl. collapsed), not just active.
    diag_params = set(diagnostics["parameter"])
    assert {"P1", "P2", "P3", "P4"} <= diag_params
    # The collapsed param appears and is flagged.
    collapsed_rows = diagnostics[diagnostics["collapsed"] == True]
    assert len(collapsed_rows) >= 1


def test_correlation_matrix_pearson_and_spearman_long_form(synthetic_ensemble):
    tmp_path, prefix = synthetic_ensemble
    prior, posterior, bounds, active, all_cal = load_posterior_ensemble(tmp_path, prefix)
    corr = compute_correlation_matrix(posterior, active)
    assert {"parameter_a", "parameter_b", "pearson", "spearman"} <= set(corr.columns)
    # Only active (non-collapsed) params enter correlation.
    assert len(corr) == 6  # C(4,2)
    p1p2 = corr[
        ((corr["parameter_a"] == "P1") & (corr["parameter_b"] == "P2"))
        | ((corr["parameter_a"] == "P2") & (corr["parameter_b"] == "P1"))
    ]
    assert len(p1p2) == 1
    assert p1p2["pearson"].iloc[0] > 0.7


def test_vif_and_condition_number_on_known_correlated_params(synthetic_ensemble):
    tmp_path, prefix = synthetic_ensemble
    prior, posterior, bounds, active, all_cal = load_posterior_ensemble(tmp_path, prefix)
    vif_df, condition = compute_vif_condition(posterior, active)
    assert "parameter" in vif_df.columns and "vif" in vif_df.columns
    assert len(vif_df) == 4  # only active params
    assert np.isfinite(condition) and condition > 0
    assert vif_df["vif"].max() > 1.5


def test_pca_uses_sqrt_lambda_ratio_axis_metric(synthetic_ensemble):
    tmp_path, prefix = synthetic_ensemble
    prior, posterior, bounds, active, all_cal = load_posterior_ensemble(tmp_path, prefix)
    loadings, metrics = compute_pca(posterior, active)
    assert {"component", "parameter", "loading", "eigenvalue", "explained_variance_ratio"} <= set(loadings.columns)
    assert "ellipse_axis_ratio" in metrics
    assert metrics["ellipse_axis_ratio"] >= 1.0
    pc1_var = loadings[loadings["component"] == 1]["explained_variance_ratio"].iloc[0]
    pc4_var = loadings[loadings["component"] == 4]["explained_variance_ratio"].iloc[0]
    assert pc1_var > pc4_var


def test_functional_equifinality_finds_similar_phi_distant_params(synthetic_ensemble):
    tmp_path, prefix = synthetic_ensemble
    prior, posterior, bounds, active, all_cal = load_posterior_ensemble(tmp_path, prefix)
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
    if len(pairs):
        assert pairs["prediction_distance"].isna().all()


def test_equifinality_only_uses_active_params_for_correlation_pca(synthetic_ensemble):
    """R0.2: correlation/PCA/VIF use only active params; diagnostics cover all."""
    tmp_path, prefix = synthetic_ensemble
    prior, posterior, bounds, active, all_cal = load_posterior_ensemble(tmp_path, prefix)
    assert "COLLAPSED1" not in active
    assert set(active) == {"P1", "P2", "P3", "P4"}


def test_multimodality_detector_flags_clear_gap():
    bimodal = np.concatenate([np.full(10, 0.0), np.full(10, 10.0)])
    assert bool(_detect_multimodality(bimodal)) is True
    unimodal = np.linspace(0, 10, 20)
    assert bool(_detect_multimodality(unimodal)) is False


def test_assess_equifinality_full_pipeline(synthetic_ensemble):
    """End-to-end: assess_equifinality binds upstream status (R0.1) + candidate pairs (R0.3)."""
    tmp_path, prefix = synthetic_ensemble
    report, artifacts = assess_equifinality(tmp_path, prefix)
    assert report.run_type == "equifinality"
    # R0.1: upstream_ies_validated check exists.
    assert any(c.check_id == "upstream_ies_validated" for c in report.checks)
    assert any(c.check_id == "process_completed" and c.status == "pass" for c in report.checks)
    eq_checks = [c for c in report.checks if c.check_id.startswith("equifinality_")]
    assert len(eq_checks) >= 4
    assert all(c.status in {"pass", "warn"} for c in eq_checks)
    # R0.3: renamed to candidate_pairs.
    assert "candidate_pairs" in artifacts
    assert "functional_pairs" not in artifacts
    for key in ("diagnostics", "correlation", "vif", "pca_loadings", "candidate_pairs", "pca_metrics"):
        assert key in artifacts


# ─────────────────────────────────────────────────────────────────────────────
# P2-R0 regression tests
# ─────────────────────────────────────────────────────────────────────────────


def test_r0_equifinality_not_validated_when_upstream_ies_fails(tmp_path):
    """R0.1: equifinality inherits upstream status; cannot self-promote."""
    import json
    # Build a minimal ensemble with a FAILED upstream status.
    prior = _make_synthetic_posterior(n_real=20, active_params=["P1", "P2"], seed=1)
    posterior = _make_synthetic_posterior(n_real=15, active_params=["P1", "P2"], seed=2)
    prefix = "fail_case"
    prior.to_csv(tmp_path / f"{prefix}.0.par.csv", index=False)
    posterior.to_csv(tmp_path / f"{prefix}.3.par.csv", index=False)
    (tmp_path / "run_status.json").write_text(
        json.dumps({"status": "completed", "scientific_status": "failed"}), encoding="utf-8"
    )
    report, artifacts = assess_equifinality(tmp_path, prefix)
    # Upstream is failed → equifinality cannot be science_validated.
    assert artifacts["upstream_status"] == "failed"
    assert report.science_validated is False
    upstream_check = next(c for c in report.checks if c.check_id == "upstream_ies_validated")
    assert upstream_check.status == "fail"


def test_r0_quality_gate_rejects_low_realization_retention(tmp_path):
    """R0.6: a 25/30-realization case fails the IES quality gate."""
    from src.common.quality import assess_ies

    # 30 prior realizations, but only 25 in the final → 16.7% loss > 10% threshold.
    prior = pd.DataFrame(
        {"real_name": [f"r{i}" for i in range(30)]} |
        {f"P{j}": np.random.default_rng(j).normal(0, 1, 30) for j in range(3)}
    )
    final = prior.iloc[:25].copy()  # drop 5 realizations
    obs = pd.DataFrame(
        {"real_name": final["real_name"], "O1": np.linspace(1, 10, 25)}
    )
    phi = pd.Series(np.linspace(50, 100, 25), index=final["real_name"])
    report = assess_ies(prior, obs, parameter_final=final, phi_values=phi)
    assert report.science_validated is False
    # The realization-alignment or retention check should fail.
    failed = [c.check_id for c in report.checks if c.status == "fail"]
    assert any("realization" in f or "alignment" in f for f in failed)

