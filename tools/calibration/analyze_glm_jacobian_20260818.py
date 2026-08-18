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


def family_of(obgnme: str) -> str:
    """Map a PEST observation group to an objective family for aggregation."""
    g = str(obgnme).upper()
    if "NRESP" in g:
        return "N_RESPONSE"
    if "WRESP" in g:
        return "W_RESPONSE"
    if "CHPDTS" in g or "CHPDTM" in g:
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


def singular_values(jacobian: pd.DataFrame, weights: pd.Series) -> tuple[pd.DataFrame, dict]:
    common = [o for o in jacobian.index if o in weights.index]
    wj = jacobian.loc[common].to_numpy(float) * weights.loc[common].to_numpy(float)[:, None]
    s = np.linalg.svd(wj, compute_uv=False)
    if s.size == 0 or s[0] <= 0:
        return pd.DataFrame(columns=["index", "singular_value", "ratio_to_max"]), {
            "effective_rank": 0, "condition_number": float("inf")}
    ratios = s / s[0]
    keep = ratios > EIGTHRESH
    effective_rank = int(keep.sum())
    summary = {
        "eigthresh": EIGTHRESH,
        "n_singular_values": int(s.size),
        "effective_rank": effective_rank,
        "condition_number": float(s[0] / s[keep][-1]) if effective_rank else float("inf"),
        "min_singular_value": float(s[-1]),
        "max_singular_value": float(s[0]),
    }
    frame = pd.DataFrame({
        "index": np.arange(1, s.size + 1),
        "singular_value": s,
        "ratio_to_max": ratios,
        "above_eigthresh": keep,
    })
    return frame, summary


def step_stability(jacobians: dict[str, pd.DataFrame], weights: pd.Series) -> pd.DataFrame:
    """Derivative-step stability across step sizes (plan section 8 spot check).

    A parameter is ``stable`` when the sign of its composite sensitivity is
    consistent across steps.  Magnitude ratios are reported separately:
    DSSAT's daily output discretisation makes CSS magnitude inherently
    step-dependent, so a large ratio is recorded as information for the
    formal-run DERINC choice rather than an automatic exclusion.
    """
    css = {}
    for label, jac in jacobians.items():
        common = [o for o in jac.index if o in weights.index]
        wj = jac.loc[common].to_numpy(float) * weights.loc[common].to_numpy(float)[:, None]
        css[label] = {name: float(np.sqrt(np.square(wj[:, i]).sum()))
                      for i, name in enumerate(jac.columns)}
    rows = []
    params = sorted(set().union(*[set(c) for c in css.values()]))
    for p in params:
        values = {label: css[label].get(p) for label in css}
        finite = [v for v in values.values() if v is not None and np.isfinite(v)]
        if len(finite) < 2:
            rows.append({"parameter": p, **values,
                         "n_steps": len(finite), "stable": None,
                         "magnitude_ratio": "",
                         "note": "single step size available; stability unverified"})
            continue
        signs = np.sign([v if v != 0 else 1 for v in finite])
        nz = [abs(v) for v in finite if v != 0]
        ratio = float(max(nz) / min(nz)) if len(nz) >= 2 and min(nz) > 0 else None
        stable = bool((signs == signs[0]).all())
        note = ("sign-consistent across step sizes"
                + (f"; CSS magnitude ratio {ratio:.1f}x (step-dependent, informational)"
                   if ratio else "; zero sensitivity in at least one step"))
        rows.append({"parameter": p, **values, "n_steps": len(finite),
                     "stable": stable, "magnitude_ratio": ratio, "note": note})
    return pd.DataFrame(rows)


def recommend_formal_set(sensitivity: pd.DataFrame, correlation: pd.DataFrame,
                         stability: pd.DataFrame, max_params: int) -> pd.DataFrame:
    """Rank by scaled CSS, drop collinear partners and unverified derivatives."""
    all_scope = sensitivity[sensitivity["scope"] == "ALL"].set_index("parameter")
    top = all_scope.sort_values("css_scaled", ascending=False)
    css_max = float(top["css_scaled"].max())
    floor = css_max * MIN_CSS_FRACTION
    stable_map = {}
    if not stability.empty and "stable" in stability:
        stable_map = dict(zip(stability["parameter"], stability["stable"]))

    kept: list[str] = []
    dropped: list[tuple[str, str, float]] = []
    for name, row in top.iterrows():
        if float(row["css_scaled"]) < floor:
            dropped.append((name, "css_below_1pct_of_max", float(row["css_scaled"])))
            continue
        if stable_map.get(name) is False:
            dropped.append((name, "unstable_derivative_step", float(row["css_scaled"])))
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
        "derivative_step_stable": [bool(stable_map.get(k, None)) if stable_map.get(k) is not None else None for k in kept],
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

    sv_frame, sv_summary = singular_values(jacobian, weights)
    sv_frame.to_csv(out_dir / "jacobian_singular_values.csv", index=False)

    jacobians = {"default": jacobian}
    for item in args.jcb or []:
        path, _, label = item.partition(":")
        jacobians[label or Path(path).stem] = load_jacobian(Path(path))[0]
    stability = step_stability(jacobians, weights)
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
