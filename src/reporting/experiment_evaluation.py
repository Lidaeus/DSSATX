"""Multi-season calibration evaluation: metrics + residual diagnostics.

Reads **frozen** comparison/trajectory/receipt artefacts only -- it never
scans PEST/DSSAT temp directories or infers data roles from run layout.  All
artefacts are written to a single output directory for the article.

The ``article_rawscale_v1`` profile enforces the CHPDT-only harvest contract:
HWAM, PWAD, PWAI are rejected from the formal metrics table; CHFPW is permitted
only as a diagnostic (its metrics are computed but never enter the article
summary).  Raw-scale metrics are the paper primary; ``ln(CHPDT+1)`` (log scale)
is reported alongside to explain the Phi optimisation scale, never to replace
the raw-scale evaluation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.reporting.metrics import compute_metrics_grouped
from src.reporting.residual_diagnostics import (
    build_residual_trajectory,
    runs_test,
    treatment_bootstrap_mbe,
)

# Variables allowed in the article profile.  CHPDT is the only active harvest
# target; CHFPW is computed but flagged diagnostic-only.
ARTICLE_ALLOWED_VARIABLES = {
    "CHPDT", "CHFPW", "LAID", "LWAD", "SWAD", "ADAP", "CNAM", "LAIX",
    "DRY_CUM", "DRY_INC",  # cumulative / incremental dry harvest aliases
}
ARTICLE_FORBIDDEN_VARIABLES = {"HWAM", "PWAD", "PWAI", "HWAMS", "PWADM", "PWAIM"}
ARTICLE_DIAGNOSTIC_ONLY_VARIABLES = {"CHFPW", "FRESH_CUM", "FRESH_INC"}

PROFILE = "article_rawscale_v1"


def _read_comparison(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    for col in ("observed", "simulated"):
        if col not in df.columns:
            raise ValueError(f"comparison table missing required column {col!r}")
    return df


def _normalise_variable(name: Any) -> str:
    """Map a comparison ``variable`` value onto its canonical root for grouping."""
    s = str(name).strip().upper()
    # strip trailing M/S (PEST measured/simulated suffix) and season/time tags
    for suffix in ("M", "S"):
        if s.endswith(suffix) and len(s) > 4:
            s = s[:-1]
    aliases = {
        "DRY_CUM": "CHPDT",
        "DRY_CUMM": "CHPDT",
        "FRESH_CUM": "CHFPW",
        "FRESH_CUMM": "CHFPW",
        "DRY_INC": "DRY_INC",
        "FRESH_INC": "FRESH_INC",
    }
    return aliases.get(s, s)


def _enforce_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Reject forbidden variables; tag diagnostic-only variables."""
    df = df.copy()
    df["_variable_root"] = df["variable"].apply(_normalise_variable)
    present_forbidden = set(df["_variable_root"]) & ARTICLE_FORBIDDEN_VARIABLES
    if present_forbidden:
        raise ValueError(
            f"{PROFILE} forbids HWAM/PWAD/PWAI in formal metrics; found {sorted(present_forbidden)}"
        )
    df["_is_diagnostic_only"] = df["_variable_root"].isin(ARTICLE_DIAGNOSTIC_ONLY_VARIABLES)
    return df


def _scale_column(df: pd.DataFrame) -> pd.Series:
    """Infer the residual scale (raw vs log) per row.

    The comparison table carries raw physical values; a ``scale`` column, if
    present, is honoured.  Otherwise raw is assumed.
    """
    if "scale" in df.columns:
        return df["scale"].astype(str).str.lower()
    return pd.Series(["raw"] * len(df), index=df.index)


def evaluate_experiment(
    comparison_csv: str | Path,
    out_dir: str | Path,
    *,
    trajectory_csv: str | Path | None = None,
    treatment_metadata_csv: str | Path | None = None,
    receipt_json: str | Path | None = None,
    profile: str = PROFILE,
    group_cols: list[str] | None = None,
    seed: int = 20260724,
) -> dict[str, Path]:
    """Evaluate one calibration experiment and write three result tables.

    Returns a dict of artefact name -> path.
    """
    if profile != PROFILE:
        raise ValueError(f"unsupported evaluation profile {profile!r}; expected {PROFILE!r}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    df = _read_comparison(comparison_csv)
    df = _enforce_profile(df)
    df["scale"] = _scale_column(df)
    if "experiment_id" not in df.columns:
        exp_id = ""
        if receipt_json and Path(receipt_json).is_file():
            try:
                exp_id = str(json.loads(Path(receipt_json).read_text(encoding="utf-8")).get("experiment_id", ""))
            except Exception:
                exp_id = ""
        df["experiment_id"] = exp_id
    if "season" not in df.columns:
        # derive season from treatment/season_id if available
        for cand in ("season_id", "season"):
            if cand in df.columns:
                df["season"] = df[cand]
                break
        if "season" not in df.columns:
            df["season"] = "all"
    if "dataset_role" not in df.columns:
        df["dataset_role"] = "calibration"
    if "scope" not in df.columns:
        df["scope"] = "all"

    if group_cols is None:
        group_cols = [c for c in (
            "experiment_id", "season", "dataset_role", "_variable_root", "scale", "scope"
        ) if c in df.columns]

    # --- comparison_raw.csv ---
    comparison_out = df.drop(columns=[c for c in ("_is_diagnostic_only",) if c in df.columns]).copy()
    comparison_out.rename(columns={"_variable_root": "variable_root"}, inplace=True)
    comparison_path = out / "comparison_raw.csv"
    comparison_out.to_csv(comparison_path, index=False)

    # --- metrics_rawscale.csv ---
    metrics_df = compute_metrics_grouped(df, group_cols, "observed", "simulated")
    # flag diagnostic-only groups
    if "_variable_root" in metrics_df.columns:
        metrics_df["is_diagnostic_only"] = metrics_df["_variable_root"].isin(
            ARTICLE_DIAGNOSTIC_ONLY_VARIABLES
        )
    metrics_path = out / "metrics_rawscale.csv"
    metrics_df.to_csv(metrics_path, index=False)

    # --- residual_diagnostics.csv ---
    diag_rows: list[dict[str, Any]] = []
    # runs test per season x treatment x variable_root (true time order)
    order_col = "harvest_number" if "harvest_number" in df.columns else (
        "dap" if "dap" in df.columns else "time"
    )
    if order_col not in df.columns:
        order_col = None
    runs_keys = [c for c in ("season", "treatment", "_variable_root") if c in df.columns]
    if order_col and runs_keys:
        ordered = df.sort_values(runs_keys + [order_col]) if order_col else df
        for keys, sub in ordered.groupby(runs_keys, sort=True):
            if not isinstance(keys, tuple):
                keys = (keys,)
            rt = runs_test((sub["simulated"].astype(float) - sub["observed"].astype(float)).to_numpy())
            row = dict(zip(runs_keys, keys))
            row.update(rt)
            diag_rows.append(row)
    # treatment-block bootstrap MBE per season x variable_root
    boot_keys = [c for c in ("season", "_variable_root") if c in df.columns]
    if "treatment" in df.columns and boot_keys:
        for keys, sub in df.groupby(boot_keys, sort=True):
            if not isinstance(keys, tuple):
                keys = (keys,)
            bt = treatment_bootstrap_mbe(sub, seed=seed)
            row = dict(zip(boot_keys, keys))
            row.update({f"boot_{k}": v for k, v in bt.items()})
            diag_rows.append(row)
    diag_df = pd.DataFrame(diag_rows) if diag_rows else pd.DataFrame()
    diag_path = out / "residual_diagnostics.csv"
    diag_df.to_csv(diag_path, index=False)

    # residual trajectory (auxiliary)
    if order_col:
        try:
            traj = build_residual_trajectory(df, runs_keys)
            traj.to_csv(out / "residual_trajectory.csv", index=False)
        except Exception:
            pass  # trajectory is auxiliary, not a hard gate

    artefacts = {
        "comparison_raw": comparison_path,
        "metrics_rawscale": metrics_path,
        "residual_diagnostics": diag_path,
    }
    return artefacts


__all__ = ["evaluate_experiment", "ARTICLE_ALLOWED_VARIABLES", "ARTICLE_FORBIDDEN_VARIABLES", "PROFILE"]
