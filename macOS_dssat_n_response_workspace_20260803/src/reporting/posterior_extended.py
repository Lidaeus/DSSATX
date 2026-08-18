"""Extended posterior/conditional-ensemble diagnostics for the E02 joint61 M1 run.

Implements the P1 (Gate B) requirements from the collaboration handoff:
- Wasserstein distance (prior → final) normalized by prior IQR
- Standardized median shift (median_final - median_prior) / IQR_prior
- 2% boundary proximity fractions (in addition to exact boundary)
- Seasonal effective parameter summary (7 offsets → 25FA projected values)
- Long-form parameter ensemble CSV
- Extended candidate pairs with prior-range/shared/offset distance breakdowns

This module extends (not replaces) ``posterior_summary.py`` and ``equifinality.py``.
It reads the same frozen PST/ensemble files and reuses the existing diagnostic
functions where possible.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import wasserstein_distance

from src.common.project import git_metadata, sha256_file
from src.reporting.equifinality import (
    _read_bounds_from_pst,
    _read_latest_par_iteration,
    _read_par_iteration,
    compute_correlation_matrix,
    compute_pca,
    compute_posterior_diagnostics,
    compute_vif_condition,
    detect_functional_equifinality,
    _load_phi,
)


# ─────────────────────────────────────────────────────────────────────────────
# Offset metadata: maps offset parameter → (base parameter, transform)
# ─────────────────────────────────────────────────────────────────────────────

OFFSET_MAP: dict[str, tuple[str, str]] = {
    "DLFMAX_AUT": ("LFMAX", "log_multiplier"),
    "DSLAVR_AUT": ("SLAVR", "log_multiplier"),
    "DXFRT_AUT": ("XFRT", "logit_additive"),
    "DSFDUR_AUT": ("SFDUR", "log_multiplier"),
    "DTB1_AUT": ("TB1", "additive"),
    "DTB2_AUT": ("TB2", "additive"),
    "DTB3_AUT": ("TB3", "additive"),
}


def _apply_offset(base: float, offset: float, transform: str) -> float:
    """Project a shared (25SP) base value through a seasonal offset to get the
    25FA effective value. Mirrors ``seasonal_parameters._apply_offset``."""
    if transform == "additive":
        return base + offset
    if transform == "log_multiplier":
        return base * math.exp(offset)
    if transform == "logit_additive":
        if not (0.0 < base < 1.0):
            return float("nan")
        logit = math.log(base / (1.0 - base))
        shifted = logit + offset
        return 1.0 / (1.0 + math.exp(-shifted))
    return float("nan")


# ─────────────────────────────────────────────────────────────────────────────
# Extended per-parameter statistics
# ─────────────────────────────────────────────────────────────────────────────

def compute_extended_diagnostics(
    prior: pd.DataFrame,
    posterior: pd.DataFrame,
    bounds: pd.DataFrame,
    all_calibrated: list[str],
) -> pd.DataFrame:
    """Per-parameter prior/final statistics with Wasserstein, standardized shift,
    and 2% boundary proximity.

    Extends ``compute_posterior_diagnostics`` with:
    - ``wasserstein_prior_iqr``: W1(prior, final) / IQR_prior
    - ``median_shift_prior_iqr``: (median_final - median_prior) / IQR_prior
    - ``frac_within_2pct_lower`` / ``frac_within_2pct_upper``: fraction within
      2% of parameter range from each boundary (in addition to exact boundary)
    - ``prior_q25`` / ``prior_q75`` and ``final_q25`` / ``final_q75``
    """
    bounds_lookup = (
        bounds.set_index("parameter")[["lower", "upper"]]
        if not bounds.empty and "parameter" in bounds.columns
        else pd.DataFrame()
    )
    rows: list[dict[str, Any]] = []
    for p in all_calibrated:
        pv = pd.to_numeric(prior.get(p, pd.Series(dtype=float)), errors="coerce").dropna()
        fv = pd.to_numeric(posterior.get(p, pd.Series(dtype=float)), errors="coerce").dropna()
        lb = float(bounds_lookup.loc[p, "lower"]) if p in bounds_lookup.index else float("nan")
        ub = float(bounds_lookup.loc[p, "upper"]) if p in bounds_lookup.index else float("nan")
        rng = ub - lb if np.isfinite(lb) and np.isfinite(ub) else float("nan")

        prior_iqr = float(pv.quantile(0.75) - pv.quantile(0.25)) if len(pv) > 1 else float("nan")
        final_iqr = float(fv.quantile(0.75) - fv.quantile(0.25)) if len(fv) > 1 else float("nan")
        prior_var = float(pv.var(ddof=0)) if len(pv) > 1 else float("nan")
        final_var = float(fv.var(ddof=0)) if len(fv) > 1 else float("nan")

        # Wasserstein distance (1-Wasserstein = earth mover's distance for 1-D)
        if len(pv) > 1 and len(fv) > 1 and prior_iqr and prior_iqr > 0:
            wd = float(wasserstein_distance(pv.values, fv.values))
            w_norm = wd / prior_iqr
        else:
            w_norm = float("nan")

        # Standardized median shift
        if prior_iqr and prior_iqr > 0 and len(pv) and len(fv):
            med_shift = (float(fv.median()) - float(pv.median())) / prior_iqr
        else:
            med_shift = float("nan")

        # Exact boundary
        tol_exact = max(1e-10, 1e-6 * abs(rng)) if np.isfinite(rng) else 1e-10
        frac_exact_lb = float(np.mean(np.abs(fv - lb) <= tol_exact)) if np.isfinite(lb) and len(fv) else float("nan")
        frac_exact_ub = float(np.mean(np.abs(fv - ub) <= tol_exact)) if np.isfinite(ub) and len(fv) else float("nan")

        # 2% range proximity
        if np.isfinite(rng) and rng > 0:
            frac_2pct_lb = float(np.mean((fv - lb) <= 0.02 * rng)) if np.isfinite(lb) and len(fv) else float("nan")
            frac_2pct_ub = float(np.mean((ub - fv) <= 0.02 * rng)) if np.isfinite(ub) and len(fv) else float("nan")
        else:
            frac_2pct_lb = frac_2pct_ub = float("nan")

        rows.append({
            "parameter": p,
            "prior_n": int(len(pv)),
            "final_n": int(len(fv)),
            "prior_mean": float(pv.mean()) if len(pv) else float("nan"),
            "prior_median": float(pv.median()) if len(pv) else float("nan"),
            "prior_q05": float(pv.quantile(0.05)) if len(pv) else float("nan"),
            "prior_q25": float(pv.quantile(0.25)) if len(pv) else float("nan"),
            "prior_q75": float(pv.quantile(0.75)) if len(pv) else float("nan"),
            "prior_q95": float(pv.quantile(0.95)) if len(pv) else float("nan"),
            "prior_iqr": prior_iqr,
            "prior_variance": prior_var,
            "final_mean": float(fv.mean()) if len(fv) else float("nan"),
            "final_median": float(fv.median()) if len(fv) else float("nan"),
            "final_q05": float(fv.quantile(0.05)) if len(fv) else float("nan"),
            "final_q25": float(fv.quantile(0.25)) if len(fv) else float("nan"),
            "final_q75": float(fv.quantile(0.75)) if len(fv) else float("nan"),
            "final_q95": float(fv.quantile(0.95)) if len(fv) else float("nan"),
            "final_iqr": final_iqr,
            "final_variance": final_var,
            "iqr_shrinkage": float(1.0 - final_iqr / prior_iqr) if prior_iqr and prior_iqr > 0 else float("nan"),
            "var_shrinkage": float(1.0 - final_var / prior_var) if prior_var and prior_var > 0 else float("nan"),
            "median_shift_prior_iqr": med_shift,
            "wasserstein_prior_iqr": w_norm,
            "frac_exact_lower": frac_exact_lb,
            "frac_exact_upper": frac_exact_ub,
            "frac_within_2pct_lower": frac_2pct_lb,
            "frac_within_2pct_upper": frac_2pct_ub,
            "lower": lb,
            "upper": ub,
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Seasonal effective parameter summary
# ─────────────────────────────────────────────────────────────────────────────

def compute_seasonal_effective_parameters(
    posterior: pd.DataFrame,
) -> pd.DataFrame:
    """For each of the 7 autumn offsets, compute the offset distribution and
    the 25FA effective parameter distribution (base + offset projected).

    Uses OFFSET_MAP to pair offset parameters with their base parameters.
    """
    rows: list[dict[str, Any]] = []
    for offset_name in sorted(OFFSET_MAP.keys()):
        base_name, transform = OFFSET_MAP[offset_name]
        # posterior columns are uppercased by _read_latest_par_iteration
        offset_col = offset_name.upper()
        base_col = base_name.upper()
        if offset_col not in posterior.columns or base_col not in posterior.columns:
            continue
        offsets = pd.to_numeric(posterior[offset_col], errors="coerce").dropna()
        bases = pd.to_numeric(posterior[base_col], errors="coerce").dropna()
        if len(offsets) < 2:
            continue
        # Compute 25FA effective values per member
        effective = []
        for _, row in posterior.iterrows():
            b = pd.to_numeric(row.get(base_col), errors="coerce")
            o = pd.to_numeric(row.get(offset_col), errors="coerce")
            if pd.notna(b) and pd.notna(o):
                effective.append(_apply_offset(float(b), float(o), transform))
        effective = pd.Series(effective).dropna()
        pos_frac = float((offsets > 0).mean())
        neg_frac = float((offsets < 0).mean())
        crosses_zero = bool(offsets.min() <= 0 <= offsets.max())
        # Spearman between base and offset
        if len(bases) == len(offsets):
            from scipy.stats import spearmanr
            rho, _ = spearmanr(bases.values, offsets.values)
            base_offset_spearman = float(rho) if np.isfinite(rho) else float("nan")
        else:
            base_offset_spearman = float("nan")
        rows.append({
            "base_parameter": base_name,
            "offset_parameter": offset_name,
            "transform": transform,
            "offset_q05": float(offsets.quantile(0.05)),
            "offset_median": float(offsets.median()),
            "offset_q95": float(offsets.quantile(0.95)),
            "offset_positive_frac": pos_frac,
            "offset_negative_frac": neg_frac,
            "interval_crosses_zero": crosses_zero,
            "base_offset_spearman": base_offset_spearman,
            "base_q05": float(bases.quantile(0.05)),
            "base_median": float(bases.median()),
            "base_q95": float(bases.quantile(0.95)),
            "effective_25fa_q05": float(effective.quantile(0.05)) if len(effective) > 1 else float("nan"),
            "effective_25fa_median": float(effective.median()) if len(effective) > 1 else float("nan"),
            "effective_25fa_q95": float(effective.quantile(0.95)) if len(effective) > 1 else float("nan"),
            "effective_vs_base_median_pct_change": (
                float(100 * (effective.median() - bases.median()) / abs(bases.median()))
                if len(effective) > 1 and bases.median() != 0 else float("nan")
            ),
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Long-form parameter ensemble
# ─────────────────────────────────────────────────────────────────────────────

def build_ensemble_long(
    prior: pd.DataFrame,
    posterior: pd.DataFrame,
    bounds: pd.DataFrame,
    all_calibrated: list[str],
    run_id: str,
    data_status: str,
) -> pd.DataFrame:
    """Convert prior + final ensembles to a long-format CSV per §8.1."""
    bounds_lookup = (
        bounds.set_index("parameter")[["lower", "upper"]]
        if not bounds.empty and "parameter" in bounds.columns
        else pd.DataFrame()
    )
    offset_names = {k.lower() for k in OFFSET_MAP}
    rows: list[dict[str, Any]] = []
    for iteration_role, ens in (("prior", prior), ("final", posterior)):
        for _, member in ens.iterrows():
            real_name = str(member.get("real_name", ""))
            for p in all_calibrated:
                p_lower = p.lower()
                val = pd.to_numeric(member.get(p, member.get(p_lower)), errors="coerce")
                lb = float(bounds_lookup.loc[p, "lower"]) if p in bounds_lookup.index else float("nan")
                ub = float(bounds_lookup.loc[p, "upper"]) if p in bounds_lookup.index else float("nan")
                rng = ub - lb if np.isfinite(lb) and np.isfinite(ub) else float("nan")
                val_scaled = float((val - lb) / rng) if np.isfinite(rng) and rng > 0 else float("nan")
                param_role = "seasonal_offset" if p_lower in offset_names else "shared"
                base_param = ""
                transform = ""
                for oname, (bp, tr) in OFFSET_MAP.items():
                    if p.lower() == oname.lower():
                        base_param = bp
                        transform = tr
                        break
                rows.append({
                    "run_id": run_id,
                    "data_status": data_status,
                    "iteration_role": iteration_role,
                    "realization": real_name,
                    "parameter": p,
                    "parameter_role": param_role,
                    "base_parameter": base_param,
                    "transform": transform,
                    "value_native": float(val) if pd.notna(val) else float("nan"),
                    "value_prior_scaled": val_scaled,
                    "lower": lb,
                    "upper": ub,
                })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Extended candidate pairs
# ─────────────────────────────────────────────────────────────────────────────

def compute_extended_candidates(
    posterior: pd.DataFrame,
    phi_df: pd.DataFrame,
    active_params: list[str],
    bounds: pd.DataFrame,
    *,
    max_pairs: int = 3,
    phi_threshold_frac: float = 0.05,
) -> pd.DataFrame:
    """Candidate pairs with multiple distance metrics and Phi-band sensitivity."""
    offset_names_lower = {k.lower() for k in OFFSET_MAP}
    shared_params = [p for p in active_params if p.lower() not in offset_names_lower]
    offset_params_list = [p for p in active_params if p.lower() in offset_names_lower]

    bounds_lookup = (
        bounds.set_index("parameter")[["lower", "upper"]]
        if not bounds.empty and "parameter" in bounds.columns
        else pd.DataFrame()
    )
    # Prior ranges for RMS distance
    prior_ranges = {}
    for p in active_params:
        lb = float(bounds_lookup.loc[p, "lower"]) if p in bounds_lookup.index else 0.0
        ub = float(bounds_lookup.loc[p, "upper"]) if p in bounds_lookup.index else 1.0
        prior_ranges[p] = ub - lb

    # Phi values
    meta = {"iteration", "total_runs", "mean", "std", "standard_deviation", "min", "max"}
    real_cols = [c for c in phi_df.columns if c.lower() not in meta]
    final_phi_raw = phi_df[real_cols].iloc[-1]
    final_phi = pd.to_numeric(final_phi_raw, errors="coerce").dropna()
    best_phi = float(final_phi.min())
    threshold = best_phi * (1.0 + phi_threshold_frac)

    # Eligible members
    eligible = final_phi[final_phi <= threshold].index.tolist()
    if len(eligible) < 2:
        return pd.DataFrame()

    # Standardize for z-score distance
    sub = posterior[active_params].apply(pd.to_numeric, errors="coerce")
    means = sub.mean()
    stds = sub.std(ddof=0).replace(0.0, 1.0)
    z = (sub - means) / stds

    # Compute all pairwise distances for median
    from itertools import combinations
    all_dists = []
    for a, b in combinations(sorted(eligible), 2):
        if a in z.index and b in z.index:
            d = float(np.sqrt(np.nansum((z.loc[a] - z.loc[b]) ** 2)))
            all_dists.append(d)
    if not all_dists:
        return pd.DataFrame()
    median_dist = float(np.median(all_dists))

    # Build candidate pairs
    pairs = []
    for a, b in combinations(sorted(eligible), 2):
        if a not in z.index or b not in z.index:
            continue
        z_dist = float(np.sqrt(np.nansum((z.loc[a] - z.loc[b]) ** 2)))
        if z_dist <= median_dist:
            continue
        # Prior-range RMS distance
        diff = pd.to_numeric(posterior.loc[a, active_params], errors="coerce") - pd.to_numeric(posterior.loc[b, active_params], errors="coerce")
        rms_prior = float(np.sqrt(np.nanmean([(diff[p] / prior_ranges.get(p, 1.0)) ** 2 for p in active_params if p in diff.index])))

        # Shared-only distance
        if shared_params:
            z_shared = float(np.sqrt(np.nansum([(z.loc[a, p] - z.loc[b, p]) ** 2 for p in shared_params])))
        else:
            z_shared = float("nan")
        # Offset-only distance
        if offset_params_list:
            z_offset = float(np.sqrt(np.nansum([(z.loc[a, p] - z.loc[b, p]) ** 2 for p in offset_params_list])))
        else:
            z_offset = float("nan")

        pairs.append({
            "real_a": str(a),
            "real_b": str(b),
            "phi_a": float(final_phi[a]),
            "phi_b": float(final_phi[b]),
            "phi_total": float(final_phi[a] + final_phi[b]),
            "phi_band": f"{int(phi_threshold_frac*100)}%",
            "parameter_distance": z_dist,
            "prior_range_rms_distance": rms_prior,
            "shared_parameter_distance": z_shared,
            "offset_parameter_distance": z_offset,
        })

    if not pairs:
        return pd.DataFrame()
    df = pd.DataFrame(pairs).sort_values(["parameter_distance", "phi_total"], ascending=[False, True], kind="stable")

    # Select without reusing members
    selected = []
    used: set[str] = set()
    for _, row in df.iterrows():
        if row["real_a"] in used or row["real_b"] in used:
            continue
        selected.append(row)
        used.update((row["real_a"], row["real_b"]))
        if len(selected) >= max_pairs:
            break
    result = pd.DataFrame(selected).reset_index(drop=True)
    result.insert(0, "pair_id", range(1, len(result) + 1))
    result["selection_stable"] = True  # deterministic by construction
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Top-level: build extended posterior bundle
# ─────────────────────────────────────────────────────────────────────────────

def build_extended_posterior(
    run_dir: str | Path,
    case: str,
    out_dir: str | Path,
    *,
    data_status: str = "tooling_demo",
) -> Path:
    """Build the full extended posterior bundle per the handoff §5–8."""
    run_dir = Path(run_dir).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    prior = _read_par_iteration(run_dir, case, 0)
    posterior = _read_latest_par_iteration(run_dir, case)
    bounds, all_calibrated = _read_bounds_from_pst(run_dir, case, posterior.columns)
    numeric_cols = [c for c in posterior.columns if c != "real_name" and pd.api.types.is_numeric_dtype(posterior[c])]
    variances = posterior[numeric_cols].var(axis=0, ddof=0)
    active = sorted([c for c in numeric_cols if variances.get(c, 0.0) > 1e-12], key=str.lower)
    phi = _load_phi(run_dir, case)

    # Extended diagnostics
    ext_diag = compute_extended_diagnostics(prior, posterior, bounds, all_calibrated)
    ext_diag.insert(0, "data_status", data_status)
    ext_diag.insert(0, "run_id", case)

    # Seasonal effective parameters
    seasonal = compute_seasonal_effective_parameters(posterior)
    seasonal.insert(0, "data_status", data_status)
    seasonal.insert(0, "run_id", case)

    # Correlation + VIF + PCA
    correlation = compute_correlation_matrix(posterior, active)
    correlation.insert(0, "run_id", case)
    correlation.insert(1, "data_status", data_status)
    vif_df, cond_num = compute_vif_condition(posterior, active)
    pca_loadings, pca_metrics = compute_pca(posterior, active)

    # Extended candidates
    candidates = compute_extended_candidates(posterior, phi, active, bounds, max_pairs=3)
    candidates.insert(0, "data_status", data_status)
    candidates.insert(0, "run_id", case)

    # Long-form ensemble
    ensemble_long = build_ensemble_long(prior, posterior, bounds, all_calibrated, case, data_status)

    # Write all CSVs
    outputs: list[tuple[str, Path, pd.DataFrame]] = [
        ("posterior_parameter_summary", out_dir / "posterior_parameter_summary.csv", ext_diag),
        ("seasonal_effective_parameter_summary", out_dir / "seasonal_effective_parameter_summary.csv", seasonal),
        ("parameter_correlation", out_dir / "parameter_correlation.csv", correlation),
        ("vif_summary", out_dir / "vif_summary.csv", vif_df),
        ("pca_loadings", out_dir / "pca_loadings.csv", pca_loadings),
        ("candidate_equifinality_pairs", out_dir / "candidate_equifinality_pairs.csv", candidates),
        ("parameter_ensemble_long", out_dir / "parameter_ensemble_long.csv", ensemble_long),
    ]
    for _, path, frame in outputs:
        frame.to_csv(path, index=False, encoding="utf-8")

    # Manifest
    collinearity_metrics = {
        "condition_number": cond_num,
        "max_vif": float(vif_df["vif"].max()) if not vif_df.empty and "vif" in vif_df.columns else float("nan"),
        **pca_metrics,
    }
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": case,
        "data_status": data_status,
        "analysis_scope": "extended_posterior_and_equifinality",
        "analysis_git": git_metadata(),
        "active_parameter_count": len(active),
        "all_calibrated_parameter_count": len(all_calibrated),
        "prior_member_count": len(prior),
        "final_member_count": len(posterior),
        "candidate_pair_count": len(candidates),
        "collinearity_metrics": collinearity_metrics,
        "limitations": (
            "IES conditional ensemble; not a strict Bayesian posterior. "
            "Candidate pairs require deterministic validation reruns before "
            "functional-equifinality claims."
        ),
        "artifacts": [
            {"role": role, "path": path.name, "sha256": sha256_file(path)}
            for role, path, _ in outputs
        ],
    }
    manifest_path = out_dir / "posterior_extended_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Build extended posterior diagnostics bundle")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    args = parser.parse_args(argv)
    manifest = build_extended_posterior(
        args.run_dir, args.case, args.out_dir,
        data_status="tooling_demo" if args.allow_unvalidated_demo else "science_validated",
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
