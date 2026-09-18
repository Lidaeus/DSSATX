"""Single source of truth for raw-scale calibration goodness-of-fit metrics.

This module deliberately imports **no plotting library** (only numpy/pandas) so
it can be exercised by every calibration experiment, by ``figure_data``, and by
the unit-test suite without pulling matplotlib into a data-export path.

All metrics are defined on the **raw physical scale**.  ``residual = simulated -
observed`` (positive = overestimate), matching the project weight/reporting
convention.  The OLS systematic/unsystematic MSE decomposition follows the
article-calibration contract:

    sim_hat = a + b * observed
    MSE_s = mean((sim_hat - observed)^2)     # systematic
    MSE_u = mean((simulated - sim_hat)^2)    # unsystematic

and is numerically closed: ``MSE = MSE_s + MSE_u`` is asserted to within 1e-9.

References
----------
Robeson & Willmott (2023), PLoS ONE 18(2): e0279774 -- on the decomposition and
its limitations.  Kobayashi & Salam (2000), Agron. J. 92:345 -- the
SB+SDSD+LCS decomposition is a complementary view, not implemented here.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

MISSING_VALUE = -99.0
_CLOSURE_TOL = 1e-9

# Metric computation status.  "ok" means all metrics are finite; any other
# value means at least one metric is NA and ``na_reason`` explains why.
_OK = "ok"
_EMPTY = "empty"
_INSUFFICIENT = "insufficient_n"  # n < 2
_NON_FINITE = "non_finite"        # all pairs dropped after cleaning
_ZERO_MEAN = "zero_mean"          # RRMSE denominator
_ZERO_RANGE = "zero_range"        # NRMSE_range denominator
_CONSTANT_SERIES = "constant_series"  # NSE / R denominator (no variance)


def valid_pair_mask(observed, simulated, *, value_kind: str = "raw") -> np.ndarray:
    """Validate pairs BEFORE unit conversion or subtraction.

    raw: finite input values, excluding the DSSAT -99 sentinel (roundoff tolerant).
    state: nonnegative physical states/harvest quantities.
    signed: already-derived contrasts/changes; even -99 can be a real difference.
    Missing source values must become NaN before forming signed differences.
    """
    o = np.asarray(observed, dtype=float)
    s = np.asarray(simulated, dtype=float)
    if o.shape != s.shape:
        raise ValueError(
            f"observed and simulated must have the same shape, got {o.shape} vs {s.shape}"
        )
    mask = np.isfinite(o) & np.isfinite(s)
    if value_kind == "state":
        return mask & (o >= 0) & (s >= 0)
    if value_kind == "signed":
        return mask
    if value_kind != "raw":
        raise ValueError(f"Unknown value_kind: {value_kind!r}")
    return mask & ~np.isclose(o, MISSING_VALUE, rtol=0, atol=1e-6) & ~np.isclose(s, MISSING_VALUE, rtol=0, atol=1e-6)


def _clean_pairs(observed, simulated, *, value_kind="raw") -> tuple[np.ndarray, np.ndarray, str]:
    o = np.asarray(observed, dtype=float)
    s = np.asarray(simulated, dtype=float)
    mask = valid_pair_mask(o, s, value_kind=value_kind)
    if not mask.any():
        return o[mask], s[mask], _EMPTY if o.size == 0 else _NON_FINITE
    return o[mask], s[mask], _OK


def _ols(obs: np.ndarray, sim: np.ndarray) -> tuple[float, float, np.ndarray]:
    """Ordinary-least-squares fit ``sim_hat = a + b * obs``.

    Returns ``(intercept a, slope b, sim_hat)``.  Uses the normal equations
    directly (no statsmodels dependency).  When obs has zero variance the slope
    is 0 and the intercept is mean(sim) -- the fit collapses to a constant.
    """
    n = obs.size
    mean_o = float(obs.mean())
    mean_s = float(sim.mean())
    ss_oo = float(np.sum((obs - mean_o) ** 2))
    if ss_oo <= 0.0:
        # No variance in observed: best fit is a horizontal line at mean(sim).
        b = 0.0
        a = mean_s
    else:
        ss_os = float(np.sum((obs - mean_o) * (sim - mean_s)))
        b = ss_os / ss_oo
        a = mean_s - b * mean_o
    sim_hat = a + b * obs
    return a, b, sim_hat


def compute_metrics(observed, simulated, *, value_kind: str = "raw") -> dict[str, Any]:
    """Compute the full metric set for one comparison group.

    Always returns every key; inapplicable metrics are ``np.nan`` with a
    ``status``/``na_reason`` explaining why.  Residual sign is
    ``simulated - observed``.
    """
    obs, sim, status = _clean_pairs(observed, simulated, value_kind=value_kind)
    n = int(obs.size)
    result: dict[str, Any] = {
        "n": n,
        "status": status,
        "na_reason": "",
        "MBE": np.nan, "RMSE": np.nan, "MAE": np.nan,
        "RRMSE_pct": np.nan, "NRMSE_range_pct": np.nan, "NSE": np.nan,
        "MSE": np.nan, "MSE_s": np.nan, "MSE_u": np.nan,
        "MSE_s_over_MSE": np.nan, "MSE_u_over_MSE": np.nan,
        "R2": np.nan, "slope": np.nan, "intercept": np.nan,
    }
    if status == _EMPTY:
        result["na_reason"] = "no observations provided"
        return result
    if status == _NON_FINITE:
        result["na_reason"] = "all pairs were non-finite or missing (-99) after cleaning"
        return result
    if n < 2:
        # With a single pair, RMSE/MAE/MBE are still defined but variance-based
        # metrics (NSE, R, OLS) are not.  Report what we can.
        result["status"] = _INSUFFICIENT
        result["na_reason"] = f"only n={n} valid pair; variance-based metrics undefined"
        resid = sim - obs
        result["MBE"] = float(resid[0])
        result["RMSE"] = float(abs(resid[0]))
        result["MAE"] = float(abs(resid[0]))
        result["MSE"] = float(resid[0] ** 2)
        mean_o = float(obs[0])
        if mean_o != 0.0:
            result["RRMSE_pct"] = 100.0 * abs(resid[0]) / abs(mean_o)
        rng = 0.0  # single point -> zero range
        # NRMSE_range stays NA (zero range)
        # MSE decomp undefined for n<2 (OLS needs 2 points) -> leave NaN
        return result

    resid = sim - obs
    mbe = float(np.mean(resid))
    mse = float(np.mean(resid ** 2))
    rmse = float(np.sqrt(mse))
    mae = float(np.mean(np.abs(resid)))
    mean_o = float(np.mean(obs))
    o_range = float(np.max(obs) - np.min(obs))

    result["MBE"] = mbe
    result["RMSE"] = rmse
    result["MAE"] = mae
    result["MSE"] = mse

    if mean_o != 0.0:
        result["RRMSE_pct"] = 100.0 * rmse / abs(mean_o)
    else:
        # zero mean -- RRMSE undefined; flag but keep going
        if status == _OK:
            status = _ZERO_MEAN
    if o_range != 0.0:
        result["NRMSE_range_pct"] = 100.0 * rmse / o_range
    # else zero range -> NRMSE_range stays NA

    # NSE and R require variance in observed.
    ss_tot = float(np.sum((obs - mean_o) ** 2))
    var_obs_zero = ss_tot <= 0.0
    sim_var = float(np.sum((sim - float(np.mean(sim))) ** 2))
    var_sim_zero = sim_var <= 0.0
    if not var_obs_zero:
        result["NSE"] = 1.0 - mse * n / ss_tot  # = 1 - SS_res/SS_tot
    # R requires both variances
    if not var_obs_zero and not var_sim_zero:
        r = float(np.corrcoef(obs, sim)[0, 1])
        result["R2"] = r * r
    if var_obs_zero or var_sim_zero:
        if status == _OK:
            status = _CONSTANT_SERIES

    # OLS systematic/unsystematic MSE decomposition (always defined for n>=2).
    a, b, sim_hat = _ols(obs, sim)
    result["intercept"] = a
    result["slope"] = b
    mse_s = float(np.mean((sim_hat - obs) ** 2))
    mse_u = float(np.mean((sim - sim_hat) ** 2))
    result["MSE_s"] = mse_s
    result["MSE_u"] = mse_u
    if mse > 0.0:
        result["MSE_s_over_MSE"] = mse_s / mse
        result["MSE_u_over_MSE"] = mse_u / mse
    # Numerical closure check: MSE = MSE_s + MSE_u.
    closure_err = abs(mse - (mse_s + mse_u))
    if closure_err > _CLOSURE_TOL:
        raise AssertionError(
            f"MSE decomposition not closed: MSE={mse!r} vs MSE_s+MSE_u={mse_s + mse_u!r} "
            f"(abs error {closure_err:.3e} > {_CLOSURE_TOL:.0e})"
        )

    # Set status text + na_reason for the non-ok flags.
    if status == _OK:
        result["na_reason"] = ""
    elif status == _ZERO_MEAN:
        result["na_reason"] = "observed mean is zero; RRMSE undefined"
    elif status == _CONSTANT_SERIES:
        result["na_reason"] = "observed or simulated series has zero variance; NSE/R undefined"
    result["status"] = status
    return result


def compute_metrics_grouped(
    frame: pd.DataFrame,
    group_cols: list[str],
    observed_col: str = "observed",
    simulated_col: str = "simulated",
    *,
    value_kind: str = "raw",
) -> pd.DataFrame:
    """Compute metrics for each group, returning one row per group.

    ``group_cols`` typically includes experiment/season/dataset_role/variable/
    scale/scope.  Groups with zero valid pairs are still emitted with
    ``status='empty'`` so the audit trail is complete.
    """
    for col in (observed_col, simulated_col):
        if col not in frame.columns:
            raise ValueError(f"frame must contain column {col!r}")
    for col in group_cols:
        if col not in frame.columns:
            raise ValueError(f"group column {col!r} not in frame")
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return pd.DataFrame(columns=group_cols + list(compute_metrics([], []).keys()))
    for keys, sub in frame.groupby(group_cols, sort=True, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        record = dict(zip(group_cols, keys))
        metrics = compute_metrics(sub[observed_col].to_numpy(), sub[simulated_col].to_numpy(), value_kind=value_kind)
        record.update(metrics)
        rows.append(record)
    return pd.DataFrame(rows)


__all__ = ["compute_metrics", "compute_metrics_grouped", "valid_pair_mask"]
