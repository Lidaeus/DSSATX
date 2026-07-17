"""Equifinality diagnostics for IES posterior ensembles.

Implements the 4-piece evidence chain specified in ``DEVELOPER_GUIDE.md §5``:
1. Pearson/Spearman parameter correlation matrix;
2. VIF, condition number, cross-physiological-group correlation network;
3. standardized-parameter-space PCA with ``sqrt(lambda1/lambda2)`` axis ratio;
4. functional equifinality — solutions with similar Phi but distant parameters.

This module is the **Python computation layer only**. It writes frozen CSV
contracts that the R figure pipeline (``paper/R/``) consumes. It must not
import a plotting library (matplotlib banned by the dual-track rule). It does
not perform automatic equifinality *rejection* — per the P1 v4 plan §5 line
172, this phase freezes interfaces and gates, not auto-judgement.

Per W4 §7, equifinality analysis may only use ensembles that passed the P2
quality gate. Outputs are tagged via the caller's quality context.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from src.common.project import sha256_file
from src.common.quality import QualityReport


_ZERO_VARIANCE_TOL = 1e-12
# A parameter whose 95% interval splits into two clearly separated sub-ranges
# is flagged multimodal: the ratio of gap-between-halves to total range.
_MULTIMODALITY_GAP_RATIO = 0.25
# Functional-equifinality: pairs within this fraction of best Phi are "similar".
_DEFAULT_PHI_THRESHOLD_FRAC = 0.05
# High collinearity warning thresholds.
_VIF_WARN = 10.0
_CONDITION_WARN = 30.0
_CORRELATION_WARN = 0.8


# ─────────────────────────────────────────────────────────────────────────────
# Loading
# ─────────────────────────────────────────────────────────────────────────────


def load_posterior_ensemble(
    run_dir: str | Path,
    prefix: str,
    *,
    variance_tol: float = _ZERO_VARIANCE_TOL,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """Load the IES prior + posterior parameter ensembles and the bounds.

    Returns ``(prior, posterior, bounds, active_params)`` where ``active_params``
    is the list of parameter columns that vary in the posterior above
    ``variance_tol``. Zero-variance (held-constant) parameters are filtered out
    so correlation/PCA/VIF are not dominated by degenerate columns.
    """
    run_dir = Path(run_dir)
    prior = _read_par_iteration(run_dir, prefix, 0)
    posterior = _read_latest_par_iteration(run_dir, prefix)
    bounds = _read_bounds_from_pst(run_dir, prefix, posterior.columns)

    numeric_cols = [
        c for c in posterior.columns
        if c != "real_name" and pd.api.types.is_numeric_dtype(posterior[c])
    ]
    variances = posterior[numeric_cols].var(axis=0, ddof=0)
    active = [c for c in numeric_cols if variances.get(c, 0.0) > variance_tol]
    active = sorted(active, key=str.lower)
    if not active:
        raise ValueError(
            f"No parameters vary in the posterior ensemble above {variance_tol}; "
            "equifinality analysis requires at least one active parameter"
        )
    return prior, posterior, bounds, active


def _read_par_iteration(run_dir: Path, prefix: str, iteration: int) -> pd.DataFrame:
    path = run_dir / f"{prefix}.{iteration}.par.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Prior ensemble not found: {path}")
    df = pd.read_csv(path)
    # Normalise parameter column names to uppercase for DSSAT convention.
    rename = {c: str(c).strip().upper() for c in df.columns if c != "real_name"}
    return df.rename(columns=rename)


def _read_latest_par_iteration(run_dir: Path, prefix: str) -> pd.DataFrame:
    candidates = sorted(run_dir.glob(f"{prefix}.*.par.csv"))
    if not candidates:
        raise FileNotFoundError(f"No posterior ensemble found for prefix {prefix!r} in {run_dir}")
    # Skip iteration 0 (prior) — pick the highest iteration number.
    posterior_candidates = [p for p in candidates if not p.name.endswith(".0.par.csv")]
    if not posterior_candidates:
        posterior_candidates = candidates
    path = posterior_candidates[-1]
    df = pd.read_csv(path)
    rename = {c: str(c).strip().upper() for c in df.columns if c != "real_name"}
    return df.rename(columns=rename)


def _read_bounds_from_pst(run_dir: Path, prefix: str, param_columns) -> pd.DataFrame:
    """Extract per-parameter lower/upper/init bounds from the PEST control file."""
    pst_path = run_dir / f"{prefix}.pst"
    rows: list[dict[str, float]] = []
    if not pst_path.is_file():
        return pd.DataFrame(columns=["parameter", "lower", "upper", "init"])
    try:
        import pyemu  # local import — heavy dependency

        pst = pyemu.Pst(str(pst_path))
        pd_data = pst.parameter_data
        for name in param_columns:
            if name == "real_name":
                continue
            if name in pd_data.index:
                row = pd_data.loc[name]
                rows.append({
                    "parameter": str(name),
                    "lower": float(row.get("parlbnd", np.nan)),
                    "upper": float(row.get("parubnd", np.nan)),
                    "init": float(row.get("parval1", np.nan)),
                })
    except Exception:
        pass
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Posterior diagnostics (shrinkage, bounds, multimodality)
# ─────────────────────────────────────────────────────────────────────────────


def compute_posterior_diagnostics(
    prior: pd.DataFrame,
    posterior: pd.DataFrame,
    bounds: pd.DataFrame,
    active_params: list[str],
) -> pd.DataFrame:
    """Per-parameter prior/posterior summary, shrinkage, and bound proximity.

    Output columns (科研图表设计 line 121 extension):
    ``parameter, prior_mean, prior_median, prior_q05, prior_q95, prior_iqr,
    posterior_mean, posterior_median, posterior_q05, posterior_q95,
    posterior_iqr, iqr_shrinkage, var_shrinkage, frac_near_lower,
    frac_near_upper, multimodality_flag``
    """
    bounds_lookup = (
        bounds.set_index("parameter")[["lower", "upper"]]
        if not bounds.empty and "parameter" in bounds.columns
        else pd.DataFrame()
    )
    rows: list[dict[str, Any]] = []
    for p in active_params:
        prior_vals = pd.to_numeric(prior.get(p, pd.Series(dtype=float)), errors="coerce").dropna()
        post_vals = pd.to_numeric(posterior[p], errors="coerce").dropna()
        prior_iqr = float(prior_vals.quantile(0.75) - prior_vals.quantile(0.25)) if len(prior_vals) else np.nan
        post_iqr = float(post_vals.quantile(0.75) - post_vals.quantile(0.25)) if len(post_vals) else np.nan
        prior_var = float(prior_vals.var(ddof=0)) if len(prior_vals) > 1 else np.nan
        post_var = float(post_vals.var(ddof=0)) if len(post_vals) > 1 else np.nan
        lb = float(bounds_lookup.loc[p, "lower"]) if p in bounds_lookup.index else np.nan
        ub = float(bounds_lookup.loc[p, "upper"]) if p in bounds_lookup.index else np.nan
        rng = ub - lb if np.isfinite(lb) and np.isfinite(ub) else np.nan
        tol = max(1e-10, 1e-6 * abs(rng)) if np.isfinite(rng) else 1e-10
        frac_lb = float(np.mean(np.abs(post_vals - lb) <= tol)) if np.isfinite(lb) and len(post_vals) else np.nan
        frac_ub = float(np.mean(np.abs(post_vals - ub) <= tol)) if np.isfinite(ub) and len(post_vals) else np.nan
        rows.append({
            "parameter": p,
            "prior_mean": float(prior_vals.mean()) if len(prior_vals) else np.nan,
            "prior_median": float(prior_vals.median()) if len(prior_vals) else np.nan,
            "prior_q05": float(prior_vals.quantile(0.05)) if len(prior_vals) else np.nan,
            "prior_q95": float(prior_vals.quantile(0.95)) if len(prior_vals) else np.nan,
            "prior_iqr": prior_iqr,
            "posterior_mean": float(post_vals.mean()) if len(post_vals) else np.nan,
            "posterior_median": float(post_vals.median()) if len(post_vals) else np.nan,
            "posterior_q05": float(post_vals.quantile(0.05)) if len(post_vals) else np.nan,
            "posterior_q95": float(post_vals.quantile(0.95)) if len(post_vals) else np.nan,
            "posterior_iqr": post_iqr,
            "iqr_shrinkage": float(1.0 - post_iqr / prior_iqr) if prior_iqr and prior_iqr > 0 else np.nan,
            "var_shrinkage": float(1.0 - post_var / prior_var) if prior_var and prior_var > 0 else np.nan,
            "frac_near_lower": frac_lb,
            "frac_near_upper": frac_ub,
            "multimodality_flag": _detect_multimodality(post_vals.values),
        })
    return pd.DataFrame(rows)


def _detect_multimodality(values: np.ndarray) -> bool:
    """Heuristic: flag if the sorted values show a clear gap splitting into two halves."""
    values = np.sort(values[np.isfinite(values)])
    if len(values) < 8:
        return False
    mid = len(values) // 2
    lower_max = values[:mid].max()
    upper_min = values[mid:].min()
    total_range = values.max() - values.min()
    if total_range <= 0:
        return False
    gap_ratio = (upper_min - lower_max) / total_range
    return gap_ratio > _MULTIMODALITY_GAP_RATIO


# ─────────────────────────────────────────────────────────────────────────────
# 2. Correlation matrix (Pearson + Spearman)
# ─────────────────────────────────────────────────────────────────────────────


def compute_correlation_matrix(
    posterior: pd.DataFrame,
    active_params: list[str],
) -> pd.DataFrame:
    """Long-form Pearson + Spearman correlations between active parameters.

    Output columns: ``parameter_a, parameter_b, pearson, spearman``.
    Only unique pairs (a < b alphabetically) are emitted.
    """
    sub = posterior[active_params].apply(pd.to_numeric, errors="coerce")
    pearson = sub.corr(method="pearson")
    spearman = sub.corr(method="spearman")
    rows: list[dict[str, Any]] = []
    for a, b in combinations(sorted(active_params), 2):
        rows.append({
            "parameter_a": a,
            "parameter_b": b,
            "pearson": float(pearson.loc[a, b]) if a in pearson.index and b in pearson.columns else np.nan,
            "spearman": float(spearman.loc[a, b]) if a in spearman.index and b in spearman.columns else np.nan,
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 3. VIF + condition number
# ─────────────────────────────────────────────────────────────────────────────


def compute_vif_condition(
    posterior: pd.DataFrame,
    active_params: list[str],
) -> tuple[pd.DataFrame, float]:
    """Variance inflation factors and the standardized parameter-space condition number.

    VIF_j = 1 / (1 - R²_j), where R²_j is from regressing parameter j on all
    others. The condition number is ``sqrt(max_eigenvalue / min_eigenvalue)``
    of the standardized (z-scored) parameter correlation matrix — a standard
    collinearity diagnostic (Belsley et al.).
    """
    sub = posterior[active_params].apply(pd.to_numeric, errors="coerce").dropna()
    if len(sub) < len(active_params) + 1:
        # Underdetermined — VIF undefined; report condition only if possible.
        pass

    rows: list[dict[str, Any]] = []
    for j, target in enumerate(active_params):
        others = [p for p in active_params if p != target]
        if not others or len(sub) < len(others) + 2:
            rows.append({"parameter": target, "vif": np.nan, "r_squared": np.nan})
            continue
        y = sub[target].values
        X = sub[others].values
        X = np.column_stack([np.ones(len(X)), X])
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ beta
            ss_res = float(np.sum(resid ** 2))
            ss_tot = float(np.sum((y - y.mean()) ** 2))
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
            vif = 1.0 / (1.0 - r2) if (1.0 - r2) > 1e-12 else np.inf
        except Exception:
            r2 = np.nan
            vif = np.nan
        rows.append({"parameter": target, "vif": float(vif), "r_squared": float(r2)})

    # Standardized correlation matrix → eigenvalues → condition number.
    standardized = sub.apply(lambda c: (c - c.mean()) / (c.std(ddof=0) or 1.0))
    corr = standardized.cov().values  # covariance of z-scores == correlation
    try:
        eigenvalues = np.linalg.eigvalsh(corr)
        eigenvalues = np.sort(eigenvalues)[::-1]
        lam_max = float(eigenvalues[0])
        lam_min = float(eigenvalues[-1])
        condition_number = float(np.sqrt(lam_max / lam_min)) if lam_min > 1e-12 else np.inf
    except Exception:
        condition_number = np.nan
    return pd.DataFrame(rows), condition_number


# ─────────────────────────────────────────────────────────────────────────────
# 4. PCA with sqrt(lambda1/lambda2) axis ratio
# ─────────────────────────────────────────────────────────────────────────────


def compute_pca(
    posterior: pd.DataFrame,
    active_params: list[str],
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Standardized PCA on the active parameter posterior.

    Returns ``(loadings_df, metrics)`` where metrics includes:
    - ``explained_variance_ratio`` per component;
    - ``ellipse_axis_ratio`` = ``sqrt(lambda1 / lambda2)`` (PC1/PC2 eigenvalue ratio).
    """
    sub = posterior[active_params].apply(pd.to_numeric, errors="coerce").dropna()
    standardized = (sub - sub.mean()) / (sub.std(ddof=0).replace(0.0, 1.0))
    cov = standardized.cov().values
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    # Sort descending.
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]
    total = float(eigenvalues.sum())
    ratios = (eigenvalues / total).tolist() if total > 0 else []

    rows: list[dict[str, Any]] = []
    for comp_idx in range(len(active_params)):
        for param_idx, param in enumerate(active_params):
            rows.append({
                "component": comp_idx + 1,
                "parameter": param,
                "loading": float(eigenvectors[param_idx, comp_idx]),
                "eigenvalue": float(eigenvalues[comp_idx]),
                "explained_variance_ratio": float(ratios[comp_idx]) if comp_idx < len(ratios) else np.nan,
            })
    loadings = pd.DataFrame(rows)
    lam1 = float(eigenvalues[0]) if len(eigenvalues) else np.nan
    lam2 = float(eigenvalues[1]) if len(eigenvalues) > 1 else np.nan
    metrics = {
        "pc1_explained_variance_ratio": float(ratios[0]) if ratios else np.nan,
        "pc2_explained_variance_ratio": float(ratios[1]) if len(ratios) > 1 else np.nan,
        "ellipse_axis_ratio": float(np.sqrt(lam1 / lam2)) if np.isfinite(lam1) and np.isfinite(lam2) and lam2 > 0 else np.nan,
    }
    return loadings, metrics


# ─────────────────────────────────────────────────────────────────────────────
# 5. Functional equifinality
# ─────────────────────────────────────────────────────────────────────────────


def detect_functional_equifinality(
    posterior: pd.DataFrame,
    phi_df: pd.DataFrame,
    active_params: list[str],
    *,
    threshold_frac: float = _DEFAULT_PHI_THRESHOLD_FRAC,
) -> pd.DataFrame:
    """Find realization pairs with similar Phi but distant parameters.

    A pair is a *functional-equifinality candidate* if both realizations have
    Phi within ``threshold_frac`` of the best Phi, but their standardized
    parameter Euclidean distance exceeds the posterior median pairwise distance.

    Output columns (科研图表设计 line 123 contract):
    ``pair_id, real_a, real_b, phi_a, phi_b, phi_total, parameter_distance,
    prediction_distance`` (``prediction_distance`` left NaN pending
    deterministic representative reruns).
    """
    if phi_df.empty or "phi" not in phi_df.columns:
        return pd.DataFrame(columns=[
            "pair_id", "real_a", "real_b", "phi_a", "phi_b", "phi_total",
            "parameter_distance", "prediction_distance",
        ])
    # Use the final iteration's Phi per realization.
    final_iter = int(phi_df["iteration"].max())
    final_phi = phi_df[phi_df["iteration"] == final_iter].set_index("realization")["phi"]
    best_phi = float(final_phi.min())
    phi_band = best_phi * (1.0 + threshold_frac)
    good_reals = final_phi[final_phi <= phi_band].index.astype(str).tolist()
    if len(good_reals) < 2:
        return pd.DataFrame(columns=[
            "pair_id", "real_a", "real_b", "phi_a", "phi_b", "phi_total",
            "parameter_distance", "prediction_distance",
        ])

    # Standardized parameter space for distance.
    sub = posterior.set_index(posterior["real_name"].astype(str))[active_params]
    sub = sub.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    standardized = (sub - sub.mean()) / (sub.std(ddof=0).replace(0.0, 1.0))
    # All-pair distances among the full posterior for the median reference.
    all_dists: list[float] = []
    for a, b in combinations(standardized.index, 2):
        all_dists.append(float(np.linalg.norm(standardized.loc[a] - standardized.loc[b])))
    median_dist = float(np.median(all_dists)) if all_dists else np.nan

    rows: list[dict[str, Any]] = []
    pair_id = 0
    for a, b in combinations(good_reals, 2):
        if a not in standardized.index or b not in standardized.index:
            continue
        dist = float(np.linalg.norm(standardized.loc[a] - standardized.loc[b]))
        if dist > median_dist and np.isfinite(median_dist):
            phi_a = float(final_phi.loc[a]) if a in final_phi.index else np.nan
            phi_b = float(final_phi.loc[b]) if b in final_phi.index else np.nan
            pair_id += 1
            rows.append({
                "pair_id": pair_id,
                "real_a": a,
                "real_b": b,
                "phi_a": phi_a,
                "phi_b": phi_b,
                "phi_total": (phi_a + phi_b) / 2.0 if np.isfinite(phi_a) and np.isfinite(phi_b) else np.nan,
                "parameter_distance": dist,
                "prediction_distance": np.nan,  # Pending deterministic representative reruns.
            })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Quality report (warn-level, never fail)
# ─────────────────────────────────────────────────────────────────────────────


def assess_equifinality(
    run_dir: str | Path,
    prefix: str,
) -> tuple[QualityReport, dict[str, Any]]:
    """Assemble a warn-level QualityReport summarising equifinality signals.

    This does NOT reject a run — per plan §5 line 172, automatic equifinality
    judgement is out of scope for this phase. It records the signals for human
    review: max |correlation|, max VIF, condition number, PC1 explained
    variance, functional-equifinality pair count.
    """
    run_dir = Path(run_dir)
    prior, posterior, bounds, active = load_posterior_ensemble(run_dir, prefix)
    diagnostics = compute_posterior_diagnostics(prior, posterior, bounds, active)
    correlation = compute_correlation_matrix(posterior, active)
    vif_df, condition = compute_vif_condition(posterior, active)
    pca_loadings, pca_metrics = compute_pca(posterior, active)
    phi_df = _load_phi(run_dir, prefix)
    func_pairs = detect_functional_equifinality(posterior, phi_df, active)

    max_corr = float(correlation[["pearson", "spearman"]].abs().max().max()) if not correlation.empty else np.nan
    max_vif = float(vif_df["vif"].max()) if not vif_df.empty and "vif" in vif_df.columns else np.nan

    report = QualityReport(run_type="equifinality", run_id=run_dir.name)
    report.add(
        "process_completed", True, "Posterior ensemble loaded and diagnostics computed",
        actual={"active_params": len(active), "posterior_realizations": len(posterior)},
        threshold={"active_params": 1},
    )
    report.add(
        "equifinality_max_correlation",
        not (np.isfinite(max_corr) and max_corr > _CORRELATION_WARN),
        "Strongest parameter correlation (|r|)",
        actual=max_corr, threshold=_CORRELATION_WARN,
        warning=True,
    )
    report.add(
        "equifinality_max_vif",
        not (np.isfinite(max_vif) and max_vif > _VIF_WARN),
        "Maximum variance inflation factor",
        actual=max_vif, threshold=_VIF_WARN,
        warning=True,
    )
    report.add(
        "equifinality_condition_number",
        not (np.isfinite(condition) and condition > _CONDITION_WARN),
        "Standardized parameter-space condition number",
        actual=condition, threshold=_CONDITION_WARN,
        warning=True,
    )
    report.add(
        "equifinality_functional_pairs",
        True,
        "Functional-equifinality candidate pairs (similar Phi, distant params)",
        actual=len(func_pairs),
        warning=True,
    )

    artifacts = {
        "diagnostics": diagnostics,
        "correlation": correlation,
        "vif": vif_df,
        "condition_number": condition,
        "pca_loadings": pca_loadings,
        "pca_metrics": pca_metrics,
        "functional_pairs": func_pairs,
        "active_params": active,
    }
    return report, artifacts


def _load_phi(run_dir: Path, prefix: str) -> pd.DataFrame:
    """Load the IES Phi history in long form (iteration, realization, phi)."""
    phi_path = run_dir / f"{prefix}.phi.actual.csv"
    if not phi_path.is_file():
        return pd.DataFrame(columns=["iteration", "realization", "phi"])
    wide = pd.read_csv(phi_path)
    summary_cols = {"iteration", "total_runs", "mean", "standard_deviation", "std", "min", "max", "base"}
    real_cols = [c for c in wide.columns if c not in summary_cols]
    if not real_cols:
        return pd.DataFrame(columns=["iteration", "realization", "phi"])
    long = wide.melt(id_vars=["iteration"], value_vars=real_cols, var_name="realization", value_name="phi")
    long["iteration"] = pd.to_numeric(long["iteration"], errors="coerce")
    long["phi"] = pd.to_numeric(long["phi"], errors="coerce")
    return long.dropna(subset=["iteration", "phi"]).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Output + CLI
# ─────────────────────────────────────────────────────────────────────────────


def write_equifinality_outputs(
    out_dir: str | Path,
    report: QualityReport,
    artifacts: dict[str, Any],
    *,
    run_dir: Path,
    prefix: str,
) -> Path:
    """Write the frozen CSV contracts + quality + manifest."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def _write(df: pd.DataFrame, name: str) -> Path:
        path = out_dir / name
        df.to_csv(path, index=False, encoding="utf-8")
        written.append(path)
        return path

    _write(artifacts["diagnostics"], "posterior_diagnostics.csv")
    _write(artifacts["correlation"], "parameter_correlation.csv")
    _write(artifacts["vif"], "vif_condition.csv")
    _write(artifacts["pca_loadings"], "pca_loadings.csv")
    _write(artifacts["functional_pairs"], "functional_equifinality_pairs.csv")

    # Condition number is a scalar — embed in vif CSV as a sidecar metric CSV.
    pd.DataFrame([{
        "metric": "condition_number",
        "value": artifacts["condition_number"],
    }, {
        "metric": "ellipse_axis_ratio",
        "value": artifacts["pca_metrics"].get("ellipse_axis_ratio", np.nan),
    }, {
        "metric": "pc1_explained_variance_ratio",
        "value": artifacts["pca_metrics"].get("pc1_explained_variance_ratio", np.nan),
    }]).to_csv(out_dir / "collinearity_metrics.csv", index=False, encoding="utf-8")
    written.append(out_dir / "collinearity_metrics.csv")

    # Quality report.
    quality_path = out_dir / "equifinality_quality.json"
    quality_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    written.append(quality_path)

    # Manifest with SHA-256 of every artifact + run provenance.
    payload: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_dir": str(run_dir.resolve()),
        "prefix": prefix,
        "active_params": artifacts["active_params"],
        "artifacts": [{"path": p.name, "sha256": sha256_file(p)} for p in written],
    }
    manifest_path = out_dir / "equifinality_manifest.json"
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Equifinality diagnostics for IES posterior ensembles")
    parser.add_argument("--run-dir", required=True, help="IES run directory containing .par.csv/.phi.actual.csv")
    parser.add_argument("--prefix", required=True, help="PEST case prefix (e.g. eggplant_stage2_v4_sobol20)")
    parser.add_argument("--out-dir", required=True, help="Output directory for frozen CSV contracts")
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir)
    report, artifacts = assess_equifinality(run_dir, args.prefix)
    manifest = write_equifinality_outputs(
        args.out_dir, report, artifacts, run_dir=run_dir, prefix=args.prefix
    )
    print(f"Equifinality diagnostics written to {args.out_dir}")
    print(f"Status: {report.status} | science_validated: {report.science_validated}")
    print(f"Active params: {len(artifacts['active_params'])}")
    print(f"Condition number: {artifacts['condition_number']:.2f}")
    print(f"Max |correlation|: {artifacts['correlation'][['pearson','spearman']].abs().max().max():.3f}")
    print(f"Functional-equifinality pairs: {len(artifacts['functional_pairs'])}")
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
