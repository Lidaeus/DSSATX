"""WP3: audit the local Jacobian of a PEST-GLM pilot run (plan 20260818 §9-WP3).

Reads the ``<case>.jcb`` produced by pestpp-glm after its derivative runs and
writes, into ``<run_dir>/glm_quality/``:

* ``jacobian_parameter_sensitivity.csv`` — composite scaled sensitivity per
  parameter, reported on the raw and range-scaled Jacobian, aggregated over
  ALL / DRY_CUM / N_RESPONSE / W_RESPONSE / ORGAN objective subsets.
* ``jacobian_column_correlation.csv`` — weighted-Jacobian column correlations.
* ``jacobian_singular_values.csv`` — SVD spectrum with effective rank at the
  ``eigthresh`` cutoff and the condition number.
* ``derivative_step_stability.csv`` — compares multiple labelled Jacobians
  (e.g. derinc 0.5% / 1% / 2%); with a single Jacobian it records that only
  one step size is available and flags parameters as unverified.
* ``recommended_formal_parameter_set.csv`` — ranked, collinearity-pruned set
  for the formal GLM (plan §7 stage-3 cap: 10-18 parameters).
* ``jacobian_audit.json`` — machine-readable summary and thresholds.

Usage:
    python tools/calibration/analyze_glm_jacobian_20260818.py --run-dir <dir> [--case <case>]
        [--jcb path[:label] ...] [--max-formal-params 18]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EIGTHRESH = 1.0e-6          # PEST++ default singular-value cutoff
CORRELATION_DROP = 0.98     # above this the lower-CSS member of a pair is dropped
MIN_CSS_FRACTION = 0.01     # keep parameters with CSS >= 1% of the maximum CSS
# Vector-stability thresholds (pairwise across derivative step sizes).
STABILITY_MIN_COSINE = 0.70
STABILITY_MIN_SIGN_AGREEMENT = 0.80


def family_of(obgnme: str) -> str:
    """Map a PEST observation group to an objective family for aggregation."""
    g = str(obgnme).strip().upper()
    if "NRESP" in g:
        return "N_RESPONSE"
    if "WRESP" in g:
        return "W_RESPONSE"
    # The formal dry-NSE PST assigns all cumulative-dry observations (CHPDTS
    # terminal + CHPDTS_T intermediate, both seasons) to the single 'drynse'
    # group; legacy per-harvest group names are also accepted.
    if g == "DRYNSE" or "CHPDTS" in g or "CHPDTM" in g:
        return "DRY_CUM"
    if any(tok in g for tok in ("LAID", "LWAD", "SWAD", "CHTD")):
        return "ORGAN"
    return "OTHER"


def load_jacobian(path: Path) -> tuple[pd.DataFrame, pd.Series]:
    """Return (jacobian DataFrame [obs x par], observation weights Series)."""
    jco = pyemu.Jco.from_binary(str(path))
    frame = jco.to_dataframe()
    weights = (frame.index.get_level_values(0)
               if isinstance(frame.index, pd.MultiIndex) else pd.Series(index=frame.index))
    return frame, weights


def load_weights_from_pst(pst_path: Path) -> pd.Series:
    pst = pyemu.Pst(str(pst_path))
    return pst.observation_data["weight"].astype(float)


def composite_sensitivities(
    jacobian: pd.DataFrame, weights: pd.Series, ranges: pd.Series, families: pd.Series
) -> pd.DataFrame:
    """CSS on the raw and range-scaled weighted Jacobian, per family subset."""
    common = [o for o in jacobian.index if o in weights.index]
    j = jacobian.loc[common]
    w = weights.loc[common].to_numpy(float)
    fam = families.loc[common].to_numpy()
    wj = j.to_numpy(float) * w[:, None]          # weighted Jacobian
    scaled = wj * ranges.loc[j.columns].to_numpy(float)[None, :]  # dimensionless

    scopes = [("ALL", np.ones(len(common), dtype=bool))]
    for f in ("DRY_CUM", "N_RESPONSE", "W_RESPONSE", "ORGAN"):
        scopes.append((f, fam == f))
    rows: list[dict] = []
    for scope, mask in scopes:
        if not mask.any():
            continue
        block = wj[mask]
        block_scaled = scaled[mask]
        for i, name in enumerate(j.columns):
            rows.append({
                "scope": scope,
                "parameter": name,
                "css_raw": float(np.sqrt(np.square(block[:, i]).sum())),
                "css_scaled": float(np.sqrt(np.square(block_scaled[:, i]).sum())),
                "n_obs": int(mask.sum()),
            })
    return pd.DataFrame(rows)


def column_correlations(jacobian: pd.DataFrame, weights: pd.Series) -> pd.DataFrame:
    common = [o for o in jacobian.index if o in weights.index]
    wj = (jacobian.loc[common].to_numpy(float)
          * weights.loc[common].to_numpy(float)[:, None])
    corr = pd.DataFrame(np.corrcoef(wj, rowvar=False),
                        index=jacobian.columns, columns=jacobian.columns)
    return corr


def singular_values(jacobian: pd.DataFrame, weights: pd.Series,
                    ranges: pd.Series | None = None) -> tuple[pd.DataFrame, dict]:
    """SVD spectrum of the weighted Jacobian, range-scaled for unit invariance.

    Raw weighted Jacobians mix parameter units, so singular values, effective
    rank and condition number depend on the unit system.  The primary spectrum
    uses ``WJ @ diag(upper - lower)``; the raw spectrum is reported alongside
    for traceability only.
    """
    common = [o for o in jacobian.index if o in weights.index]
    wj = jacobian.loc[common].to_numpy(float) * weights.loc[common].to_numpy(float)[:, None]
    if ranges is not None:
        scale = ranges.loc[jacobian.columns].to_numpy(float)
        scaled = wj * scale[None, :]
    else:
        scaled = wj

    def spectrum(matrix: np.ndarray) -> tuple[np.ndarray, dict]:
        s = np.linalg.svd(matrix, compute_uv=False)
        if s.size == 0 or s[0] <= 0:
            return s, {"effective_rank": 0, "condition_number": float("inf"),
                       "min_singular_value": 0.0, "max_singular_value": 0.0}
        ratios = s / s[0]
        keep = ratios > EIGTHRESH
        effective_rank = int(keep.sum())
        summary = {
            "effective_rank": effective_rank,
            "condition_number": float(s[0] / s[keep][-1]) if effective_rank else float("inf"),
            "min_singular_value": float(s[-1]),
            "max_singular_value": float(s[0]),
        }
        return s, summary

    s_scaled, summary_scaled = spectrum(scaled)
    _, summary_raw = spectrum(wj)
    summary = {
        "eigthresh": EIGTHRESH,
        "n_singular_values": int(s_scaled.size),
        "scaling": "weighted_jacobian_times_parameter_ranges",
        **{f"range_scaled_{k}": v for k, v in summary_scaled.items()},
        **{f"raw_{k}": v for k, v in summary_raw.items()},
        # Back-compat aliases: the primary rank/condition numbers are the
        # range-scaled ones.
        "effective_rank": summary_scaled["effective_rank"],
        "condition_number": summary_scaled["condition_number"],
    }
    if s_scaled.size == 0:
        frame = pd.DataFrame(columns=["index", "singular_value", "ratio_to_max"])
        return frame, summary
    ratios = s_scaled / s_scaled[0]
    frame = pd.DataFrame({
        "index": np.arange(1, s_scaled.size + 1),
        "singular_value": s_scaled,
        "ratio_to_max": ratios,
        "above_eigthresh": ratios > EIGTHRESH,
    })
    return frame, summary


def _derivative_columns(jacobian: pd.DataFrame, weights: pd.Series) -> dict[str, np.ndarray]:
    common = [o for o in jacobian.index if o in weights.index]
    wj = jacobian.loc[common].to_numpy(float) * weights.loc[common].to_numpy(float)[:, None]
    return {name: wj[:, i] for i, name in enumerate(jacobian.columns)}


def _vector_agreement(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    """Pairwise directional agreement metrics for two derivative columns."""
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0.0 and nb == 0.0:
        return {"cosine": 1.0, "sign_agreement": 1.0, "norm_ratio": 1.0, "both_zero": 1.0}
    if na == 0.0 or nb == 0.0:
        return {"cosine": 0.0, "sign_agreement": 0.0, "norm_ratio": float("inf"), "both_zero": 0.0}
    dot = float(np.dot(a, b))
    cosine = dot / (na * nb)
    active = (a != 0.0) | (b != 0.0)
    agreement = float(np.mean(np.sign(a[active]) == np.sign(b[active]))) if active.any() else 1.0
    return {"cosine": cosine, "sign_agreement": agreement,
            "norm_ratio": max(na, nb) / min(na, nb), "both_zero": 0.0}


def step_stability(jacobians: dict[str, pd.DataFrame], weights: pd.Series,
                   families: pd.Series | None = None) -> pd.DataFrame:
    """Vector-level derivative stability across step sizes.

    Compares each parameter's full weighted derivative column between every
    pair of step sizes using cosine similarity, per-observation sign-agreement
    and the norm ratio.  A non-negative CSS summary cannot detect direction
    flips; this can.  ``stable`` requires every pair to satisfy
    ``STABILITY_MIN_COSINE`` and ``STABILITY_MIN_SIGN_AGREEMENT``.
    """
    columns = {label: _derivative_columns(jac, weights) for label, jac in jacobians.items()}
    labels = sorted(columns.keys())
    scopes: dict[str, np.ndarray | None] = {"": None}
    if families is not None:
        for family in ("DRY_CUM", "N_RESPONSE", "W_RESPONSE"):
            mask = families.astype(str).isin([family]).to_numpy()
            scopes[f"_{family.lower()}"] = mask if mask.any() else None

    params = sorted(set().union(*[set(c) for c in columns.values()]))
    rows = []
    for p in params:
        present = {label: columns[label].get(p) for label in labels if p in columns[label]}
        if len(present) < 2:
            rows.append({"parameter": p, "n_steps": len(present), "stable": None,
                         "min_cosine": "", "min_sign_agreement": "", "max_norm_ratio": "",
                         "note": "single step size available; stability unverified"})
            continue
        pair_results = []
        keys = sorted(present.keys())
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                pair_results.append((keys[i], keys[j], _vector_agreement(present[keys[i]], present[keys[j]])))
        min_cos = min(r["cosine"] for *_, r in pair_results)
        min_sign = min(r["sign_agreement"] for *_, r in pair_results)
        max_ratio = max(r["norm_ratio"] for *_, r in pair_results)
        stable = bool(min_cos >= STABILITY_MIN_COSINE and min_sign >= STABILITY_MIN_SIGN_AGREEMENT)
        row = {"parameter": p, "n_steps": len(present), "stable": stable,
               "min_cosine": round(min_cos, 4), "min_sign_agreement": round(min_sign, 4),
               "max_norm_ratio": round(max_ratio, 4) if np.isfinite(max_ratio) else "inf",
               "note": ("" if stable else
                        f"direction unstable: min cosine {min_cos:.2f}, "
                        f"min sign agreement {min_sign:.2f}")}
        for suffix, mask in scopes.items():
            if mask is None:
                continue
            sub = {label: vec[mask] for label, vec in present.items()}
            pairs = [_vector_agreement(sub[a], sub[b])
                     for i, a in enumerate(sorted(sub)) for b in sorted(sub)[i + 1:]]
            row[f"min_cosine{suffix}"] = round(min(r["cosine"] for r in pairs), 4)
            row[f"min_sign_agreement{suffix}"] = round(min(r["sign_agreement"] for r in pairs), 4)
        rows.append(row)
    return pd.DataFrame(rows)


def recommend_formal_set(sensitivity: pd.DataFrame, correlation: pd.DataFrame,
                         stability: pd.DataFrame, max_params: int) -> pd.DataFrame:
    """Rank by scaled CSS, drop collinear partners and direction-unstable derivatives.

    Parameters whose derivative direction is unstable across step sizes, or
    that were only differentiated at a single step size (unverified), are
    excluded from the formal recommendation.
    """
    all_scope = sensitivity[sensitivity["scope"] == "ALL"].set_index("parameter")
    top = all_scope.sort_values("css_scaled", ascending=False)
    css_max = float(top["css_scaled"].max())
    floor = css_max * MIN_CSS_FRACTION
    if "stable" in stability.columns and not stability.empty:
        stable_map = dict(zip(stability["parameter"], stability["stable"]))
    else:
        stable_map = {}

    kept: list[str] = []
    dropped: list[tuple[str, str, float]] = []
    for name, row in top.iterrows():
        if float(row["css_scaled"]) < floor:
            dropped.append((name, "css_below_1pct_of_max", float(row["css_scaled"])))
            continue
        verdict = stable_map.get(name, None)
        if verdict is False:
            dropped.append((name, "derivative_direction_unstable", float(row["css_scaled"])))
            continue
        if verdict is None:
            dropped.append((name, "derivative_stability_unverified_single_step",
                            float(row["css_scaled"])))
            continue
        collinear = None
        for other in kept:
            r = abs(float(correlation.loc[name, other]))
            if r > CORRELATION_DROP:
                collinear = (other, r)
                break
        if collinear:
            dropped.append((name, f"collinear_with_{collinear[0]}", collinear[1]))
            continue
        kept.append(name)
        if len(kept) >= max_params:
            break
    frame = pd.DataFrame({
        "rank": range(1, len(kept) + 1),
        "parameter": kept,
        "css_scaled": [float(all_scope.loc[k, "css_scaled"]) for k in kept],
        "derivative_step_stable": [bool(stable_map.get(k)) for k in kept],
    })
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--case", default=None)
    parser.add_argument("--jcb", action="append", default=None,
                        help="extra Jacobian path[:label] for step-stability comparison")
    parser.add_argument("--max-formal-params", type=int, default=18)
    args = parser.parse_args()

    run_dir: Path = args.run_dir
    case = args.case or next(
        (p.stem for p in run_dir.glob("*.pst") if not p.stem.endswith("_params")), None)
    if case is None:
        raise SystemExit("no PST found in run dir; pass --case")
    pst_path = run_dir / f"{case}.pst"
    jcb_path = run_dir / f"{case}.jcb"
    if not jcb_path.is_file():
        raise SystemExit(f"Jacobian not found: {jcb_path}")

    out_dir = run_dir / "glm_quality"
    out_dir.mkdir(exist_ok=True)

    pst = pyemu.Pst(str(pst_path))
    weights = pst.observation_data["weight"].astype(float)
    par = pst.parameter_data
    adjustable = par[par.partrans.astype(str).str.lower() != "fixed"]
    ranges = (adjustable["parubnd"].astype(float) - adjustable["parlbnd"].astype(float))

    jacobian, _ = load_jacobian(jcb_path)
    jacobian = jacobian.reindex(columns=list(adjustable.index))
    families = pd.Series([family_of(g) for g in pst.observation_data["obgnme"]],
                         index=pst.observation_data.index)

    sensitivity = composite_sensitivities(jacobian, weights, ranges, families)
    sensitivity.to_csv(out_dir / "jacobian_parameter_sensitivity.csv", index=False)

    correlation = column_correlations(jacobian, weights)
    correlation.to_csv(out_dir / "jacobian_column_correlation.csv")

    sv_frame, sv_summary = singular_values(jacobian, weights, ranges)
    sv_frame.to_csv(out_dir / "jacobian_singular_values.csv", index=False)

    jacobians = {"default": jacobian}
    for item in args.jcb or []:
        path, _, label = item.partition(":")
        jacobians[label or Path(path).stem] = load_jacobian(Path(path))[0]
    stability = step_stability(jacobians, weights, families)
    stability.to_csv(out_dir / "derivative_step_stability.csv", index=False)

    recommended = recommend_formal_set(sensitivity, correlation, stability,
                                       args.max_formal_params)
    recommended.to_csv(out_dir / "recommended_formal_parameter_set.csv", index=False)

    n_params = len(adjustable)
    audit = {
        "schema_version": 1,
        "case": case,
        "jacobian_file": str(jcb_path),
        "n_parameters": n_params,
        "n_observations_used": int(len([o for o in jacobian.index if o in weights.index])),
        "svd": sv_summary,
        "effective_rank_fraction": sv_summary["effective_rank"] / max(n_params, 1),
        "rank_deficient": sv_summary["effective_rank"] < 0.6 * n_params,
        "thresholds": {
            "eigthresh": EIGTHRESH,
            "correlation_drop": CORRELATION_DROP,
            "min_css_fraction": MIN_CSS_FRACTION,
            "stability_min_cosine": STABILITY_MIN_COSINE,
            "stability_min_sign_agreement": STABILITY_MIN_SIGN_AGREEMENT,
        },
        "n_recommended_formal_params": int(len(recommended)),
        "step_sizes_compared": sorted(jacobians.keys()),
        "top5_by_scaled_css": sensitivity[sensitivity["scope"] == "ALL"]
            .nlargest(5, "css_scaled")[["parameter", "css_scaled"]]
            .to_dict(orient="records"),
    }
    (out_dir / "jacobian_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({k: v for k, v in audit.items() if k != "top5_by_scaled_css"},
                     ensure_ascii=False, indent=2))
    print(f"outputs: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
