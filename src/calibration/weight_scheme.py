"""Auditable observation-error and PEST weight calculations.

PEST evaluates ``phi = sum((weight * residual) ** 2)``.  Therefore an
observation error standard deviation ``sigma`` maps to ``weight = 1/sigma``.

P0 deliberately supports raw-scale residuals only.  Candidate-dependent
Min-Max normalization and partially implemented log residuals are rejected so
they cannot silently change the objective function between realizations.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd


WEIGHT_POLICY_ID = "raw_sigma_v1"
MISSING_VALUE = -99.0

# Kept as public compatibility metadata.  P0 does not activate these transforms.
LOG_TRANSFORM_VARS: set[str] = set()
NON_CUMULATIVE_VARS = {"ADAPM", "HIAMM", "LAIXM", "CHTAM", "CNAAM", "H#AMM"}


VARIABLE_TREATMENT = {
    "ADAPM": {"log_transform": False, "sigma_base": 25.0, "cumulate": False},
    "CNAMM": {"log_transform": False, "sigma_base": 25.0, "cumulate": True},
    "HIAMM": {"log_transform": False, "sigma_base": 0.10, "cumulate": False},
    "HWAMM": {"log_transform": False, "sigma_base": 50.0, "cumulate": True},
    "LAIXM": {"log_transform": False, "sigma_base": 0.8, "cumulate": False},
    "LAIDM": {"log_transform": False, "sigma_base": 2.0, "cumulate": False},
    "LWADM": {"log_transform": False, "sigma_base": 150.0, "cumulate": False},
    "SWADM": {"log_transform": False, "sigma_base": 200.0, "cumulate": False},
    "CHTAM": {"log_transform": False, "sigma_base": 15.0, "cumulate": False},
    "CNAAM": {"log_transform": False, "sigma_base": 20.0, "cumulate": False},
    "H#AMM": {"log_transform": False, "sigma_base": 50.0, "cumulate": False},
    "PWADM": {"log_transform": False, "sigma_base": 250.0, "cumulate": True},
    "PWAIM": {"log_transform": False, "sigma_base": 250.0, "cumulate": False},
}


def weight_from_sigma(sigma: float, group_multiplier: float = 1.0) -> float:
    """Convert a standard deviation and explicit multiplier to a PEST weight."""
    sigma = float(sigma)
    group_multiplier = float(group_multiplier)
    if not math.isfinite(sigma) or sigma <= 0:
        raise ValueError(f"sigma must be positive and finite, got {sigma!r}")
    if not math.isfinite(group_multiplier) or group_multiplier <= 0:
        raise ValueError(
            f"group_multiplier must be positive and finite, got {group_multiplier!r}"
        )
    return group_multiplier / sigma


def compute_phi(
    observed: pd.Series | np.ndarray | list[float],
    simulated: pd.Series | np.ndarray | list[float],
    weights: pd.Series | np.ndarray | list[float],
) -> float:
    """Compute the PEST measurement objective for a hand-checkable test case."""
    obs = np.asarray(observed, dtype=float)
    sim = np.asarray(simulated, dtype=float)
    weight = np.asarray(weights, dtype=float)
    if obs.shape != sim.shape or obs.shape != weight.shape:
        raise ValueError("observed, simulated, and weights must have the same shape")
    if not np.isfinite(obs).all() or not np.isfinite(sim).all():
        raise ValueError("observed and simulated values must be finite")
    if not np.isfinite(weight).all() or (weight < 0).any():
        raise ValueError("weights must be finite and non-negative")
    return float(np.square(weight * (obs - sim)).sum())


def minmax_normalize(
    obs_series: pd.Series, sim_series: pd.Series
) -> Tuple[pd.Series, pd.Series, float]:
    """Reject the retired candidate-dependent Min-Max objective design."""
    raise ValueError(
        "Dynamic Min-Max normalization is disabled: it makes the residual scale "
        "depend on each candidate simulation. Use raw-scale sigma weights."
    )


def normalize_and_weight(
    obs_series: pd.Series,
    sim_series: pd.Series,
    sigma_original: float,
    use_log_transform: bool = False,
    eps: float = 1e-6,
) -> Tuple[float, pd.Series, pd.Series, float]:
    """Compatibility entry point for the P0 raw-scale policy.

    No normalization is performed.  Log residuals are rejected until an
    Observation Spec can transform both observations and model outputs before
    PEST reads them.
    """
    del eps
    if use_log_transform:
        raise ValueError(
            "Log residuals are not available in P0; observations and simulations "
            "must be transformed together before weighting"
        )
    if len(obs_series) != len(sim_series):
        raise ValueError("Observed and simulated series must have the same length")
    weight = weight_from_sigma(sigma_original)
    return weight, obs_series.copy(), sim_series.copy(), float(sigma_original)


def compute_cv_based_sigma(
    obs_series: pd.Series,
    sigma0: float = 1.0,
    cv_override: Optional[float] = None,
) -> Tuple[float, float]:
    """Estimate ``sqrt(sigma0² + (cv * |median|)²)`` from valid observations."""
    sigma0 = float(sigma0)
    if not math.isfinite(sigma0) or sigma0 <= 0:
        raise ValueError("sigma0 must be positive and finite")
    valid = pd.to_numeric(obs_series, errors="coerce")
    valid = valid[(valid != MISSING_VALUE) & valid.notna()]
    if valid.empty:
        return sigma0, 0.0
    if cv_override is None:
        mean = float(valid.mean())
        std = float(valid.std(ddof=1)) if len(valid) > 1 else 0.0
        cv = abs(std / mean) if mean != 0 else 0.0
    else:
        cv = float(cv_override)
    if not math.isfinite(cv) or cv < 0:
        raise ValueError("cv must be finite and non-negative")
    sigma = math.sqrt(sigma0**2 + (cv * abs(float(valid.median()))) ** 2)
    return sigma, cv


def _validate_weight_frames(obs_df: pd.DataFrame, sim_df: pd.DataFrame) -> pd.DataFrame:
    required_obs = {"obsnme", "obsval", "obgnme"}
    required_sim = {"obsnme", "simulated"}
    if not required_obs.issubset(obs_df.columns):
        raise ValueError(f"obs_df missing columns: {sorted(required_obs - set(obs_df.columns))}")
    if not required_sim.issubset(sim_df.columns):
        raise ValueError(f"sim_df missing columns: {sorted(required_sim - set(sim_df.columns))}")
    if obs_df["obsnme"].duplicated().any() or sim_df["obsnme"].duplicated().any():
        raise ValueError("obsnme must be unique in observation and simulation tables")
    merged = obs_df.merge(sim_df, on="obsnme", how="left", validate="one_to_one")
    if merged["simulated"].isna().any():
        missing = merged.loc[merged["simulated"].isna(), "obsnme"].tolist()
        raise ValueError(f"Missing baseline simulations for observations: {missing[:10]}")
    return merged


def compute_balanced_weights(
    obs_df: pd.DataFrame,
    sim_df: pd.DataFrame,
    original_sigmas: Dict[str, float],
    target_per_group: float = 1.0,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Experimental, explicit group-phi balancing.

    The function is strict by design: every observation group needs a sigma and
    a baseline simulation.  It never falls back to a guessed group or weight.
    """
    merged = _validate_weight_frames(obs_df, sim_df)
    merged = merged[(merged["obsval"] != MISSING_VALUE)].copy()
    groups = set(merged["obgnme"].astype(str))
    sigma_groups = set(map(str, original_sigmas))
    if groups != sigma_groups:
        raise ValueError(
            "Sigma keys must exactly match observation groups; "
            f"missing={sorted(groups - sigma_groups)}, extra={sorted(sigma_groups - groups)}"
        )
    if not math.isfinite(float(target_per_group)) or target_per_group <= 0:
        raise ValueError("target_per_group must be positive and finite")

    current: dict[str, float] = {}
    for group, frame in merged.groupby("obgnme"):
        sigma = float(original_sigmas[str(group)])
        base = weight_from_sigma(sigma)
        current[str(group)] = float(np.square(base * (frame["obsval"] - frame["simulated"])).mean())
    if any(not math.isfinite(value) or value <= 0 for value in current.values()):
        raise ValueError("Group balancing requires positive finite baseline phi in every group")

    weights: dict[str, float] = {}
    adjusted_sigmas: dict[str, float] = {}
    for group, phi in current.items():
        multiplier = math.sqrt(float(target_per_group) / phi)
        weights[group] = weight_from_sigma(original_sigmas[group], multiplier)
        adjusted_sigmas[group] = 1.0 / weights[group]
    return weights, adjusted_sigmas


def apply_weight_scheme_to_obs_df(
    obs_df: pd.DataFrame,
    sim_df: pd.DataFrame,
    group_sigmas: Dict[str, float],
    use_log_transform_groups: Optional[Dict[str, bool]] = None,
    apply_pwtadj1: bool = False,
    noptmax0_sims: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Apply raw sigma weights, optionally enabling strict experimental balance."""
    transforms = use_log_transform_groups or {}
    if any(transforms.values()):
        raise ValueError("Log residuals are disabled in the P0 raw-scale policy")
    result = obs_df.copy()
    groups = set(result["obgnme"].astype(str))
    missing = groups - set(group_sigmas)
    if missing:
        raise ValueError(f"Missing sigma definitions for groups: {sorted(missing)}")
    weights = {group: weight_from_sigma(group_sigmas[group]) for group in groups}
    if apply_pwtadj1:
        baseline = noptmax0_sims if noptmax0_sims is not None else sim_df
        weights, _ = compute_balanced_weights(result, baseline, group_sigmas)
    result["sigma"] = result["obgnme"].map(group_sigmas)
    result["base_weight"] = result["obgnme"].map(
        {group: weight_from_sigma(group_sigmas[group]) for group in groups}
    )
    result["group_multiplier"] = result.apply(
        lambda row: weights[str(row["obgnme"])] / row["base_weight"], axis=1
    )
    result["weight"] = result["obgnme"].map(weights)
    result["weight_policy_id"] = WEIGHT_POLICY_ID
    return result


def build_observation_weights(
    obs_data: list,
    df_override: Optional[pd.DataFrame] = None,
    sim_baseline: Optional[pd.DataFrame] = None,
    apply_normalization: bool = False,
    apply_log_transform: bool = False,
    apply_pwtadj1: bool = False,
    cv_based_sigma: bool = False,
) -> list:
    """Build an auditable raw-scale weight table from observation records."""
    if not obs_data:
        return obs_data
    if apply_normalization:
        raise ValueError("Dynamic Min-Max normalization is retired and cannot be enabled")
    if apply_log_transform:
        raise ValueError("Log residuals are not implemented in the P0 raw-scale policy")
    if apply_pwtadj1 and sim_baseline is None:
        raise ValueError("Experimental pwtadj1 balancing requires baseline simulations")

    obs_df = pd.DataFrame(obs_data).copy()
    required = {"obsnme", "obsval", "obgnme", "weight"}
    if not required.issubset(obs_df.columns):
        raise ValueError(f"Observation records missing: {sorted(required - set(obs_df.columns))}")
    obs_df["_var_root"] = (
        obs_df["obgnme"].astype(str).str.replace(r"_H\d+|_D\d+$", "", regex=True).str.upper()
    )

    sigmas: dict[str, float] = {}
    for group, frame in obs_df.groupby("obgnme"):
        explicit = pd.to_numeric(frame.get("sigma"), errors="coerce") if "sigma" in frame else pd.Series(dtype=float)
        if not explicit.empty and explicit.notna().any():
            unique = explicit.dropna().unique()
            if len(unique) != 1:
                raise ValueError(f"Observation group {group} has inconsistent sigma values")
            sigma = float(unique[0])
        else:
            root = str(frame["_var_root"].iloc[0])
            sigma = float(VARIABLE_TREATMENT.get(root, {"sigma_base": 1.0})["sigma_base"])
        if cv_based_sigma:
            sigma, _ = compute_cv_based_sigma(frame["obsval"], sigma0=sigma)
        weight_from_sigma(sigma)
        sigmas[str(group)] = sigma

    base_weights = {group: weight_from_sigma(sigma) for group, sigma in sigmas.items()}
    final_weights = base_weights.copy()
    if apply_pwtadj1:
        final_weights, _ = compute_balanced_weights(
            obs_df[["obsnme", "obsval", "obgnme"]], sim_baseline, sigmas
        )

    obs_df["sigma"] = obs_df["obgnme"].map(sigmas)
    obs_df["base_weight"] = obs_df["obgnme"].map(base_weights)
    obs_df["weight"] = obs_df["obgnme"].map(final_weights)
    obs_df.loc[obs_df["obsval"] == MISSING_VALUE, "weight"] = 0.0
    obs_df["group_multiplier"] = np.where(
        obs_df["base_weight"] > 0, obs_df["weight"] / obs_df["base_weight"], 0.0
    )
    obs_df["transform"] = "raw"
    obs_df["weight_policy_id"] = WEIGHT_POLICY_ID
    return obs_df.drop(columns=["_var_root"]).to_dict("records")


__all__ = [
    "LOG_TRANSFORM_VARS",
    "NON_CUMULATIVE_VARS",
    "VARIABLE_TREATMENT",
    "WEIGHT_POLICY_ID",
    "apply_weight_scheme_to_obs_df",
    "build_observation_weights",
    "compute_balanced_weights",
    "compute_cv_based_sigma",
    "compute_phi",
    "minmax_normalize",
    "normalize_and_weight",
    "weight_from_sigma",
]
