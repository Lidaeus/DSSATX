"""Residual evidence chain for calibration experiments.

Implements the directional-residual diagnostics prescribed by the article-
calibration contract (§4.2 of the experiment matrix).  No plotting library.

Three products:

* :func:`runs_test` -- Wald-Wolfowitz runs test on residual *signs*, executed
  on the true time order of ``season x treatment x variable``.  Zero residuals
  are dropped; sequences shorter than 8 events are reported ``not_tested``
  rather than approximated.
* :func:`treatment_bootstrap_mbe` -- MBE confidence interval with the
  **treatment as the resampling unit** (treatment-block bootstrap).  Cumulative-
  harvest observations are never treated as independent per-time-point samples.
* :func:`build_residual_trajectory` -- per-treatment residual trajectory in
  harvest-event order, with an explicit ``is_cumulative_non_independent`` flag.

References
----------
NIST e-Handbook, §1.3.5.17 (runs test):
https://www.itl.nist.gov/div898/handbook/eda/section3/eda35d.htm
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
import pandas as pd

MIN_RUNS_TEST_N = 8  # below this, the normal approximation is unreliable


def runs_test(residuals: Sequence[float]) -> dict[str, Any]:
    """Wald-Wolfowitz runs test on the signs of non-zero residuals.

    A "run" is a maximal subsequence of equal sign.  Under the null (signs are
    random) the number of runs is approximately normal with:

        E[R] = 2 n1 n2 / n + 1
        Var[R] = 2 n1 n2 (2 n1 n2 - n) / (n^2 (n - 1))

    Returns ``status='not_tested'`` (with counts) when fewer than
    :data:`MIN_RUNS_TEST_N` non-zero residuals remain, or when all residuals
    share one sign (n1=0 or n2=0).
    """
    arr = np.asarray(residuals, dtype=float)
    finite = arr[np.isfinite(arr)]
    n_zero = int(np.sum(finite == 0.0))
    nz = finite[finite != 0.0]
    n_pos = int(np.sum(nz > 0))
    n_neg = int(np.sum(nz < 0))
    n = n_pos + n_neg
    base = {
        "n": int(n),
        "n_pos": n_pos,
        "n_neg": n_neg,
        "n_zero": n_zero,
        "n_runs": 0,
        "z": np.nan,
        "p_value": np.nan,
        "status": "not_tested",
        "note": "",
    }
    if n == 0:
        base["note"] = "no non-zero residuals"
        return base
    # count runs on the sign sequence (+1 / -1)
    signs = np.where(nz > 0, 1, -1)
    n_runs = int(np.sum(signs[1:] != signs[:-1]) + 1)
    base["n_runs"] = n_runs
    if n < MIN_RUNS_TEST_N:
        base["note"] = f"n={n} < {MIN_RUNS_TEST_N}; normal approximation unreliable"
        return base
    if n_pos == 0 or n_neg == 0:
        base["note"] = "all non-zero residuals share one sign"
        return base
    # normal approximation
    e_r = 2.0 * n_pos * n_neg / n + 1.0
    denom = n * n * (n - 1.0)
    var_r = 2.0 * n_pos * n_neg * (2.0 * n_pos * n_neg - n) / denom if denom > 0 else 0.0
    if var_r <= 0.0:
        base["note"] = "zero variance of runs statistic"
        return base
    z = (n_runs - e_r) / math.sqrt(var_r)
    # two-sided p
    p = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))
    base["z"] = float(z)
    base["p_value"] = float(min(max(p, 0.0), 1.0))
    base["status"] = "tested"
    base["note"] = f"E[R]={e_r:.2f}, Var[R]={var_r:.2f}"
    return base


def _treatment_mbe(group: pd.DataFrame, obs_col: str, sim_col: str) -> float:
    """Mean bias error for one treatment (sim - obs)."""
    resid = group[sim_col].to_numpy(dtype=float) - group[obs_col].to_numpy(dtype=float)
    return float(np.mean(resid))


def treatment_bootstrap_mbe(
    frame: pd.DataFrame,
    treatment_col: str = "treatment",
    observed_col: str = "observed",
    simulated_col: str = "simulated",
    *,
    n_bootstrap: int = 2000,
    ci: float = 0.95,
    seed: int = 20260724,
    min_treatments: int = 8,
) -> dict[str, Any]:
    """Treatment-block bootstrap of the mean bias error.

    The resampling unit is the **treatment**, never the individual cumulative-
    harvest time point.  This avoids pseudo-replication from correlated
    successive cumulative observations.  When fewer than ``min_treatments``
    treatments are present, a permutation (sign-flip) test is also reported as a
    small-sample robustness check; the bootstrap CI is still returned but
    flagged.
    """
    for col in (treatment_col, observed_col, simulated_col):
        if col not in frame.columns:
            raise ValueError(f"frame must contain column {col!r}")
    per_treatment = [
        _treatment_mbe(g, observed_col, simulated_col)
        for _, g in frame.groupby(treatment_col, sort=True)
        if len(g)
    ]
    per_treatment = np.asarray(per_treatment, dtype=float)
    n_t = int(per_treatment.size)
    point = float(np.mean(per_treatment)) if n_t else np.nan
    result: dict[str, Any] = {
        "n_treatments": n_t,
        "MBE": point,
        "ci_level": ci,
        "ci_lower": np.nan,
        "ci_upper": np.nan,
        "n_bootstrap": n_bootstrap,
        "small_sample": n_t < min_treatments,
        "permutation_p_value": np.nan,
        "status": "tested" if n_t >= 2 else "not_tested",
        "note": "",
    }
    if n_t < 2:
        result["note"] = "fewer than 2 treatments; cannot resample"
        return result
    rng = np.random.default_rng(seed)
    boots = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        idx = rng.integers(0, n_t, size=n_t)
        boots[i] = float(np.mean(per_treatment[idx]))
    alpha = (1.0 - ci) / 2.0
    result["ci_lower"] = float(np.quantile(boots, alpha))
    result["ci_upper"] = float(np.quantile(boots, 1.0 - alpha))
    if n_t < min_treatments:
        # sign-flip permutation test on the treatment MBEs (small-sample robust)
        flipped = per_treatment[:, None] * (1 - 2 * rng.integers(0, 2, size=(n_t, 2000)))
        dist = flipped.mean(axis=0)
        obs_abs = abs(point)
        tail = float(np.mean(np.abs(dist) >= obs_abs)) if obs_abs == obs_abs else np.nan
        result["permutation_p_value"] = float(min(max(tail, 0.0), 1.0))
        result["note"] = f"small sample (n_t={n_t}<{min_treatments}); permutation p reported"
    return result


def build_residual_trajectory(
    frame: pd.DataFrame,
    key_cols: list[str] | None = None,
    *,
    observed_col: str = "observed",
    simulated_col: str = "simulated",
    order_col: str = "harvest_number",
    cumulative_variable_mark: str = "cum",
    variable_col: str = "variable",
) -> pd.DataFrame:
    """Per-treatment residual trajectory in event order with non-independence flags.

    ``key_cols`` (default ``[season, treatment, variable]``) define one
    trajectory.  Rows are sorted by ``order_col`` (e.g. harvest_number).  A
    trajectory with >1 event whose variable name contains the
    ``cumulative_variable_mark`` (case-insensitive, default ``"cum"`` to match
    ``DRY_CUM``/``FRESH_CUM``/``cumulative``) is flagged
    ``is_cumulative_non_independent=True`` because successive cumulative
    harvests share the error of all prior harvests.
    """
    if key_cols is None:
        key_cols = [c for c in ("season", "treatment", "variable") if c in frame.columns]
    needed = list(set(key_cols + [observed_col, simulated_col]))
    if order_col not in frame.columns:
        # fall back to row order when no explicit event index is present
        frame = frame.copy()
        frame[order_col] = np.arange(1, len(frame) + 1)
    keep = needed + ([order_col] if order_col not in needed else []) + ([variable_col] if variable_col not in needed else [])
    sub = frame[keep].copy()
    sub["residual"] = sub[simulated_col].astype(float) - sub[observed_col].astype(float)
    sub = sub.sort_values(key_cols + [order_col]).reset_index(drop=True)
    mark = cumulative_variable_mark.lower()
    # Assign per-group flags via a manual loop to keep all columns (groupby.apply
    # with include_groups=False would drop the grouping keys we need in output).
    flags = np.zeros(len(sub), dtype=bool)
    finals = np.full(len(sub), np.nan, dtype=float)
    for _, idx in sub.groupby(key_cols, sort=False).indices.items():
        block = sub.index[idx]
        if len(block) == 0:
            continue
        first = sub.loc[block[0]]
        is_cum = (
            len(block) > 1
            and variable_col in sub.columns
            and mark in str(first[variable_col]).lower()
        )
        flags[block.to_numpy()] = is_cum
        finals[block.to_numpy()] = float(sub.loc[block[-1], "residual"])
    sub["is_cumulative_non_independent"] = flags
    sub["final_cumulative_residual"] = finals
    return sub


__all__ = [
    "MIN_RUNS_TEST_N",
    "runs_test",
    "treatment_bootstrap_mbe",
    "build_residual_trajectory",
]
