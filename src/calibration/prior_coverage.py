"""Prior-data coverage diagnostics for PEST++-IES preflight runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def summarize_prior_coverage(
    pdc_csv: str | Path,
    weights_audit_csv: str | Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Summarize observation-level prior coverage and conflict by group.

    PEST++'s PDC file contains the prior simulated and observation-plus-noise
    ranges. A conflict is recorded when the statistical ranges do not overlap.
    This function deliberately does not change weights or drop observations.
    """
    pdc = pd.read_csv(pdc_csv)
    audit = pd.read_csv(weights_audit_csv, encoding="utf-8-sig")
    required = {
        "name", "obs_mean", "obs_std", "obs_min", "obs_max",
        "sim_mean", "sim_std", "sim_min", "sim_max", "distance",
    }
    missing = required - set(pdc.columns)
    if missing:
        raise ValueError(f"PDC file missing columns: {sorted(missing)}")
    if "obsnme" not in audit or "obgnme" not in audit:
        raise ValueError("weights audit requires obsnme and obgnme")
    audit_cols = ["obsnme", "obgnme"] + (["weight"] if "weight" in audit.columns else [])
    audit = audit[audit_cols].drop_duplicates("obsnme").copy()
    if "weight" in audit:
        audit = audit[pd.to_numeric(audit["weight"], errors="coerce") > 0].copy()
    audit["_key"] = audit["obsnme"].astype(str).str.upper()
    pdc["_key"] = pdc["name"].astype(str).str.upper()
    pdc = pdc.merge(audit[["_key", "obgnme"]], on="_key", how="left", validate="many_to_one")
    if pdc["obgnme"].isna().any():
        raise ValueError("PDC contains observations absent from the weights audit")
    numeric = [
        "obs_mean", "obs_std", "obs_min", "obs_max", "sim_mean", "sim_std",
        "sim_min", "sim_max", "distance",
    ]
    for col in numeric:
        pdc[col] = pd.to_numeric(pdc[col], errors="coerce")
    if not np.isfinite(pdc[numeric].to_numpy(dtype=float)).all():
        raise ValueError("PDC contains non-finite numeric values")
    # PEST++ normally emits only conflicted observations.  Diagnostic tables
    # may also include zero-distance rows; those explicitly indicate no
    # conflict and must not be counted as such.
    pdc = pdc.loc[pdc["distance"] > 0.0].copy()
    pdc["signed_residual"] = pdc["sim_mean"] - pdc["obs_mean"]
    # PEST++ writes only conflicted observations to *.pdc.csv. The denominator
    # therefore comes from the full non-zero-weight policy audit, not the PDC
    # row count.
    pdc["conflict"] = True
    conflict_metrics = (
        pdc.groupby("obgnme", sort=True)
        .agg(
            conflict_count=("name", "size"),
            mean_distance=("distance", "mean"),
            median_distance=("distance", "median"),
            mean_signed_residual=("signed_residual", "mean"),
            mean_abs_signed_residual=("signed_residual", lambda x: float(np.abs(x).mean())),
            mean_sim_std=("sim_std", "mean"),
            mean_obs_std=("obs_std", "mean"),
        )
    )
    totals = audit.groupby("obgnme", sort=True).size().rename("observation_count")
    group = totals.to_frame().join(conflict_metrics, how="left").fillna({"conflict_count": 0})
    group["conflict_count"] = group["conflict_count"].astype(int)
    group["conflict_fraction"] = group["conflict_count"] / group["observation_count"]
    group = group.reset_index()
    report = {
        "schema_version": 1,
        "pdc_file": str(Path(pdc_csv)),
        "weights_audit": str(Path(weights_audit_csv)),
        "observation_count": int(len(audit)),
        "conflict_count": int(len(pdc)),
        "conflict_fraction": float(len(pdc) / len(audit)) if len(audit) else 0.0,
        "groups_with_full_conflict": sorted(
            group.loc[group["conflict_fraction"] >= 1.0, "obgnme"].astype(str).tolist()
        ),
    }
    return group, report


def write_prior_coverage_report(
    pdc_csv: str | Path,
    weights_audit_csv: str | Path,
    out_dir: str | Path,
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    group, report = summarize_prior_coverage(pdc_csv, weights_audit_csv)
    group.to_csv(out / "prior_coverage_by_group.csv", index=False)
    (out / "prior_coverage_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report
