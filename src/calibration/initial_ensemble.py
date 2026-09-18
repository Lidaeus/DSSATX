"""Generate space-filling initial parameter ensembles for PEST++ IES.

This module provides Latin Hypercube Sampling (LHS) and Sobol sequence
methods to generate initial parameter ensembles that ensure uniform coverage
of the prior parameter space, replacing PEST++'s default random sampling.

The generated ensemble is written to a CSV file that can be supplied to
PEST++ via the ``ies_parameter_ensemble`` option.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Bootstrap for both direct execution and module import.
_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from scipy.stats import qmc


def generate_lhs_ensemble(
    n_reals: int,
    bounds_df: pd.DataFrame,
    seed: int,
    *,
    method: str = "sobol",
    optimization: str = "random-cd",
    include_base: bool = False,
) -> pd.DataFrame:
    """Generate a space-filling initial parameter ensemble.

    Parameters
    ----------
    n_reals
        Number of realizations to generate.
    bounds_df
        Frozen bounds DataFrame with columns: ``name``, ``init``, ``lower``,
        ``upper``, ``status``. Only parameters with ``status == "active"``
        are included in the ensemble.
    seed
        Random seed for reproducibility.
    method
        Sampling method: ``"sobol"`` (Sobol sequence, default) or ``"lhs"``
        (Latin Hypercube).
    optimization
        LHS optimization strategy passed to ``scipy.stats.qmc.LatinHypercube``.
        Common values: ``"random-cd"`` (default), ``"lloyd"``.
    include_base
        If True, add the initial values (``init`` column) as the first
        realization (realization 0). This mirrors PEST++'s ``ies_add_base``
        option.

    Returns
    -------
    DataFrame
        Ensemble in PEST++ format: first column ``"real_name"`` with values
        like ``"0"``, ``"1"``, ..., followed by one column per parameter.
        Realization names use plain integer strings to match PEST++'s
        observation-ensemble index convention.
    """
    # Filter to active parameters only.
    active = bounds_df[bounds_df["status"].astype(str).str.lower() == "active"].copy()
    if active.empty:
        raise ValueError("No active parameters found in bounds DataFrame")

    n_par = len(active)
    par_names = active["name"].tolist()
    lower = active["lower"].to_numpy(dtype=float)
    upper = active["upper"].to_numpy(dtype=float)
    init_vals = active["init"].to_numpy(dtype=float)

    # Generate samples in unit hypercube [0, 1]^d.
    if method == "sobol":
        # Sobol sequence: use scipy's Sobol engine with random_base2.
        sampler = qmc.Sobol(d=n_par, scramble=True, seed=seed)
        m = (n_reals - 1).bit_length()
        unit_samples = sampler.random_base2(m=m)[:n_reals]
    elif method == "lhs":
        sampler = qmc.LatinHypercube(d=n_par, optimization=optimization, seed=seed)
        unit_samples = sampler.random(n_reals)
    else:
        raise ValueError(f"Unknown method: {method}. Use 'sobol' or 'lhs'.")

    # Scale from [0, 1] to [lower, upper].
    samples = qmc.scale(unit_samples, lower, upper)

    # Build the ensemble DataFrame.
    ensemble_data = {}
    ensemble_data["real_name"] = [str(i) for i in range(n_reals)]
    for i, name in enumerate(par_names):
        ensemble_data[name] = samples[:, i]

    df = pd.DataFrame(ensemble_data)

    # Optionally prepend the base realization (initial values).
    if include_base:
        base_row = {"real_name": "base"}
        for name, val in zip(par_names, init_vals):
            base_row[name] = val
        df = pd.concat([pd.DataFrame([base_row]), df], ignore_index=True)

    return df


def write_ensemble_csv(
    ensemble_df: pd.DataFrame,
    out_path: Path | str,
) -> None:
    """Write the ensemble DataFrame to CSV in PEST++ format.

    Parameters
    ----------
    ensemble_df
        Ensemble DataFrame from :func:`generate_lhs_ensemble`.
    out_path
        Output CSV file path.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ensemble_df.to_csv(out_path, index=False, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Generate space-filling initial parameter ensemble for PEST++ IES"
    )
    parser.add_argument(
        "--bounds-csv",
        required=True,
        help="Path to frozen bounds CSV file",
    )
    parser.add_argument(
        "--n-reals",
        type=int,
        required=True,
        help="Number of realizations to generate",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260731,
        help="Random seed for reproducibility (default: 20260731)",
    )
    parser.add_argument(
        "--method",
        choices=["lhs", "sobol"],
        default="lhs",
        help="Sampling method: lhs (default) or sobol",
    )
    parser.add_argument(
        "--optimization",
        default="random-cd",
        help="LHS optimization strategy (default: random-cd)",
    )
    parser.add_argument(
        "--include-base",
        action="store_true",
        help="Include initial values as realization 'base'",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output CSV file path for the ensemble",
    )
    args = parser.parse_args()

    bounds_df = pd.read_csv(args.bounds_csv, encoding="utf-8-sig")
    ensemble = generate_lhs_ensemble(
        n_reals=args.n_reals,
        bounds_df=bounds_df,
        seed=args.seed,
        method=args.method,
        optimization=args.optimization,
        include_base=args.include_base,
    )
    write_ensemble_csv(ensemble, args.output)
    print(f"Ensemble written to {args.output} ({len(ensemble)} realizations)")


if __name__ == "__main__":
    main()