"""src/calibration/weight_scheme.py - Advanced weight calculation scheme.

Implements the improved weight design from the weight proposal:
  - Inverse-variance weighting (base framework)
  - Min-Max normalization for cross-variable balance
  - Log transformation for heteroscedastic time-series data
  - pwtadj1-equivalent automatic weight balancing (OLS -> WLS two-step)
  - CV-based sigma estimation from observed data

Processing pipeline (Step 1-6):
  [Step 1] Data preprocessing (normalization + log transform)
            |
  [Step 2] Compute base_weight = 1/sigma^2 (in physical or log units)
            |
  [Step 3] OLS single-group fitting (AgMIP Step 6)
            |
  [Step 4] Compute pwtadj1 adjustment factor (AgMIP Step 7)
            |
  [Step 5] final_weight = base_weight x adjustment_factor
            |
  [Step 6] Global WLS optimization
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional


LOG_TRANSFORM_VARS = {"LWADM", "SWADM", "LAIDM", "HWAMM", "CNAMM"}

NON_CUMULATIVE_VARS = {"ADAPM", "HIAMM", "LAIXM", "CHTAM", "CNAAM", "H#AMM"}


def minmax_normalize(obs_series: pd.Series, sim_series: pd.Series
                      ) -> Tuple[pd.Series, pd.Series, float]:
    """Normalize a pair of observed and simulated series to [0, 1].

    Parameters
    ----------
    obs_series : pd.Series
        Observed values.
    sim_series : pd.Series
        Simulated values (used only to determine min/max range).
    Returns
    -------
    norm_obs, norm_sim, scale
        Normalized series and the original range (max - min).
    """
    all_vals = pd.concat([obs_series, sim_series]).replace(-99.0, np.nan).dropna()
    if all_vals.empty:
        return obs_series, sim_series, 1.0
    min_val = all_vals.min()
    max_val = all_vals.max()
    if max_val == min_val:
        return obs_series, sim_series, 1.0
    scale = max_val - min_val
    norm_obs = (obs_series - min_val) / scale
    norm_sim = (sim_series - min_val) / scale
    return norm_obs, norm_sim, scale


def normalize_and_weight(
    obs_series: pd.Series,
    sim_series: pd.Series,
    sigma_original: float,
    use_log_transform: bool = False,
    eps: float = 1e-6
) -> Tuple[float, pd.Series, pd.Series]:
    """Compute weight for an observation group with correct processing order.

    For cumulative variables (LWADM, SWADM, LAIDM, HWAMM, CNAMM):
        Step 1: log transform (in original space to stabilize variance)
        Step 2: Min-Max normalize in log space
        Step 3: Compute weight in normalized space

    For non-cumulative variables (ADAPM, HIAMM, LAIXM, etc.):
        Step 1: Min-Max normalize directly
        Step 2: Compute weight in normalized space

    Parameters
    ----------
    obs_series : pd.Series
        Observed values (may contain -99.0 for missing).
    sim_series : pd.Series
        Simulated values from model.
    sigma_original : float
        Base sigma value in physical units.
    use_log_transform : bool
        Whether to apply log transform first (for cumulative variables).
    eps : float
        Small constant added before log to avoid log(0).

    Returns
    -------
    weight : float
        Final weight = 1 / effective_sigma^2.
    norm_obs : pd.Series
        Normalized observed series.
    norm_sim : pd.Series
        Normalized simulated series.
    """
    mask = (obs_series != -99.0) & (~obs_series.isna())
    _obs = np.asarray(obs_series[mask], dtype=float)
    _sim = np.asarray(sim_series[mask], dtype=float)

    if _obs.size == 0:
        return 0.0, obs_series, sim_series

    if use_log_transform:
        log_obs = np.log(_obs + eps)
        log_sim = np.log(_sim + eps)
        all_log_vals = np.concatenate([log_obs, log_sim])
        log_min = float(np.min(all_log_vals))
        log_max = float(np.max(all_log_vals))
        log_range = log_max - log_min + eps
        norm_obs = (log_obs - log_min) / log_range
        norm_sim = (log_sim - log_min) / log_range
        effective_sigma = sigma_original / log_range
    else:
        all_vals = np.concatenate([_obs, _sim])
        min_v = float(np.min(all_vals))
        max_v = float(np.max(all_vals))
        if max_v == min_v:
            effective_sigma = float(sigma_original)
        else:
            effective_sigma = sigma_original / (max_v - min_v + eps)
        norm_obs = (_obs - min_v) / (max_v - min_v + eps)
        norm_sim = (_sim - min_v) / (max_v - min_v + eps)

    effective_sigma = float(effective_sigma)
    if effective_sigma <= 0:
        effective_sigma = 1.0
    weight = 1.0 / (effective_sigma ** 2)
    return weight, pd.Series(norm_obs), pd.Series(norm_sim), effective_sigma


def compute_cv_based_sigma(
    obs_series: pd.Series,
    sigma0: float = 1.0,
    cv_override: Optional[float] = None
) -> Tuple[float, float]:
    """Compute sigma from observed data using coefficient of variation.

    sigma = sqrt(sigma0^2 + (cv * |median|)^2)

    Parameters
    ----------
    obs_series : pd.Series
        Observed values (may contain -99.0 for missing).
    sigma0 : float
        Base sigma (minimum uncertainty floor).
    cv_override : float, optional
        If provided, use this CV directly instead of estimating from data.

    Returns
    -------
    sigma : float
        Computed sigma value.
    cv : float
        The CV used (either estimated or overridden).
    """
    valid = obs_series[obs_series > 0].replace(-99.0, np.nan).dropna()
    if valid.empty:
        return sigma0, 0.0
    median_val = valid.median()
    if cv_override is not None:
        cv = cv_override
    else:
        mean_val = valid.mean()
        std_val = valid.std()
        cv = (std_val / mean_val) if mean_val != 0 else 0.2
    sigma = np.sqrt(sigma0**2 + (cv * abs(median_val))**2)
    return float(sigma), float(cv)


def compute_balanced_weights(
    obs_df: pd.DataFrame,
    sim_df: pd.DataFrame,
    original_sigmas: Dict[str, float],
    target_per_group: float = 1.0
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Simulate PEST's pwtadj1.exe weight balancing logic.

    Evaluates the initial residual variance of each observation group from
    a baseline (noptmax=0) run and adjusts weights so that each group
    contributes equally to the total objective function.

    AgMIP Phase 4 Step 6-7:
      Step 6 (OLS): Individual group fitting to get residual variance.
      Step 7 (WLS): Adjust weights by inverse of group residual variance.

    Parameters
    ----------
    obs_df : pd.DataFrame
        DataFrame with 'obsnme', 'obsval', 'obgnme' columns.
        obsval is the measured value.
    sim_df : pd.DataFrame
        DataFrame with 'obsnme', 'simulated' columns.
        simulated is the model output at baseline parameters.
    original_sigmas : Dict[str, float]
        Base sigma per observation group (group name -> sigma).
    target_per_group : float
        Desired total contribution fraction per group (default 1/G where G
        is number of groups, achieved by equal weighting).

    Returns
    -------
    balanced_weights : Dict[str, float]
        Adjusted weight per group (group name -> weight = 1/sigma^2).
    adjusted_sigmas : Dict[str, float]
        Adjusted sigma per group after balancing.
    """
    obs_df = obs_df.copy()
    sim_df = sim_df.copy()

    if 'obsval' not in obs_df.columns or 'obgnme' not in obs_df.columns:
        raise ValueError("obs_df must have 'obsval' and 'obgnme' columns")
    if 'simulated' not in sim_df.columns:
        raise ValueError("sim_df must have 'simulated' column")

    obs_df = obs_df.rename(columns={'obsnme': 'obsnme'})
    sim_df = sim_df.rename(columns={'obsnme': 'obsnme'})

    merged = obs_df.merge(sim_df, on='obsnme', how='left')
    merged['residual'] = merged['simulated'] - merged['obsval']
    merged['residual_sq'] = merged['residual'] ** 2

    groups = merged.groupby('obgnme')
    n_groups = len(groups)

    group_phi = {}
    for obgnme, g in groups:
        valid = g[g['obsval'] != -99.0]
        if valid.empty:
            group_phi[obgnme] = 0.0
        else:
            group_phi[obgnme] = float(valid['residual_sq'].sum() / len(valid))

    total_phi = sum(group_phi.values())
    if total_phi == 0:
        return {k: 1.0 / (v**2) for k, v in original_sigmas.items()}, original_sigmas.copy()

    adjusted_sigmas = {}
    for obgnme, sigma in original_sigmas.items():
        contrib_ratio = group_phi.get(obgnme, 1e-10) / total_phi
        target_contribution = target_per_group / n_groups
        adj_factor = np.sqrt(target_contribution * n_groups / (contrib_ratio + 1e-10))
        adjusted_sigmas[obgnme] = sigma * adj_factor

    balanced_weights = {k: 1.0 / (v**2) if v > 0 else 0.0
                        for k, v in adjusted_sigmas.items()}
    return balanced_weights, adjusted_sigmas


def apply_weight_scheme_to_obs_df(
    obs_df: pd.DataFrame,
    sim_df: pd.DataFrame,
    group_sigmas: Dict[str, float],
    use_log_transform_groups: Optional[Dict[str, bool]] = None,
    apply_pwtadj1: bool = True,
    noptmax0_sims: Optional[pd.DataFrame] = None
) -> pd.DataFrame:
    """Apply the full improved weight scheme to an observation DataFrame.

    This is the main entry point that orchestrates all five improvements:
      1. CV-based sigma estimation
      2. Min-Max normalization (cross-variable balance)
      3. Log transformation (heteroscedasticity)
      4. pwtadj1-equivalent balancing
      5. Final weight computation

    Parameters
    ----------
    obs_df : pd.DataFrame
        DataFrame with 'obsnme', 'obsval', 'obgnme' columns.
    sim_df : pd.DataFrame
        DataFrame with 'obsnme', 'simulated' columns (from noptmax=0 run).
    group_sigmas : Dict[str, float]
        Base sigma per observation group.
    use_log_transform_groups : Dict[str, bool], optional
        Override for which groups use log transform.
        If None, uses LOG_TRANSFORM_VARS set.
    apply_pwtadj1 : bool
        Whether to apply pwtadj1-equivalent balancing.
    noptmax0_sims : pd.DataFrame, optional
        Simulation results from a baseline (noptmax=0) run.
        Required if apply_pwtadj1 is True.

    Returns
    -------
    pd.DataFrame
        Copy of obs_df with updated 'weight' and 'obgnme' columns.
    """
    use_log_transform_groups = use_log_transform_groups or {}

    result_df = obs_df.copy()

    balanced_weights = None
    if apply_pwtadj1 and noptmax0_sims is not None:
        balanced_weights, _ = compute_balanced_weights(
            obs_df, noptmax0_sims, group_sigmas
        )
    elif apply_pwtadj1:
        balanced_weights = {k: 1.0 / (v**2) if v > 0 else 0.0
                            for k, v in group_sigmas.items()}

    weights = {}
    for obgnme, group_data in result_df.groupby('obgnme'):
        sigma = group_sigmas.get(obgnme, 25.0)
        use_log = use_log_transform_groups.get(
            obgnme, obgnme in LOG_TRANSFORM_VARS
        )

        obs_vals = group_data['obsval']
        sim_vals = sim_df.loc[group_data.index, 'simulated'] \
            if 'simulated' in sim_df.columns else group_data['obsval']

        weight, _, _, _ = normalize_and_weight(
            obs_vals, sim_vals, sigma, use_log_transform=use_log
        )

        if balanced_weights is not None and obgnme in balanced_weights:
            base_weight = balanced_weights[obgnme]
        else:
            base_weight = 1.0 / (sigma ** 2) if sigma > 0 else 0.0

        weights[obgnme] = base_weight

    result_df['weight'] = result_df['obgnme'].map(weights).fillna(1.0)
    return result_df


VARIABLE_TREATMENT = {
    "ADAPM": {"log_transform": False, "sigma_base": 25.0, "cumulate": False},
    "CNAMM": {"log_transform": True,  "sigma_base": 0.1,   "cumulate": True},
    "HIAMM": {"log_transform": False, "sigma_base": 0.05,  "cumulate": False},
    "HWAMM": {"log_transform": True,  "sigma_base": 0.1,   "cumulate": True},
    "LAIXM": {"log_transform": False, "sigma_base": 0.1,   "cumulate": False},
    "LAIDM": {"log_transform": True,  "sigma_base": 0.1,   "cumulate": True},
    "LWADM": {"log_transform": True,  "sigma_base": 0.1,   "cumulate": True},
    "SWADM": {"log_transform": True,  "sigma_base": 0.1,   "cumulate": True},
    "CHTAM": {"log_transform": False, "sigma_base": 15.0,  "cumulate": False},
    "CNAAM": {"log_transform": False, "sigma_base": 20.0,  "cumulate": False},
    "H#AMM": {"log_transform": False, "sigma_base": 50.0,  "cumulate": False},
    "PWADM": {"log_transform": True,  "sigma_base": 0.1,   "cumulate": True},
    "PWAIM": {"log_transform": True,  "sigma_base": 0.1,   "cumulate": True},
}


def build_observation_weights(
    obs_data: list,
    df_override: Optional[pd.DataFrame] = None,
    sim_baseline: Optional[pd.DataFrame] = None,
    apply_normalization: bool = True,
    apply_log_transform: bool = True,
    apply_pwtadj1: bool = True,
    cv_based_sigma: bool = True,
) -> list:
    """Apply the full improved weight scheme to an observation DataFrame.

    Key design decisions:
      - Weight is computed per variable-root (LAIDM, LWADM, etc.), NOT per date-specific
        group. All dates of the same variable share the same weight, ensuring that
        the normalization range (min/max) spans all observations of that variable.
      - The VARIABLE_TREATMENT lookup uses the variable-root in UPPERCASE to match
        the dictionary keys.
      - For pwtadj1, the group key is the FULL obgnme (e.g., laidm_d25075), so
        each date-specific group gets its own pwtadj1 adjustment factor.

    Parameters
    ----------
    obs_data : list
        List of observation dicts from create_ins_and_pst or _build_ins_and_obs.
        Each dict has 'obsnme', 'obsval', 'weight', 'obgnme'.
    df_override : pd.DataFrame, optional
        If provided, use this DataFrame for normalization ranges.
    sim_baseline : pd.DataFrame, optional
        Baseline simulation results for pwtadj1 balancing.
    apply_normalization : bool
        Apply Min-Max normalization when computing effective sigma.
    apply_log_transform : bool
        Apply log transform to cumulative variables.
    apply_pwtadj1 : bool
        Apply pwtadj1-equivalent weight balancing.
    cv_based_sigma : bool
        Estimate sigma from observed data CV instead of using fixed values.

    Returns
    -------
    list
        Updated obs_data with new 'weight' values.
    """
    if not obs_data:
        return obs_data

    obs_df = pd.DataFrame(obs_data)
    obs_df['_orig_weight'] = obs_df['weight']

    obs_df['_var_root_raw'] = obs_df['obgnme'].str.replace(r'_H\d+|_D\d+$', '', regex=True)
    obs_df['_var_root'] = obs_df['_var_root_raw'].str.upper()

    obs_df['_simulated'] = None
    if sim_baseline is not None and 'simulated' in sim_baseline.columns:
        sim_indexed = sim_baseline.set_index('obsnme')['simulated']
        obs_df['_simulated'] = obs_df['obsnme'].map(sim_indexed)

    var_roots = obs_df['_var_root'].unique()
    var_treatments = {}
    for vr in var_roots:
        if vr in VARIABLE_TREATMENT:
            var_treatments[vr] = dict(VARIABLE_TREATMENT[vr])
        else:
            var_treatments[vr] = {
                "log_transform": False,
                "sigma_base": 1.0,
                "cumulate": False
            }

    if cv_based_sigma and df_override is not None:
        for vr, treatment in var_treatments.items():
            root_lower = vr.lower()
            col_candidates = [
                c for c in df_override.columns
                if c.startswith(root_lower) and c.endswith('M')
            ]
            for col in col_candidates:
                valid = df_override[df_override[col] != -99.0][col]
                if not valid.empty:
                    sigma_est, cv_est = compute_cv_based_sigma(
                        valid, sigma0=treatment["sigma_base"], cv_override=None
                    )
                    treatment["sigma_base"] = sigma_est
                    break

    var_base_weights = {}
    for vr, treatment in var_treatments.items():
        sigma = treatment["sigma_base"]
        use_log = apply_log_transform and treatment["log_transform"]

        var_obs = obs_df[obs_df['_var_root'] == vr]
        obs_vals = var_obs['obsval']
        sim_vals = var_obs['_simulated'].fillna(obs_vals)

        if apply_normalization:
            weight, _, _, effective_sigma = normalize_and_weight(
                obs_vals.reset_index(drop=True),
                sim_vals.reset_index(drop=True),
                sigma,
                use_log_transform=use_log
            )
        else:
            effective_sigma = sigma

        if effective_sigma <= 0:
            effective_sigma = 1.0
        var_base_weights[vr] = weight

    obs_df['_base_weight'] = obs_df['_var_root'].map(var_base_weights).fillna(1.0)

    if apply_pwtadj1 and sim_baseline is not None:
        try:
            obs_for_pwtadj1 = obs_df[obs_df['obsval'] != -99.0].copy()
            if not obs_for_pwtadj1.empty and '_simulated' in obs_for_pwtadj1.columns:
                sim_for_pwtadj1 = obs_for_pwtadj1[[
                    'obsnme', 'obgnme', 'obsval', '_simulated'
                ]].copy()
                sim_for_pwtadj1 = sim_for_pwtadj1.rename(columns={'_simulated': 'simulated'})
                balanced_w, _ = compute_balanced_weights(
                    sim_for_pwtadj1[['obsnme', 'obsval', 'obgnme']],
                    sim_for_pwtadj1[['obsnme', 'simulated', 'obgnme']],
                    {vr: v["sigma_base"] for vr, v in var_treatments.items()}
                )

                obs_df['_pwtadj1_weight'] = obs_df.apply(
                    lambda r: balanced_w.get(r['obgnme'], r['_base_weight']), axis=1
                )
                obs_df['weight'] = obs_df['_pwtadj1_weight']
            else:
                obs_df['weight'] = obs_df['_base_weight']
        except Exception:
            obs_df['weight'] = obs_df['_base_weight']
    else:
        obs_df['weight'] = obs_df['_base_weight']

    obs_df['weight'] = obs_df['weight'].fillna(1.0).replace([float('inf')], 1.0)

    keep_cols = [c for c in obs_df.columns if not c.startswith('_')]
    return obs_df[keep_cols].to_dict('records')
